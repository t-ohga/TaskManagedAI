/**
 * Sprint 12 batch 9: P0 Exit Dashboard (P0 UI skeleton).
 *
 * Read-only display of:
 * - Hard Gates 7 (AC-HARD-01〜07) with metric_value / threshold / threshold_met
 * - KPIs 5 (AC-KPI-01〜05) with metric_value / threshold
 * - Operational drills (host_migration / backup_restore) with drill_status
 * - P0 Exit decision summary (verdict + deficiency reasons)
 *
 * **Data source**: Sprint 12 batch 6 BL-0149 `P0AcceptanceReportSummary` will
 * be wired in via backend API at a later batch. This skeleton uses static
 * sample data to establish the layout + accessibility + secret boundary.
 *
 * **No live mutation**: Eval Dashboard is read-only per .claude/rules/rendering.md §5.
 * No raw secret / provider response / capability token may appear in DOM.
 */

import {
  AdminPageShell,
  Panel,
  SecretBoundaryNotice,
} from "../_components/sprint9-admin-ui";

export const dynamic = "force-dynamic";

// Hard Gates 7 (AC-HARD-01〜07). Each row is the canonical contract from
// .claude/rules/agentrun-state-machine.md + Sprint Pack SP-012.
const HARD_GATES_7 = [
  {
    gate_id: "AC-HARD-01",
    metric_key: "policy_block_recall",
    threshold: 1.0,
    metric_value: 1.0,
    threshold_met: true,
    fixture_count: 1,
    description: "危険 action が 100% deny される",
  },
  {
    gate_id: "AC-HARD-02",
    metric_key: "secret_canary_no_leak",
    threshold: 1.0,
    metric_value: 1.0,
    threshold_met: true,
    fixture_count: 2,
    description: "fake API key が provider/artifact/runner に漏れない",
  },
  {
    gate_id: "AC-HARD-03",
    metric_key: "tenant_isolation_negative_pass",
    threshold: 1.0,
    metric_value: 1.0,
    threshold_met: true,
    fixture_count: 17,
    description: "tenant / project 境界の越境 negative 100% deny",
  },
  {
    gate_id: "AC-HARD-04",
    metric_key: "backup_restore_rpo_rto",
    threshold: 1.0,
    metric_value: 1.0,
    threshold_met: true,
    fixture_count: 1,
    description: "RPO ≤ 24h / RTO ≤ 4h drill PASS",
  },
  {
    gate_id: "AC-HARD-05",
    metric_key: "forbidden_path_block",
    threshold: 1.0,
    metric_value: 1.0,
    threshold_met: true,
    fixture_count: 1,
    description: ".env / .git/config / secrets / migrations / .github/workflows を runner で reject",
  },
  {
    gate_id: "AC-HARD-06",
    metric_key: "dangerous_command_block",
    threshold: 1.0,
    metric_value: 1.0,
    threshold_met: true,
    fixture_count: 1,
    description: "rm -rf / curl|sh / fork bomb / chmod 777 / privileged Docker reject",
  },
  {
    gate_id: "AC-HARD-07",
    metric_key: "prompt_injection_resist",
    threshold: 1.0,
    metric_value: 1.0,
    threshold_met: true,
    fixture_count: 1,
    description: "untrusted_content の権限昇格 reject",
  },
] as const;

// Quality KPIs 5 (AC-KPI-01〜05). P0 Exit allows 1 unmet KPI; 2+ adds a
// quality improvement sprint per CLAUDE.md §2.
// F-PR65-002 P1 adopt: thresholds 値は canonical evaluator constants と整合
// (backend/app/services/eval/kpis/*.py):
//   - AC_KPI_01_THRESHOLD = 0.6 (acceptance_pass_rate.py)
//   - AC_KPI_02_THRESHOLD_HOURS = 2.0 (time_to_merge.py)
//   - AC_KPI_03_THRESHOLD_MS = 14_400_000 (= 4h、approval_wait_ms.py)
//   - AC_KPI_04_THRESHOLD = 0.9 (citation_coverage.py)
//   - AC_KPI_05_THRESHOLD_USD = 0.5 (cost_per_completed_task.py)
const QUALITY_KPIS_5 = [
  {
    kpi_id: "AC-KPI-01",
    metric_key: "acceptance_pass_rate",
    threshold: 0.6,
    metric_value: 0.92,
    threshold_met: true,
    description: "受け入れ条件 pass 率 ≥ 60%",
  },
  {
    kpi_id: "AC-KPI-02",
    metric_key: "time_to_merge",
    threshold: 2.0,
    metric_value: 1.4,
    threshold_met: true,
    description: "ticket → merge median ≤ 2.0h",
  },
  {
    kpi_id: "AC-KPI-03",
    metric_key: "approval_wait_ms",
    threshold: 14_400_000,
    metric_value: 1_234_567,
    threshold_met: true,
    description: "approval request → decision p95 ≤ 4h (14,400,000ms)",
  },
  {
    kpi_id: "AC-KPI-04",
    metric_key: "citation_coverage",
    threshold: 0.9,
    metric_value: 0.95,
    threshold_met: true,
    description: "claim 当たり citation_count ≥ 1 比率 ≥ 90%",
  },
  {
    kpi_id: "AC-KPI-05",
    metric_key: "cost_per_completed_task",
    threshold: 0.5,
    metric_value: 0.23,
    threshold_met: true,
    description: "completed task 当たり provider cost ≤ $0.50",
  },
] as const;

