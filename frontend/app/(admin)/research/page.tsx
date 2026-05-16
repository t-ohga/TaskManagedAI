import Link from "next/link";

import {
  AdminPageShell,
  KeyboardReadinessStrip,
  Panel
} from "../_components/sprint9-admin-ui";
import {
  getAdminResearchProjectId,
  listResearchTasks,
  type ResearchTask,
  type ResearchTaskListResponse
} from "@/lib/api/research";

export const dynamic = "force-dynamic";

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toISOString();
}

function StatusBadge({ status }: { readonly status: ResearchTask["status"] }) {
  const tone =
    status === "completed"
      ? "border-teal-200 bg-teal-50 text-accent"
      : status === "failed"
        ? "border-rose-200 bg-rose-50 text-danger"
        : "border-line bg-slate-50 text-ink";

  return (
    <span className={`rounded-md border px-2 py-1 font-mono text-xs font-semibold ${tone}`}>
      {status}
    </span>
  );
}

function ResearchTaskTable({ tasks }: { readonly tasks: readonly ResearchTask[] }) {
  if (tasks.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-line bg-white p-4 text-sm text-muted">
        No research tasks yet.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="min-w-full border-separate border-spacing-0 text-left text-sm">
        <caption className="sr-only">
          Research tasks with status, title, creation time, and project boundary.
        </caption>
        <thead className="bg-slate-50 text-xs uppercase tracking-normal text-muted">
          <tr>
            <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
              status
            </th>
            <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
              title
            </th>
            <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
              created_at
            </th>
            <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
              project_id
            </th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={task.id} className="align-top">
              <td className="border-b border-line px-3 py-2">
                <StatusBadge status={task.status} />
              </td>
              <th scope="row" className="border-b border-line px-3 py-2 font-medium text-ink">
                <Link
                  className="outline-offset-2 hover:text-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                  href={`/research/${task.id}`}
                >
                  {task.title}
                </Link>
                <p className="mt-1 font-mono text-xs text-muted">{task.id}</p>
              </th>
              <td className="border-b border-line px-3 py-2 text-muted">
                <time dateTime={task.created_at}>{formatDate(task.created_at)}</time>
              </td>
              <td className="border-b border-line px-3 py-2">
                <code className="break-all font-mono text-xs text-ink">{task.project_id}</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ErrorPanel({ error }: { readonly error: unknown }) {
  return (
    <Panel
      description="The read-only Research API did not return a renderable response."
      title="Research load error"
      titleId="research-load-error"
    >
      <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-danger">
        Failed to load research tasks: {error instanceof Error ? error.message : "unknown error"}
      </p>
    </Panel>
  );
}

export default async function ResearchListPage() {
  let result: ResearchTaskListResponse;
  let loadError: unknown = null;

  try {
    result = await listResearchTasks();
  } catch (error) {
    result = { items: [], total: 0, limit: 50, offset: 0 };
    loadError = error;
  }

  const projectId = getAdminResearchProjectId();

  return (
    <AdminPageShell
      description={
        <>
          Sprint 10 BL-0120 read-only Research / Claim / Evidence surface for project{" "}
          <code>{projectId}</code>. Mutation UI remains deferred to P1.
        </>
      }
      eyebrow="Admin / Research"
      regionLabel="Research"
      title="Research"
    >
      <KeyboardReadinessStrip current="Research" />

      {loadError === null ? null : <ErrorPanel error={loadError} />}

      <Panel
        aside={
          <span className="rounded-md border border-line bg-white px-3 py-2 font-mono text-xs text-muted">
            total {result.total}
          </span>
        }
        description="Project-scoped GET-only listing. tenant_id, project_id, and actor_id are resolved on the server side."
        title="Research tasks"
        titleId="research-task-list"
      >
        <ResearchTaskTable tasks={result.items} />
      </Panel>
    </AdminPageShell>
  );
}
