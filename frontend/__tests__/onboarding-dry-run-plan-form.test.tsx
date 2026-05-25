import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DryRunPlanReview } from "@/app/(admin)/onboarding/_components/dry-run-plan-form";
import type { OnboardingDryRunPlan } from "@/lib/api/onboarding";

describe("DryRunPlanReview", () => {
  it("renders a response-only plan without approve or execution controls", () => {
    render(<DryRunPlanReview plan={buildPlan()} />);

    const result = screen.getByRole("region", { name: "dry-run 結果" });
    expect(within(result).getByText("draft_pr_requires_approval")).toBeVisible();
    expect(within(result).getAllByText("pr_open")).toHaveLength(2);
    expect(within(result).getByText("require_approval")).toBeVisible();
    expect(within(result).getByText("required")).toBeVisible();
    expect(within(result).getByText("approval_required_before_execution")).toBeVisible();
    expect(within(result).getByText("No rollback is required.")).toBeVisible();
    expect(within(result).getByText(/response-only deterministic response/u)).toBeInTheDocument();

    const ledger = within(result).getByRole("region", { name: "would_create ledger" });
    expect(within(ledger).getByText("ticket")).toBeVisible();
    expect(within(ledger).getAllByText("false")).toHaveLength(7);
    expect(within(result).getByRole("link", { name: "承認" })).toHaveAttribute(
      "href",
      "/approvals"
    );
    expect(within(result).queryByRole("button", { name: /承認|実行開始|開始/ })).not.toBeInTheDocument();
  });
});

function buildPlan(): OnboardingDryRunPlan {
  return {
    starter_mode: "draft_pr_requires_approval",
    requested_action_class: "pr_open",
    effective_action_class: "pr_open",
    policy_effect: "require_approval",
    approval_required: true,
    risk_level: "high",
    estimated_cost: "0 committed; no provider call was performed by this dry run.",
    rollback_plan: "No rollback is required.",
    test_plan: ["Review the generated plan before any execution is started."],
    blocked_reasons: [
      "dry_run_only_no_execution_started",
      "approval_required_before_execution"
    ],
    next_safe_routes: ["/approvals", "/runs", "/timeline"],
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
