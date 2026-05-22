/**
 * Tickets API client (SP-012-9 BL-UIW-003/004 wiring 完成版).
 *
 * Backend route (`GET /api/v1/projects/{project_id}/tickets`) は PR #111 で
 * 実装済。本 module は実 fetch + Zod strict validate で wiring 完成。
 *
 * server-owned-boundary §1:
 * - tenant_id / project_id は Server Component で session から resolve、
 *   caller-supplied 経路なし (default は DEFAULT_PROJECT_ID で seeds と整合)
 * - response schema は Zod で strict validate、unknown field は drop
 *
 * sync target: backend/app/schemas/ticket.py TicketRead Pydantic schema。
 */

import { z } from "zod";

import { fetchBackendJson } from "@/lib/api/client";

/** Default project id seeded by `backend/app/seeds/initial.py` (`DEFAULT_PROJECT_ID`). */
export const DEFAULT_PROJECT_ID = "00000000-0000-4000-8000-000000000004";

// backend ticket.py Literal + DB CHECK と完全一致 (Sprint 11 contract test で drift 検証)
export const TicketStatusEnum = z.enum([
  "open",
  "in_progress",
  "blocked",
  "review",
  "closed",
  "cancelled"
]);

export type TicketStatus = z.infer<typeof TicketStatusEnum>;

export const TicketPriorityEnum = z.enum(["low", "medium", "high", "critical"]);

export type TicketPriority = z.infer<typeof TicketPriorityEnum>;

/** Backend `TicketRead` Pydantic schema と整合 (sync via repository contract test). */
export const TicketReadSchema = z.object({
  id: z.string().uuid(),
  tenant_id: z.number().int(),
  project_id: z.string().uuid(),
  repository_id: z.string().uuid().nullable(),
  slug: z.string(),
  title: z.string(),
  description: z.string().nullable(),
  status: TicketStatusEnum,
  priority: TicketPriorityEnum.nullable(),
  assignee_actor_id: z.string().uuid().nullable(),
  created_by_actor_id: z.string().uuid(),
  metadata: z.record(z.string(), z.unknown()),
  created_at: z.string(),
  updated_at: z.string()
});

export type TicketRead = z.infer<typeof TicketReadSchema>;

/** Backend `TicketListResponse` Pydantic schema と整合. */
export const TicketListResponseSchema = z.object({
  items: z.array(TicketReadSchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int(),
  offset: z.number().int()
});

export type TicketListResponse = z.infer<typeof TicketListResponseSchema>;

/**
 * GET /api/v1/projects/{project_id}/tickets (list、pagination).
 *
 * @param projectId - project UUID (session 経由 resolve、default は DEFAULT_PROJECT_ID)
 * @param limit - 1〜200 (default 50)
 * @param offset - >= 0 (default 0)
 */
export async function listTickets(
  projectId: string,
  options: { limit?: number; offset?: number } = {}
): Promise<TicketListResponse> {
  if (!/^[0-9a-f-]{36}$/i.test(projectId)) {
    throw new Error("invalid project id format");
  }
  const params = new URLSearchParams();
  if (options.limit !== undefined) {
    params.set("limit", String(options.limit));
  }
  if (options.offset !== undefined) {
    params.set("offset", String(options.offset));
  }
  const query = params.toString();
  const path = query
    ? (`/api/v1/projects/${projectId}/tickets?${query}` as `/${string}`)
    : (`/api/v1/projects/${projectId}/tickets` as `/${string}`);
  return fetchBackendJson<TicketListResponse>(path, TicketListResponseSchema);
}

/**
 * GET /api/v1/projects/{project_id}/tickets/{ticket_id} (detail).
 */
export async function getTicket(
  projectId: string,
  ticketId: string
): Promise<TicketRead> {
  if (!/^[0-9a-f-]{36}$/i.test(projectId)) {
    throw new Error("invalid project id format");
  }
  if (!/^[0-9a-f-]{36}$/i.test(ticketId)) {
    throw new Error("invalid ticket id format");
  }
  return fetchBackendJson<TicketRead>(
    `/api/v1/projects/${projectId}/tickets/${ticketId}` as `/${string}`,
    TicketReadSchema
  );
}
