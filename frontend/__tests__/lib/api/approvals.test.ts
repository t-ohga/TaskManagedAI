import { describe, expect, it } from "vitest";

import { ApprovalDetailSchema } from "@/lib/api/approvals";

const baseApprovalDetail = {
  id: "00000000-0000-4000-8000-00000000a101",
  action_class: "repo_write",
  resource_ref: "repo:TaskManagedAI:approval-detail",
  risk_level: "high",
  status: "pending",
  requested_by_actor_id: "00000000-0000-4000-8000-00000000a102",
  decided_by_actor_id: null,
  requested_at: "2026-05-24T00:00:00Z",
  decided_at: null,
  rationale: null,
  artifact_hash: "a".repeat(64),
  diff_hash: "b".repeat(64),
  policy_version: "policy-v1",
  policy_pack_lock: "c".repeat(64),
  provider_request_fingerprint: "d".repeat(64),
};

describe("approval API schemas", () => {
  it("parses decision packet stale event sequence", () => {
    expect(
      ApprovalDetailSchema.parse({
        ...baseApprovalDetail,
        stale_after_event_seq: 42,
      }).stale_after_event_seq
    ).toBe(42);
  });

  it("treats missing stale event sequence as null for additive backend rollout", () => {
    expect(ApprovalDetailSchema.parse(baseApprovalDetail).stale_after_event_seq).toBeNull();
  });
});
