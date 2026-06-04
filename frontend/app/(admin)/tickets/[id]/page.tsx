import { notFound } from "next/navigation";

import { TicketStatusChanger } from "@/components/ticket-status-changer";
import { Breadcrumb } from "@/components/breadcrumb";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { ActivityTimeline } from "@/components/activity-timeline";
import { CommentForm } from "@/components/comment-form";
import { PrintButton } from "@/components/print-button";
import { EditTicketForm } from "./_components/edit-ticket-form";
import { TicketDeleteButton } from "@/components/ticket-delete-button";
import { TrackRecentTicket } from "@/components/recent-tickets";
import { TagChip } from "@/components/tag-chip";
import { TicketTagManager } from "@/components/ticket-tag-manager";
import { getCurrentProject } from "@/lib/api/session";
import { getTicketActivity, type TicketActivityEntry } from "@/lib/api/tickets";
import { listTags } from "@/lib/api/tags";
import { fetchAssignableActors } from "@/lib/api/actors";
import {
  buildAssigneeNameMap,
  assigneeLabel,
  type AssignableActor
} from "@/lib/domain/assignee";
import type { TagRead } from "@/lib/domain/tag";
import { isValidYmd } from "@/lib/domain/due-date";

import { addTicketCommentAction } from "../actions";
import { loadTicket } from "./load-ticket";

export const dynamic = "force-dynamic";

type TicketDetailPageProps = {
  params: Promise<{ id: string }>;
};

const STATUS_LABELS: Record<string, string> = {
  open: "未着手",
  in_progress: "進行中",
  blocked: "ブロック",
  review: "レビュー",
  closed: "完了",
  cancelled: "中止",
};

function statusLabel(value: string | null | undefined): string {
  if (!value) return "不明";
  return STATUS_LABELS[value] ?? value;
}

// ADR-00041 N-2: backend activity entry を ActivityTimeline の表示 entry へ写像する。
// actor / message は server-owned (backend が redaction + author 解決済) をそのまま使う。
type TimelineEntryView = {
  id: string;
  type: "comment" | "status_change" | "event";
  actor: string | null;
  body: string;
  created_at: string;
};

function toTimelineEntry(entry: TicketActivityEntry): TimelineEntryView {
  const actor = entry.actor_id ?? null;
  if (entry.type === "comment") {
    return { id: entry.id, type: "comment", actor, body: entry.message ?? "", created_at: entry.created_at };
  }
  if (entry.type === "status_change") {
    return {
      id: entry.id,
      type: "status_change",
      actor,
      body: `ステータスを「${statusLabel(entry.previous_status)}」から「${statusLabel(entry.new_status)}」に変更しました`,
      created_at: entry.created_at,
    };
  }
  if (entry.type === "created") {
    return { id: entry.id, type: "event", actor, body: "チケットが作成されました", created_at: entry.created_at };
  }
  return { id: entry.id, type: "event", actor, body: "チケットが更新されました", created_at: entry.created_at };
}

// due_date は SQL date (YYYY-MM-DD) のプレーンな日付。timezone を持たないため、
// new Date(...) / toLocaleDateString による変換は使わず文字列を直接整形する
// (UTC parse → JST 変換で日付が 1 日ずれる事故を防ぐ)。
// 非実在日 / 不正形式は raw を echo せず「未設定」扱い (A-7 R11 F-001: schema が strict だが
// defense-in-depth、malformed を bogus deadline として表示しない)。
function formatDueDate(value: string | null): string {
  if (!value || !isValidYmd(value)) return "未設定";
  const [year, month, day] = value.split("-");
  return `${year}/${month}/${day}`;
}

function statusBadge(status: string) {
  const colors: Record<string, string> = {
    open: "bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300",
    in_progress: "bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300",
    closed: "bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400",
    cancelled: "bg-red-50 dark:bg-red-950/40 text-red-600 dark:text-red-400",
  };
  const labels: Record<string, string> = {
    open: "未着手",
    in_progress: "進行中",
    closed: "完了",
    cancelled: "中止",
  };
  return (
    <span
      className={`rounded-full px-3 py-1 text-sm font-medium ${colors[status] ?? "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300"}`}
    >
      {labels[status] ?? status}
    </span>
  );
}

