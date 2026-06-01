import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  fetchKpiRollupOrFallback as fetchKpiRollupOrFallbackType,
  KpiRollupResponse,
} from "@/lib/api/eval-dashboard";

type EvalDashboardModule = {
  fetchKpiRollupOrFallback: typeof fetchKpiRollupOrFallbackType;
};

// SP-022 T08 batch 6: page は async Server Component で fetchKpiRollupOrFallback
// を呼び出すため、test では fetchKpiRollupOrFallback を mock して live source
// data を返す。R2 F-003 fix で source=skeleton_fallback の場合 p0_exit_decision=false
// 強制されるため、verdict=READY assertion を維持するには live source mock 必須。
const LIVE_KPI_RESPONSE: KpiRollupResponse = {
  kpi_count: 5,
  met_count: 5,
  failed_count: 0,
  p0_accept: true,
  fail_tolerance: 1,
  entries: [
    { kpi_id: "AC-KPI-01", metric_key: "acceptance_pass_rate", metric_value: 0.92, threshold_met: true, threshold_reason: "threshold_met" },
    { kpi_id: "AC-KPI-02", metric_key: "time_to_merge", metric_value: 1.4, threshold_met: true, threshold_reason: "threshold_met" },
    { kpi_id: "AC-KPI-03", metric_key: "approval_wait_ms", metric_value: 1_234_567, threshold_met: true, threshold_reason: "threshold_met" },
    { kpi_id: "AC-KPI-04", metric_key: "citation_coverage", metric_value: 0.95, threshold_met: true, threshold_reason: "threshold_met" },
    { kpi_id: "AC-KPI-05", metric_key: "cost_per_completed_task", metric_value: 0.23, threshold_met: true, threshold_reason: "threshold_met" },
  ],
  corpus_loads: [],
};

vi.mock("@/lib/api/eval-dashboard", async (importOriginal) => {
  const actual = await importOriginal<EvalDashboardModule>();
  return {
    ...actual,
    fetchKpiRollupOrFallback: vi.fn(async () => ({
      source: "live" as const,
      data: LIVE_KPI_RESPONSE,
    })),
  };
});

import EvalDashboardPage from "@/app/(admin)/eval-dashboard/page";

beforeEach(() => {
  vi.clearAllMocks();
});

// async Server Component を sync renderer (RTL) で render するための helper。
async function renderAsync() {
  const tree = await EvalDashboardPage();
  return render(tree);
}

