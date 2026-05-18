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

  it("renders all 7 P0 sources in verdict (F-PR65-001 P1 adopt)", () => {
    render(<EvalDashboardPage />);
    const verdictSection = screen
      .getByRole("heading", { name: "P0 Exit verdict" })
      .closest("section");
    expect(verdictSection).not.toBeNull();
    if (verdictSection) {
      const within_ = within(verdictSection);
      // 7 sources: hard_gates / kpis / drills / smoke / private_staging /
      // gated_rows + p0_exit_decision + deficiency_reasons
      expect(within_.getByText("hard_gates_pass")).toBeInTheDocument();
      expect(within_.getByText("kpis_pass")).toBeInTheDocument();
      expect(within_.getByText("operational_drills_pass")).toBeInTheDocument();
      expect(within_.getByText("smoke.overall_success")).toBeInTheDocument();
      expect(within_.getByText("private_staging_passed")).toBeInTheDocument();
      expect(within_.getByText("gated_acceptance_rows_satisfied")).toBeInTheDocument();
      expect(within_.getByText("deficiency_reasons")).toBeInTheDocument();
    }
  });

  it("renders canonical KPI thresholds (F-PR65-002 P1 adopt)", () => {
    render(<EvalDashboardPage />);
    // canonical values from backend/app/services/eval/kpis/*.py:
    // AC-KPI-01: 0.6 / AC-KPI-02: 2 / AC-KPI-03: 14,400,000 / AC-KPI-04: 0.9 / AC-KPI-05: 0.5
    const kpiSection = screen
      .getByRole("heading", { name: "Quality KPIs 5" })
      .closest("section");
    expect(kpiSection).not.toBeNull();
    if (kpiSection) {
      const within_ = within(kpiSection);
      expect(within_.getByText("0.6")).toBeInTheDocument();
      expect(within_.getByText("14400000")).toBeInTheDocument();
      expect(within_.getByText("0.9")).toBeInTheDocument();
      expect(within_.getAllByText("0.5").length).toBeGreaterThan(0);
      // AC-KPI-02 threshold = 2.0 という値も同 panel 内に存在
      const monoTwos = within_.getAllByText("2");
      expect(monoTwos.length).toBeGreaterThan(0);
    }
  });

  it("renders Ticket-to-PR smoke section + private staging section + gated rows", () => {
    render(<EvalDashboardPage />);
    expect(screen.getByRole("heading", { name: "Ticket-to-PR smoke" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Private staging" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Gated acceptance rows" }),
    ).toBeInTheDocument();
  });

  it("renders STRUCTURED_DEFER status for partially-deferred gated rows", () => {
    render(<EvalDashboardPage />);
    expect(screen.getByText("STRUCTURED_DEFER")).toBeInTheDocument();
  });
});
