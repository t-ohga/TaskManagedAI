/**
 * Sprint 9 BL-0106: AgentRun API client (Zod schema + AgentRunEvent timeline).
 *
 * AgentRun 16 状態 + blocked_reason 3 種 + 22 event_type を Sprint 4 / Sprint 7
 * backend と整合 verify。
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
  "cli_decision_recorded"
]);

export type AgentRunEventType = z.infer<typeof AgentRunEventTypeEnum>;

export const AgentRunListItemSchema = z.object({
  id: z.string().uuid(),
  ticket_id: z.string().uuid(),
  status: AgentRunStatusEnum,
  blocked_reason: BlockedReasonEnum.nullable(),
  created_at: z.string(),
  updated_at: z.string()
});

export type AgentRunListItem = z.infer<typeof AgentRunListItemSchema>;

export const AgentRunEventSchema = z.object({
  id: z.string().uuid(),
  run_id: z.string().uuid(),
  seq_no: z.number().int().nonnegative(),
  event_type: AgentRunEventTypeEnum,
  /** payload は raw secret なし (AC-HARD-02 invariant)、key 名のみ */
  payload: z.record(z.string(), z.unknown()),
  created_at: z.string()
});

export type AgentRunEvent = z.infer<typeof AgentRunEventSchema>;

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

/**
 * GET /api/v1/agent-runs
 */
export async function listAgentRuns(): Promise<AgentRunListItem[]> {
  return fetchBackendJson<AgentRunListItem[]>(
    "/api/v1/agent-runs",
    z.array(AgentRunListItemSchema)
  );
}

/**
 * GET /api/v1/agent-runs/{id}
 */
export async function getAgentRun(id: string): Promise<AgentRunDetail> {
  if (!/^[0-9a-f-]{36}$/i.test(id)) {
    throw new Error("invalid agent run id format");
  }
  return fetchBackendJson<AgentRunDetail>(
    `/api/v1/agent-runs/${id}` as `/${string}`,
    AgentRunDetailSchema
  );
}
