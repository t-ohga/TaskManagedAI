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
 * **DRAFT** GET /api/v1/audit_events (Codex audit F-004 adopt: backend route
 * 未実装、Sprint 9 では client draft のみ、Sprint 11 で backend route +
 * tenant boundary integration test 結線)。
 */
export async function _listAuditEventsDraft(
  cursor?: string,
  eventType?: AuditEventType
): Promise<AuditListResponse> {
  const params = new URLSearchParams();
  if (cursor) params.set("cursor", cursor);
  if (eventType) params.set("event_type", eventType);
  const qs = params.toString();
  const path: `/${string}` = qs
    ? (`/api/v1/audit_events?${qs}` as `/${string}`)
    : "/api/v1/audit_events";
  return fetchBackendJson<AuditListResponse>(path, AuditListResponseSchema);
}
