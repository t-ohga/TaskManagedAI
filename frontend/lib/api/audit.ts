/**
 * Audit Log API client (SP-012-9 residual wiring).
 *
 * Backend returns redacted audit metadata only. Raw `event_payload` values are
 * intentionally not part of the response shape.
 */

import { z } from "zod";

import { fetchBackendJson } from "@/lib/api/client";
import { NoRawPayloadFieldsSchema } from "@/lib/api/redaction";

/**
 * Codex SP9 R1 F-SP9-003 adopt: frequently used audit filters.
 *
 * backend `_audit_events` テーブルは `event_type: Mapped[str]` で正本 Literal
 * source なし。本 enum は UI filter suggestion 用で、AuditEventSchema の
 * response validation では `event_type: z.string()` を維持する。
 *
 * **将来計画**: backend に AuditEventType Literal/registry を追加し、
 * frontend Zod は自動生成 or contract test (`tests/contracts/test_frontend_backend_audit_event_drift.py`)
 * で exact set 比較。本 enum はそれまでの暫定 filter list。
 */
export const AuditEventTypeEnum = z.enum([
  // policy / approval
  "policy_decision_created",
  "policy_blocked",
  "approval_pending",
  "approval_requested", // FastAPI route 経由 (将来 backend で emit 予定)
  "approval_decided",   // 同上
  // provider
  "provider_blocked",
  // secret broker
  "secret_capability_issued",
  "secret_capability_redeemed",
  "secret_capability_denied",
  "secret_canary_detected", // Sprint 11 で実装予定 (現状 unused、defer-safe)
  // runner
  "runner_started",
  "runner_completed",
  "runner_blocked",
  // budget
  "budget_blocked",
  "budget_created",
  "budget_active_flag_updated",
  "budget_limits_updated",
  "budget_soft_threshold_warning",
  // agent runtime
  "schema_validated",
  "validation_failed",
  "repair_retry_scheduled",
  "repair_exhausted",
  "run_cancelled",
  // github / webhook (Sprint 11 で実装予定)
  "repo_pr_opened",
  "webhook_hmac_failed",
  // future / orchestration
  "orchestrator_failover",
  "orchestrator_failover_triggered",
  "orchestrator_lease_expired",
  "orchestrator_lease_renewed",
  "orchestrator_kill_engaged",
  "tenant_isolation_negative",
  "forbidden_path_block",
  "dangerous_command_block"
]);

export type AuditEventType = z.infer<typeof AuditEventTypeEnum>;

export const AuditEventSchema = NoRawPayloadFieldsSchema.pipe(z.object({
  id: z.string().uuid(),
  event_type: z.string(),
  actor_id: z.string().uuid().nullable(),
  principal_id: z.string().uuid().nullable(),
  tenant_id: z.number().int().positive(),
  trace_id: z.string().nullable(),
  correlation_id: z.string().nullable(),
  reason_code: z.string().nullable(),
  payload_keys: z.array(z.string()),
  payload_redaction_status: z.enum(["keys_only", "blocked_by_secret_scan"]),
  created_at: z.string()
}));

export type AuditEvent = z.infer<typeof AuditEventSchema>;

export const AuditListResponseSchema = z.object({
  events: z.array(AuditEventSchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int(),
  offset: z.number().int()
});

export type AuditListResponse = z.infer<typeof AuditListResponseSchema>;

export async function listAuditEvents(
  options: {
    eventType?: string;
    actorId?: string;
    limit?: number;
    offset?: number;
  } = {}
): Promise<AuditListResponse> {
  const params = new URLSearchParams();
  if (options.eventType) params.set("event_type", options.eventType);
  if (options.actorId) params.set("actor_id", options.actorId);
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.offset !== undefined) params.set("offset", String(options.offset));
  const qs = params.toString();
  const path: `/${string}` = qs
    ? (`/api/v1/audit_events?${qs}` as `/${string}`)
    : "/api/v1/audit_events";
  return fetchBackendJson<AuditListResponse>(path, AuditListResponseSchema);
}
