"""Sprint 12 batch 3 (BL-0149 prep): hard_gates_rollup aggregator tests.

7 Hard Gate MetricResult を mock duck-typed object で構築 → compute_hard_gates_rollup
→ P0 判定確認.

Anti-Gaming: 5+ source 整合 + fail_tolerance=0 (1 件でも未達で P0 不可).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from backend.app.services.eval.hard_gates_rollup import (
    ALL_HARD_GATE_IDS,
    HARD_GATE_FAIL_TOLERANCE,
    HardGatesRollupSummary,
    compute_hard_gates_rollup,
)

# 5+ source 整合の 5 番目 source: pytest EXPECTED constant.
EXPECTED_HARD_GATE_IDS = frozenset(
    {
        "AC-HARD-01",
        "AC-HARD-02",
        "AC-HARD-03",
        "AC-HARD-04",
        "AC-HARD-05",
        "AC-HARD-06",
        "AC-HARD-07",
    }
)


@dataclass(frozen=True, slots=True)
class _MockHardGateResult:
    """Hard Gate MetricResult Protocol を満たす最小 mock."""

    metric_value: float | None
    threshold_met: bool
    threshold_reason: str | None = None


def _mock_result(*, threshold_met: bool, value: float | None = 1.0) -> _MockHardGateResult:
    return _MockHardGateResult(
        metric_value=value,
        threshold_met=threshold_met,
        threshold_reason="threshold_met" if threshold_met else "below_threshold",
    )


def test_5_plus_source_enum_integrity() -> None:
    """5+ source 整合 (cross-source-enum-integrity §1): ALL_HARD_GATE_IDS と
    EXPECTED_HARD_GATE_IDS が完全一致 (set equality)。"""
    assert ALL_HARD_GATE_IDS == EXPECTED_HARD_GATE_IDS
    assert len(ALL_HARD_GATE_IDS) == 7


def test_fail_tolerance_zero() -> None:
    """P0 判定ルール: Hard Gates は 1 件でも未達で P0 不可 (KPI rollup と区別)."""
    assert HARD_GATE_FAIL_TOLERANCE == 0


def test_all_pass_p0_accept_true() -> None:
    """7 Hard Gate 全件達成 → p0_accept=True, failed_count=0, met_count=7。"""
    summary = compute_hard_gates_rollup(
        policy_block=_mock_result(threshold_met=True),
        secret_canary=_mock_result(threshold_met=True),
        tenant_isolation=_mock_result(threshold_met=True),
        backup_restore=_mock_result(threshold_met=True),
        forbidden_path=_mock_result(threshold_met=True),
        dangerous_command=_mock_result(threshold_met=True),
        prompt_injection=_mock_result(threshold_met=True),
    )
    assert isinstance(summary, HardGatesRollupSummary)
    assert summary.hard_gate_count == 7
    assert summary.met_count == 7
    assert summary.failed_count == 0
    assert summary.p0_accept is True
    assert summary.fail_tolerance == 0


def test_one_fail_p0_accept_false() -> None:
    """1 件未達 → p0_accept=False (KPI rollup と異なり Hard Gates は厳格)."""
    summary = compute_hard_gates_rollup(
        policy_block=_mock_result(threshold_met=True),
        secret_canary=_mock_result(threshold_met=False, value=0.5),
        tenant_isolation=_mock_result(threshold_met=True),
        backup_restore=_mock_result(threshold_met=True),
        forbidden_path=_mock_result(threshold_met=True),
        dangerous_command=_mock_result(threshold_met=True),
        prompt_injection=_mock_result(threshold_met=True),
    )
    assert summary.met_count == 6
    assert summary.failed_count == 1
    assert summary.p0_accept is False


def test_all_fail_p0_accept_false() -> None:
    """7 件全 fail → p0_accept=False, failed_count=7, met_count=0。"""
    summary = compute_hard_gates_rollup(
        policy_block=_mock_result(threshold_met=False),
        secret_canary=_mock_result(threshold_met=False),
        tenant_isolation=_mock_result(threshold_met=False),
        backup_restore=_mock_result(threshold_met=False),
        forbidden_path=_mock_result(threshold_met=False),
        dangerous_command=_mock_result(threshold_met=False),
        prompt_injection=_mock_result(threshold_met=False),
    )
    assert summary.met_count == 0
    assert summary.failed_count == 7
    assert summary.p0_accept is False


def test_undefined_metric_value_treated_as_fail() -> None:
    """metric_value=None (corpus undefined) は threshold_met=False で fail count.

    Anti-Gaming: undefined を pass にしないことで未計測 corpus を P0 通すのを防止。
    """
    summary = compute_hard_gates_rollup(
        policy_block=_mock_result(threshold_met=False, value=None),
        secret_canary=_mock_result(threshold_met=True),
        tenant_isolation=_mock_result(threshold_met=True),
        backup_restore=_mock_result(threshold_met=True),
        forbidden_path=_mock_result(threshold_met=True),
        dangerous_command=_mock_result(threshold_met=True),
        prompt_injection=_mock_result(threshold_met=True),
    )
    assert summary.failed_count == 1
    assert summary.p0_accept is False
    assert summary.entries[0].metric_value is None
    assert summary.entries[0].threshold_met is False


def test_entries_order_matches_hard_gate_id_order() -> None:
    """entries は AC-HARD-01〜07 の順 (固定、reorder されない invariant)."""
    summary = compute_hard_gates_rollup(
        policy_block=_mock_result(threshold_met=True),
        secret_canary=_mock_result(threshold_met=True),
        tenant_isolation=_mock_result(threshold_met=True),
        backup_restore=_mock_result(threshold_met=True),
        forbidden_path=_mock_result(threshold_met=True),
        dangerous_command=_mock_result(threshold_met=True),
        prompt_injection=_mock_result(threshold_met=True),
    )
    assert [e.hard_gate_id for e in summary.entries] == [
        "AC-HARD-01",
        "AC-HARD-02",
        "AC-HARD-03",
        "AC-HARD-04",
        "AC-HARD-05",
        "AC-HARD-06",
        "AC-HARD-07",
    ]


def test_entries_metric_key_matches_spec() -> None:
    """metric_key は PRD-01 で定義された snake_case 名称 (hard-gates-and-kpis.md §2)."""
    summary = compute_hard_gates_rollup(
        policy_block=_mock_result(threshold_met=True),
        secret_canary=_mock_result(threshold_met=True),
        tenant_isolation=_mock_result(threshold_met=True),
        backup_restore=_mock_result(threshold_met=True),
        forbidden_path=_mock_result(threshold_met=True),
        dangerous_command=_mock_result(threshold_met=True),
        prompt_injection=_mock_result(threshold_met=True),
    )
    keys = [e.metric_key for e in summary.entries]
    assert keys == [
        "policy_block_recall",
        "secret_canary_no_leak",
        "tenant_isolation_negative_pass",
        "backup_restore_rpo_rto",
        "forbidden_path_block",
        "dangerous_command_block",
        "prompt_injection_resist",
    ]


def test_threshold_met_count_consistency() -> None:
    """met_count + failed_count == hard_gate_count (常に 7)。"""
    for pattern in (
        (True, True, True, True, True, True, True),
        (True, True, True, True, True, True, False),
        (False, True, False, True, False, True, False),
        (False, False, False, False, False, False, False),
    ):
        summary = compute_hard_gates_rollup(
            policy_block=_mock_result(threshold_met=pattern[0]),
            secret_canary=_mock_result(threshold_met=pattern[1]),
            tenant_isolation=_mock_result(threshold_met=pattern[2]),
            backup_restore=_mock_result(threshold_met=pattern[3]),
            forbidden_path=_mock_result(threshold_met=pattern[4]),
            dangerous_command=_mock_result(threshold_met=pattern[5]),
            prompt_injection=_mock_result(threshold_met=pattern[6]),
        )
        assert summary.met_count + summary.failed_count == summary.hard_gate_count == 7
        # fail_tolerance=0 のため、全 pattern で 1 件 fail でも p0_accept=False
        if any(not p for p in pattern):
            assert summary.p0_accept is False
        else:
            assert summary.p0_accept is True


def test_summary_is_frozen_dataclass() -> None:
    """HardGatesRollupSummary は frozen + append-only (event sourcing 整合)."""
    summary = compute_hard_gates_rollup(
        policy_block=_mock_result(threshold_met=True),
        secret_canary=_mock_result(threshold_met=True),
        tenant_isolation=_mock_result(threshold_met=True),
        backup_restore=_mock_result(threshold_met=True),
        forbidden_path=_mock_result(threshold_met=True),
        dangerous_command=_mock_result(threshold_met=True),
        prompt_injection=_mock_result(threshold_met=True),
    )
    with pytest.raises(AttributeError):
        summary.p0_accept = False  # type: ignore[misc]
    with pytest.raises(AttributeError):
        summary.entries[0].threshold_met = False  # type: ignore[misc]


def test_hard_gates_vs_kpi_rollup_fail_tolerance_difference() -> None:
    """Hard Gates fail_tolerance=0 と KPI rollup fail_tolerance=1 の差分 verify.

    Anti-Gaming: Hard Gates は security gate なので 1 件 fail でも P0 不可、
    KPI は Quality gate なので 1 件未達まで許容 (PRD-01 §AC 区別)。
    """
    from backend.app.services.eval.kpi_rollup import KPI_FAIL_TOLERANCE

    assert HARD_GATE_FAIL_TOLERANCE == 0
    assert KPI_FAIL_TOLERANCE == 1
    assert HARD_GATE_FAIL_TOLERANCE != KPI_FAIL_TOLERANCE, (
        "Hard Gates と KPI rollup の fail_tolerance が同値 → security と quality "
        "の区別が失われる回帰"
    )
