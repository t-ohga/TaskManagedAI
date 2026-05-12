"""Repair retry policy driven by ``config/policy_pack.toml`` (Sprint 5.5).

Sprint 4 で hardcode された ``MAX_REPAIR_RETRIES = 3`` を policy_pack 駆動に
refactor。``backend/app/domain/artifact/plan.py:MAX_REPAIR_RETRIES`` は Plan
artifact 内 default 値として後方互換のため保持し、本 service layer の
runtime 上限は ``PolicyPack.repair_retry_max_attempts`` から解決する。

ADR-00009 §Sprint 5.5 update / SP-005-5 BL-0064 設計判断。
"""

from __future__ import annotations

from backend.app.db.models.agent_run import AgentRun
from backend.app.domain.artifact.plan import MAX_REPAIR_RETRIES
from backend.app.services.policy_pack.loader import PolicyPack, get_policy_pack


def resolve_repair_retry_max_attempts(
    policy_pack: PolicyPack | None = None,
) -> int:
    """Resolve the runtime repair retry upper bound.

    Tests inject a ``PolicyPack`` directly; production callers omit the
    argument and read from the cached default policy pack.
    """

    pack = policy_pack if policy_pack is not None else get_policy_pack()
    return pack.repair_retry_max_attempts


def should_repair(
    run: AgentRun,
    retry_count: int,
    *,
    policy_pack: PolicyPack | None = None,
) -> bool:
    """Return True iff a further repair retry is allowed.

    BudgetGuard ``repair_budget_remaining`` is enforced by the caller; this
    helper only encodes the policy_pack-driven attempt bound (BL-0064 §設計判断
    "どちらかが exhausted なら repair_exhausted").
    """

    _ = run
    if retry_count < 0:
        raise ValueError("retry_count must be zero or greater.")
    max_attempts = resolve_repair_retry_max_attempts(policy_pack)
    return retry_count < max_attempts


__all__ = [
    "MAX_REPAIR_RETRIES",
    "resolve_repair_retry_max_attempts",
    "should_repair",
]
