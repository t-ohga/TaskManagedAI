"""Sprint 12 batch 0 (BL-0148): kpi_rollup aggregator tests.

5 KPI MetricResult を mock 構築 → compute_kpi_rollup → P0 判定確認.
Anti-Gaming: 5+ source 整合 (EXPECTED_KPI_IDS が rules / docs / PRD と一致).
"""

from __future__ import annotations

import pytest

from backend.app.services.eval.kpi_rollup import (
    ALL_KPI_IDS,
    KPI_FAIL_TOLERANCE,
    KpiRollupSummary,
    compute_kpi_rollup,
)
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

# 5+ source 整合の 5 番目 source: pytest EXPECTED constant.
# .claude/rules/cross-source-enum-integrity.md §1 準拠。
EXPECTED_KPI_IDS = frozenset(
    {
        "AC-KPI-01",
        "AC-KPI-02",
        "AC-KPI-03",
        "AC-KPI-04",
        "AC-KPI-05",
    }
)


def _acceptance(*, threshold_met: bool, value: float | None = 0.7) -> AcceptancePassRateMetricResult:
    return AcceptancePassRateMetricResult(
        metric_value=value,
        fixture_count=1,
        total_criteria_across_corpus=10,
        evaluated_criteria_across_corpus=10,
        satisfied_criteria_across_corpus=7,
        rejected_criteria_across_corpus=3,
        pass_count=1 if threshold_met else 0,
        fail_count=0 if threshold_met else 1,
        per_fixture=(),
        threshold=0.6,
        threshold_operator=">=",
        threshold_met=threshold_met,
        threshold_reason="threshold_met" if threshold_met else "below_threshold",
        manifest_violation_reason=None,
    )


def _time_to_merge(*, threshold_met: bool, value: float | None = 1.5) -> TimeToMergeMetricResult:
    return TimeToMergeMetricResult(
        metric_value=value,
        fixture_count=1,
        total_pulls_across_corpus=5,
        merged_count_across_corpus=5,
        pass_count=1 if threshold_met else 0,
        fail_count=0 if threshold_met else 1,
        per_fixture=(),
        threshold_hours=2.0,
        threshold_operator="<=",
        threshold_met=threshold_met,
        threshold_reason="threshold_met" if threshold_met else "exceeded",
        manifest_violation_reason=None,
    )


def _approval_wait(*, threshold_met: bool, value: float | None = 3_000_000.0) -> ApprovalWaitMsMetricResult:
    return ApprovalWaitMsMetricResult(
        metric_value=value,
        fixture_count=1,
        total_samples_across_corpus=5,
        decided_count_across_corpus=5,
        pass_count=1 if threshold_met else 0,
        fail_count=0 if threshold_met else 1,
        per_fixture=(),
        threshold_ms=14_400_000,
        threshold_operator="<=",
        threshold_met=threshold_met,
        threshold_reason="threshold_met" if threshold_met else "exceeded",
        manifest_violation_reason=None,
    )


def _citation(*, threshold_met: bool, value: float = 0.95) -> CitationCoverageMetricResult:
    return CitationCoverageMetricResult(
        metric_value=value,
        fixture_count=1,
        total_claims_across_corpus=10,
        claims_with_citation_across_corpus=9 if threshold_met else 7,
        pass_count=1 if threshold_met else 0,
        fail_count=0 if threshold_met else 1,
        per_fixture=(),
        threshold=0.9,
        threshold_operator=">=",
        threshold_met=threshold_met,
        threshold_reason="threshold_met" if threshold_met else "below_threshold",
        manifest_violation_reason=None,
    )


def _cost(*, threshold_met: bool, value: float | None = 0.3) -> CostPerCompletedTaskMetricResult:
    return CostPerCompletedTaskMetricResult(
        metric_value=value,
        fixture_count=1,
        total_completed_runs_across_corpus=5,
        total_cost_usd_across_corpus=1.5,
        pass_count=1 if threshold_met else 0,
        fail_count=0 if threshold_met else 1,
        per_fixture=(),
        threshold_usd=0.5,
        currency="USD",
        threshold_met=threshold_met,
        threshold_reason="threshold_met" if threshold_met else "exceeded",
        manifest_violation_reason=None,
    )


def test_5_plus_source_enum_integrity() -> None:
    """5+ source 整合 (cross-source-enum-integrity §1): ALL_KPI_IDS と
    EXPECTED_KPI_IDS が完全一致 (set equality)。"""
    assert ALL_KPI_IDS == EXPECTED_KPI_IDS
    assert len(ALL_KPI_IDS) == 5


def test_kpi_fail_tolerance_constant() -> None:
    """P0 判定ルール: 未達 1 個以下を P0 承認可とする (PRD-01 §AC-KPI)."""
    assert KPI_FAIL_TOLERANCE == 1


def test_all_pass_p0_accept_true() -> None:
    """5 KPI 全件達成 → p0_accept=True, failed_count=0, met_count=5。"""
    summary = compute_kpi_rollup(
        acceptance=_acceptance(threshold_met=True),
        time_to_merge=_time_to_merge(threshold_met=True),
        approval_wait=_approval_wait(threshold_met=True),
        citation=_citation(threshold_met=True),
        cost=_cost(threshold_met=True),
    )
    assert isinstance(summary, KpiRollupSummary)
    assert summary.kpi_count == 5
    assert summary.met_count == 5
    assert summary.failed_count == 0
    assert summary.p0_accept is True
    assert summary.fail_tolerance == 1


