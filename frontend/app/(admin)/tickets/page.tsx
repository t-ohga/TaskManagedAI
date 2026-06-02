import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { BackendApiError } from "@/lib/api/client";
import { getCurrentProject } from "@/lib/api/session";
import { fetchDateContext } from "@/lib/api/reminders";
import {
  loadProjectTags,
  loadProjects,
  loadTickets,
  type TicketItem
} from "@/lib/api/tickets-board";
import type { TagRead } from "@/lib/domain/tag";
import { ticketDueBucket, type DueDateBucket } from "@/lib/domain/due-date";
import { ProjectTab } from "@/components/project-tab";
import { TicketStatusIndicator } from "@/components/ticket-status-indicator";
import { TicketCreateDialog } from "@/components/ticket-create-dialog";
import { TagChip } from "@/components/tag-chip";
import { TagFilter } from "@/components/tag-filter";
import { SearchBar } from "@/components/search-bar";
import { StatusFilter } from "@/components/status-filter";
import { PriorityFilter } from "@/components/priority-filter";
import { DateRangeFilter } from "@/components/date-range-filter";
import { SortControl } from "@/components/sort-control";
import { ViewToggle } from "@/components/view-toggle";
import { SelectableTicketList } from "@/components/selectable-ticket-list";

export const dynamic = "force-dynamic";

// due_date は SQL date (YYYY-MM-DD) のプレーンな暦日。timezone を持たないため
// new Date(...) を介さず文字列から直接整形し、JST 変換による日付ずれを防ぐ。
function formatDueDate(value: string | null): string | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return value;
  const [, , month, day] = match;
  return `${Number(month)}/${Number(day)}`;
}

type KanbanGroup = "todo" | "active" | "done";

const STATUS_TO_KANBAN: Record<string, KanbanGroup> = {
  open: "todo",
  in_progress: "active",
  blocked: "active",
  review: "active",
  closed: "done",
  cancelled: "done",
};

const KANBAN_COLUMNS: { key: KanbanGroup; title: string; color: string; hint: string }[] = [
  { key: "todo", title: "未着手", color: "bg-blue-50", hint: "新しいチケットがここに入ります" },
  { key: "active", title: "進行中", color: "bg-amber-50", hint: "作業中・レビュー中・ブロック中のチケット" },
  { key: "done", title: "完了", color: "bg-emerald-50", hint: "完了・中止されたチケット" },
];