export default async function TicketDetailPage({ params }: TicketDetailPageProps) {
  const { id } = await params;
  const ticket = await loadTicket(id);

  if (!ticket) {
    notFound();
  }

  // mutation (ステータス変更 / 編集 / 中止) は updateTicketAction が session の
  // current_project に PATCH するため、ticket の所有 project が current_project と
  // 一致するときだけ書込 UI を出す。非一致時は wrong-project へ submit して 404 になる
  // 編集 UI を出さず閲覧のみにする (Codex B2b R7 finding、create gating と同じ方針)。
  const currentProject = await getCurrentProject().catch(() => null);
  const isWritable = currentProject !== null && ticket.project_id === currentProject.project_id;

  // ADR-00044 (A-5): project の全タグ (tag 管理 / 付与候補)。取得失敗は付与中タグ表示に degrade
  // (補助情報なので fail-soft、ticket.tags は by-id load 済で常に表示できる)。
  let allTags: TagRead[] = [];
  if (isWritable) {
    try {
      allTags = (await listTags(ticket.project_id)).items;
    } catch {
      allTags = [];
    }
  }

  // A-6 (ADR-00046): 担当者候補 (tenant 内 human)。表示 (UUID -> display_name) + 編集 select に使う。
  // 取得失敗は degraded (空 list + flag) に倒す。表示は assigneeLabel の中立 fallback、編集 select は
  // 現 assignee のみ option 保持 + 警告 (silent に未割当へ変えない、R1 F-009)。
  let assignableActors: AssignableActor[] = [];
  let assignableActorsDegraded = false;
  let assignableActorsTruncated = false;
  try {
    const assignableResp = await fetchAssignableActors();
    assignableActors = assignableResp.actors;
    // Codex App F-C3: truncated を編集フォームへ伝えて cap 切り詰めを可視化する (一覧 page と同扱い)。
    assignableActorsTruncated = assignableResp.truncated;
  } catch {
    assignableActorsDegraded = true;
  }
  const assigneeNameById = buildAssigneeNameMap(assignableActors);

  // ADR-00041 N-2: comment + status 変更 + created を backend 集約 endpoint から取得。
  // 取得失敗 (backend 障害 / 一時的 5xx) はページ全体を落とさず、作成/更新の合成 entry に
  // degrade する (timeline は補助情報、章単位で fail-soft)。
  let activityEntries: TimelineEntryView[] | null = null;
  try {
    const activity = await getTicketActivity(ticket.project_id, ticket.id);
    activityEntries = activity.entries.map(toTimelineEntry);
  } catch {
    activityEntries = null;
  }

  const fallbackEntries: TimelineEntryView[] = [
    ...(ticket.created_at
      ? [{
          id: "created",
          type: "event" as const,
          actor: null,
          body: "チケットが作成されました",
          created_at: ticket.created_at,
        }]
      : []),
    ...(ticket.updated_at && ticket.updated_at !== ticket.created_at
      ? [{
          id: "updated",
          type: "event" as const,
          actor: null,
          body: "チケットが更新されました",
          created_at: ticket.updated_at,
        }]
      : []),
  ];

  return (
    <section aria-label="チケット詳細" className="grid gap-6">
      <TrackRecentTicket ticket={{ id: ticket.id, title: ticket.title, slug: ticket.slug }} />
      <header className="grid gap-2">
        <Breadcrumb items={[
          { label: "ダッシュボード", href: "/dashboard" },
          { label: "チケット", href: "/tickets" },
          { label: ticket.slug },
        ]} />
        <div className="flex flex-wrap items-center gap-4">
          <h1 className="text-3xl font-semibold tracking-normal">{ticket.title}</h1>
          {statusBadge(ticket.status)}
          {/* S-1: チケット印刷ビュー。印刷 CSS が操作系を隠し内容のみを出す */}
          <div className="ml-auto">
            <PrintButton label="印刷" />
          </div>
        </div>
      </header>

      <div className="grid gap-4 md:grid-cols-2">
        <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
          <h2 className="text-lg font-semibold">基本情報</h2>
          <dl className="mt-4 grid gap-3 text-sm">
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">チケット ID</dt>
              <dd className="font-mono text-xs">{ticket.id.slice(0, 8)}...</dd>
            </div>
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">スラッグ</dt>
              <dd className="font-mono">{ticket.slug}</dd>
            </div>
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">ステータス</dt>
              <dd>{statusBadge(ticket.status)}</dd>
            </div>
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">優先度</dt>
              <dd>{ticket.priority ?? "未設定"}</dd>
            </div>
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">期限</dt>
              <dd>{formatDueDate(ticket.due_date)}</dd>
            </div>
            <div className="flex justify-between border-t border-line pt-3">
              {/* A-6: assignee は display_name で表示 (UUID 生表示はしない、map-miss は中立 fallback)。 */}
              <dt className="text-muted-foreground">担当者</dt>
              <dd>{assigneeLabel(assigneeNameById, ticket.assignee_actor_id)}</dd>
            </div>
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">作成日</dt>
              <dd>
                {ticket.created_at
                  ? new Date(ticket.created_at).toLocaleString("ja-JP")
                  : "—"}
              </dd>
            </div>
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">更新日</dt>
              <dd>
                {ticket.updated_at
                  ? new Date(ticket.updated_at).toLocaleString("ja-JP")
                  : "—"}
              </dd>
            </div>
          </dl>
        </article>

        <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
          <h2 className="text-lg font-semibold">説明</h2>
          <div className="mt-4 text-sm leading-relaxed text-muted-foreground">
            {ticket.description ? (
              <MarkdownRenderer content={ticket.description} />
            ) : (
              <p className="italic">説明はまだありません</p>
            )}
          </div>
        </article>
      </div>

      {/* ADR-00044 (A-5): ラベル。付与中タグは閲覧/印刷可、操作 (manager) は no-print + isWritable のみ */}
      <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
        <h2 className="text-lg font-semibold">ラベル</h2>
        {isWritable ? (
          <>
            {/* 操作 UI は画面のみ。印刷では下の print-only サマリで付与中タグを出す */}
            <div className="no-print mt-4">
              <TicketTagManager
                ticketId={ticket.id}
                currentTags={ticket.tags}
                allTags={allTags}
              />
            </div>
            <div className="print-only mt-4 flex flex-wrap gap-2">
              {ticket.tags.length === 0 ? (
                <p className="text-sm text-muted-foreground">タグはありません</p>
              ) : (
                ticket.tags.map((tag) => (
                  <TagChip key={tag.id} name={tag.name} color={tag.color} />
                ))
              )}
            </div>
          </>
        ) : (
          <div className="mt-4 flex flex-wrap gap-2">
            {ticket.tags.length === 0 ? (
              <p className="text-sm text-muted-foreground">タグはありません</p>
            ) : (
              ticket.tags.map((tag) => (
                <TagChip key={tag.id} name={tag.name} color={tag.color} />
              ))
            )}
          </div>
        )}
      </article>
      {!isWritable ? (
        <div className="no-print rounded-md border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 px-4 py-3 text-sm text-amber-700 dark:text-amber-300">
          このチケットは現在の作業プロジェクト外のため、ここでは閲覧のみ可能です。
          ステータス変更・編集・中止は、そのチケットが属するプロジェクトを現在の
          プロジェクトにしているときだけ行えます。
        </div>
      ) : null}
      {/* S-1: 操作系 (ステータス変更 / アクション) は印刷物には出さない (.no-print) */}
      <div className="no-print grid gap-4 md:grid-cols-2">
        <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
          <h2 className="text-lg font-semibold">ステータス変更</h2>
          <div className="mt-4">
            {isWritable ? (
              <TicketStatusChanger ticketId={ticket.id} currentStatus={ticket.status} />
            ) : (
              <p className="text-sm text-muted-foreground">
                現在のプロジェクト外のため変更できません。
              </p>
            )}
          </div>
        </article>

        <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
          <h2 className="text-lg font-semibold">アクション</h2>
          <div className="mt-4 grid gap-2">
            <a
              href={`/tickets?project=${encodeURIComponent(ticket.project_slug)}`}
              className="rounded-md border border-line px-4 py-2 text-center text-sm font-medium text-muted-foreground transition-colors hover:bg-slate-50 dark:hover:bg-slate-800"
            >
              プロジェクトの看板に戻る
            </a>
            {isWritable && ticket.status !== "cancelled" ? (
              <TicketDeleteButton ticketId={ticket.id} projectId={ticket.project_id} />
            ) : null}
          </div>
        </article>
      </div>

      {/* S-1: 編集フォームは印刷物には出さない (.no-print) */}
      {isWritable ? (
        <div className="no-print">
          {/* A-6 (R1 F-006): as-unknown cast を解消。TicketDetail (assignee_actor_id 含む) を直接渡す。 */}
          <EditTicketForm
            ticket={ticket}
            assignableActors={assignableActors}
            assignableActorsDegraded={assignableActorsDegraded}
            assignableActorsTruncated={assignableActorsTruncated}
          />
        </div>
      ) : null}

      <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
        <h2 className="text-lg font-semibold">アクティビティ</h2>
        {/* S-1: コメント入力欄は印刷物には出さない。コメント履歴 (timeline) は印刷する */}
        {isWritable ? (
          <div className="no-print mt-4">
            <CommentForm ticketId={ticket.id} onSubmit={addTicketCommentAction} />
          </div>
        ) : null}
        {activityEntries === null ? (
          <p className="mt-4 text-sm text-amber-700 dark:text-amber-300">
            アクティビティを読み込めませんでした。基本的な履歴のみ表示しています。
          </p>
        ) : null}
        <div className="mt-4">
          <ActivityTimeline entries={activityEntries ?? fallbackEntries} />
        </div>
      </article>
    </section>
  );
}
