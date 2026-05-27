import Link from "next/link";
import { Suspense } from "react";

import { fetchBackendRaw } from "@/lib/api/client";
import { KanbanColumn } from "@/components/kanban-column";
import { ProjectTab } from "@/components/project-tab";
import { TicketStatusIndicator } from "@/components/ticket-status-indicator";

export const dynamic = "force-dynamic";

type TicketItem = {
  id: string;
  title: string;
  status: string;
  priority: string | null;
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
    const res = await fetchBackendRaw(`/api/v1/projects/${projectId}/tickets` as `/${string}`);
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

const KANBAN_COLUMNS: { key: KanbanGroup; title: string; color: string }[] = [
  { key: "todo", title: "未着手", color: "bg-blue-50" },
  { key: "active", title: "進行中", color: "bg-amber-50" },
  { key: "done", title: "完了", color: "bg-emerald-50" },
];

function TicketCard({ ticket, projectSlug }: { ticket: TicketItem; projectSlug?: string | undefined }) {
  return (
    <Link
      href={`/tickets/${ticket.id}` as never}
      className="block rounded-md border border-line bg-panel p-3 shadow-sm transition-all hover:border-accent/30 hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm font-medium leading-tight">{ticket.title}</span>
        <TicketStatusIndicator status={ticket.status} />
      </div>
      <div className="mt-2 flex items-center gap-2">
        {projectSlug && (
          <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-muted-foreground">
            {projectSlug}
          </span>
        )}
        <span className="text-[10px] text-muted-foreground">
          {ticket.created_at ? new Date(ticket.created_at).toLocaleDateString("ja-JP") : ""}
        </span>
      </div>
    </Link>
  );
}

type Props = {
  searchParams: Promise<{ project?: string }>;
};

export default async function TicketsKanbanPage({ searchParams }: Props) {
  const params = await searchParams;
  const selectedProject = params.project ?? "all";
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

  const grouped: Record<KanbanGroup, typeof allTickets> = { todo: [], active: [], done: [] };
  for (const ticket of allTickets) {
    const group = STATUS_TO_KANBAN[ticket.status] ?? "todo";
    grouped[group].push(ticket);
  }

  const showProjectBadge = selectedProject === "all";

  return (
    <section aria-label="チケット看板ボード" className="grid gap-4">
      <header className="grid gap-2">
        <p className="text-sm font-medium text-accent">管理</p>
        <h1 className="text-3xl font-semibold tracking-normal">チケット</h1>
        <p className="text-sm text-muted-foreground">
          全 {allTickets.length} チケット
          {selectedProject !== "all" && ` — ${selectedProject}`}
        </p>
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

      {selectedProject !== "all" && (
        <p className="text-xs text-muted-foreground">
          ※ チケットの作成・更新はプロジェクトを選択してから行えます
        </p>
      )}
      {selectedProject === "all" && (
        <p className="text-xs text-muted-foreground">
          ※ 全プロジェクト横断表示中。作成・更新するにはプロジェクトを選択してください
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        {KANBAN_COLUMNS.map((col) => (
          <KanbanColumn
            key={col.key}
            title={col.title}
            count={grouped[col.key].length}
            color={col.color}
          >
            {grouped[col.key].map((ticket) => (
              <TicketCard
                key={ticket.id}
                ticket={ticket}
                projectSlug={showProjectBadge ? ticket.projectSlug : undefined}
              />
            ))}
          </KanbanColumn>
        ))}
      </div>
    </section>
  );
}
