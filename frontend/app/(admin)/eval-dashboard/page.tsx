/**
 * Sprint 12 batch 9 + SP-022 T08 batch 6: P0 Exit Dashboard with live KPI wiring.
 *
 * Read-only display of:
 * - Hard Gates 7 (AC-HARD-01〜07) with metric_value / threshold / threshold_met (static)
 * - KPIs 5 (AC-KPI-01〜05) — **live fetch from `/api/v1/eval/kpi-rollup`** with
 *   skeleton fallback when backend unavailable (503/501) [SP-022 T08 batch 6]
 * - Operational drills (host_migration / backup_restore) with drill_status (static)
 * - P0 Exit decision summary (verdict + deficiency reasons)
 *
 * **Data source**: KPI section now wires to backend `/api/v1/eval/kpi-rollup`
 * via `fetchKpiRollupOrFallback`, with graceful skeleton fallback for backend
 * outage. Hard Gates / Smoke / Private staging / Drills remain static until
 * SP-013+ backend endpoints (BL-0149 sign-off completion).
 *
 * **No live mutation**: Eval Dashboard is read-only per .claude/rules/rendering.md §5.
 * No raw secret / provider response / capability token may appear in DOM.
 * Backend fetch errors are sanitized (status code only, no DSN/credentials leak).
 */

import { BackendApiError } from "@/lib/api/client";
import {
  fetchKpiRollupOrFallback,
  type KpiRollupResponse,
  type KpiRollupSource,
} from "@/lib/api/eval-dashboard";

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

// SP-022 T08 batch 6: skeleton fallback for KPI section (static、backend
// 503/501/network 失敗時に表示)。canonical thresholds (backend evaluator constants):
//   - AC_KPI_01_THRESHOLD = 0.6 (acceptance_pass_rate.py)
//   - AC_KPI_02_THRESHOLD_HOURS = 2.0 (time_to_merge.py)
//   - AC_KPI_03_THRESHOLD_MS = 14_400_000 (= 4h、approval_wait_ms.py)
//   - AC_KPI_04_THRESHOLD = 0.9 (citation_coverage.py)
//   - AC_KPI_05_THRESHOLD_USD = 0.5 (cost_per_completed_task.py)
const KPI_SKELETON_FALLBACK: KpiRollupResponse = {
  kpi_count: 5,
  met_count: 5,
  failed_count: 0,
  p0_accept: true,
  fail_tolerance: 1,
  entries: [
    {
      kpi_id: "AC-KPI-01",
      metric_key: "acceptance_pass_rate",
      metric_value: 0.92,
      threshold_met: true,
      threshold_reason: "threshold_met",
    },
    {
      kpi_id: "AC-KPI-02",
      metric_key: "time_to_merge",
      metric_value: 1.4,
      threshold_met: true,
      threshold_reason: "threshold_met",
    },
    {
      kpi_id: "AC-KPI-03",
      metric_key: "approval_wait_ms",
      metric_value: 1_234_567,
      threshold_met: true,
      threshold_reason: "threshold_met",
    },
    {
      kpi_id: "AC-KPI-04",
      metric_key: "citation_coverage",
      metric_value: 0.95,
      threshold_met: true,
      threshold_reason: "threshold_met",
    },
    {
      kpi_id: "AC-KPI-05",
      metric_key: "cost_per_completed_task",
      metric_value: 0.23,
      threshold_met: true,
      threshold_reason: "threshold_met",
    },
  ],
  corpus_loads: [],
};

const KPI_THRESHOLDS: Record<string, number> = {
  "AC-KPI-01": 0.6,
  "AC-KPI-02": 2.0,
  "AC-KPI-03": 14_400_000,
  "AC-KPI-04": 0.9,
  "AC-KPI-05": 0.5,
};

const KPI_DESCRIPTIONS: Record<string, string> = {
  "AC-KPI-01": "受け入れ条件 pass 率 ≥ 60%",
  "AC-KPI-02": "ticket → merge median ≤ 2.0h",
  "AC-KPI-03": "approval request → decision median ≤ 4h (14,400,000ms)",
  "AC-KPI-04": "claim 当たり citation_count ≥ 1 比率 ≥ 90%",
  "AC-KPI-05": "completed task 当たり provider cost ≤ $0.50",
};

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

