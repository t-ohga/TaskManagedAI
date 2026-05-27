/**
 * Sprint 9 BL-0106: AgentRun API client (Zod schema + PENDING REDACTION).
 *
 * **PENDING SPRINT 11** (Codex audit F-004 + F-008 adopt、2026-05-13):
 * - 対応 backend route `GET /api/v1/agent_runs` / `GET /api/v1/agent_runs/{id}`
 *   は **未実装** (現状 backend は `POST /api/v1/agent_runs/{id}/cancel` のみ)。
 *   Sprint 11 で list / detail route + integration test を追加。
 * - AC-HARD-02 raw secret 非露出 enforcement は `audit.ts` 同様 Sprint 11 で
 *   `RedactedAgentRunEventPayloadSchema` として実装予定。
 *
 * AgentRun 16 状態 + blocked_reason 3 種 + 22 event_type を Sprint 4 / Sprint 7
 * backend と整合 verify (Sprint 11 で contract test 追加予定、Codex F-006 adopt)。
 */

import { z } from "zod";

import { fetchBackendJson } from "@/lib/api/client";

// AgentRun 16 状態 (Sprint 4 で確立、本 Sprint で frontend と同期)
export const AgentRunStatusEnum = z.enum([
  "queued",
  "gathering_context",
  "running",
  "generated_artifact",
  "schema_validated",
  "policy_linted",
  "diff_ready",
  "waiting_approval",
  "blocked",
  "provider_refused",
  "provider_incomplete",
  "validation_failed",
  "repair_exhausted",
  "completed",
  "failed",
  "cancelled"
]);

export type AgentRunStatus = z.infer<typeof AgentRunStatusEnum>;

export const BlockedReasonEnum = z.enum([
  "policy_blocked",
  "budget_blocked",
  "runtime_blocked"
]);

export type BlockedReason = z.infer<typeof BlockedReasonEnum>;

// 22 event_type (Sprint 4 で予約済、Sprint 7 で runner_* + repo_pr_opened)
export const AgentRunEventTypeEnum = z.enum([
  "run_queued",
  "context_gathered",
  "provider_requested",
  "provider_responded",
  "artifact_generated",
  "schema_validated",
  "validation_failed",
  "repair_retry_scheduled",
  "policy_linted",
  "policy_blocked",
  "budget_blocked",
  "runtime_blocked",
  "diff_ready",
  "approval_requested",
  "approval_decided",
  "runner_started",
  "runner_completed",
  "runner_blocked",
  "repo_pr_opened",
  "run_completed",
  "run_failed",
  "run_cancelled",
  "repair_exhausted",
  "trust_level_promoted",
  "trust_level_promotion_denied",
  "cli_invocation_started",
  "cli_process_completed",
  "cli_decision_recorded",
  "orchestrator_dispatched",
  "orchestrator_lease_renewed",
  "orchestrator_lease_expired",
  "orchestrator_failover_triggered",
  "orchestrator_kill_engaged",
  "inter_agent_message_sent_ref",
  "inter_agent_message_consumed_ref",
  "tool_web_fetch_executed",
  "tool_docs_search_executed"
]);

export type AgentRunEventType = z.infer<typeof AgentRunEventTypeEnum>;

export const AgentRunListItemSchema = z.object({
  id: z.string().uuid(),
  ticket_id: z.string().uuid().nullable().optional(),
  status: AgentRunStatusEnum,
  blocked_reason: BlockedReasonEnum.nullable(),
  role_id: z.string().nullable().optional(),
  role_scope: z.string().nullable().optional(),
  progress_seq: z.number().int().nonnegative().nullable().optional(),
  last_progress_at: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string()
});

export type AgentRunListItem = z.infer<typeof AgentRunListItemSchema>;

export const AgentRunEventSchema = z.object({
  id: z.string().uuid(),
  run_id: z.string().uuid(),
  seq_no: z.number().int().nonnegative(),
  event_type: AgentRunEventTypeEnum,
  actor_id: z.string().uuid().nullable().optional(),
  payload_keys: z.array(z.string()).optional().default([]),
  payload_redaction_status: z.string().nullable().optional().default(null),
  created_at: z.string()
}).strict();

export type AgentRunEvent = z.infer<typeof AgentRunEventSchema>;

export const ContextSnapshotReadSchema = z.object({
  id: z.string().uuid(),
  run_id: z.string().uuid(),
  prompt_pack_version: z.string(),
  prompt_pack_lock: z.string(),
  policy_version: z.string(),
  policy_pack_lock: z.string(),
  repo_state_keys: z.array(z.string()),
  tool_manifest_keys: z.array(z.string()),
  evidence_set_hash: z.string().nullable(),
  has_provider_continuation_ref: z.boolean(),
  provider_request_fingerprint_keys: z.array(z.string()),
  snapshot_kind: z.enum(["input", "pre_tool", "post_tool", "resume", "final"]),
  created_at: z.string()
}).strict();

export type ContextSnapshotRead = z.infer<typeof ContextSnapshotReadSchema>;

export const AgentRunDetailSchema = AgentRunListItemSchema.extend({
  events: z.array(AgentRunEventSchema),
  context_snapshot: z
    .object({
      prompt_pack_version: z.string(),
      prompt_pack_lock: z.string(),
      policy_version: z.string(),
      policy_pack_lock: z.string(),
      repo_state: z.record(z.string(), z.unknown()),
      tool_manifest: z.string(),
      evidence_set_hash: z.string().nullable(),
      provider_continuation_ref: z.record(z.string(), z.unknown()).nullable(),
      provider_request_fingerprint: z.string(),
      snapshot_kind: z.enum([
        "input",
        "pre_tool",
        "post_tool",
        "resume",
        "final"
      ])
    })
    .nullable()
});

export type AgentRunDetail = z.infer<typeof AgentRunDetailSchema>;

const AgentRunListResponseSchema = z.object({
  items: z.array(AgentRunListItemSchema),
  total: z.number().int().nonnegative()
});

export type AgentRunListResponse = z.infer<typeof AgentRunListResponseSchema>;

export async function listAgentRuns(
  options: { limit?: number; offset?: number } = {}
): Promise<AgentRunListResponse> {
  const params = new URLSearchParams();
  if (options.limit != null) params.set("limit", String(options.limit));
  if (options.offset != null) params.set("offset", String(options.offset));
  const qs = params.toString();
  const path: `/${string}` = qs
    ? (`/api/v1/agent_runs?${qs}` as `/${string}`)
    : "/api/v1/agent_runs";
  return fetchBackendJson<AgentRunListResponse>(path, AgentRunListResponseSchema);
}

export async function getAgentRun(id: string): Promise<AgentRunDetail> {
  if (!/^[0-9a-f-]{36}$/i.test(id)) {
    throw new Error("invalid agent run id format");
  }
  return fetchBackendJson<AgentRunDetail>(
    `/api/v1/agent_runs/${id}` as `/${string}`,
    AgentRunDetailSchema
  );
}
