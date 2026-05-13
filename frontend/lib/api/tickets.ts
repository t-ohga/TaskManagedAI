/**
 * Sprint 9 BL-0104: Ticket API client (Zod schema + Server Component fetch helper).
 *
 * server-owned-boundary §1:
 * - tenant_id / project_id は Server Component で session から resolve、
 *   caller-supplied 経路なし
 * - response schema は Zod で strict validate、unknown field は drop
 */

import { z } from "zod";

import { fetchBackendJson } from "@/lib/api/client";

export const TicketStatusEnum = z.enum([
  "open",
  "in_progress",
  "waiting_review",
  "done",
  "archived",
  "cancelled"
]);

export type TicketStatus = z.infer<typeof TicketStatusEnum>;

export const PayloadDataClassEnum = z.enum([
  "public",
  "internal",
  "confidential",
  "pii"
]);

export type PayloadDataClass = z.infer<typeof PayloadDataClassEnum>;

export const TicketListItemSchema = z.object({
  id: z.string().uuid(),
  title: z.string(),
  status: TicketStatusEnum,
  project_id: z.string().uuid(),
  created_at: z.string(),
  updated_at: z.string(),
  agent_run_count: z.number().int().nonnegative()
});

export type TicketListItem = z.infer<typeof TicketListItemSchema>;

export const AcceptanceCriterionSchema = z.object({
  id: z.string(),
  description: z.string(),
  eval_fixture_ref: z.string().nullable()
});

export type AcceptanceCriterion = z.infer<typeof AcceptanceCriterionSchema>;

export const EvidenceCitationSchema = z.object({
  claim_id: z.string(),
  source_id: z.string(),
  url: z.string().url().nullable()
});

export type EvidenceCitation = z.infer<typeof EvidenceCitationSchema>;

export const TicketDetailSchema = TicketListItemSchema.extend({
  description: z.string().nullable(),
  acceptance_criteria: z.array(AcceptanceCriterionSchema),
  evidence_set_hash: z.string().nullable(),
  citations: z.array(EvidenceCitationSchema),
  latest_agent_run_id: z.string().uuid().nullable(),
  payload_data_class: PayloadDataClassEnum
});

export type TicketDetail = z.infer<typeof TicketDetailSchema>;

export const TicketsListResponseSchema = z.object({
  tickets: z.array(TicketListItemSchema),
  total: z.number().int().nonnegative()
});

export type TicketsListResponse = z.infer<typeof TicketsListResponseSchema>;

/**
 * GET /api/v1/tickets — Server Component fetch (tenant_id / project_id は
 * session cookie + middleware で server-side resolve)。
 */
export async function listTickets(): Promise<TicketsListResponse> {
  return fetchBackendJson<TicketsListResponse>(
    "/api/v1/tickets",
    TicketsListResponseSchema
  );
}

/**
 * GET /api/v1/tickets/{id}
 */
export async function getTicket(id: string): Promise<TicketDetail> {
  if (!/^[0-9a-f-]{36}$/i.test(id)) {
    throw new Error("invalid ticket id format");
  }
  return fetchBackendJson<TicketDetail>(
    `/api/v1/tickets/${id}` as `/${string}`,
    TicketDetailSchema
  );
}