// F-PR65-006 P1 adopt: backend GatedRowStatus enum values are lowercase
// (backend/app/services/eval/p0_acceptance_report.py): pass / structured_defer
// / natural_defer / missing. uppercase comparison would route all valid rows
// through FAIL branch.
type GatedRowStatus = "pass" | "structured_defer" | "natural_defer" | "missing";

// F-PR65-005 P1 adopt: SP-012 line 682-704 acceptance artifact fields.
// pass_evidence (PASS / STRUCTURED_DEFER 両方 server-persisted、Codex
// F-PR61-005 P2 carry-over).
type PassEvidence = {
  readonly target_hash: string;
  readonly evidence_artifact_hash: string;
  readonly verified_by: string;
  readonly verified_at: string;
};

// 6-field structured_defer schema (SP-012 line 218-247).
type StructuredDeferFields = {
  readonly owner: string;
  readonly impact: string;
  readonly resume_condition: string;
  readonly blocked_by: readonly string[];
  readonly verification: string;
  readonly target_hash: string;
};

type GatedAcceptanceRowEntry = {
  readonly row_id: string;
  readonly status: GatedRowStatus;
  readonly description: string;
  readonly pass_evidence: PassEvidence | null;
  readonly structured_defer_fields: StructuredDeferFields | null;
};

// F-PR65-004 P1 adopt: canonical gated row set per SP-012 lines 93-99.
// 旧 sample list (BL-0140b / BL-0145 / BL-0149 / BL-0150) は internal core
// rows、SP-012 表 2 の gated proof row 集合と drift していた.
const GATED_ACCEPTANCE_ROWS: readonly GatedAcceptanceRowEntry[] = [
  {
    row_id: "BL-0140a-research-to-pr",
    status: "pass",
    description:
      "Research → Decision → Generated Ticket → Plan → Approval → Runner → Draft PR (hash chain 完備)",
    pass_evidence: {
      target_hash: "0".repeat(64),
      evidence_artifact_hash: "1".repeat(64),
      verified_by: "actor:human:reviewer-001",
      verified_at: "2026-05-18T00:00:00Z",
    },
    structured_defer_fields: null,
  },
  {
    row_id: "AC-KPI-04-research-coverage",
    status: "pass",
    description:
      "citation_coverage ≥ 0.9 AND citation_source_count ≥ 1 AND denominator_nonzero (3 条件 PASS、F-P2R1-011)",
    pass_evidence: {
      target_hash: "2".repeat(64),
      evidence_artifact_hash: "3".repeat(64),
      verified_by: "actor:human:reviewer-001",
      verified_at: "2026-05-18T00:00:00Z",
    },
    structured_defer_fields: null,
  },
  {
    row_id: "BL-0029b-cross-project-negative-agent-runs",
    status: "pass",
    description:
      "agent_runs.parent_run_id cross-project negative を Research-to-PR sub-run でも PASS",
    pass_evidence: {
      target_hash: "4".repeat(64),
      evidence_artifact_hash: "5".repeat(64),
      verified_by: "actor:human:reviewer-001",
      verified_at: "2026-05-18T00:00:00Z",
    },
    structured_defer_fields: null,
  },
  {
    row_id: "BL-0029c-cross-project-negative-research-tasks",
    status: "pass",
    description: "research_tasks cross-project negative (tenant/project boundary)",
    pass_evidence: {
      target_hash: "6".repeat(64),
      evidence_artifact_hash: "7".repeat(64),
      verified_by: "actor:human:reviewer-001",
      verified_at: "2026-05-18T00:00:00Z",
    },
    structured_defer_fields: null,
  },
  {
    row_id: "BL-0151b-secret-capability-tokens-fk",
    status: "pass",
    description:
      "secret_capability_tokens.agent_run_id FK を Research sub-run でも binding verify",
    pass_evidence: {
      target_hash: "8".repeat(64),
      evidence_artifact_hash: "9".repeat(64),
      verified_by: "actor:human:reviewer-001",
      verified_at: "2026-05-18T00:00:00Z",
    },
    structured_defer_fields: null,
  },
  {
    row_id: "research-hash-chain-proof",
    status: "pass",
    description:
      "research_id / source_set_hash / generated_ticket_hash / plan_artifact_hash / approval_id / pr_artifact_hash 全件 binding (F-P2R1-010)",
    pass_evidence: {
      target_hash: "a".repeat(64),
      evidence_artifact_hash: "b".repeat(64),
      verified_by: "actor:human:reviewer-001",
      verified_at: "2026-05-18T00:00:00Z",
    },
    structured_defer_fields: null,
  },
  {
    row_id: "research-to-pr-target-days-review",
    status: "structured_defer",
    description:
      "Research-to-PR representative flow target_days 再見積もり (Sprint Review pending、F-P2R1-014)",
    pass_evidence: null,
    structured_defer_fields: {
      owner: "actor:human:reviewer-001",
      impact: "target_days/max_days 引き上げ可能性、Sprint Exit 判定の事前要件",
      resume_condition: "Sprint Review で max_days 9 days 引き上げを最終判断後",
      blocked_by: ["SP-018 (Hermes memory sprint) との番号衝突解消"],
      verification: "Sprint Pack ## Review § Pending entries に記録",
      target_hash: "c".repeat(64),
    },
  },
];

