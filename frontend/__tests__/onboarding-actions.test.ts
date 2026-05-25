import { afterEach, describe, expect, it, vi } from "vitest";
import type * as OnboardingApi from "@/lib/api/onboarding";

import { createOnboardingDryRunPlanAction } from "@/app/(admin)/onboarding/actions";

const apiMocks = vi.hoisted(() => ({
  createOnboardingDryRunPlan: vi.fn()
}));

vi.mock("@/lib/api/onboarding", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...(actual as typeof OnboardingApi),
    createOnboardingDryRunPlan: apiMocks.createOnboardingDryRunPlan
  };
});

afterEach(() => {
  apiMocks.createOnboardingDryRunPlan.mockReset();
});

describe("createOnboardingDryRunPlanAction", () => {
  it("rejects invalid form values before calling the backend", async () => {
    const result = await createOnboardingDryRunPlanAction({ kind: "idle" }, buildForm({}));

    expect(result).toEqual({ kind: "error", message: "入力内容を確認してください。" });
    expect(apiMocks.createOnboardingDryRunPlan).not.toHaveBeenCalled();
  });

  it("returns the dry-run plan on success", async () => {
    const plan = buildPlan();
    apiMocks.createOnboardingDryRunPlan.mockResolvedValueOnce(plan);

    const result = await createOnboardingDryRunPlanAction(
      { kind: "idle" },
      buildForm({
        purpose: "Plan the safest next task.",
        expected_artifact: "Reviewed plan",
        allowed_action_class: "pr_open",
        starter_mode: "draft_pr_requires_approval",
        target_repo_ref: "t-ohga/TaskManagedAI",
        budget_cap: "0 USD committed"
      })
    );

    expect(result).toEqual({ kind: "ok", plan });
    expect(apiMocks.createOnboardingDryRunPlan).toHaveBeenCalledWith({
      purpose: "Plan the safest next task.",
      expected_artifact: "Reviewed plan",
      allowed_action_class: "pr_open",
      starter_mode: "draft_pr_requires_approval",
      target_repo_ref: "t-ohga/TaskManagedAI",
      budget_cap: "0 USD committed"
    });
  });

  it("sanitizes backend failures", async () => {
    apiMocks.createOnboardingDryRunPlan.mockRejectedValueOnce(new Error("sk-AAAAAAAAAAAAAAAAAAAAAAAA"));

    const result = await createOnboardingDryRunPlanAction(
      { kind: "idle" },
      buildForm({
        purpose: "Plan the safest next task.",
        expected_artifact: "Reviewed plan",
        allowed_action_class: "read_only",
        starter_mode: "plan_only"
      })
    );

    expect(result).toEqual({
      kind: "error",
      message: "dry-run 計画を作成できませんでした。"
    });
  });
});

function buildForm(values: Record<string, string>): FormData {
  const formData = new FormData();
  for (const [key, value] of Object.entries(values)) {
    formData.set(key, value);
  }
  return formData;
}

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
