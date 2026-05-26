/**
 * Sprint 9 BL-0107: Audit Log API client (PENDING BACKEND + REDACTION SCHEMA).
 *
 * **PENDING SPRINT 11** (Codex audit F-004 + F-008 adopt、2026-05-13):
 * - 対応 backend route (`GET /api/v1/audit_events`) は **未実装**。本 module は
 *   schema draft + cursor pagination interface のみ。Sprint 11 で backend
 *   route 実装 + tenant boundary integration test と一緒に enable。
 * - **AC-HARD-02 raw secret 非露出 enforcement (F-008)**: 現状
 *   `payload: z.record(z.string(), z.unknown())` は arbitrary value を許可。
 *   backend `_payload_secret_scan.py` の recursive secret scanner を frontend
 *   側にも `RedactedAuditPayloadSchema` として port し、prohibited key set +
 *   raw secret regex で parse 時 reject する設計を Sprint 11 で追加予定。
 * - 現状は backend が key 名 + hash + reason_code のみ送る前提に依存、schema
 *   側で enforce していない。
 *
 * append-only audit_event を Server Component で fetch。
 */

import { z } from "zod";

import { fetchBackendJson } from "@/lib/api/client";

/**
 * Codex SP9 R1 F-SP9-003 adopt: backend で実際に emit される event_type を網羅。
 *
 * backend `_audit_events` テーブルは `event_type: Mapped[str]` で正本 Literal
 * source なし。本 enum は backend repository / service で `event_type="..."`
 * literal として実際 emit される値を**直接 grep で列挙**したもの (2026-05-13、
 * commit `9cd542a` 時点)。
 *
 * **将来計画 (Sprint 11)**: backend に AuditEventType Literal/registry を追加し、
 * frontend Zod は自動生成 or contract test (`tests/contracts/test_frontend_backend_audit_event_drift.py`)
 * で exact set 比較。本 enum はそれまでの暫定 hardcode。
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
  "tenant_isolation_negative",
  "forbidden_path_block",
  "dangerous_command_block"
]);

export type AuditEventType = z.infer<typeof AuditEventTypeEnum>;

export const AuditEventSchema = z.object({
  id: z.string().uuid(),
  event_type: z.string(),
  actor_id: z.string().uuid(),
  principal_id: z.string().uuid().nullable().optional(),
  run_id: z.string().uuid().nullable().optional(),
  tenant_id: z.number().int().positive().optional(),
  project_id: z.string().uuid().nullable().optional(),
  trace_id: z.string().nullable().optional(),
  correlation_id: z.string().nullable().optional(),
  reason_code: z.string().nullable().optional(),
  payload: z.record(z.string(), z.unknown()).optional().default({}),
  payload_keys: z.array(z.string()).optional().default([]),
  payload_redaction_status: z.string().nullable().optional().default(null),
  created_at: z.string()
}).strict();

export type AuditEvent = z.infer<typeof AuditEventSchema>;

export const AuditListResponseSchema = z.object({
  events: z.array(AuditEventSchema),
  next_cursor: z.string().nullable()
});

export type AuditListResponse = z.infer<typeof AuditListResponseSchema>;

const AuditEventListResponseSchema = z.object({
  events: z.array(AuditEventSchema),
  total: z.number().int().nonnegative(),
  next_cursor: z.string().nullable()
});

export type AuditEventListResponse = z.infer<typeof AuditEventListResponseSchema>;

export async function listAuditEvents(
  options: { limit?: number; offset?: number; cursor?: string; eventType?: AuditEventType } = {}
): Promise<AuditEventListResponse> {
  const params = new URLSearchParams();
  if (options.limit != null) params.set("limit", String(options.limit));
  if (options.offset != null) params.set("offset", String(options.offset));
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.eventType) params.set("event_type", options.eventType);
  const qs = params.toString();
  const path: `/${string}` = qs
    ? (`/api/v1/audit_events?${qs}` as `/${string}`)
    : "/api/v1/audit_events";
  return fetchBackendJson<AuditEventListResponse>(path, AuditEventListResponseSchema);
}