// Codex PR #91 R1 F-003 fix (P2): verdict summary を live KPI rollup から derive
// (static `P0_EXIT_VERDICT.kpis_pass_count=5` のままだと KPI table が live で fail でも
// verdict は READY と矛盾、data-integrity regression)。
// Hard Gates / Drills / Smoke / Private staging / Gated rows は依然 static (live endpoint は
// SP-013+ BL-0149 sign-off で追加予定)、本 derive は KPI 部分のみ live data 反映。
const STATIC_VERDICT_BASE = {
  hard_gates_pass_count: 7,
  drills_pass_count: 2,
  smoke_success: true,
  private_staging_passed: true,
  gated_rows_satisfied: true,
} as const;

// Codex PR #91 R3 F-001 fix (P1): kpiSource includes "fetch_error" (4xx auth /
// config error) in addition to "live" / "skeleton_fallback"。両 fallback state は
// 共に p0_exit_decision=false 強制。
function deriveVerdict(
  kpiRollup: KpiRollupResponse,
  kpiSource: KpiRollupSource | "fetch_error",
): {
  readonly p0_exit_decision: boolean;
  readonly hard_gates_pass_count: number;
  readonly kpis_pass_count: number;
  readonly drills_pass_count: number;
  readonly smoke_success: boolean;
  readonly private_staging_passed: boolean;
  readonly gated_rows_satisfied: boolean;
  readonly deficiency_reasons: readonly string[];
} {
  const deficiencies: string[] = [];
  // Codex PR #91 R2 F-003 fix (P1) + R3 F-001 fix (P1): KPI data が
  // skeleton_fallback (outage) or fetch_error (auth/config) の場合、live KPI 真値
  // が未取得なので p0_exit_decision=true を主張してはならない。両 fallback state を
  // 「KPI source unavailable」として deficiency reason に明示し、BLOCKED として表示。
  // 旧実装は kpiRollup.p0_accept=true (skeleton 既定値) で常に p0_exit_decision=true
  // を返していた → 実態 (backend down / auth fail) と矛盾する verdict が DOM に出る regression。
  const kpiLive = kpiSource === "live";
  if (!kpiLive) {
    const reason =
      kpiSource === "fetch_error"
        ? "kpi_fetch_error: live KPI rollup unreachable (auth/config error)"
        : "kpi_source_unavailable: skeleton fallback in use, live KPI verdict unverifiable";
    deficiencies.push(reason);
  }
  if (!kpiRollup.p0_accept) {
    deficiencies.push(
      `kpis_pass: ${kpiRollup.met_count}/${kpiRollup.kpi_count} (fail_tolerance=${kpiRollup.fail_tolerance})`,
    );
  }
  // 他 source は static の間は不変、live endpoint 追加後 deficiency 検出ロジック拡張
  const allGreen =
    kpiLive &&
    kpiRollup.p0_accept &&
    STATIC_VERDICT_BASE.hard_gates_pass_count === 7 &&
    STATIC_VERDICT_BASE.drills_pass_count === 2 &&
    STATIC_VERDICT_BASE.smoke_success &&
    STATIC_VERDICT_BASE.private_staging_passed &&
    STATIC_VERDICT_BASE.gated_rows_satisfied;
  return {
    p0_exit_decision: allGreen,
    hard_gates_pass_count: STATIC_VERDICT_BASE.hard_gates_pass_count,
    kpis_pass_count: kpiRollup.met_count,
    drills_pass_count: STATIC_VERDICT_BASE.drills_pass_count,
    smoke_success: STATIC_VERDICT_BASE.smoke_success,
    private_staging_passed: STATIC_VERDICT_BASE.private_staging_passed,
    gated_rows_satisfied: STATIC_VERDICT_BASE.gated_rows_satisfied,
    deficiency_reasons: deficiencies,
  };
}

