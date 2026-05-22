/**
 * Ticket detail page (SP-012-11 BL-TCU-005 wiring 完成版).
 *
 * Sprint 9 BL-0104 で skeleton として実装、SP-012-11 で実 backend route
 * (`GET /api/v1/projects/{project_id}/tickets/{ticket_id}`、PR #111) と接続し
 * **実データ表示 + edit form** に拡張。dogfooding seed (PR #113-#117) で
 * 投入された Ticket の status / title / description / priority を UI 経由で更新可能。
 *
 * server-owned-boundary §1:
 * - project_id は session 経由 resolve、default は DEFAULT_PROJECT_ID
 * - PATCH endpoint で created_by_actor_id / project_id / tenant_id は更新不可
 *   (caller-supplied 排除、`extra="forbid"` Pydantic)
 */

import { notFound } from "next/navigation";

import { BackendApiError } from "@/lib/api/client";
import { formatTicketPriority, formatTicketStatus } from "@/lib/i18n/ticket-labels";
import { getCurrentProjectId } from "@/lib/api/session";
import { getTicket, type TicketRead } from "@/lib/api/tickets";

import { UUID_V1_TO_V5_PATTERN } from "../../_lib/route-id";
import { EditTicketForm } from "./_components/edit-ticket-form";

export const dynamic = "force-dynamic";

type TicketDetailPageProps = {
  params: Promise<{ id: string }>;
};

type TicketDetailState =
  | { kind: "ok"; ticket: TicketRead }
  | { kind: "not-found" }
  | { kind: "error"; message: string };

async function readTicket(ticketId: string): Promise<TicketDetailState> {
  try {
    // SP-012-11.1 BL-TCU-014: Codex PR #121 R1 F-PR121-003 (P1) carry-over fix
    // session 経由 project resolve (DEFAULT_PROJECT_ID hardcode 解除)
    const projectId = await getCurrentProjectId();
    const ticket = await getTicket(projectId, ticketId);
    return { kind: "ok", ticket };
  } catch (error: unknown) {
    if (error instanceof BackendApiError && error.status === 404) {
      return { kind: "not-found" };
    }
    if (error instanceof BackendApiError) {
      return {
        kind: "error",
        message: `バックエンドが ${error.status} を返しました: ${error.message}`
      };
    }
    const message =
      error instanceof Error ? error.message : "チケットの取得に失敗しました。";
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

export default async function TicketDetailPage({ params }: TicketDetailPageProps) {
  const { id } = await params;

  // server-owned-boundary: UUID v1-v5 guard で caller-supplied path 排除
  if (!id || !UUID_V1_TO_V5_PATTERN.test(id)) {
    notFound();
  }

  const state = await readTicket(id);

  if (state.kind === "not-found") {
    notFound();
  }

  return (
    <section aria-label="チケット詳細" className="grid gap-4">
      <header>
        <p className="text-sm font-medium text-accent">管理 / チケット</p>
        <h1 className="text-3xl font-semibold tracking-normal">チケット詳細</h1>
        <p className="mt-2 font-mono text-xs text-muted">{id}</p>
      </header>

      {state.kind === "error" ? (
        <article role="status" className="rounded-md border border-attention bg-amber-50 p-4">
          <h2 className="text-base font-semibold text-attention">
            チケットを表示できません
          </h2>
          <p className="mt-1 text-sm text-muted">{state.message}</p>
        </article>
      ) : (
        <>
          <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
            <h2 className="text-lg font-semibold">{state.ticket.title}</h2>
            <dl className="mt-4 grid gap-3 text-sm">
              <div className="flex justify-between gap-4 border-t border-line pt-3">
                <dt className="text-muted">Slug</dt>
                <dd className="font-mono">{state.ticket.slug}</dd>
              </div>
              <div className="flex justify-between gap-4 border-t border-line pt-3">
                <dt className="text-muted">状態</dt>
                <dd>
                  <span className="rounded-md bg-panel-muted px-2 py-1 text-xs font-medium">
                    {formatTicketStatus(state.ticket.status)}
                  </span>
                </dd>
              </div>
              <div className="flex justify-between gap-4 border-t border-line pt-3">
                <dt className="text-muted">優先度</dt>
                <dd>{formatTicketPriority(state.ticket.priority)}</dd>
              </div>
              <div className="flex justify-between gap-4 border-t border-line pt-3">
                <dt className="text-muted">作成日時</dt>
                <dd className="font-mono text-xs">{formatDate(state.ticket.created_at)}</dd>
              </div>
              <div className="flex justify-between gap-4 border-t border-line pt-3">
                <dt className="text-muted">更新日時</dt>
                <dd className="font-mono text-xs">{formatDate(state.ticket.updated_at)}</dd>
              </div>
              {state.ticket.description ? (
                <div className="border-t border-line pt-3">
                  <dt className="text-muted">説明</dt>
                  <dd className="mt-2 whitespace-pre-wrap text-sm">
                    {state.ticket.description}
                  </dd>
                </div>
              ) : null}
            </dl>
          </article>

          <EditTicketForm ticket={state.ticket} />
        </>
      )}
    </section>
  );
}
