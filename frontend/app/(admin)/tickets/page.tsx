import Link from "next/link";

import { fetchBackendRaw } from "@/lib/api/client";

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
  status: string;
};

async function loadProjects(): Promise<ProjectItem[]> {
  try {
    const res = await fetchBackendRaw("/api/v1/me/projects");
    const raw = res as Record<string, unknown>;
    return (raw?.projects ?? raw?.items ?? []) as ProjectItem[];
  } catch {
    return [];
  }
}

async function loadTickets(projectId: string): Promise<TicketItem[]> {
  try {
    const res = await fetchBackendRaw(
      `/api/v1/projects/${projectId}/tickets` as `/${string}`
    );
    const raw = res as Record<string, unknown>;
    return (raw?.items ?? []) as TicketItem[];
  } catch {
    return [];
  }
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
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${colors[status] ?? "bg-gray-100 text-gray-600"}`}
    >
      {labels[status] ?? status}
    </span>
  );
}

export default async function TicketsListPage() {
  const projects = await loadProjects();

  const projectTickets: { project: ProjectItem; tickets: TicketItem[] }[] = [];
  for (const p of projects) {
    const pid = String((p as Record<string, unknown>).project_id ?? (p as Record<string, unknown>).id ?? "");
    if (!pid) continue;
    const tickets = await loadTickets(pid);
    projectTickets.push({ project: p, tickets });
  }

  const totalTickets = projectTickets.reduce((sum, pt) => sum + pt.tickets.length, 0);

  return (
    <section aria-label="チケット一覧" className="grid gap-6">
      <header className="grid gap-2">
        <p className="text-sm font-medium text-accent">管理</p>
        <h1 className="text-3xl font-semibold tracking-normal">チケット一覧</h1>
        <p className="text-sm text-muted-foreground">
          全 {projects.length} プロジェクト / {totalTickets} チケット
        </p>
      </header>

      {projectTickets.length === 0 ? (
        <div className="rounded-lg border border-line bg-panel p-8 text-center">
          <p className="text-muted-foreground">プロジェクトが見つかりません</p>
        </div>
      ) : (
        projectTickets.map(({ project, tickets }) => (
          <article
            key={String((project as Record<string, unknown>).project_id ?? (project as Record<string, unknown>).id)}
            className="rounded-lg border border-line bg-panel shadow-sm"
          >
            <div className="flex items-center justify-between border-b border-line px-5 py-3">
              <div className="flex items-center gap-3">
                <h2 className="text-lg font-semibold">{project.name}</h2>
                <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-muted-foreground">
                  {project.slug}
                </span>
              </div>
              <span className="text-sm text-muted-foreground">
                {tickets.length} チケット
              </span>
            </div>

            {tickets.length === 0 ? (
              <div className="px-5 py-4 text-sm text-muted-foreground">
                チケットはまだありません
              </div>
            ) : (
              <div className="divide-y divide-line">
                {tickets.map((ticket) => (
                  <Link
                    key={ticket.id}
                    href={`/tickets/${ticket.id}` as never}
                    className="flex items-center justify-between px-5 py-3 transition-colors hover:bg-slate-50"
                  >
                    <div className="flex items-center gap-3">
                      {statusBadge(ticket.status)}
                      <span className="text-sm font-medium">{ticket.title}</span>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {ticket.created_at
                        ? new Date(ticket.created_at).toLocaleDateString("ja-JP")
                        : ""}
                    </span>
                  </Link>
                ))}
              </div>
            )}
          </article>
        ))
      )}
    </section>
  );
}
