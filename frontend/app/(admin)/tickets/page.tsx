/**
 * Tickets list page (SP-012-9 BL-UIW-003/004 wiring 完成版).
 *
 * 本 page は Sprint 9 BL-0103 で skeleton として起票、SP-012-9 で実 backend
 * route (`GET /api/v1/projects/{project_id}/tickets`、PR #111) と接続し、
 * 実データ表示に置換。dogfooding seed (SP-012-10、PR #113/#114) で投入された
 * Sprint Pack 27 + ADR 29 = 56 件以上の Ticket を visualize 可能。
 *
 * server-owned-boundary §1:
 * - project_id は session 経由 resolve、default は DEFAULT_PROJECT_ID
 *   (seeds/initial.py 由来) を使う
 * - response は Zod strict validate (TicketListResponseSchema)
 */

import { BackendApiError } from "@/lib/api/client";
import { DEFAULT_PROJECT_ID, listTickets, type TicketRead } from "@/lib/api/tickets";

import { NewTicketForm } from "./_components/new-ticket-form";

export const dynamic = "force-dynamic";

type TicketsState =
  | { kind: "ok"; tickets: TicketRead[]; total: number }
  | { kind: "error"; message: string };

async function readTickets(): Promise<TicketsState> {
  try {
    const response = await listTickets(DEFAULT_PROJECT_ID, { limit: 200, offset: 0 });
    return { kind: "ok", tickets: response.items, total: response.total };
  } catch (error: unknown) {
    if (error instanceof BackendApiError) {
      return {
        kind: "error",
        message: `Backend returned ${error.status}: ${error.message}`,
      };
    }
    const message = error instanceof Error ? error.message : "Tickets fetch failed.";
    return { kind: "error", message };
  }
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toISOString().slice(0, 16).replace("T", " ");
  } catch {
    return iso;
  }
}

export default async function TicketsListPage() {
  const state = await readTickets();

  return (
    <section aria-label="Tickets" className="grid gap-4">
      <header>
        <p className="text-sm font-medium text-accent">Admin</p>
        <h1 className="text-3xl font-semibold tracking-normal">Tickets</h1>
        <p className="mt-2 text-sm text-muted">
          {state.kind === "ok"
            ? `${state.total} 件 (project: ${DEFAULT_PROJECT_ID})`
            : "tickets fetch failed"}
        </p>
      </header>

      <NewTicketForm />

      {state.kind === "error" ? (
        <article role="status" className="rounded-md border border-attention bg-amber-50 p-4">
          <h2 className="text-base font-semibold text-attention">Tickets unavailable</h2>
          <p className="mt-1 text-sm text-muted">{state.message}</p>
        </article>
      ) : state.tickets.length === 0 ? (
        <article className="rounded-md border border-base p-4 text-sm text-muted">
          tickets 0 件 (dogfooding seed が未投入の可能性、SP-012-10 CLI で seed apply)。
        </article>
      ) : (
        <article className="overflow-x-auto rounded-lg border border-line bg-panel shadow-sm">
          <table className="min-w-full divide-y divide-line text-sm">
            <thead className="bg-panel-muted text-xs uppercase tracking-wide text-muted">
              <tr>
                <th scope="col" className="px-4 py-3 text-left font-medium">Slug</th>
                <th scope="col" className="px-4 py-3 text-left font-medium">Title</th>
                <th scope="col" className="px-4 py-3 text-left font-medium">Status</th>
                <th scope="col" className="px-4 py-3 text-left font-medium">Priority</th>
                <th scope="col" className="px-4 py-3 text-left font-medium">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {state.tickets.map((ticket) => (
                <tr key={ticket.id} className="hover:bg-panel-muted">
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-muted">
                    {ticket.slug}
                  </td>
                  <td className="px-4 py-3">{ticket.title}</td>
                  <td className="px-4 py-3">
                    <span className="rounded-md bg-panel-muted px-2 py-1 text-xs font-medium">
                      {ticket.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-muted">
                    {ticket.priority ?? "-"}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-muted">
                    {formatDate(ticket.updated_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </article>
      )}
    </section>
  );
}