// Codex PR #91 R3 F-001 fix (P1): fetchKpiRollupOrFallback は 4xx (auth/permission)
// と config/runtime error を rethrow するため、page 側で catch して explicit error
// state を render する。catch なしだと 401/403 (session 期限切れ) で route 全体が
// unhandled server error になり、他 panel (Hard Gates / Drills / Smoke / Gated rows
// = static data) すら表示されない regression が発生する。
type KpiFetchError = "auth_error" | "config_error";

async function fetchKpiSafely(): Promise<
  | {
      readonly source: KpiRollupSource;
      readonly data: KpiRollupResponse;
      readonly fallbackReason?: string;
      readonly errorCategory?: undefined;
    }
  | {
      readonly source: "fetch_error";
      readonly data: KpiRollupResponse;
      readonly fallbackReason: string;
      readonly errorCategory: KpiFetchError;
    }
> {
  try {
    return await fetchKpiRollupOrFallback(KPI_SKELETON_FALLBACK);
  } catch (err) {
    // sanitize: status code / error class のみを reason に出す。raw exception text
    // (DSN / credentials / stack) を DOM に漏らさない invariant。
    if (err instanceof BackendApiError) {
      return {
        source: "fetch_error",
        data: KPI_SKELETON_FALLBACK,
        fallbackReason: `backend returned status=${err.status}`,
        errorCategory: "auth_error",
      };
    }
    // config/runtime/env misconfig: error class 名のみ出す (message を embed しない)
    const errClass = err instanceof Error ? err.constructor.name : "UnknownError";
    return {
      source: "fetch_error",
      data: KPI_SKELETON_FALLBACK,
      fallbackReason: `kpi fetch failed: ${errClass}`,
      errorCategory: "config_error",
    };
  }
}

