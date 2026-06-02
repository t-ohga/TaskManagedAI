/**
 * Sprint 9 BL-0104: Ticket API client (Zod schema + Server Component fetch helper).
 *
 * **PENDING BACKEND INTEGRATION** (Codex audit F-004 adopt、2026-05-13):
 * - 本 module は Sprint 9 で **schema draft** として整備したが、対応 backend
 *   route (`GET /api/v1/tickets`, `GET /api/v1/tickets/{id}`) は **未実装**。
 * - Sprint 9 page は `loadTicketDraft()` を呼ばず skeleton 文言のみ render。
 * - 実 backend route 実装 + integration test 結線は Sprint 11 で扱う。
 * - status / payload_data_class enum は backend ticket.py / DB CHECK と
 *   drift する可能性 (Codex audit F-006 adopt、Sprint 11 contract test 追加予定)。
 *
 * server-owned-boundary §1:
 * - tenant_id / project_id は Server Component で session から resolve、
 *   caller-supplied 経路なし (Sprint 11 で backend route 実装時に enforcement)
 * - response schema は Zod で strict validate、unknown field は drop
 */

import { z } from "zod";

import { fetchBackendJson } from "@/lib/api/client";
import { TagReadSchema } from "@/lib/domain/tag";

// Codex audit F-006 adopt: backend ticket.py Literal + DB CHECK と integrity 維持
// backend/app/db/models/ticket.py:20 と完全一致 (Sprint 11 contract test で drift 検証)
export const TicketStatusEnum = z.enum([
  "open",
  "in_progress",
  "blocked",
  "review",
  "closed",
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

export const TicketPriorityEnum = z.enum(["low", "medium", "high", "critical"]);

export type TicketPriority = z.infer<typeof TicketPriorityEnum>;

export const DEFAULT_PROJECT_ID = "00000000-0000-4000-8000-000000000004";

export const TicketListItemSchema = z.object({
  id: z.string().uuid(),
  tenant_id: z.number().int().positive().optional(),
  project_id: z.string().uuid(),
  repository_id: z.string().uuid().nullable().optional(),
  slug: z.string().nullable().optional(),
  title: z.string(),
  description: z.string().nullable().optional(),
  status: TicketStatusEnum,
  priority: TicketPriorityEnum.nullable(),
  // backend TicketRead は due_date を必須 nullable で返す (date 型、YYYY-MM-DD)。
  // optional にすると response から欠落しても検証が通り、編集フォームが空で開いて
  // 次回保存で誤って null PATCH する drift 経路を生むため、必須 nullable で締める
  // (Codex adversarial R2 F-MEDIUM)。
  due_date: z.string().nullable(),
  assignee_actor_id: z.string().uuid().nullable(),
  created_by_actor_id: z.string().uuid().nullable().optional(),
  metadata: z.record(z.string(), z.unknown()).nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
  agent_run_count: z.number().int().nonnegative().optional().default(0),
  // ADR-00044 (A-5): backend TicketRead が per-ticket tag を inject する (tags_for_tickets 由来)。
  // 旧経路 / 他 response で欠落しても落ちないよう default [] (present なら strict validate)。
  tags: z.array(TagReadSchema).default([])
});

export type TicketListItem = z.infer<typeof TicketListItemSchema>;
export type TicketRead = TicketListItem;
export const TicketReadSchema = TicketListItemSchema;

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

export const TicketListResponseSchema = z.object({
  items: z.array(TicketListItemSchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int().nonnegative().optional(),
  offset: z.number().int().nonnegative().optional()
});

export type TicketListResponse = z.infer<typeof TicketListResponseSchema>;

export async function listTickets(
  projectId: string,
  options: { limit?: number; offset?: number } = {}
): Promise<TicketListResponse> {
  const params = new URLSearchParams();
  if (options.limit != null) params.set("limit", String(options.limit));
  if (options.offset != null) params.set("offset", String(options.offset));
  const qs = params.toString();
  const path: `/${string}` = `/api/v1/projects/${projectId}/tickets${qs ? `?${qs}` : ""}` as `/${string}`;
  return fetchBackendJson<TicketListResponse>(path, TicketListResponseSchema);
}

export async function getTicket(projectId: string, id: string): Promise<TicketDetail> {
  if (!/^[0-9a-f-]{36}$/i.test(id)) {
    throw new Error("invalid ticket id format");
  }
  return fetchBackendJson<TicketDetail>(
    `/api/v1/projects/${projectId}/tickets/${id}` as `/${string}`,
    TicketDetailSchema
  );
}

// ── ADR-00041 N-1 / N-2: ticket コメント + activity timeline ──────────────
// backend schema は tickets.py TicketComment / TicketActivityEntry と整合 (Sprint 11
// と同様、drift は contract test で検証)。response は server-owned (actor_id は backend
// が payload.actor_id ?? recipient で解決、message は redaction 済) を strict validate。

export const TicketCommentSchema = z.object({
  id: z.string().uuid(),
  message: z.string(),
  // legacy row は actor_id を持たない場合があるため nullable (backend R2-2 fallback)。
  actor_id: z.string().uuid().nullable(),
  created_at: z.string()
});

export type TicketComment = z.infer<typeof TicketCommentSchema>;

export const TicketCommentListResponseSchema = z.object({
  comments: z.array(TicketCommentSchema)
});

export type TicketCommentListResponse = z.infer<typeof TicketCommentListResponseSchema>;

export const TicketActivityEntrySchema = z.object({
  id: z.string(),
  // "created" | "comment" | "status_change" | "updated"
  type: z.string(),
  message: z.string().nullable().optional(),
  actor_id: z.string().uuid().nullable().optional(),
  created_at: z.string(),
  previous_status: z.string().nullable().optional(),
  new_status: z.string().nullable().optional()
});

export type TicketActivityEntry = z.infer<typeof TicketActivityEntrySchema>;

export const TicketActivityListResponseSchema = z.object({
  entries: z.array(TicketActivityEntrySchema)
});

export type TicketActivityListResponse = z.infer<typeof TicketActivityListResponseSchema>;

export async function listTicketComments(
  projectId: string,
  ticketId: string
): Promise<TicketCommentListResponse> {
  return fetchBackendJson<TicketCommentListResponse>(
    `/api/v1/projects/${projectId}/tickets/${ticketId}/comments` as `/${string}`,
    TicketCommentListResponseSchema
  );
}

export async function getTicketActivity(
  projectId: string,
  ticketId: string
): Promise<TicketActivityListResponse> {
  return fetchBackendJson<TicketActivityListResponse>(
    `/api/v1/projects/${projectId}/tickets/${ticketId}/activity` as `/${string}`,
    TicketActivityListResponseSchema
  );
}

export async function createTicketComment(
  projectId: string,
  ticketId: string,
  message: string
): Promise<TicketComment> {
  return fetchBackendJson<TicketComment>(
    `/api/v1/projects/${projectId}/tickets/${ticketId}/comments` as `/${string}`,
    TicketCommentSchema,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message })
    }
  );
}
