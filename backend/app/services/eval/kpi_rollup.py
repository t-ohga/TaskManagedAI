"""Sprint 12 batch 0 (BL-0148): AC-KPI 5 件集計 aggregator + P0 判定ルール.

5 個の Quality KPIs (AC-KPI-01〜05) の MetricResult を集約し、P0 判定ルール
"未達 1 個以下" (P0 Exit 判定の中核) を評価する pure function.

P0 判定ルール (PRD-01 / 計画(仮).md / .claude/reference/hard-gates-and-kpis.md):
- KPI 5 件のうち未達 (`threshold_met == False`) が **1 個以下**なら P0 承認可
- 未達 2 個以上なら改善 Sprint を追加

Aggregator は pure (no DB / file system / network access)。caller が
`evaluate_*` 個別 function 5 個を実行し、本 function に 5 つの MetricResult
を渡す。BL-0148 受け入れ条件と一致.

Anti-Gaming invariant (本 aggregator):
- KPI 5 件は **固定 enum** (AC-KPI-01〜05、frozenset で 5+ source 整合)
- 各 KPI MetricResult の `threshold_met` を **信頼**して count (再計算なし、
  re-compute は個別 evaluate_* function の責務)
- caller が任意 KPI を skip / 追加できない (signature 上 5 引数固定)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from backend.app.services.eval.kpis.acceptance_pass_rate import (
    AcceptancePassRateMetricResult,
)
from backend.app.services.eval.kpis.approval_wait_ms import (
    ApprovalWaitMsMetricResult,
)
from backend.app.services.eval.kpis.citation_coverage import (
    CitationCoverageMetricResult,
)
from backend.app.services.eval.kpis.cost_per_completed_task import (
    CostPerCompletedTaskMetricResult,
)
from backend.app.services.eval.kpis.time_to_merge import (
    TimeToMergeMetricResult,
)

# 5+ source 整合: KPI 5 件 enum (.claude/rules/cross-source-enum-integrity.md §1)
# - Python frozenset (本 file)
# - PRD-01 §AC-KPI 一覧 + 計画(仮).md
# - .claude/reference/hard-gates-and-kpis.md §2
# - SP-012 Pack §AC-KPI
# - test EXPECTED_KPI_IDS (`tests/eval/test_kpi_rollup.py`)
ALL_KPI_IDS: Final[frozenset[str]] = frozenset(
    {
        "AC-KPI-01",  # acceptance_pass_rate (>=0.6)
        "AC-KPI-02",  # time_to_merge (median <= 2.0h)
        "AC-KPI-03",  # approval_wait_ms (median <= 4h = 14_400_000 ms)
        "AC-KPI-04",  # citation_coverage (>=0.9)
        "AC-KPI-05",  # cost_per_completed_task (<=$0.5)
    }
)

# P0 判定ルール (PRD-01 §AC-KPI): 未達 1 個以下なら P0 承認可
KPI_FAIL_TOLERANCE: Final[int] = 1


@dataclass(frozen=True, slots=True)
class KpiEntry:
    """単一 KPI の集計 entry (frozen、append-only)。"""

    kpi_id: Literal[
        "AC-KPI-01", "AC-KPI-02", "AC-KPI-03", "AC-KPI-04", "AC-KPI-05"
    ]
    metric_key: str  # "acceptance_pass_rate" 等
    metric_value: float | None  # corpus undefined なら None
    threshold_met: bool
    threshold_reason: str | None  # "no_evaluated_criteria" 等の理由


@dataclass(frozen=True, slots=True)
class KpiRollupSummary:
    """KPI 5 件集計 + P0 判定結果 (frozen、append-only)。

    BL-0148 受け入れ条件:
    - 5 KPI 全件評価 (kpi_count == 5)
    - met_count + failed_count == 5 (合計常に 5)
    - p0_accept = (failed_count <= KPI_FAIL_TOLERANCE)
    - p0_accept が True なら P0 承認可、False なら改善 Sprint 追加

    Note: `metric_value is None` (corpus undefined、e.g. no_evaluated_criteria)
    の場合、`threshold_met=False` で fail count に含まれる。これは
    Anti-Gaming で undefined を pass にしないため (KPI 未計測の corpus を
    P0 通すと品質劣化)。
    """

    kpi_count: int  # 常に 5 (固定 enum)
    met_count: int
    failed_count: int
    p0_accept: bool
    fail_tolerance: int  # KPI_FAIL_TOLERANCE = 1
    entries: tuple[KpiEntry, ...]


def compute_kpi_rollup(
    *,
    acceptance: AcceptancePassRateMetricResult,
    time_to_merge: TimeToMergeMetricResult,
    approval_wait: ApprovalWaitMsMetricResult,
    citation: CitationCoverageMetricResult,
    cost: CostPerCompletedTaskMetricResult,
) -> KpiRollupSummary:
    """5 KPI MetricResult を集計し P0 判定する pure function.

    BL-0148 main entry point。caller (e.g. SP-012 batch 1+ API endpoint /
    CLI / nightly cron) が 5 個の `evaluate_*` を実行し、本 function に渡す.

    Args:
        acceptance: AC-KPI-01 result (evaluate_acceptance_pass_rate)
        time_to_merge: AC-KPI-02 result (evaluate_time_to_merge)
        approval_wait: AC-KPI-03 result (evaluate_approval_wait_ms)
        citation: AC-KPI-04 result (evaluate_citation_coverage)
        cost: AC-KPI-05 result (evaluate_cost_per_completed_task)

    Returns:
        KpiRollupSummary with 5 entries + p0_accept gate decision.
    """

    entries: tuple[KpiEntry, ...] = (
        KpiEntry(
            kpi_id="AC-KPI-01",
            metric_key="acceptance_pass_rate",
            metric_value=acceptance.metric_value,
            threshold_met=acceptance.threshold_met,
            threshold_reason=acceptance.threshold_reason,
        ),
        KpiEntry(
            kpi_id="AC-KPI-02",
            metric_key="time_to_merge",
            metric_value=time_to_merge.metric_value,
            threshold_met=time_to_merge.threshold_met,
            threshold_reason=getattr(
                time_to_merge, "threshold_reason", None
            ),
        ),
        KpiEntry(
            kpi_id="AC-KPI-03",
            metric_key="approval_wait_ms",
            metric_value=approval_wait.metric_value,
            threshold_met=approval_wait.threshold_met,
            threshold_reason=getattr(
                approval_wait, "threshold_reason", None
            ),
        ),
        KpiEntry(
            kpi_id="AC-KPI-04",
            metric_key="citation_coverage",
            metric_value=citation.metric_value,
            threshold_met=citation.threshold_met,
            threshold_reason=citation.threshold_reason,
        ),
        KpiEntry(
            kpi_id="AC-KPI-05",
            metric_key="cost_per_completed_task",
            metric_value=cost.metric_value,
            threshold_met=cost.threshold_met,
            threshold_reason=getattr(cost, "threshold_reason", None),
        ),
    )

    met_count = sum(1 for e in entries if e.threshold_met)
    failed_count = len(entries) - met_count

    # P0 判定: 未達 <= KPI_FAIL_TOLERANCE
    p0_accept = failed_count <= KPI_FAIL_TOLERANCE

    return KpiRollupSummary(
        kpi_count=len(entries),
        met_count=met_count,
        failed_count=failed_count,
        p0_accept=p0_accept,
        fail_tolerance=KPI_FAIL_TOLERANCE,
        entries=entries,
    )


__all__ = [
    "ALL_KPI_IDS",
    "KPI_FAIL_TOLERANCE",
    "KpiEntry",
    "KpiRollupSummary",
    "compute_kpi_rollup",
]
