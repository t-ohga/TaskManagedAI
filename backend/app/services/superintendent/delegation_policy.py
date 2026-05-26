"""Delegation policy for Superintendent agent.

Human sets the policy. Superintendent reads and applies it.
Superintendent CANNOT modify the policy (human-only write).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

IMMUTABLE_FORBIDDEN_ACTIONS: frozenset[str] = frozenset({
    "merge",
    "deploy",
    "secret_access",
    "provider_call",
    "approval_decide",
})

AutoApproveRisk = Literal["none", "low", "medium"]


@dataclass(frozen=True, slots=True)
class DelegationPolicy:
    max_auto_approve_risk: AutoApproveRisk = "none"
    max_budget_per_run: Decimal = Decimal("1.00")
    max_concurrent_agents: int = 2
    allowed_providers: tuple[str, ...] = ()
    auto_retry_on_failure: bool = False
    escalate_to_human_after: int = 3
    forbidden_actions: frozenset[str] = field(default_factory=lambda: IMMUTABLE_FORBIDDEN_ACTIONS)

    def __post_init__(self) -> None:
        if self.forbidden_actions != IMMUTABLE_FORBIDDEN_ACTIONS:
            object.__setattr__(self, "forbidden_actions", IMMUTABLE_FORBIDDEN_ACTIONS)


POLICY_TEMPLATES: dict[str, DelegationPolicy] = {
    "conservative": DelegationPolicy(
        max_auto_approve_risk="none",
        max_budget_per_run=Decimal("1.00"),
        max_concurrent_agents=2,
    ),
    "balanced": DelegationPolicy(
        max_auto_approve_risk="low",
        max_budget_per_run=Decimal("5.00"),
        max_concurrent_agents=5,
        auto_retry_on_failure=True,
    ),
    "aggressive": DelegationPolicy(
        max_auto_approve_risk="medium",
        max_budget_per_run=Decimal("20.00"),
        max_concurrent_agents=10,
        auto_retry_on_failure=True,
        escalate_to_human_after=5,
    ),
}


def is_action_allowed(policy: DelegationPolicy, action: str) -> bool:
    return action not in policy.forbidden_actions


def can_auto_approve(policy: DelegationPolicy, risk_level: str) -> bool:
    if policy.max_auto_approve_risk == "none":
        return False
    if policy.max_auto_approve_risk == "low":
        return risk_level in ("read_only", "task_write")
    if policy.max_auto_approve_risk == "medium":
        return risk_level in ("read_only", "task_write", "repo_write")
    return False
