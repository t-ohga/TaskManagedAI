"""Output Validator core decision tests (Sprint 5.5 BL-0064).

These tests cover the pure decision function ``decide_repair`` exposed by
``backend.app.services.output_validator.core``. Full AgentRun runtime
integration (state_machine + AgentRunEvent + ContextSnapshot snapshot_kind=
resume) is exercised in BL-0067 (Sprint 5.5 batch 2).
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from backend.app.services.output_validator.core import (
    RepairDecision,
    decide_repair,
)
from backend.app.services.policy_pack.loader import PolicyPack


def _policy_pack(max_attempts: int) -> PolicyPack:
    return PolicyPack(
        policy_version="test-vN.N",
        policy_pack_lock="0" * 64,
        repair_retry_max_attempts=max_attempts,
        trust_level_promotion_to_trusted_instruction_requires_human_approval=True,
    )


def test_decide_repair_retries_when_below_policy_limit_and_budget_available() -> None:
    decision = decide_repair(
        retry_count=0,
        repair_budget_remaining=Decimal("1.00"),
        policy_pack=_policy_pack(3),
    )
    assert decision.outcome == "retry"
    assert decision.retry_count_after == 1
    assert decision.exhaustion_reasons == ()


def test_decide_repair_exhausts_at_policy_limit() -> None:
    decision = decide_repair(
        retry_count=3,
        repair_budget_remaining=Decimal("1.00"),
        policy_pack=_policy_pack(3),
    )
    assert decision.outcome == "repair_exhausted"
    assert "policy_max_attempts_reached" in decision.exhaustion_reasons
    assert "budget_exhausted" not in decision.exhaustion_reasons


def test_decide_repair_exhausts_when_budget_zero_even_below_policy_limit() -> None:
    decision = decide_repair(
        retry_count=0,
        repair_budget_remaining=Decimal("0"),
        policy_pack=_policy_pack(3),
    )
    assert decision.outcome == "repair_exhausted"
    assert decision.exhaustion_reasons == ("budget_exhausted",)


def test_decide_repair_exhausts_when_budget_negative() -> None:
    decision = decide_repair(
        retry_count=1,
        repair_budget_remaining=Decimal("-0.01"),
        policy_pack=_policy_pack(3),
    )
    assert decision.outcome == "repair_exhausted"
    assert decision.exhaustion_reasons == ("budget_exhausted",)


def test_decide_repair_records_both_reasons_when_simultaneously_exhausted() -> None:
    decision = decide_repair(
        retry_count=3,
        repair_budget_remaining=Decimal("0"),
        policy_pack=_policy_pack(3),
    )
    assert decision.outcome == "repair_exhausted"
    assert set(decision.exhaustion_reasons) == {
        "policy_max_attempts_reached",
        "budget_exhausted",
    }


def test_decide_repair_rejects_none_budget_remaining_as_fail_closed() -> None:
    """SP55-B1-F-004 fix: BudgetGuard MUST always supply a concrete value.

    ``None`` was previously coerced to ``Decimal("Infinity")`` which let
    retries through whenever BudgetGuard was unwired — a fail-open hole
    that violated the policy AND budget AND-gate (Sprint Pack §設計判断).
    The decider now rejects ``None`` at the type layer.
    """

    with pytest.raises(TypeError):
        decide_repair(  # type: ignore[call-overload]
            retry_count=0,
            repair_budget_remaining=None,
            policy_pack=_policy_pack(3),
        )


def test_decide_repair_rejects_infinity_budget_as_fail_closed() -> None:
    """Decimal('Infinity') / NaN are explicitly rejected (no silent fail-open)."""

    with pytest.raises(ValueError, match="finite"):
        decide_repair(
            retry_count=0,
            repair_budget_remaining=Decimal("Infinity"),
            policy_pack=_policy_pack(3),
        )


@pytest.mark.parametrize(
    "non_finite_float",
    [float("inf"), float("-inf"), float("nan")],
)
def test_decide_repair_rejects_non_finite_float_budget(
    non_finite_float: float,
) -> None:
    """SP55-B1-R2-F-002 fix: float('inf' | '-inf' | 'nan') must be rejected.

    Previously the int / float branch never called ``is_finite()`` after
    ``Decimal(str(value))`` coercion, so ``float('inf')`` produced
    ``Decimal('Infinity')`` and silently allowed retry forever. The fix
    runs ``is_finite`` uniformly on the coerced Decimal.
    """

    with pytest.raises(ValueError, match="finite"):
        decide_repair(
            retry_count=0,
            repair_budget_remaining=non_finite_float,
            policy_pack=_policy_pack(3),
        )


def test_decide_repair_rejects_decimal_nan_budget() -> None:
    with pytest.raises(ValueError, match="finite"):
        decide_repair(
            retry_count=0,
            repair_budget_remaining=Decimal("NaN"),
            policy_pack=_policy_pack(3),
        )


def test_decide_repair_rejects_negative_retry_count() -> None:
    with pytest.raises(ValueError, match="retry_count"):
        decide_repair(
            retry_count=-1,
            repair_budget_remaining=Decimal("1.00"),
            policy_pack=_policy_pack(3),
        )


def test_decide_repair_rejects_policy_pack_with_zero_max_attempts() -> None:
    with pytest.raises(ValueError, match="repair_retry_max_attempts"):
        decide_repair(
            retry_count=0,
            repair_budget_remaining=Decimal("1.00"),
            policy_pack=_policy_pack(0),
        )


def test_decide_repair_returns_immutable_value_object() -> None:
    """`RepairDecision` is a frozen dataclass; mutation must fail."""

    decision = decide_repair(
        retry_count=0,
        repair_budget_remaining=Decimal("1.00"),
        policy_pack=_policy_pack(3),
    )
    assert isinstance(decision, RepairDecision)
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.outcome = "repair_exhausted"  # type: ignore[misc]
