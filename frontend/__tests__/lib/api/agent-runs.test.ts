import { describe, expect, it } from "vitest";

import {
  AgentRunEventSchema,
  AgentRunEventTypeEnum,
  AgentRunStatusEnum,
  BlockedReasonEnum,
  ContextSnapshotReadSchema
} from "@/lib/api/agent-runs";

const baseEvent = {
  id: "00000000-0000-4000-8000-00000000c001",
  run_id: "00000000-0000-4000-8000-00000000c002",
  seq_no: 1,
  event_type: "run_queued",
  actor_id: "00000000-0000-4000-8000-00000000c003",
  payload_keys: ["reason_code"],
  payload_redaction_status: "keys_only",
  created_at: "2026-05-24T00:00:00Z"
};

const baseSnapshot = {
  id: "00000000-0000-4000-8000-00000000c011",
  run_id: "00000000-0000-4000-8000-00000000c012",
  prompt_pack_version: "2026.05.24",
  prompt_pack_lock: "lock",
  policy_version: "policy-v1",
  policy_pack_lock: "policy-lock",
  repo_state_keys: ["head_sha"],
  tool_manifest_keys: ["allowed_tools"],
  evidence_set_hash: "a".repeat(64),
  has_provider_continuation_ref: false,
  provider_request_fingerprint_keys: ["model"],
  snapshot_kind: "input",
  created_at: "2026-05-24T00:00:00Z"
};

describe("agent run API schemas", () => {
  it("preserves the closed AgentRun status and blocked_reason sets", () => {
    expect(AgentRunStatusEnum.options).toEqual([
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
    expect(BlockedReasonEnum.options).toEqual([
      "policy_blocked",
      "budget_blocked",
      "runtime_blocked"
    ]);
  });

  it("preserves the current AgentRunEvent type set", () => {
    expect(AgentRunEventTypeEnum.options).toHaveLength(37);
    expect(AgentRunEventTypeEnum.options).toContain("repo_pr_opened");
    expect(AgentRunEventTypeEnum.options).toContain("tool_docs_search_executed");
  });

  it("accepts redacted event metadata with payload keys only", () => {
    expect(AgentRunEventSchema.parse(baseEvent).payload_keys).toEqual(["reason_code"]);
  });

  it("rejects raw AgentRunEvent payload fields before DOM rendering", () => {
    expect(() =>
      AgentRunEventSchema.parse({
        ...baseEvent,
        event_payload: { api_key: "sk-fakeButSecretShaped0123456789" }
      })
    ).toThrow();
  });

  it("rejects raw ContextSnapshot JSON fields before DOM rendering", () => {
    expect(() =>
      ContextSnapshotReadSchema.parse({
        ...baseSnapshot,
        repo_state: { raw_provider_response: "sk-fakeButSecretShaped0123456789" }
      })
    ).toThrow();
  });
});
