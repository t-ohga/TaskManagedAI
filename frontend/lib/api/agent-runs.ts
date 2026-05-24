/**
 * AgentRun API client (SP-012-9 residual wiring).
 *
 * Backend exposes read-only list/detail routes and returns redacted event
 * metadata (`payload_keys` + redaction status) instead of raw payload values.
 */

import { z } from "zod";

import { fetchBackendJson } from "@/lib/api/client";
import { NoRawPayloadFieldsSchema } from "@/lib/api/redaction";

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

// AgentRun event_type 37 種 (P0.1+ SP-014 / Tool Registry events included)
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
  tenant_id: z.number().int().positive(),
  project_id: z.string().uuid(),
  parent_run_id: z.string().uuid().nullable(),
  status: AgentRunStatusEnum,
  blocked_reason: BlockedReasonEnum.nullable(),
  error_code: z.string().nullable(),
  error_summary: z.string().nullable(),
  completed_at: z.string().nullable(),
  role_id: z.string().nullable(),
  role_scope: z.string().nullable(),
  orchestrator_lease_expires_at: z.string().nullable(),
  last_progress_at: z.string().nullable(),
  progress_seq: z.number().int().nonnegative(),
  created_at: z.string(),
  updated_at: z.string()
});

export type AgentRunListItem = z.infer<typeof AgentRunListItemSchema>;

export const AgentRunEventSchema = NoRawPayloadFieldsSchema.pipe(z.object({
  id: z.string().uuid(),
  run_id: z.string().uuid(),
  seq_no: z.number().int().nonnegative(),
  event_type: AgentRunEventTypeEnum,
  actor_id: z.string().uuid(),
  payload_keys: z.array(z.string()),
  payload_redaction_status: z.enum(["keys_only", "blocked_by_secret_scan"]),
  created_at: z.string()
}));

export type AgentRunEvent = z.infer<typeof AgentRunEventSchema>;

export const ContextSnapshotReadSchema = NoRawPayloadFieldsSchema.pipe(z.object({
  id: z.string().uuid(),
  run_id: z.string().uuid(),
  prompt_pack_version: z.string(),
  prompt_pack_lock: z.string(),
  policy_version: z.string(),
  policy_pack_lock: z.string(),
  repo_state_keys: z.array(z.string()),
  tool_manifest_keys: z.array(z.string()),
  evidence_set_hash: z.string(),
  has_provider_continuation_ref: z.boolean(),
  provider_request_fingerprint_keys: z.array(z.string()),
  snapshot_kind: z.enum([
    "input",
    "pre_tool",
    "post_tool",
    "resume",
    "final"
  ]),
  created_at: z.string()
}));

export type ContextSnapshotRead = z.infer<typeof ContextSnapshotReadSchema>;

export const AgentRunListResponseSchema = z.object({
  items: z.array(AgentRunListItemSchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int(),
  offset: z.number().int()
});

export type AgentRunListResponse = z.infer<typeof AgentRunListResponseSchema>;

export const AgentRunDetailSchema = AgentRunListItemSchema.extend({
  events: z.array(AgentRunEventSchema),
  context_snapshot: ContextSnapshotReadSchema.nullable()
});

export type AgentRunDetail = z.infer<typeof AgentRunDetailSchema>;

export async function listAgentRuns(
  options: { status?: AgentRunStatus; role?: string; limit?: number; offset?: number } = {}
): Promise<AgentRunListResponse> {
  const params = new URLSearchParams();
  if (options.status) params.set("status", options.status);
  if (options.role) params.set("role", options.role);
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.offset !== undefined) params.set("offset", String(options.offset));
  const query = params.toString();
  const path = query ? `/api/v1/agent_runs?${query}` : "/api/v1/agent_runs";
  return fetchBackendJson(path as `/${string}`, AgentRunListResponseSchema);
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
