import Link from "next/link";
import { Suspense } from "react";

import { fetchBackendRaw } from "@/lib/api/client";
import { ProjectTab } from "@/components/project-tab";
import { TicketStatusIndicator } from "@/components/ticket-status-indicator";
import { TicketCreateDialog } from "@/components/ticket-create-dialog";
import { SearchBar } from "@/components/search-bar";
import { StatusFilter } from "@/components/status-filter";
import { PriorityFilter } from "@/components/priority-filter";
import { DateRangeFilter } from "@/components/date-range-filter";
import { ViewToggle } from "@/components/view-toggle";

export const dynamic = "force-dynamic";

type TicketItem = {
  id: string;
  title: string;
  status: string;
  priority: string | null;
  description: string | null;
  created_at: string | null;
};

type ProjectItem = {
  project_id?: string;
  id?: string;
  slug: string;
  name: string;
};

async function loadProjects(): Promise<ProjectItem[]> {
  try {
    const res = await fetchBackendRaw("/api/v1/me/projects");
    const raw = res as Record<string, unknown>;
    return ((raw?.projects ?? raw?.items ?? []) as ProjectItem[]);
  } catch {
    return [];
  }
}

async function loadTickets(projectId: string): Promise<TicketItem[]> {
  try {
    const res = await fetchBackendRaw(`/api/v1/projects/${projectId}/tickets?limit=200` as `/${string}`);
    const raw = res as Record<string, unknown>;
    return ((raw?.items ?? []) as TicketItem[]);
  } catch {
    return [];
  }
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

function TicketCard({ ticket, projectSlug }: { ticket: TicketItem; projectSlug?: string | undefined }) {
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

      {ticket.description && (
        <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
          {ticket.description}
        </p>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <TicketStatusIndicator status={ticket.status} />
        {priorityBadge(ticket.priority)}
        {projectSlug && (
          <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-muted-foreground">
            {projectSlug}
          </span>
        )}
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
  searchParams: Promise<{ project?: string; q?: string; status?: string; priority?: string; range?: string; view?: string; sort?: string }>;
};

export default async function TicketsKanbanPage({ searchParams }: Props) {
  const params = await searchParams;
  const selectedProject = params.project ?? "all";
  const searchQuery = params.q ?? "";
  const statusFilter = params.status ?? "";
  const priorityFilter = params.priority ?? "";
  const rangeFilter = params.range ?? "";
  const currentView = (params.view === "list" ? "list" : "kanban") as "kanban" | "list";
  const sortKey = params.sort ?? "created_desc";
  const projects = await loadProjects();

  let allTickets: (TicketItem & { projectSlug: string })[] = [];

  if (selectedProject === "all") {
    for (const p of projects) {
      const pid = String((p as Record<string, unknown>).project_id ?? (p as Record<string, unknown>).id ?? "");
      if (!pid) continue;
      const tickets = await loadTickets(pid);
      allTickets.push(...tickets.map((t) => ({ ...t, projectSlug: p.slug })));
    }
  } else {
    const project = projects.find((p) => p.slug === selectedProject);
    if (project) {
      const pid = String((project as Record<string, unknown>).project_id ?? (project as Record<string, unknown>).id ?? "");
      const tickets = await loadTickets(pid);
      allTickets = tickets.map((t) => ({ ...t, projectSlug: project.slug }));
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

  const grouped: Record<KanbanGroup, typeof allTickets> = { todo: [], active: [], done: [] };
  for (const ticket of filteredTickets) {
    const group = STATUS_TO_KANBAN[ticket.status] ?? "todo";
    grouped[group].push(ticket);
  }

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
          <ViewToggle currentView={currentView} />
        </div>
      </Suspense>

      {selectedProject === "all" ? (
        <div className="rounded-md border border-blue-200 bg-blue-50 px-4 py-2 text-xs text-blue-700">
          全プロジェクト横断表示中。チケットの作成・更新するにはプロジェクトを選択してください。
        </div>
      ) : (
        <TicketCreateDialog
          projectSlug={selectedProject}
          projectId={(() => {
            const p = projects.find((p) => p.slug === selectedProject);
            return p ? String((p as Record<string, unknown>).project_id ?? (p as Record<string, unknown>).id ?? "") : undefined;
          })()}
        />
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
                />
              ))}
            </KanbanColumnEnhanced>
          ))}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full text-sm">
            <thead className="bg-canvas text-left text-xs font-medium text-muted-foreground">
              <tr>
                <th className="px-4 py-3">タイトル</th>
                <th className="px-4 py-3">ステータス</th>
                <th className="px-4 py-3">優先度</th>
                {showProjectBadge && <th className="px-4 py-3">プロジェクト</th>}
                <th className="px-4 py-3">作成日</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {filteredTickets.map((ticket) => (
                <tr key={ticket.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <Link href={`/tickets/${ticket.id}` as never} className="font-medium text-accent hover:underline">
                      {ticket.title}
                    </Link>
                  </td>
                  <td className="px-4 py-3"><TicketStatusIndicator status={ticket.status} /></td>
                  <td className="px-4 py-3">{priorityBadge(ticket.priority)}</td>
                  {showProjectBadge && (
                    <td className="px-4 py-3 text-xs text-muted-foreground">{ticket.projectSlug}</td>
                  )}
                  <td className="px-4 py-3 text-xs text-muted-foreground">
                    {ticket.created_at ? new Date(ticket.created_at).toLocaleDateString("ja-JP") : ""}
                  </td>
                </tr>
              ))}
              {filteredTickets.length === 0 && (
                <tr>
                  <td colSpan={showProjectBadge ? 5 : 4} className="px-4 py-8 text-center text-muted-foreground">
                    チケットがありません
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
