import { notFound } from "next/navigation";

import { fetchBackendRaw } from "@/lib/api/client";
import { TicketStatusChanger } from "@/components/ticket-status-changer";
import { Breadcrumb } from "@/components/breadcrumb";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { ActivityTimeline } from "@/components/activity-timeline";
import { EditTicketForm } from "./_components/edit-ticket-form";
import { TicketDeleteButton } from "@/components/ticket-delete-button";
import { TrackRecentTicket } from "@/components/recent-tickets";

export const dynamic = "force-dynamic";

type TicketDetailPageProps = {
  params: Promise<{ id: string }>;
};

type TicketDetail = {
  id: string;
  title: string;
  slug: string;
  status: string;
  description: string | null;
  priority: string | null;
  due_date: string | null;
  created_at: string | null;
  updated_at: string | null;
  project_id: string;
  // 看板への戻り導線で使う project slug (tickets 一覧の ?project= は slug を期待する)。
  project_slug: string;
};

// due_date は SQL date (YYYY-MM-DD) のプレーンな日付。timezone を持たないため、
// new Date(...) / toLocaleDateString による変換は使わず文字列を直接整形する
// (UTC parse → JST 変換で日付が 1 日ずれる事故を防ぐ)。
function formatDueDate(value: string | null): string {
  if (!value) return "未設定";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return value;
  const [, year, month, day] = match;
  return `${year}/${month}/${day}`;
}

function statusBadge(status: string) {
  const colors: Record<string, string> = {
    open: "bg-blue-50 text-blue-700",
    in_progress: "bg-amber-50 text-amber-700",
    closed: "bg-gray-100 text-gray-500",
    cancelled: "bg-red-50 text-red-600",
  };
  const labels: Record<string, string> = {
    open: "未着手",
    in_progress: "進行中",
    closed: "完了",
    cancelled: "中止",
  };
  return (
    <span
      className={`rounded-full px-3 py-1 text-sm font-medium ${colors[status] ?? "bg-gray-100 text-gray-600"}`}
    >
      {labels[status] ?? status}
    </span>
  );
}

async function loadTicket(id: string): Promise<TicketDetail | null> {
  try {
    const projectsRes = await fetchBackendRaw("/api/v1/me/projects");
    const projects = ((projectsRes as Record<string, unknown>)?.projects ?? []) as Record<string, string>[];

    // 各 project の by-id detail endpoint を直接叩く。
    // 一覧 (default limit=50) を走査して find する旧実装だと、51 件以上ある project では
    // 新規作成直後の ticket が先頭 50 件に入らず 404 になり得た (Codex B2b R2 finding)。
    // by-id 取得なら project 内の件数に依存せず確実に解決する。
    const results = await Promise.all(
      projects.map(async (p) => {
        const pid = String(p.project_id ?? p.id ?? "");
        const slug = String(p.slug ?? "");
        if (!pid) return null;
        try {
          const ticketRes = await fetchBackendRaw(
            `/api/v1/projects/${pid}/tickets/${id}` as `/${string}`
          );
          const ticket = ticketRes as (TicketDetail & { id?: string }) | null;
          if (ticket && ticket.id === id) {
            return { ...ticket, project_id: pid, project_slug: slug };
          }
        } catch {
          /* 404 (別 project) / inaccessible project は skip */
        }
        return null;
      })
    );
    return results.find((r) => r !== null) ?? null;
  } catch {
    return null;
  }
}

export default async function TicketDetailPage({ params }: TicketDetailPageProps) {
  const { id } = await params;
  const ticket = await loadTicket(id);

  if (!ticket) {
    notFound();
  }

  return (
    <section aria-label="チケット詳細" className="grid gap-6">
      <TrackRecentTicket ticket={{ id: ticket.id, title: ticket.title, slug: ticket.slug }} />
      <header className="grid gap-2">
        <Breadcrumb items={[
          { label: "ダッシュボード", href: "/dashboard" },
          { label: "チケット", href: "/tickets" },
          { label: ticket.slug },
        ]} />
        <div className="flex items-center gap-4">
          <h1 className="text-3xl font-semibold tracking-normal">{ticket.title}</h1>
          {statusBadge(ticket.status)}
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
      <div className="grid gap-4 md:grid-cols-2">
        <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
          <h2 className="text-lg font-semibold">ステータス変更</h2>
          <div className="mt-4">
            <TicketStatusChanger ticketId={ticket.id} currentStatus={ticket.status} />
          </div>
        </article>

        <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
          <h2 className="text-lg font-semibold">アクション</h2>
          <div className="mt-4 grid gap-2">
            <a
              href={`/tickets?project=${ticket.project_slug}`}
              className="rounded-md border border-line px-4 py-2 text-center text-sm font-medium text-muted-foreground transition-colors hover:bg-slate-50"
            >
              プロジェクトの看板に戻る
            </a>
            {ticket.status !== "cancelled" ? (
              <TicketDeleteButton ticketId={ticket.id} projectId={ticket.project_id} />
            ) : null}
          </div>
        </article>
      </div>

      <EditTicketForm ticket={{
        ...ticket,
        assignee_actor_id: null,
        acceptance_criteria: null,
        evidence_ids: [],
        agent_run_ids: [],
      } as unknown as Parameters<typeof EditTicketForm>[0]["ticket"]} />

      <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
        <h2 className="text-lg font-semibold">アクティビティ</h2>
        <div className="mt-4">
          <ActivityTimeline entries={[
            ...(ticket.created_at ? [{
              id: "created",
              type: "event" as const,
              actor: null,
              body: "チケットが作成されました",
              created_at: ticket.created_at,
            }] : []),
            ...(ticket.updated_at && ticket.updated_at !== ticket.created_at ? [{
              id: "updated",
              type: "event" as const,
              actor: null,
              body: "チケットが更新されました",
              created_at: ticket.updated_at,
            }] : []),
          ]} />
        </div>
      </article>
    </section>
  );
}
