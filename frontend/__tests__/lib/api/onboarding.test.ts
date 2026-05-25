import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createOnboardingDryRunPlan,
  OnboardingDryRunPlanRequestSchema
} from "@/lib/api/onboarding";

const clientMocks = vi.hoisted(() => ({
  fetchBackendJson: vi.fn()
}));

vi.mock("@/lib/api/client", () => ({
  fetchBackendJson: clientMocks.fetchBackendJson
}));

afterEach(() => {
  clientMocks.fetchBackendJson.mockReset();
});

describe("onboarding API client", () => {
  it("rejects server-owned request fields at the frontend boundary", () => {
    expect(() =>
      OnboardingDryRunPlanRequestSchema.parse({
        purpose: "Plan",
        expected_artifact: "Reviewed plan",
        allowed_action_class: "read_only",
        starter_mode: "plan_only",
        policy_profile: "caller-owned"
      })
    ).toThrow();
  });

  it("calls the response-only dry-run endpoint and returns the plan", async () => {
    const plan = buildPlan();
    clientMocks.fetchBackendJson.mockResolvedValueOnce({ dry_run_plan: plan });

    await expect(
      createOnboardingDryRunPlan({
        purpose: "  Plan safely  ",
        expected_artifact: "Reviewed plan",
        allowed_action_class: "read_only",
        starter_mode: "plan_only",
        target_repo_ref: "",
        budget_cap: ""
      })
    ).resolves.toEqual(plan);

    expect(clientMocks.fetchBackendJson).toHaveBeenCalledWith(
      "/api/v1/onboarding/dry_run_plan",
      expect.any(Object),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          purpose: "Plan safely",
          expected_artifact: "Reviewed plan",
          allowed_action_class: "read_only",
          starter_mode: "plan_only"
        })
      })
    );
  });
});

function buildPlan() {
  return {
    starter_mode: "plan_only",
    requested_action_class: "read_only",
    effective_action_class: "read_only",
    policy_effect: "allow",
    approval_required: false,
    risk_level: "low",
    estimated_cost: "0 committed",
    rollback_plan: "No rollback is required.",
    test_plan: ["Review the plan."],
    blocked_reasons: ["dry_run_only_no_execution_started"],
    next_safe_routes: ["/settings"],
    would_create: {
      ticket: false,
      agent_run: false,
      approval: false,
      notification: false,
      audit_event: false,
      repository_operation: false,
      provider_call: false
    }
  };
}