describe("EvalDashboardPage (Sprint 12 batch 9 skeleton + SP-022 T08 batch 6 live wiring)", () => {
  it("renders P0 Exit verdict section with READY when p0_exit_decision is true", async () => {
    await renderAsync();
    expect(
      screen.getByRole("heading", { name: "P0 出口判定" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/READY\./)).toBeInTheDocument();
  });

  it("renders all 7 Hard Gates rows (AC-HARD-01 〜 07)", async () => {
    await renderAsync();
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

  it("renders all 7 Hard Gates metric_key labels (canonical strings)", async () => {
    await renderAsync();
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

  it("renders all 5 Quality KPIs rows (AC-KPI-01 〜 05)", async () => {
    await renderAsync();
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

  it("renders all 5 KPI metric_key labels (canonical strings)", async () => {
    await renderAsync();
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

  it("renders SecretBoundaryNotice indicating no raw secret in DOM", async () => {
    await renderAsync();
    // SecretBoundaryNotice は title prop を <h3> heading として描画する。eval-dashboard は
    // title="シークレット・トークン非表示" を渡す (i18n 日本語化済)。
    expect(
      screen.getByRole("heading", { name: "シークレット・トークン非表示" }),
    ).toBeInTheDocument();
  });

  it("renders operational drills (host_migration + backup_restore)", async () => {
    await renderAsync();
    expect(screen.getByText("host_migration")).toBeInTheDocument();
    expect(screen.getByText("backup_restore")).toBeInTheDocument();
  });

  it("renders PASS badge for every Hard Gate (all threshold_met=true in skeleton)", async () => {
    await renderAsync();
    const hardGatesSection = screen.getByRole("heading", { name: "ハードゲート 7" }).closest("section");
    expect(hardGatesSection).not.toBeNull();
    if (hardGatesSection) {
      const passBadges = within(hardGatesSection).getAllByText("PASS");
      expect(passBadges).toHaveLength(7);
    }
  });

  it("renders all 7 P0 sources in verdict (F-PR65-001 P1 adopt)", async () => {
    await renderAsync();
    const verdictSection = screen
      .getByRole("heading", { name: "P0 出口判定" })
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

  it("renders canonical KPI thresholds (F-PR65-002 P1 adopt)", async () => {
    await renderAsync();
    // canonical values from backend/app/services/eval/kpis/*.py:
    // AC-KPI-01: 0.6 / AC-KPI-02: 2 / AC-KPI-03: 14,400,000 / AC-KPI-04: 0.9 / AC-KPI-05: 0.5
    const kpiSection = screen
      .getByRole("heading", { name: "品質 KPI 5" })
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

  it("renders Ticket-to-PR smoke section + private staging section + gated rows", async () => {
    await renderAsync();
    expect(screen.getByRole("heading", { name: "チケット→PR スモークテスト" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "プライベートステージング" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "ゲート付き受入基準" }),
    ).toBeInTheDocument();
  });

  it("renders structured_defer lowercase status (F-PR65-006 P1 adopt: backend enum lowercase)", async () => {
    await renderAsync();
    // backend GatedRowStatus enum: pass / structured_defer / natural_defer /
    // missing (all lowercase).
    expect(screen.getByText("structured_defer")).toBeInTheDocument();
  });

  it("renders canonical SP-012 gated row IDs (F-PR65-004 P1 adopt)", async () => {
    await renderAsync();
    // SP-012 lines 93-99 canonical gated proof set.
    for (const rowId of [
      "BL-0140a-research-to-pr",
      "AC-KPI-04-research-coverage",
      "BL-0029b-cross-project-negative-agent-runs",
      "BL-0029c-cross-project-negative-research-tasks",
      "BL-0151b-secret-capability-tokens-fk",
      "research-hash-chain-proof",
      "research-to-pr-target-days-review",
    ]) {
      expect(screen.getByText(rowId)).toBeInTheDocument();
    }
  });

  it("renders gated row proof fields (F-PR65-005 P1 adopt: target_hash + evidence_artifact_hash + verified_by + verified_at)", async () => {
    await renderAsync();
    // pass_evidence fields are rendered for PASS rows.
    expect(screen.getAllByText(/^target_hash:/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^evidence:/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^verified_by:/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^verified_at:/).length).toBeGreaterThan(0);
  });

  it("renders structured_defer 6 fields (F-PR65-005 P1 adopt: SP-012 §218-247)", async () => {
    await renderAsync();
    // SP-012 line 218-247 structured_defer 6 fields schema.
    expect(screen.getByText("owner:")).toBeInTheDocument();
    expect(screen.getByText("impact:")).toBeInTheDocument();
    expect(screen.getByText("resume_condition:")).toBeInTheDocument();
    expect(screen.getByText("blocked_by:")).toBeInTheDocument();
    expect(screen.getByText("verification:")).toBeInTheDocument();
  });

  it("R3 F-001: handles 401 auth error without crashing route (renders BLOCKED verdict + error reason)", async () => {
    // Codex PR #91 R3 F-001 fix (P1): fetchKpiRollupOrFallback rethrows 4xx (auth)、
    // page は fetchKpiSafely で catch して error state を render する。
    const { BackendApiError } = await import("@/lib/api/client");
    const { fetchKpiRollupOrFallback } = await import("@/lib/api/eval-dashboard");
    const mockFetch = vi.mocked(fetchKpiRollupOrFallback);
    mockFetch.mockRejectedValueOnce(new BackendApiError(401, "Unauthorized"));
    await renderAsync();
    // route が crash しないこと
    expect(screen.getByRole("heading", { name: "P0 出口判定" })).toBeInTheDocument();
    // verdict は BLOCKED (kpi source unavailable)
    expect(screen.getByText(/BLOCKED\./)).toBeInTheDocument();
    // deficiency_reasons に kpi_fetch_error が含まれる
    expect(screen.getByText(/kpi_fetch_error/)).toBeInTheDocument();
    // raw exception text が DOM に漏れない invariant (Codex PR #91 R3 boundary)
    expect(screen.queryByText(/Unauthorized\b/)).not.toBeInTheDocument();
  });

  it("R3 F-001: handles config error (Error class) without crashing route", async () => {
    // Codex PR #91 R3 F-001 fix (P1): config / runtime error も catch して error state
    const { fetchKpiRollupOrFallback } = await import("@/lib/api/eval-dashboard");
    const mockFetch = vi.mocked(fetchKpiRollupOrFallback);
    mockFetch.mockRejectedValueOnce(new Error("INTERNAL_API_URL must be configured"));
    await renderAsync();
    expect(screen.getByRole("heading", { name: "P0 出口判定" })).toBeInTheDocument();
    expect(screen.getByText(/BLOCKED\./)).toBeInTheDocument();
    // error class 名のみ (Error) で raw message を embed しない
    expect(screen.getByText(/kpi fetch failed: Error/)).toBeInTheDocument();
    // raw exception message は出ない
    expect(screen.queryByText(/INTERNAL_API_URL must be configured/)).not.toBeInTheDocument();
  });

  it("AC-KPI-03 description uses 'median' not 'p95' (F-PR65-003 P2 adopt)", async () => {
    const { container } = await renderAsync();
    // textContent-based assertion: DOM 全体に "decision median" が含まれることを確認、
    // "decision p95" は含まれないことを確認.
    expect(container.textContent).toMatch(/decision median/);
    expect(container.textContent).not.toMatch(/decision p95/);
  });
});