function priorityBadge(priority: string | null | undefined) {
  if (!priority) return null;
  const colors: Record<string, string> = {
    critical: "bg-red-100 text-red-700",
    high: "bg-orange-100 text-orange-700",
    medium: "bg-yellow-100 text-yellow-700",
    low: "bg-blue-100 text-blue-700",
  };
  const labels: Record<string, string> = {
    critical: "最優先",
    high: "高",
    medium: "中",
    low: "低",
  };
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${colors[priority] ?? "bg-gray-100 text-gray-600"}`}>
      {labels[priority] ?? priority}
    </span>
  );
}

// A-7 (ADR-00045): 期限 chip の色 (overdue=赤 / due_today・upcoming=橙 / future・基準日なし=neutral)。
function dueChipClass(bucket: DueDateBucket | null): string {
  switch (bucket) {
    case "overdue":
      return "bg-red-50 font-medium text-red-700";
    case "due_today":
    case "upcoming":
      return "bg-amber-50 font-medium text-amber-700";
    default:
      return "bg-slate-50 text-muted-foreground";
  }
}

// 色だけに依存しない (a11y): overdue / due_today は接頭ラベルでも区別する。
function dueChipPrefix(bucket: DueDateBucket | null): string {
  if (bucket === "overdue") return "超過";
  if (bucket === "due_today") return "本日";
  return "期限";
}

function TicketCard({
  ticket,
  projectSlug,
  referenceDate,
  thresholdDays,
}: {
  ticket: TicketItem;
  projectSlug?: string | undefined;
  referenceDate?: string | undefined;
  thresholdDays?: number | undefined;
}) {
  const formattedDue = formatDueDate(ticket.due_date);
  // status + 期限から強調 bucket を導出。非 actionable (closed/cancelled) / 基準日不明は null
  // → neutral (backend reminders の actionable 集合と揃え、画面間不整合・誤分類を防ぐ、R3 F-001)。
  const dueBucket = ticketDueBucket(
    ticket.due_date,
    ticket.status,
    referenceDate,
    thresholdDays
  );
  return (
    <Link
      href={`/tickets/${ticket.id}` as never}
      className="group block rounded-lg border border-line bg-panel p-3 shadow-sm transition-all hover:border-accent/40 hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-2">
        <h4 className="text-sm font-medium leading-tight group-hover:text-accent">
          {ticket.title}
        </h4>
      </div>

      {ticket.description ? <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
          {ticket.description}
        </p> : null}

      {ticket.tags.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1">
          {ticket.tags.map((tag) => (
            <TagChip key={tag.id} name={tag.name} color={tag.color} />
          ))}
        </div>
      ) : null}

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <TicketStatusIndicator status={ticket.status} />
        {priorityBadge(ticket.priority)}
        {projectSlug ? <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-muted-foreground">
            {projectSlug}
          </span> : null}
        {formattedDue ? (
          <span className={`rounded px-1.5 py-0.5 text-[10px] ${dueChipClass(dueBucket)}`}>
            {dueChipPrefix(dueBucket)} {formattedDue}
          </span>
        ) : null}
        <span className="ml-auto text-[10px] text-muted-foreground">
          {ticket.created_at ? new Date(ticket.created_at).toLocaleDateString("ja-JP") : ""}
        </span>
      </div>
    </Link>
  );
}

function KanbanColumnEnhanced({
  title,
  count,
  color,
  hint,
  children,
}: {
  title: string;
  count: number;
  color: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-[400px] flex-col rounded-lg border border-line bg-canvas">
      <div className={`flex items-center justify-between rounded-t-lg border-b border-line px-4 py-3 ${color}`}>
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold">{title}</h3>
          <span className="rounded-full bg-white/80 px-2 py-0.5 text-xs font-semibold tabular-nums">
            {count}
          </span>
        </div>
      </div>
      <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-3">
        {count === 0 ? (
          <div className="flex flex-1 items-center justify-center">
            <p className="text-center text-xs text-muted-foreground">{hint}</p>
          </div>
        ) : (
          children
        )}
      </div>
    </div>
  );
}

type Props = {
  searchParams: Promise<{ project?: string; q?: string; status?: string; priority?: string; range?: string; view?: string; sort?: string; tag?: string }>;
};

export default async function TicketsKanbanPage({ searchParams }: Props) {
  const params = await searchParams;
  const selectedProject = params.project ?? "all";
  const searchQuery = params.q ?? "";
  const statusFilter = params.status ?? "";
  const priorityFilter = params.priority ?? "";
  const rangeFilter = params.range ?? "";
  const tagFilter = params.tag ?? "";
  const currentView = (params.view === "list" ? "list" : "kanban") as "kanban" | "list";
  const sortKey = params.sort ?? "created_desc";
  // 具体 project 選択中 or tag filter 適用中は project metadata を fail-closed で要求する
  // (取得失敗で「0 件」board を完全な結果として描画しない、Codex R5 HIGH)。横断時は fail-soft。
  const projects = await loadProjects(selectedProject !== "all" || Boolean(tagFilter));
  // 作成先は server action が session の current_project から resolve する。
  // 表示中 project (URL ?project=) と current_project が一致するときだけ作成 CTA を出す
  // (Codex B2b finding: URL 選択と session current_project の乖離による wrong-project write 防止)。
  const currentProject = await getCurrentProject().catch(() => null);
  // A-7 (ADR-00045 R2 F-002): 期限強調用の単一 "today" authority を一度だけ取得する (all view の
  // 複数 list 呼びでも全 row に同一基準を適用)。取得失敗 / schema 不正は fail-closed で null に倒し、
  // 基準日不明のまま赤/橙を誤表示せず neutral 表示にする。
  const dateContext = await fetchDateContext().catch(() => null);
  const referenceDate = dateContext?.reference_date;
  const thresholdDays = dateContext?.threshold_days;

  // ADR-00044 (A-5): tag filter 用に specific project の tags を取得 (all view は project 混在で
  // tag scope が曖昧なため非表示)。tagFilter 適用中は fail-closed (tag metadata が読めない状態で
  // 絞り込み済み subset を「全件」と誤認させない、Codex R4 HIGH)、未適用時は fail-soft。
  let projectTags: TagRead[] = [];
  if (selectedProject !== "all") {
    const selProject = projects.find((p) => p.slug === selectedProject);
    if (selProject) {
      const pid = String(
        (selProject as Record<string, unknown>).project_id ??
          (selProject as Record<string, unknown>).id ??
          ""
      );
      if (pid) {
        projectTags = await loadProjectTags(pid, Boolean(tagFilter));
      }
    }
  }

  let allTickets: (TicketItem & { projectSlug: string })[] = [];
  // tag 絞り込みは specific project でのみ backend query を使う (all view は project 混在で
  // tag scope が曖昧)。指定タグが無効 (404) のときは絞り込みを解除して全件を出し、UI で通知する。
  let tagFilterInvalid = false;
  // tag 絞り込み結果が limit を超えて truncate された場合の通知 (不完全を完全と見せない、R3 HIGH)。
  let tagFilterTruncated: { total: number; shown: number } | null = null;

  // 横断 (all view) で取得に失敗した project 数 (fail-soft、欠落を warning で可視化)。
  let omittedProjects = 0;

  if (selectedProject === "all") {
    for (const p of projects) {
      const pid = String((p as Record<string, unknown>).project_id ?? (p as Record<string, unknown>).id ?? "");
      if (!pid) continue;
      try {
        const board = await loadTickets(pid);
        allTickets.push(...board.items.map((t) => ({ ...t, projectSlug: p.slug })));
      } catch {
        // all view は 1 project の一時障害で全体を落とさず、欠落を warning で可視化 (fail-soft)。
        omittedProjects += 1;
      }
    }
  } else {
    const project = projects.find((p) => p.slug === selectedProject);
    if (!project) {
      // selectedProject の slug が /me/projects に解決できない (stale URL / 権限欠落 / degraded
      // response で slug 欠落)。空 board を「0 件」と誤表示せず fail-closed で notFound に倒す
      // (Codex R6 HIGH)。
      notFound();
    }
    {
      const pid = String((project as Record<string, unknown>).project_id ?? (project as Record<string, unknown>).id ?? "");
      if (!pid) {
        // project row は解決できたが id/project_id が欠落 (degraded response)。同様に fail-closed。
        notFound();
      }
      if (tagFilter) {
        try {
          const board = await loadTickets(pid, tagFilter);
          allTickets = board.items.map((t) => ({ ...t, projectSlug: project.slug }));
          if (board.truncated) {
            tagFilterTruncated = { total: board.total, shown: board.items.length };
          }
        } catch (error) {
          if (error instanceof BackendApiError && error.status === 404) {
            // 無効タグ (cross-project / nonexistent / soft-deleted) のみ絞り込み解除して全件取得。
            // fallback の loadTickets も失敗を throw → error boundary に流す (fail-closed、R5 HIGH:
            // 「filter cleared, all displayed」を 0 件で見せない)。
            tagFilterInvalid = true;
            const board = await loadTickets(pid);
            allTickets = board.items.map((t) => ({ ...t, projectSlug: project.slug }));
          } else {
            // auth / backend / network 障害は「該当なし」と誤表示せず error boundary に流す
            // (fail-closed、Codex frontend R2 HIGH)。
            throw error;
          }
        }
      } else {
        // selected-project load は fail-closed (loadTickets が throw → error boundary、R5 HIGH:
        // 障害を「ticket 0 件の project」と誤表示しない)。
        const board = await loadTickets(pid);
        allTickets = board.items.map((t) => ({ ...t, projectSlug: project.slug }));
      }
    }
  }

  let filteredTickets = allTickets;
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    filteredTickets = filteredTickets.filter((t) =>
      t.title.toLowerCase().includes(q) || (t.description?.toLowerCase().includes(q) ?? false)
    );
  }
  if (statusFilter) {
    filteredTickets = filteredTickets.filter((t) => t.status === statusFilter);
  }
  if (priorityFilter) {
    filteredTickets = filteredTickets.filter((t) => t.priority === priorityFilter);
  }
  // tag 絞り込みは loadTickets の backend tag_id query で適用済 (client-side filter は不要)。
  if (rangeFilter) {
    const now = new Date();
    const cutoff = new Date();
    if (rangeFilter === "today") cutoff.setHours(0, 0, 0, 0);
    else if (rangeFilter === "week") cutoff.setDate(now.getDate() - 7);
    else if (rangeFilter === "month") cutoff.setMonth(now.getMonth() - 1);
    else if (rangeFilter === "quarter") cutoff.setMonth(now.getMonth() - 3);
    filteredTickets = filteredTickets.filter((t) =>
      t.created_at ? new Date(t.created_at) >= cutoff : false
    );
  }

  // C-3 (Codex review fix): sort を grouped 構築の前に適用する。grouped (Kanban) は filteredTickets
  // から作られるため、後でソートすると Kanban カード順が変わらず list 表示しか並ばなかった。
  const PRIORITY_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
  if (sortKey === "priority") {
    filteredTickets.sort((a, b) => (PRIORITY_RANK[a.priority ?? ""] ?? 99) - (PRIORITY_RANK[b.priority ?? ""] ?? 99));
  } else if (sortKey === "title") {
    filteredTickets.sort((a, b) => a.title.localeCompare(b.title, "ja"));
  } else if (sortKey === "status") {
    filteredTickets.sort((a, b) => a.status.localeCompare(b.status));
  } else {
    filteredTickets.sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
  }

  const grouped: Record<KanbanGroup, typeof allTickets> = { todo: [], active: [], done: [] };
  for (const ticket of filteredTickets) {
    const group = STATUS_TO_KANBAN[ticket.status] ?? "todo";
    grouped[group].push(ticket);
  }

  const showProjectBadge = selectedProject === "all";
  const totalFiltered = filteredTickets.length;
  const totalAll = allTickets.length;

  return (
    <section aria-label="チケット看板ボード" className="grid gap-4">
      <header className="grid gap-2">
        <p className="text-sm font-medium text-accent">管理</p>
        <h1 className="text-3xl font-semibold tracking-normal">チケット</h1>
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <span>{totalFiltered === totalAll ? `全 ${totalAll}` : `${totalFiltered} / ${totalAll}`} チケット</span>
          <span className="text-muted-foreground/50">|</span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-blue-500" />
            未着手 {grouped.todo.length}
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-amber-500" />
            進行中 {grouped.active.length}
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" />
            完了 {grouped.done.length}
          </span>
        </div>
      </header>

      <Suspense fallback={<div className="text-sm text-muted-foreground">読み込み中...</div>}>
        <ProjectTab
          projects={projects.map((p) => ({
            id: String((p as Record<string, unknown>).project_id ?? (p as Record<string, unknown>).id ?? ""),
            slug: p.slug,
            name: p.name,
          }))}
        />
      </Suspense>

      <Suspense fallback={null}>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex-1"><SearchBar /></div>
          <StatusFilter />
          <PriorityFilter />
          <DateRangeFilter />
          <SortControl />
          <ViewToggle currentView={currentView} />
        </div>
        {projectTags.length > 0 ? <TagFilter tags={projectTags} /> : null}
        {tagFilterInvalid ? (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-700">
            選択したタグが見つからないため、絞り込みを解除して全件を表示しています。
          </div>
        ) : null}
        {tagFilterTruncated ? (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-700">
            このタグには {tagFilterTruncated.total} 件のチケットがマッチしますが、最初の
            {tagFilterTruncated.shown} 件のみ表示しています。すべて確認するにはステータスや期間で
            さらに絞り込んでください。
          </div>
        ) : null}
        {omittedProjects > 0 ? (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-700">
            {omittedProjects} 件のプロジェクトのチケットを取得できなかったため、一覧から除外しています。
            時間をおいて再読み込みしてください。
          </div>
        ) : null}
      </Suspense>

      {selectedProject === "all" ? (
        <div className="rounded-md border border-blue-200 bg-blue-50 px-4 py-2 text-xs text-blue-700">
          全プロジェクト横断表示中。チケットの作成・更新するにはプロジェクトを選択してください。
        </div>
      ) : currentProject && selectedProject === currentProject.slug ? (
        <TicketCreateDialog />
      ) : (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-700">
          チケットは現在のプロジェクト
          {currentProject ? `「${currentProject.name}」` : ""}に作成されます。
          {currentProject
            ? `この project でチケットを作成するには、上のタブで「${currentProject.name}」を選択してください。`
            : "現在のプロジェクトを取得できませんでした。再読み込みしてください。"}
        </div>
      )}

      {currentView === "kanban" ? (
        <div className="grid gap-4 lg:grid-cols-3">
          {KANBAN_COLUMNS.map((col) => (
            <KanbanColumnEnhanced
              key={col.key}
              title={col.title}
              count={grouped[col.key].length}
              color={col.color}
              hint={col.hint}
            >
              {grouped[col.key].map((ticket) => (
                <TicketCard
                  key={ticket.id}
                  ticket={ticket}
                  projectSlug={showProjectBadge ? ticket.projectSlug : undefined}
                  referenceDate={referenceDate}
                  thresholdDays={thresholdDays}
                />
              ))}
            </KanbanColumnEnhanced>
          ))}
        </div>
      ) : (
        <SelectableTicketList
          tickets={filteredTickets.map((t) => ({
            id: t.id,
            title: t.title,
            status: t.status,
            priority: t.priority,
            projectSlug: t.projectSlug,
            due_date: t.due_date,
            created_at: t.created_at,
            tags: t.tags,
          }))}
          showProjectBadge={showProjectBadge}
          referenceDate={referenceDate}
          thresholdDays={thresholdDays}
        />
      )}
    </section>
  );
}