export default async function EvalDashboardPage() {
  // SP-022 T08 batch 6: live fetch KPI rollup from backend with skeleton fallback
  // (outage-only: 5xx / Zod mismatch、4xx auth / config は fetchKpiSafely で catch)
  const kpiRollupResult = await fetchKpiSafely();
  const kpiRollup = kpiRollupResult.data;
  const kpiSource: KpiRollupSource | "fetch_error" = kpiRollupResult.source;
  const kpiFallbackReason = kpiRollupResult.fallbackReason;
  // Codex PR #91 R1 F-003 fix (P2) + R2 F-003 fix (P1) + R3 F-001 fix (P1):
  // verdict を live KPI rollup から derive。source != "live" (skeleton_fallback /
  // fetch_error) はすべて p0_exit_decision=false 強制。
  const P0_EXIT_VERDICT = deriveVerdict(kpiRollup, kpiSource);

  return (
    <AdminPageShell
      description="Sprint 12 BL-0149 P0 Exit Dashboard skeleton。Hard Gates 7、Quality KPIs 5、operational drills を read-only で表示します。Backend API integration は follow-up batch に defer しています。"
      eyebrow="管理 / 評価"
      regionLabel="P0 Exit ダッシュボード"
      title="P0 Exit ダッシュボード"
    >
      <SecretBoundaryNotice title="No secret / token / raw provider response is rendered" />

      <Panel
        description={`P0 Exit verdict: ${P0_EXIT_VERDICT.p0_exit_decision ? "READY" : "BLOCKED"}.`}
        title="P0 Exit verdict"
        titleId="p0-exit-verdict"
      >
        <dl className="grid gap-3 text-sm">
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted-foreground">p0_exit_decision</dt>
            <dd className="font-mono">
              {P0_EXIT_VERDICT.p0_exit_decision ? "true" : "false"}
            </dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted-foreground">hard_gates_pass</dt>
            <dd className="font-mono">{P0_EXIT_VERDICT.hard_gates_pass_count} / 7</dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted-foreground">kpis_pass</dt>
            <dd className="font-mono">{P0_EXIT_VERDICT.kpis_pass_count} / 5</dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted-foreground">operational_drills_pass</dt>
            <dd className="font-mono">{P0_EXIT_VERDICT.drills_pass_count} / 2</dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted-foreground">smoke.overall_success</dt>
            <dd className="font-mono">
              {P0_EXIT_VERDICT.smoke_success ? "true" : "false"}
            </dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted-foreground">private_staging_passed</dt>
            <dd className="font-mono">
              {P0_EXIT_VERDICT.private_staging_passed ? "true" : "false"}
            </dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted-foreground">gated_acceptance_rows_satisfied</dt>
            <dd className="font-mono">
              {P0_EXIT_VERDICT.gated_rows_satisfied ? "true" : "false"}
            </dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted-foreground">deficiency_reasons</dt>
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
        description={
          `AC-KPI-01〜05. Up to 1 unmet KPI is acceptable for P0 Exit; 2+ adds a quality improvement sprint. ` +
          `Data source: ${
            kpiSource === "live"
              ? "live backend"
              : kpiSource === "fetch_error"
                ? `error fallback (${kpiFallbackReason ?? "unknown reason"})`
                : `skeleton fallback (${kpiFallbackReason ?? "unknown reason"})`
          }.`
        }
        title="Quality KPIs 5"
        titleId="quality-kpis-5"
      >
        <div className="mb-2 text-xs text-muted-foreground">
          source: <span className="font-mono">{kpiSource}</span>
          {" "}| p0_accept: <span className="font-mono">{kpiRollup.p0_accept ? "true" : "false"}</span>
          {" "}| met: <span className="font-mono">{kpiRollup.met_count}/{kpiRollup.kpi_count}</span>
        </div>
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="min-w-full border-separate border-spacing-0 text-left text-sm">
            <caption className="sr-only">
              Quality KPIs 5 with kpi_id, metric_key, metric_value, threshold,
              threshold_met. Data source: {kpiSource}.
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
                <th scope="col" className="border-b border-line px-3 py-2">
                  description
                </th>
              </tr>
            </thead>
            <tbody>
              {kpiRollup.entries.map((kpi) => (
                <tr key={kpi.kpi_id}>
                  <td className="border-b border-line px-3 py-2 font-mono">
                    {kpi.kpi_id}
                  </td>
                  <td className="border-b border-line px-3 py-2 font-mono">
                    {kpi.metric_key}
                  </td>
                  <td className="border-b border-line px-3 py-2 text-right font-mono">
                    {kpi.metric_value !== null ? kpi.metric_value : "—"}
                  </td>
                  <td className="border-b border-line px-3 py-2 text-right font-mono">
                    {KPI_THRESHOLDS[kpi.kpi_id] ?? "—"}
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
                  <td className="border-b border-line px-3 py-2 text-xs">
                    {KPI_DESCRIPTIONS[kpi.kpi_id] ?? kpi.threshold_reason ?? "—"}
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
            <dt className="text-muted-foreground">overall_success</dt>
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
            <dt className="text-muted-foreground">passed_count</dt>
            <dd className="font-mono">{SMOKE_RESULT.passed_count}</dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted-foreground">failed_count</dt>
            <dd className="font-mono">{SMOKE_RESULT.failed_count}</dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3">
            <dt className="text-muted-foreground">skipped_count</dt>
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
            <dt className="text-muted-foreground">status</dt>
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
            <dt className="text-muted-foreground">description</dt>
            <dd className="text-right">{PRIVATE_STAGING.description}</dd>
          </div>
        </dl>
      </Panel>

      <Panel
        description="SP-012 表 2 + lines 682-704: gated acceptance rows. status=pass (with pass_evidence) or structured_defer (6-field schema) required. F-PR65-004/005/006 P1 adopt."
        title="Gated acceptance rows"
        titleId="gated-acceptance-rows"
      >
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="min-w-full border-separate border-spacing-0 text-left text-sm">
            <caption className="sr-only">
              Gated acceptance rows with row_id, status, description, target_hash,
              evidence_artifact_hash, verified_by, verified_at, structured_defer 6 fields.
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
                <th scope="col" className="border-b border-line px-3 py-2">
                  evidence / structured_defer
                </th>
              </tr>
            </thead>
            <tbody>
              {GATED_ACCEPTANCE_ROWS.map((row) => (
                <tr key={row.row_id}>
                  <td className="border-b border-line px-3 py-2 font-mono">{row.row_id}</td>
                  <td className="border-b border-line px-3 py-2">
                    {row.status === "pass" ? (
                      <span className="rounded-md bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">
                        pass
                      </span>
                    ) : row.status === "structured_defer" ? (
                      <span className="rounded-md bg-sky-50 px-2 py-1 text-xs font-semibold text-sky-700">
                        structured_defer
                      </span>
                    ) : (
                      <span className="rounded-md bg-amber-50 px-2 py-1 text-xs font-semibold text-attention">
                        {row.status}
                      </span>
                    )}
                  </td>
                  <td className="border-b border-line px-3 py-2 text-xs">{row.description}</td>
                  <td className="border-b border-line px-3 py-2 text-xs">
                    {row.pass_evidence !== null ? (
                      <dl className="grid gap-1 font-mono">
                        <div>
                          target_hash: {row.pass_evidence.target_hash.slice(0, 16)}…
                        </div>
                        <div>
                          evidence: {row.pass_evidence.evidence_artifact_hash.slice(0, 16)}…
                        </div>
                        <div>verified_by: {row.pass_evidence.verified_by}</div>
                        <div>verified_at: {row.pass_evidence.verified_at}</div>
                      </dl>
                    ) : row.structured_defer_fields !== null ? (
                      <dl className="grid gap-1">
                        <div>
                          <span className="font-mono">owner:</span>{" "}
                          {row.structured_defer_fields.owner}
                        </div>
                        <div>
                          <span className="font-mono">impact:</span>{" "}
                          {row.structured_defer_fields.impact}
                        </div>
                        <div>
                          <span className="font-mono">resume_condition:</span>{" "}
                          {row.structured_defer_fields.resume_condition}
                        </div>
                        <div>
                          <span className="font-mono">blocked_by:</span>{" "}
                          {row.structured_defer_fields.blocked_by.join(", ")}
                        </div>
                        <div>
                          <span className="font-mono">verification:</span>{" "}
                          {row.structured_defer_fields.verification}
                        </div>
                        <div>
                          <span className="font-mono">target_hash:</span>{" "}
                          {row.structured_defer_fields.target_hash.slice(0, 16)}…
                        </div>
                      </dl>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
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
              <dt className="text-muted-foreground">
                <span className="font-mono">{drill.drill_kind}</span>
                <span className="ml-2 text-xs text-muted-foreground">{drill.description}</span>
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
