"""Output Validator core (Sprint 5.5 BL-0064).

After a provider response has been mapped to ``validation_failed`` (Sprint 5
ProviderAdapter contract), this module decides whether the AgentRun should
schedule another repair retry or transition to ``repair_exhausted``
(terminal, ADR-00004 §13).

The decision combines two independent constraints:

1. **policy_pack** — ``repair_retry_max_attempts`` from
   ``config/policy_pack.toml`` (default 3).
2. **BudgetGuard** — ``repair_budget_remaining`` (caller-supplied snapshot of
   the remaining repair-cost budget; 0 / negative => exhausted).

If *either* constraint is exhausted the run must transition to
``repair_exhausted``; both must allow continuation for a retry.

Full AgentRun runtime integration (state_machine + AgentRunEvent append +
ContextSnapshot snapshot_kind=resume) is scheduled in BL-0067 (Sprint 5.5
batch 2). This module returns a pure ``RepairDecision`` value object so the
runtime orchestrator can chain it with ``transition_with_event``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from backend.app.services.policy_pack.loader import PolicyPack, get_policy_pack

RepairOutcome = Literal["retry", "repair_exhausted"]

# Reason codes attached to a ``repair_exhausted`` decision. Each value is
# audit-friendly and contains no raw secret material.
ExhaustionReason = Literal[
    "policy_max_attempts_reached",
    "budget_exhausted",
]


@dataclass(frozen=True)
class RepairDecision:
    """Pure value object describing the next repair step.

    ``outcome`` selects the next AgentRun transition:

    - ``"retry"``: caller schedules ``validation_failed -> running`` with
      ``repair_retry_scheduled`` event.
    - ``"repair_exhausted"``: caller schedules
      ``validation_failed -> repair_exhausted`` with ``repair_exhausted``
      event (terminal).

    ``exhaustion_reasons`` is empty for ``"retry"`` and contains one or both
    of ``"policy_max_attempts_reached"`` / ``"budget_exhausted"`` otherwise.
    Both reasons MAY appear when policy and budget exhaust simultaneously;
    the caller surfaces them in the AgentRunEvent payload (raw secret nil).
    """

    outcome: RepairOutcome
    retry_count_after: int
    policy_max_attempts: int
    repair_budget_remaining: Decimal
    exhaustion_reasons: tuple[ExhaustionReason, ...] = field(default_factory=tuple)


def _coerce_repair_budget_remaining(value: Decimal | int | float) -> Decimal:
    # SP55-B1-F-004 fix: ``None`` is rejected at the type layer — BudgetGuard
    # MUST always supply a concrete remaining amount. Pass ``Decimal(0)`` to
    # force ``repair_exhausted``; never pass ``None``.
    if value is None:
        raise TypeError(
            "repair_budget_remaining must not be None "
            "(BudgetGuard is a mandatory AND-gate, SP55-B1-F-004)"
        )
    if isinstance(value, bool):
        # bool is a subclass of int; reject explicitly to avoid accidents.
        raise ValueError("repair_budget_remaining must be Decimal | int | float")
    if not isinstance(value, (int, float, Decimal)):
        raise TypeError(
            "repair_budget_remaining must be Decimal | int | float, "
            f"got {type(value).__name__}"
        )

    # SP55-B1-R2-F-002 fix: apply ``is_finite`` uniformly *after* coercion so
    # that ``float('inf')`` / ``float('-inf')`` / ``float('nan')`` are rejected
    # in addition to ``Decimal('Infinity')``. The previous branch-only check
    # let float Infinity through ``Decimal(str(value))`` and produced
    # ``outcome=retry`` regardless of policy attempts.
    coerced = value if isinstance(value, Decimal) else Decimal(str(value))
    if not coerced.is_finite():
        raise ValueError(
            "repair_budget_remaining must be a finite value (no Infinity / NaN)"
        )
    return coerced


def decide_repair(
    *,
    retry_count: int,
    repair_budget_remaining: Decimal | int | float,
    policy_pack: PolicyPack | None = None,
) -> RepairDecision:
    """Return a ``RepairDecision`` for the current validation_failed event.

    Parameters
    ----------
    retry_count:
        Number of repair retries already executed for this run (>= 0). The
        current ``validation_failed`` event is **not yet** counted; the
        decision answers "should we schedule retry #(retry_count + 1)?".
    repair_budget_remaining:
        Remaining repair budget exposed by ``BudgetGuard``. Caller MUST
        pass a concrete ``Decimal | int | float`` value (BudgetGuard is a
        mandatory contributor to the policy AND budget AND-gate; passing
        ``None`` or omitting tracking is **not** supported — SP55-B1-F-004
        fix). To force ``repair_exhausted`` without exercising policy, pass
        ``Decimal(0)``.
    policy_pack:
        Optional injected PolicyPack (tests / non-default paths). Production
        callers omit this and the cached default pack is read.
    """

    if retry_count < 0:
        raise ValueError("retry_count must be zero or greater.")

    pack = policy_pack if policy_pack is not None else get_policy_pack()
    policy_max = pack.repair_retry_max_attempts
    if policy_max < 1:
        raise ValueError(
            "policy_pack.output_validator.repair_retry_max_attempts must be >= 1"
        )

    budget = _coerce_repair_budget_remaining(repair_budget_remaining)

    reasons: list[ExhaustionReason] = []
    if retry_count >= policy_max:
        reasons.append("policy_max_attempts_reached")
    if budget <= Decimal(0):
        reasons.append("budget_exhausted")

    if reasons:
        return RepairDecision(
            outcome="repair_exhausted",
            retry_count_after=retry_count,
            policy_max_attempts=policy_max,
            repair_budget_remaining=budget,
            exhaustion_reasons=tuple(reasons),
        )

    return RepairDecision(
        outcome="retry",
        retry_count_after=retry_count + 1,
        policy_max_attempts=policy_max,
        repair_budget_remaining=budget,
        exhaustion_reasons=(),
    )


__all__ = [
    "ExhaustionReason",
    "RepairDecision",
    "RepairOutcome",
    "decide_repair",
]
