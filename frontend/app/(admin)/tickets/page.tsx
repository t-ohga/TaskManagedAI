import Link from "next/link";
import type { Route } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { BackendApiError } from "@/lib/api/client";
import { getCurrentProject } from "@/lib/api/session";
import { fetchDateContext } from "@/lib/api/reminders";
import { fetchAssignableActors } from "@/lib/api/actors";
import {
  buildAssigneeNameMap,
  assigneeLabel,
  type AssignableActor
} from "@/lib/domain/assignee";
import {
  loadProjectTags,
  loadProjects,
  loadProjectsAllView,
  loadTickets,
  type LoadTicketsOptions,
  type ProjectBoardItem,
  type TicketItem
} from "@/lib/api/tickets-board";
import { mapWithConcurrency } from "@/lib/map-with-concurrency";
import type { TagRead } from "@/lib/domain/tag";
import { isValidYmd, ticketDueBucket, type DueDateBucket } from "@/lib/domain/due-date";
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
// 非実在日 / 不正形式は raw を echo せず null (R7 F-001: schema strict + defense-in-depth)。
function formatDueDate(value: string | null): string | null {
  if (!value || !isValidYmd(value)) return null;
  const [, month, day] = value.split("-");
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

// ADR-00054 (code review fix): status は backend へ渡すため、URL 由来の未知値を allowlist で弾く。
// 未知 status を backend (ticket_status: TicketStatus) に渡すと 422 になり、selected project は error
// boundary / all view は全 project omission で空画面に昇格する。未知値は「絞り込みなし」として扱う。
const VALID_TICKET_STATUSES = new Set(Object.keys(STATUS_TO_KANBAN));

// A-3 (board 体感改善): 横断 (all view) の per-project ticket fetch の同時実行上限。逐次 (=1) では
// project 数だけ round-trip が積み上がり遅い一方、無制限 Promise.all は project 数だけ同時 fetch を
// 投げ単一 VPS backend / DB pool を枯らす (Codex adversarial finding)。backend の SQLAlchemy pool は
// pool_size=5 + max_overflow=5 = 10 connection (backend/app/db/session.py)。board fan-out を pool budget
// の十分下に抑え、Wave 1 fetch / background worker / 複数同時 render の余地を残すため 3 並列に bound
// する (逐次よりは速く、無制限よりは安全)。将来 project 数が大きく増えるなら、all-view 集約を 1
// session/query budget で完結する backend endpoint へ移すのが root fix (本 perf PR では scope 外)。
const BOARD_FETCH_CONCURRENCY = 3;

const KANBAN_COLUMNS: { key: KanbanGroup; title: string; color: string; hint: string }[] = [
  { key: "todo", title: "未着手", color: "bg-blue-50 dark:bg-blue-950/40", hint: "新しいチケットがここに入ります" },
  { key: "active", title: "進行中", color: "bg-amber-50 dark:bg-amber-950/40", hint: "作業中・レビュー中・ブロック中のチケット" },
  { key: "done", title: "完了", color: "bg-emerald-50 dark:bg-emerald-950/40", hint: "完了したチケット（中止は既定で非表示）" },
];

function priorityBadge(priority: string | null | undefined) {
  if (!priority) return null;
  const colors: Record<string, string> = {
    critical: "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300",
    high: "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300",
    medium: "bg-yellow-100 dark:bg-yellow-900/40 text-yellow-700 dark:text-yellow-300",
    low: "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300",
  };
  const labels: Record<string, string> = {
    critical: "最優先",
    high: "高",
    medium: "中",
    low: "低",
  };
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${colors[priority] ?? "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300"}`}>
      {labels[priority] ?? priority}
    </span>
  );
}

// A-7 (ADR-00045): 期限 chip の色 (overdue=赤 / due_today・upcoming=橙 / future・基準日なし=neutral)。
function dueChipClass(bucket: DueDateBucket | null): string {
  switch (bucket) {
    case "overdue":
      return "bg-red-50 dark:bg-red-950/40 font-medium text-red-700 dark:text-red-300";
    case "due_today":
    case "upcoming":
      return "bg-amber-50 dark:bg-amber-950/40 font-medium text-amber-700 dark:text-amber-300";
    default:
      return "bg-slate-50 dark:bg-slate-800 text-muted-foreground";
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
  projectActive,
  referenceDate,
  thresholdDays,
  assigneeNameById,
}: {
  ticket: TicketItem;
  projectSlug?: string | undefined;
  projectActive: boolean;
  referenceDate?: string | undefined;
  thresholdDays?: number | undefined;
  // A-6: assignee UUID -> display_name 解決 map (取得失敗時は空 map → 中立 fallback)。
  assigneeNameById?: Map<string, string | null> | undefined;
}) {
  const formattedDue = formatDueDate(ticket.due_date);
  // project active + ticket status + 期限から強調 bucket を導出。archived project / 非 actionable
  // (closed/cancelled) / 基準日不明は null → neutral (backend reminders と同じゲートで画面間不整合・
  // 誤分類を防ぐ、R3 F-001 / R4 F-001)。
  const dueBucket = ticketDueBucket(
    ticket.due_date,
    ticket.status,
    projectActive,
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
        {projectSlug ? <span className="rounded bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-[10px] text-muted-foreground">
            {projectSlug}
          </span> : null}
        {formattedDue ? (
          <span className={`rounded px-1.5 py-0.5 text-[10px] ${dueChipClass(dueBucket)}`}>
            {dueChipPrefix(dueBucket)} {formattedDue}
          </span>
        ) : null}
        {/* A-6: 担当者が居るときのみ display_name chip (UUID 生表示はしない)。 */}
        {ticket.assignee_actor_id ? (
          <span className="rounded bg-indigo-50 dark:bg-indigo-950/40 px-1.5 py-0.5 text-[10px] text-indigo-700 dark:text-indigo-300">
            担当: {assigneeLabel(assigneeNameById ?? new Map(), ticket.assignee_actor_id)}
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
          <span className="rounded-full bg-panel/80 px-2 py-0.5 text-xs font-semibold tabular-nums">
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
  // ADR-00054 (code review fix): URL の未知 status は backend へ渡さず「絞り込みなし」に倒す
  // (422 を error boundary / project omission に昇格させない)。
  const rawStatusFilter = params.status ?? "";
  const statusFilter = VALID_TICKET_STATUSES.has(rawStatusFilter) ? rawStatusFilter : "";
  const priorityFilter = params.priority ?? "";
  const rangeFilter = params.range ?? "";
  const tagFilter = params.tag ?? "";
  const currentView = (params.view === "list" ? "list" : "kanban") as "kanban" | "list";
  const sortKey = params.sort ?? "created_desc";
  // 具体 project 選択中 or tag filter 適用中は project metadata を fail-closed で要求する
  // (取得失敗で「0 件」board を完全な結果として描画しない、Codex R5 HIGH)。
  // 横断 (all view) は fail-soft だが **row-level omission** で取得する (Codex R6 HIGH: 1 行の
  // malformed project が全 project を消すのを防ぎ、valid project を保持して omission を warning 化)。
  const isProjectFailClosed = selectedProject !== "all" || Boolean(tagFilter);

  // A-3 (board 体感改善): 独立した top-level fetch を並列化して逐次 await の round-trip 積み上げを
  // 畳む。ただし orchestration は path で分ける (R3 medium: 失敗時の無駄な backend fan-out を避ける):
  //  - optional fetch (currentProject / dateContext / assignableActors): 描画まで不要かつ独立。各々
  //    .catch で握り reject させない (floating rejection なし)。
  //  - currentProject: 作成 CTA 用 (Codex B2b: URL 選択と session current_project の乖離による
  //    wrong-project write 防止)。
  //  - dateContext: A-7 (ADR-00045 R2 F-002) の単一 "today" authority。失敗は fail-closed で null に
  //    倒し期限強調を neutral 化するが、R9 F-001 で ok/error を保持し degradation を warning 可視化する。
  //  - assignableActors: A-6 (ADR-00046) の担当者候補。truncated (cap 超過) と degraded (取得失敗) を
  //    別保持して可視化する (Codex adversarial F-A3)。
  const runOptionalFetches = () =>
    Promise.all([
      getCurrentProject().catch(() => null),
      fetchDateContext()
        .then((ctx) => ({ ok: true as const, ctx }))
        .catch(() => ({ ok: false as const })),
      fetchAssignableActors()
        .then((resp) => ({ ok: true as const, resp }))
        .catch(() => ({ ok: false as const })),
    ] as const);

  // projects は後続 (tags / tickets) の前提。
  //  - fail-closed 経路 (具体 project / tag filter 中): loadProjects(true) は reject しうる
  //    (→ error boundary)。projects を先に await し、成功後にだけ optional を並列化する。これにより
  //    project 一覧の auth/backend/schema 失敗時・retry 時に、結果に使えない optional fetch を投げて
  //    pool=10 を圧迫しない (pool 枯渇対策と方向を揃える)。旧逐次 4 本 → 2 波に短縮しつつ無駄打ちゼロ。
  //  - all-view 経路: loadProjectsAllView は内部で degraded / row-level omission に倒れ reject しない
  //    (optional 結果は degraded でも全て描画に使う) ため、projects と optional を 1 波で並列化する。
  let projectsResult: { items: ProjectBoardItem[]; omittedProjects: number; degraded: boolean };
  let optional: Awaited<ReturnType<typeof runOptionalFetches>>;
  if (isProjectFailClosed) {
    projectsResult = { items: await loadProjects(true), omittedProjects: 0, degraded: false };
    optional = await runOptionalFetches();
  } else {
    [projectsResult, optional] = await Promise.all([loadProjectsAllView(), runOptionalFetches()]);
  }
  const [currentProject, dateContextResult, assignableActorsResult] = optional;

  const projects: ProjectBoardItem[] = projectsResult.items;
  // malformedProjects: all view の row-level omission 件数 (fail-closed 経路は 0)。
  const malformedProjects = projectsResult.omittedProjects;
  // R10 F-001: all view の whole-list failure (project 一覧そのものが読めない) を空状態と区別する。
  const projectListDegraded = projectsResult.degraded;

  const referenceDate = dateContextResult.ok ? dateContextResult.ctx.reference_date : undefined;
  const thresholdDays = dateContextResult.ok ? dateContextResult.ctx.threshold_days : undefined;

  let assignableActors: AssignableActor[] = [];
  let assignableActorsTruncated = false;
  const assignableActorsDegraded = !assignableActorsResult.ok;
  if (assignableActorsResult.ok) {
    assignableActors = assignableActorsResult.resp.actors;
    assignableActorsTruncated = assignableActorsResult.resp.truncated;
  }
  const assigneeNameById = buildAssigneeNameMap(assignableActors);

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

  // projectActive: 各 ticket の project が active か (R4 F-001: archived project の ticket は
  // 期限強調しない、backend reminders の projects.status='active' と整合)。
  let allTickets: (TicketItem & { projectSlug: string; projectActive: boolean })[] = [];
  // ADR-00054: status 絞り込みは backend (pagination 前、全件 in-memory) で適用する。statusFilter
  // 指定時は exact filter、未指定の既定 board は中止を除外する。client-side status filter / cancelled
  // 除外は撤去した (cap 越えの非対象 ticket を誤って隠さない、plan-review R1/R3)。
  const ticketLoadOptions: LoadTicketsOptions = statusFilter
    ? { status: statusFilter }
    : { excludeCancelled: true };
  // ADR-00054: status filter 前 (tag filter 後) の合計件数 (中止のみ/真の空 区別用) と truncation 集約。
  let boardTotalUnfiltered = 0;
  let boardTruncated = false;
  // tag 絞り込みは specific project でのみ backend query を使う (all view は project 混在で
  // tag scope が曖昧)。指定タグが無効 (404) のときは絞り込みを解除して全件を出し、UI で通知する。
  let tagFilterInvalid = false;
  // tag 絞り込み結果が limit を超えて truncate された場合の通知 (不完全を完全と見せない、R3 HIGH)。
  let tagFilterTruncated: { total: number; shown: number } | null = null;

  // 横断 (all view) で除外した project 数 (fail-soft、欠落を warning で可視化)。malformed な project
  // metadata (R6 row-level omission) + ticket fetch 失敗の両方を含める。
  let omittedProjects = malformedProjects;

  if (selectedProject === "all") {
    // A-3 (board 体感改善): project ごとの ticket fetch を逐次 await から bounded 並列に変える。N
    // project の round-trip を畳む (横断 view の体感遅延の主要因) 一方、無制限 fan-out で単一 VPS
    // backend / DB pool を枯らさないよう同時実行数を BOARD_FETCH_CONCURRENCY で bound する (Codex
    // adversarial finding)。fail-soft の per-project omission を保持するため各 fetch を try/catch で
    // ラップして「結果 / 欠落 / skip」に正規化し (callback が reject しないので helper も reject しない
    // = fail-soft 維持)、mapWithConcurrency の入力順保証 (projects 配列順) を使って集約 (allTickets /
    // boardTotalUnfiltered / boardTruncated) を決定的に保つ。
    const boards = await mapWithConcurrency(projects, BOARD_FETCH_CONCURRENCY, async (p) => {
      const pid = String(
        (p as Record<string, unknown>).project_id ?? (p as Record<string, unknown>).id ?? ""
      );
      if (!pid) return { kind: "skip" as const };
      try {
        const board = await loadTickets(pid, undefined, ticketLoadOptions);
        return { kind: "ok" as const, project: p, board };
      } catch {
        // all view は 1 project の一時障害で全体を落とさず、欠落を warning で可視化 (fail-soft)。
        return { kind: "omit" as const };
      }
    });
    for (const result of boards) {
      if (result.kind === "ok") {
        const projectActive = result.project.status === "active";
        allTickets.push(
          ...result.board.items.map((t) => ({
            ...t,
            projectSlug: result.project.slug,
            projectActive,
          }))
        );
        boardTotalUnfiltered += result.board.totalUnfiltered;
        if (result.board.truncated) boardTruncated = true;
      } else if (result.kind === "omit") {
        omittedProjects += 1;
      }
      // kind === "skip" (pid 欠落) は現状の `continue` と同じく集約に寄与しない。
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
      const projectActive = project.status === "active";
      if (tagFilter) {
        try {
          const board = await loadTickets(pid, tagFilter, ticketLoadOptions);
          allTickets = board.items.map((t) => ({ ...t, projectSlug: project.slug, projectActive }));
          boardTotalUnfiltered += board.totalUnfiltered;
          if (board.truncated) {
            boardTruncated = true;
            tagFilterTruncated = { total: board.total, shown: board.items.length };
          }
        } catch (error) {
          if (error instanceof BackendApiError && error.status === 404) {
            // 無効タグ (cross-project / nonexistent / soft-deleted) のみ絞り込み解除して全件取得。
            // fallback の loadTickets も失敗を throw → error boundary に流す (fail-closed、R5 HIGH:
            // 「filter cleared, all displayed」を 0 件で見せない)。
            tagFilterInvalid = true;
            const board = await loadTickets(pid, undefined, ticketLoadOptions);
            allTickets = board.items.map((t) => ({ ...t, projectSlug: project.slug, projectActive }));
            boardTotalUnfiltered += board.totalUnfiltered;
            if (board.truncated) boardTruncated = true;
          } else {
            // auth / backend / network 障害は「該当なし」と誤表示せず error boundary に流す
            // (fail-closed、Codex frontend R2 HIGH)。
            throw error;
          }
        }
      } else {
        // selected-project load は fail-closed (loadTickets が throw → error boundary、R5 HIGH:
        // 障害を「ticket 0 件の project」と誤表示しない)。
        const board = await loadTickets(pid, undefined, ticketLoadOptions);
        allTickets = board.items.map((t) => ({ ...t, projectSlug: project.slug, projectActive }));
        boardTotalUnfiltered += board.totalUnfiltered;
        if (board.truncated) boardTruncated = true;
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
  // ADR-00054: status 絞り込み (statusFilter 指定の exact / 既定 board の中止除外) は backend
  // (pagination 前) で適用済のため、ここでの client-side status filter は撤去した。search /
  // priority / range は引き続き client-side (pre-existing、cap 越えは truncation 警告で可視化)。
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
  // ADR-00054 表示ルール:
  // - 純粋な既定 view = statusFilter 未指定 AND q/priority/range 未指定 (client-side filter なし)。
  //   この時のみ server count (allTickets=非中止) と実画面が一致し、cancelled-only/真の空 を区別できる。
  const pureDefaultView =
    !statusFilter && !searchQuery && !priorityFilter && !rangeFilter;
  // - 純粋既定 view かつ非 truncated で、非中止が 0 件だが ticket 自体は存在 (=中止のみ) →
  //   silent empty にせず hint を出す。文言は「現在の表示条件」scope (project 全体を断定しない)。
  // - (code review fix) all view で project/ticket 取得が欠落 (omittedProjects / projectListDegraded)
  //   している間は「中止のみ」と断定しない。読めなかった project に非中止がある可能性があり、
  //   fail-soft 欠落 warning を優先する (誤った復旧行動を促さない)。
  const cancelledOnlyEmpty =
    pureDefaultView &&
    !boardTruncated &&
    omittedProjects === 0 &&
    !projectListDegraded &&
    totalAll === 0 &&
    boardTotalUnfiltered > 0;
  // - truncation 警告は board.truncated の時は常に出す (default / status=中止>200 / client filter を
  //   一律カバー)。tag 専用の詳細警告 (tagFilterTruncated) がある時はそちらに委ねる。
  const showBoardTruncatedWarning = boardTruncated && tagFilterTruncated === null;

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
          <div className="rounded-md border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 px-4 py-2 text-xs text-amber-700 dark:text-amber-300">
            選択したタグが見つからないため、絞り込みを解除して全件を表示しています。
          </div>
        ) : null}
        {tagFilterTruncated ? (
          <div className="rounded-md border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 px-4 py-2 text-xs text-amber-700 dark:text-amber-300">
            このタグには {tagFilterTruncated.total} 件のチケットがマッチしますが、最初の
            {tagFilterTruncated.shown} 件のみ表示しています。すべて確認するにはステータスや期間で
            さらに絞り込んでください。
          </div>
        ) : null}
        {/* ADR-00054: board.truncated の時は常に不完全を可視化する (default / status=中止>200 /
            client-side filter を一律カバー、cap 越えを silent partial にしない)。 */}
        {showBoardTruncatedWarning ? (
          <div role="status" className="rounded-md border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 px-4 py-2 text-xs text-amber-700 dark:text-amber-300">
            チケット件数が多いため一部のみ読み込んでいます。検索 / 期限 / 優先度の絞り込み結果や
            件数は不完全な可能性があります。ステータスやタグでさらに絞り込んでください。
          </div>
        ) : null}
        {/* ADR-00054: 純粋既定 view で表示対象が中止のみ (silent empty 回避)。文言は「現在の表示
            条件」scope で project 全体を断定しない (tag/scope 由来の誤誘導を避ける)。 */}
        {cancelledOnlyEmpty ? (
          <div role="status" className="rounded-md border border-sky-200 dark:border-sky-800 bg-sky-50 dark:bg-sky-950/40 px-4 py-2 text-xs text-sky-700 dark:text-sky-300">
            現在の表示条件では中止チケットのみです。ステータスで「中止」を選ぶと表示されます。
          </div>
        ) : null}
        {/* R10 F-001: 横断表示で project 一覧そのものが読めなかった (auth 失効 / backend 障害 /
            schema drift) を「project/ticket が無い空状態」と区別して可視化する (silent empty board
            を避ける)。 */}
        {projectListDegraded ? (
          <div role="status" className="rounded-md border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 px-4 py-2 text-xs text-amber-700 dark:text-amber-300">
            プロジェクト一覧を取得できなかったため、横断表示のチケットを表示できません
            (チケットが 0 件なのではなく取得失敗です)。時間をおいて再読み込みしてください。
          </div>
        ) : null}
        {omittedProjects > 0 ? (
          <div className="rounded-md border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 px-4 py-2 text-xs text-amber-700 dark:text-amber-300">
            {omittedProjects} 件のプロジェクトのチケットを取得できなかったため、一覧から除外しています。
            時間をおいて再読み込みしてください。
          </div>
        ) : null}
        {/* R9 F-001: date_context (期限の基準日) 取得失敗を可視化する。期限強調 (超過/本日/期限間近) は
            誤表示を避けるため neutral に倒すが、失敗を silent にせず警告する (dashboard reminder と
            silent に乖離させない)。期限の日付自体は表示される。 */}
        {!dateContextResult.ok ? (
          <div role="status" className="rounded-md border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 px-4 py-2 text-xs text-amber-700 dark:text-amber-300">
            期限の基準日を取得できなかったため、期限の強調表示 (超過 / 本日 / 期限間近) を一時的に無効にしています。
            期限の日付は表示されますが、色分けされません。時間をおいて再読み込みしてください。
          </div>
        ) : null}
        {/* A-6 (Codex adversarial F-A3): 担当者候補の取得失敗 / cap 超過を可視化する。silent に空候補や
            部分候補を見せず、作成フォームの担当者選択が不完全であることを明示する。 */}
        {assignableActorsDegraded ? (
          <div role="status" className="rounded-md border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 px-4 py-2 text-xs text-amber-700 dark:text-amber-300">
            担当者候補を取得できませんでした。新規チケットは未割当で作成され、既存の担当者は名前ではなく
            「担当者 (不明)」と表示される場合があります。時間をおいて再読み込みしてください。
          </div>
        ) : assignableActorsTruncated ? (
          <div role="status" className="rounded-md border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 px-4 py-2 text-xs text-amber-700 dark:text-amber-300">
            担当者が多いため候補の一部のみ表示しています。候補一覧に無い担当者は新規割り当てできず、
            該当する既存の担当者は「担当者 (不明)」と表示される場合があります。
          </div>
        ) : null}
      </Suspense>

      {selectedProject === "all" ? (
        // C-4 UX fix (Mac 実機検証所見): 「なぜ作成ボタンが無いのか」を説明だけで終わらせず、
        // 現在プロジェクトの view へ 1 click で移動できる actionable な導線を併置する。
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/40 px-4 py-2 text-xs text-blue-700 dark:text-blue-300">
          <span>全プロジェクト横断表示中。チケットの作成・更新はプロジェクト単位で行います。</span>
          {currentProject ? (
            <Link
              href={`/tickets?project=${encodeURIComponent(currentProject.slug)}` as Route}
              className="inline-flex items-center rounded-md border border-blue-300 dark:border-blue-700 px-2.5 py-1 font-medium hover:bg-blue-100 dark:hover:bg-blue-900/40"
            >
              + 「{currentProject.name}」でチケットを作成
            </Link>
          ) : null}
        </div>
      ) : currentProject && selectedProject === currentProject.slug ? (
        <TicketCreateDialog assignableActors={assignableActors} />
      ) : (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 px-4 py-2 text-xs text-amber-700 dark:text-amber-300">
          <span>
            チケットは現在のプロジェクト
            {currentProject ? `「${currentProject.name}」` : ""}に作成されます。
            {currentProject
              ? ""
              : "現在のプロジェクトを取得できませんでした。再読み込みしてください。"}
          </span>
          {currentProject ? (
            <Link
              href={`/tickets?project=${encodeURIComponent(currentProject.slug)}` as Route}
              className="inline-flex items-center rounded-md border border-amber-300 dark:border-amber-700 px-2.5 py-1 font-medium hover:bg-amber-100 dark:hover:bg-amber-900/40"
            >
              + 「{currentProject.name}」でチケットを作成
            </Link>
          ) : null}
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
                  projectActive={ticket.projectActive}
                  referenceDate={referenceDate}
                  thresholdDays={thresholdDays}
                  assigneeNameById={assigneeNameById}
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
            projectActive: t.projectActive,
            due_date: t.due_date,
            created_at: t.created_at,
            assignee_actor_id: t.assignee_actor_id,
            tags: t.tags,
          }))}
          showProjectBadge={showProjectBadge}
          referenceDate={referenceDate}
          thresholdDays={thresholdDays}
          assigneeNameById={assigneeNameById}
        />
      )}
    </section>
  );
}
