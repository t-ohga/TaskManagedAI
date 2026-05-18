import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import EvalDashboardPage from "@/app/(admin)/eval-dashboard/page";

describe("EvalDashboardPage (Sprint 12 batch 9 skeleton)", () => {
  it("renders P0 Exit verdict section with READY when p0_exit_decision is true", () => {
    render(<EvalDashboardPage />);
    expect(
      screen.getByRole("heading", { name: "P0 Exit verdict" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/READY\./)).toBeInTheDocument();
  });

  it("renders all 7 Hard Gates rows (AC-HARD-01 〜 07)", () => {
    render(<EvalDashboardPage />);
    for (const id of [
      "AC-HARD-01",
      "AC-HARD-02",
      "AC-HARD-03",
      "AC-HARD-04",
      "AC-HARD-05",
      "AC-HARD-06",
      "AC-HARD-07",
    ]) {
      expect(screen.getByText(id)).toBeInTheDocument();
    }
  });

  it("renders all 7 Hard Gates metric_key labels (canonical strings)", () => {
    render(<EvalDashboardPage />);
    for (const key of [
      "policy_block_recall",
      "secret_canary_no_leak",
      "tenant_isolation_negative_pass",
      "backup_restore_rpo_rto",
      "forbidden_path_block",
      "dangerous_command_block",
      "prompt_injection_resist",
    ]) {
      expect(screen.getByText(key)).toBeInTheDocument();
    }
  });

  it("renders all 5 Quality KPIs rows (AC-KPI-01 〜 05)", () => {
    render(<EvalDashboardPage />);
    for (const id of [
      "AC-KPI-01",
      "AC-KPI-02",
      "AC-KPI-03",
      "AC-KPI-04",
      "AC-KPI-05",
    ]) {
      expect(screen.getByText(id)).toBeInTheDocument();
    }
  });

  it("renders all 5 KPI metric_key labels (canonical strings)", () => {
    render(<EvalDashboardPage />);
    for (const key of [
      "acceptance_pass_rate",
      "time_to_merge",
      "approval_wait_ms",
      "citation_coverage",
      "cost_per_completed_task",
    ]) {
      expect(screen.getByText(key)).toBeInTheDocument();
    }
  });

  it("renders SecretBoundaryNotice indicating no raw secret in DOM", () => {
    render(<EvalDashboardPage />);
    expect(
      screen.getByRole("heading", {
        name: /No secret \/ token \/ raw provider response is rendered/i,
      }),
    ).toBeInTheDocument();
  });

  it("renders operational drills (host_migration + backup_restore)", () => {
    render(<EvalDashboardPage />);
    expect(screen.getByText("host_migration")).toBeInTheDocument();
    expect(screen.getByText("backup_restore")).toBeInTheDocument();
  });

  it("renders PASS badge for every Hard Gate (all threshold_met=true in skeleton)", () => {
    render(<EvalDashboardPage />);
    const hardGatesSection = screen.getByRole("heading", { name: "Hard Gates 7" }).closest("section");
    expect(hardGatesSection).not.toBeNull();
    if (hardGatesSection) {
      const passBadges = within(hardGatesSection).getAllByText("PASS");
      expect(passBadges).toHaveLength(7);
    }
  });
});