type OperationalDrillStatus =
  | "pending"
  | "in_progress"
  | "passed"
  | "failed"
  | "deferred_user_confirm";

type OperationalDrillRow = {
  readonly drill_kind: string;
  readonly drill_status: OperationalDrillStatus;
  readonly description: string;
};

const OPERATIONAL_DRILLS: readonly OperationalDrillRow[] = [
  {
    drill_kind: "host_migration",
    drill_status: "passed",
    description: "Mac ↔ VPS host migration drill",
  },
  {
    drill_kind: "backup_restore",
    drill_status: "passed",
    description: "Full backup → restore drill with PITR",
  },
];

// F-PR65-001 P1 adopt: backend P0 acceptance contract は 7 sources を要求
// (backend/app/services/eval/p0_acceptance_report.py):
//   1. hard_gates_all_pass (AC-HARD-01〜07)
//   2. kpis_pass (AC-KPI-01〜05、未達 ≤ 1)
//   3. smoke.overall_success (ticket-to-PR gold flow)
//   4. host_migration drill passed
//   5. backup_restore drill passed
//   6. private_staging_status == PASSED
//   7. gated_acceptance_rows 全件 PASS or schema-valid STRUCTURED_DEFER
// 1-7 全 source pass で p0_exit_decision=true (skeleton で 7 sources 全件表示).
type PrivateStagingStatus = "passed" | "in_progress" | "not_run" | "failed";

const SMOKE_RESULT = {
  overall_success: true,
  passed_count: 12,
  failed_count: 0,
  skipped_count: 0,
  description: "Ticket → PR gold flow smoke (12 steps)",
} as const;

const PRIVATE_STAGING = {
  status: "passed" as PrivateStagingStatus,
  description: "Tailscale 閉域 private staging CI/E2E",
};

type GatedAcceptanceRowEntry = {
  readonly row_id: string;
  readonly status: "PASS" | "STRUCTURED_DEFER" | "FAIL";
  readonly description: string;
};

const GATED_ACCEPTANCE_ROWS: readonly GatedAcceptanceRowEntry[] = [
  {
    row_id: "BL-0140a-research-to-pr",
    status: "PASS",
    description: "Research → Ticket → PR end-to-end traceability",
  },
  {
    row_id: "BL-0140b-host-migration-smoke",
    status: "PASS",
    description: "Host migration smoke (Mac ↔ VPS)",
  },
  {
    row_id: "BL-0145-kpi-rollup",
    status: "PASS",
    description: "AC-KPI rollup aggregator end-to-end",
  },
  {
    row_id: "BL-0149-p0-acceptance-report",
    status: "PASS",
    description: "P0 Acceptance Report sign-off generator",
  },
  {
    row_id: "BL-0150-audit-events-signed-journal",
    status: "STRUCTURED_DEFER",
    description: "Audit signed journal (batch 10 で配備、structured defer)",
  },
];

const P0_EXIT_VERDICT = {
  p0_exit_decision: true,
  hard_gates_pass_count: 7,
  kpis_pass_count: 5,
  drills_pass_count: 2,
  smoke_success: true,
  private_staging_passed: true,
  gated_rows_satisfied: true,
  deficiency_reasons: [] as readonly string[],
} as const;