def test_one_fail_p0_accept_true_tolerance_boundary() -> None:
    """1 件 未達 (tolerance == 1) → p0_accept=True (boundary, 通過)."""
    summary = compute_kpi_rollup(
        acceptance=_acceptance(threshold_met=True),
        time_to_merge=_time_to_merge(threshold_met=False, value=3.5),  # 1 失敗
        approval_wait=_approval_wait(threshold_met=True),
        citation=_citation(threshold_met=True),
        cost=_cost(threshold_met=True),
    )
    assert summary.met_count == 4
    assert summary.failed_count == 1
    assert summary.p0_accept is True  # 未達 == tolerance、boundary 通過


def test_two_fail_p0_accept_false() -> None:
    """2 件 未達 → p0_accept=False (改善 Sprint 必要)."""
    summary = compute_kpi_rollup(
        acceptance=_acceptance(threshold_met=False, value=0.4),
        time_to_merge=_time_to_merge(threshold_met=False, value=3.5),
        approval_wait=_approval_wait(threshold_met=True),
        citation=_citation(threshold_met=True),
        cost=_cost(threshold_met=True),
    )
    assert summary.met_count == 3
    assert summary.failed_count == 2
    assert summary.p0_accept is False


def test_all_fail_p0_accept_false() -> None:
    """5 件 未達 → p0_accept=False, failed_count=5。"""
    summary = compute_kpi_rollup(
        acceptance=_acceptance(threshold_met=False),
        time_to_merge=_time_to_merge(threshold_met=False),
        approval_wait=_approval_wait(threshold_met=False),
        citation=_citation(threshold_met=False),
        cost=_cost(threshold_met=False),
    )
    assert summary.met_count == 0
    assert summary.failed_count == 5
    assert summary.p0_accept is False


def test_undefined_metric_value_treated_as_fail() -> None:
    """metric_value=None (corpus undefined) は threshold_met=False で fail count。

    Anti-Gaming: undefined を pass にしないことで KPI 未計測 corpus を
    P0 通すのを防ぐ。
    """
    summary = compute_kpi_rollup(
        acceptance=_acceptance(threshold_met=False, value=None),
        time_to_merge=_time_to_merge(threshold_met=True),
        approval_wait=_approval_wait(threshold_met=True),
        citation=_citation(threshold_met=True),
        cost=_cost(threshold_met=True),
    )
    assert summary.failed_count == 1
    assert summary.entries[0].metric_value is None
    assert summary.entries[0].threshold_met is False


def test_entries_order_matches_kpi_id_order() -> None:
    """entries は AC-KPI-01〜05 の順 (固定、reorder されない invariant)."""
    summary = compute_kpi_rollup(
        acceptance=_acceptance(threshold_met=True),
        time_to_merge=_time_to_merge(threshold_met=True),
        approval_wait=_approval_wait(threshold_met=True),
        citation=_citation(threshold_met=True),
        cost=_cost(threshold_met=True),
    )
    assert [e.kpi_id for e in summary.entries] == [
        "AC-KPI-01",
        "AC-KPI-02",
        "AC-KPI-03",
        "AC-KPI-04",
        "AC-KPI-05",
    ]


def test_entries_metric_key_matches_spec() -> None:
    """metric_key は PRD-01 と Sprint Pack で定義された名称 (snake_case)."""
    summary = compute_kpi_rollup(
        acceptance=_acceptance(threshold_met=True),
        time_to_merge=_time_to_merge(threshold_met=True),
        approval_wait=_approval_wait(threshold_met=True),
        citation=_citation(threshold_met=True),
        cost=_cost(threshold_met=True),
    )
    keys = [e.metric_key for e in summary.entries]
    assert keys == [
        "acceptance_pass_rate",
        "time_to_merge",
        "approval_wait_ms",
        "citation_coverage",
        "cost_per_completed_task",
    ]


def test_threshold_met_count_consistency() -> None:
    """met_count + failed_count == kpi_count (常に 5)。"""
    for ac_met, tm_met, aw_met, cc_met, co_met in (
        (True, True, True, True, True),
        (True, True, True, True, False),
        (True, False, True, False, True),
        (False, False, False, False, False),
    ):
        summary = compute_kpi_rollup(
            acceptance=_acceptance(threshold_met=ac_met),
            time_to_merge=_time_to_merge(threshold_met=tm_met),
            approval_wait=_approval_wait(threshold_met=aw_met),
            citation=_citation(threshold_met=cc_met),
            cost=_cost(threshold_met=co_met),
        )
        assert summary.met_count + summary.failed_count == summary.kpi_count == 5


def test_summary_is_frozen_dataclass() -> None:
    """KpiRollupSummary は frozen + append-only (event sourcing 整合)."""
    summary = compute_kpi_rollup(
        acceptance=_acceptance(threshold_met=True),
        time_to_merge=_time_to_merge(threshold_met=True),
        approval_wait=_approval_wait(threshold_met=True),
        citation=_citation(threshold_met=True),
        cost=_cost(threshold_met=True),
    )
    with pytest.raises(AttributeError):
        summary.p0_accept = False  # type: ignore[misc]
    with pytest.raises(AttributeError):
        summary.entries[0].threshold_met = False  # type: ignore[misc]
