/**
 * Sprint 9 BL-0107: Audit Log API client.
 *
 * append-only audit_event を Server Component で fetch。
 * raw secret / raw token / raw provider response は schema レベルで含めない
 * (AC-HARD-02 invariant、payload は key 名 + hash + reason_code のみ)。
 */

import { z } from "zod";

import { fetchBackendJson } from "@/lib/api/client";

export const AuditEventTypeEnum = z.enum([
  "policy_decision_created",
  "approval_requested",
  "approval_decided",
  "provider_blocked",
  "secret_capability_issued",
  "secret_capability_redeemed",
  "secret_capability_denied",
  "secret_canary_detected",
  "runner_started",
  "runner_completed",
  "runner_blocked",
  "repo_pr_opened",
  "webhook_hmac_failed",
  "orchestrator_failover",
  "tenant_isolation_negative",
  "forbidden_path_block",
  "dangerous_command_block"
]);

export type AuditEventType = z.infer<typeof AuditEventTypeEnum>;

export const AuditEventSchema = z.object({
  id: z.string().uuid(),
  event_type: AuditEventTypeEnum,
  actor_id: z.string().uuid(),
  run_id: z.string().uuid().nullable(),
  tenant_id: z.number().int().positive(),
  project_id: z.string().uuid().nullable(),
  trace_id: z.string(),
  correlation_id: z.string(),
  reason_code: z.string().nullable(),
  /** payload key 名のみ、raw value は含めない */
  payload: z.record(z.string(), z.unknown()),
  created_at: z.string()
});

export type AuditEvent = z.infer<typeof AuditEventSchema>;

export const AuditListResponseSchema = z.object({
  events: z.array(AuditEventSchema),
  next_cursor: z.string().nullable()
});

export type AuditListResponse = z.infer<typeof AuditListResponseSchema>;

/**
 * GET /api/v1/audit-events?cursor=...&event_type=...
 */
export async function listAuditEvents(
  cursor?: string,
  eventType?: AuditEventType
): Promise<AuditListResponse> {
  const params = new URLSearchParams();
  if (cursor) params.set("cursor", cursor);
  if (eventType) params.set("event_type", eventType);
  const qs = params.toString();
  const path: `/${string}` = qs
    ? (`/api/v1/audit-events?${qs}` as `/${string}`)
    : "/api/v1/audit-events";
  return fetchBackendJson<AuditListResponse>(path, AuditListResponseSchema);
}