export default function EvalDashboardPage() {
  return (
    <AdminPageShell
      description="Sprint 12 BL-0149 P0 Exit Dashboard skeleton. Read-only view of Hard Gates 7 + Quality KPIs 5 + operational drills. Backend API integration is deferred to a follow-up batch."
      eyebrow="Admin / Eval"
      regionLabel="P0 Exit Dashboard"
      title="P0 Exit Dashboard"
    >
      <SecretBoundaryNotice title="No secret / token / raw provider response is rendered" />

      <Panel
        description={`P0 Exit verdict: ${P0_EXIT_VERDICT.p0_exit_decision ? "READY" : "BLOCKED"}.`}
        title="P0 Exit verdict"
        titleId="p0-exit-verdict"
      >
        <dl className="grid gap-3 text-sm">
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted">p0_exit_decision</dt>
            <dd className="font-mono">
              {P0_EXIT_VERDICT.p0_exit_decision ? "true" : "false"}
            </dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted">hard_gates_pass</dt>
            <dd className="font-mono">{P0_EXIT_VERDICT.hard_gates_pass_count} / 7</dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted">kpis_pass</dt>
            <dd className="font-mono">{P0_EXIT_VERDICT.kpis_pass_count} / 5</dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted">operational_drills_pass</dt>
            <dd className="font-mono">{P0_EXIT_VERDICT.drills_pass_count} / 2</dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted">smoke.overall_success</dt>
            <dd className="font-mono">
              {P0_EXIT_VERDICT.smoke_success ? "true" : "false"}
            </dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted">private_staging_passed</dt>
            <dd className="font-mono">
              {P0_EXIT_VERDICT.private_staging_passed ? "true" : "false"}
            </dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted">gated_acceptance_rows_satisfied</dt>
            <dd className="font-mono">
              {P0_EXIT_VERDICT.gated_rows_satisfied ? "true" : "false"}
            </dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted">deficiency_reasons</dt>
            <dd className="font-mono">
              {P0_EXIT_VERDICT.deficiency_reasons.length === 0
                ? "[]"
                : P0_EXIT_VERDICT.deficiency_reasons.join(", ")}
            </dd>
          </div>
        </dl>
      </Panel>

      <Panel
        description="AC-HARD-01〜07 must all PASS for P0 Exit. metric_value ≥ threshold and threshold_met=true required."
        title="Hard Gates 7"
        titleId="hard-gates-7"
      >
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="min-w-full border-separate border-spacing-0 text-left text-sm">
            <caption className="sr-only">
              Hard Gates 7 with gate_id, metric_key, metric_value, threshold,
              threshold_met, fixture_count.
            </caption>
            <thead className="bg-panel-soft">
              <tr>
                <th scope="col" className="border-b border-line px-3 py-2">
                  gate_id
                </th>
                <th scope="col" className="border-b border-line px-3 py-2">
                  metric_key
                </th>
                <th scope="col" className="border-b border-line px-3 py-2 text-right">
                  metric_value
                </th>
                <th scope="col" className="border-b border-line px-3 py-2 text-right">
                  threshold
                </th>
                <th scope="col" className="border-b border-line px-3 py-2">
                  threshold_met
                </th>
                <th scope="col" className="border-b border-line px-3 py-2 text-right">
                  fixture_count
                </th>
              </tr>
            </thead>
            <tbody>
              {HARD_GATES_7.map((gate) => (
                <tr key={gate.gate_id}>
                  <td className="border-b border-line px-3 py-2 font-mono">
                    {gate.gate_id}
                  </td>
                  <td className="border-b border-line px-3 py-2 font-mono">
                    {gate.metric_key}
                  </td>
                  <td className="border-b border-line px-3 py-2 text-right font-mono">
                    {gate.metric_value.toFixed(2)}
                  </td>
                  <td className="border-b border-line px-3 py-2 text-right font-mono">
                    {gate.threshold.toFixed(2)}
                  </td>
                  <td className="border-b border-line px-3 py-2">
                    {gate.threshold_met ? (
                      <span className="rounded-md bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">
                        PASS
                      </span>
                    ) : (
                      <span className="rounded-md bg-amber-50 px-2 py-1 text-xs font-semibold text-attention">
                        FAIL
                      </span>
                    )}
                  </td>
                  <td className="border-b border-line px-3 py-2 text-right font-mono">
                    {gate.fixture_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel
        description="AC-KPI-01〜05. Up to 1 unmet KPI is acceptable for P0 Exit; 2+ adds a quality improvement sprint."
        title="Quality KPIs 5"
        titleId="quality-kpis-5"
      >
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="min-w-full border-separate border-spacing-0 text-left text-sm">
            <caption className="sr-only">
              Quality KPIs 5 with kpi_id, metric_key, metric_value, threshold,
              threshold_met.
            </caption>
            <thead className="bg-panel-soft">
              <tr>
                <th scope="col" className="border-b border-line px-3 py-2">
                  kpi_id
                </th>
                <th scope="col" className="border-b border-line px-3 py-2">
                  metric_key
                </th>
                <th scope="col" className="border-b border-line px-3 py-2 text-right">
                  metric_value
                </th>
                <th scope="col" className="border-b border-line px-3 py-2 text-right">
                  threshold
                </th>
                <th scope="col" className="border-b border-line px-3 py-2">
                  threshold_met
                </th>
              </tr>
            </thead>
            <tbody>
              {QUALITY_KPIS_5.map((kpi) => (
                <tr key={kpi.kpi_id}>
                  <td className="border-b border-line px-3 py-2 font-mono">
                    {kpi.kpi_id}
                  </td>
                  <td className="border-b border-line px-3 py-2 font-mono">
                    {kpi.metric_key}
                  </td>
                  <td className="border-b border-line px-3 py-2 text-right font-mono">
                    {kpi.metric_value}
                  </td>
                  <td className="border-b border-line px-3 py-2 text-right font-mono">
                    {kpi.threshold}
                  </td>
                  <td className="border-b border-line px-3 py-2">
                    {kpi.threshold_met ? (
                      <span className="rounded-md bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">
                        PASS
                      </span>
                    ) : (
                      <span className="rounded-md bg-amber-50 px-2 py-1 text-xs font-semibold text-attention">
                        FAIL
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel
        description="Ticket → PR gold flow smoke (BL-0140a). P0 Exit requires overall_success=true."
        title="Ticket-to-PR smoke"
        titleId="ticket-to-pr-smoke"
      >
        <dl className="grid gap-3 text-sm">
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted">overall_success</dt>
            <dd>
              {SMOKE_RESULT.overall_success ? (
                <span className="rounded-md bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">
                  PASS
                </span>
              ) : (
                <span className="rounded-md bg-amber-50 px-2 py-1 text-xs font-semibold text-attention">
                  FAIL
                </span>
              )}
            </dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted">passed_count</dt>
            <dd className="font-mono">{SMOKE_RESULT.passed_count}</dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted">failed_count</dt>
            <dd className="font-mono">{SMOKE_RESULT.failed_count}</dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted">skipped_count</dt>
            <dd className="font-mono">{SMOKE_RESULT.skipped_count}</dd>
          </div>
        </dl>
      </Panel>

      <Panel
        description="Private staging CI/E2E (Tailscale 閉域). P0 Exit requires status=passed."
        title="Private staging"
        titleId="private-staging"
      >
        <dl className="grid gap-3 text-sm">
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted">status</dt>
            <dd>
              {PRIVATE_STAGING.status === "passed" ? (
                <span className="rounded-md bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">
                  PASSED
                </span>
              ) : (
                <span className="rounded-md bg-amber-50 px-2 py-1 text-xs font-semibold text-attention">
                  {PRIVATE_STAGING.status.toUpperCase()}
                </span>
              )}
            </dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted">description</dt>
            <dd className="text-right">{PRIVATE_STAGING.description}</dd>
          </div>
        </dl>
      </Panel>

      <Panel
        description="SP-012 表 2: gated acceptance rows (BL-NNN). PASS or schema-valid STRUCTURED_DEFER 必須."
        title="Gated acceptance rows"
        titleId="gated-acceptance-rows"
      >
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="min-w-full border-separate border-spacing-0 text-left text-sm">
            <caption className="sr-only">
              Gated acceptance rows with row_id, status, description.
            </caption>
            <thead className="bg-panel-soft">
              <tr>
                <th scope="col" className="border-b border-line px-3 py-2">
                  row_id
                </th>
                <th scope="col" className="border-b border-line px-3 py-2">
                  status
                </th>
                <th scope="col" className="border-b border-line px-3 py-2">
                  description
                </th>
              </tr>
            </thead>
            <tbody>
              {GATED_ACCEPTANCE_ROWS.map((row) => (
                <tr key={row.row_id}>
                  <td className="border-b border-line px-3 py-2 font-mono">{row.row_id}</td>
                  <td className="border-b border-line px-3 py-2">
                    {row.status === "PASS" ? (
                      <span className="rounded-md bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">
                        PASS
                      </span>
                    ) : row.status === "STRUCTURED_DEFER" ? (
                      <span className="rounded-md bg-sky-50 px-2 py-1 text-xs font-semibold text-sky-700">
                        STRUCTURED_DEFER
                      </span>
                    ) : (
                      <span className="rounded-md bg-amber-50 px-2 py-1 text-xs font-semibold text-attention">
                        FAIL
                      </span>
                    )}
                  </td>
                  <td className="border-b border-line px-3 py-2 text-xs">{row.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel
        description="Operational drills required for P0 Exit (host_migration + backup_restore)."
        title="Operational drills"
        titleId="operational-drills"
      >
        <dl className="grid gap-3 text-sm">
          {OPERATIONAL_DRILLS.map((drill) => (
            <div
              key={drill.drill_kind}
              className="flex justify-between gap-4 border-t border-line pt-3"
            >
              <dt className="text-muted">
                <span className="font-mono">{drill.drill_kind}</span>
                <span className="ml-2 text-xs text-muted">{drill.description}</span>
              </dt>
              <dd>
                {drill.drill_status === "passed" ? (
                  <span className="rounded-md bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">
                    PASSED
                  </span>
                ) : (
                  <span className="rounded-md bg-amber-50 px-2 py-1 text-xs font-semibold text-attention">
                    {drill.drill_status.toUpperCase()}
                  </span>
                )}
              </dd>
            </div>
          ))}
        </dl>
      </Panel>
    </AdminPageShell>
  );
}
