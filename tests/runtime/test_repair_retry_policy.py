from __future__ import annotations

from uuid import uuid4

import pytest

from backend.app.db.models.agent_run import AgentRun
from backend.app.domain.artifact.plan import MAX_REPAIR_RETRIES as PLAN_MAX_REPAIR_RETRIES
from backend.app.services.agent_runtime.repair_policy import (
    MAX_REPAIR_RETRIES,
    resolve_repair_retry_max_attempts,
    should_repair,
)
from backend.app.services.policy_pack.loader import PolicyPack, get_policy_pack


def _run() -> AgentRun:
    return AgentRun(
        tenant_id=1,
        project_id=uuid4(),
        status="validation_failed",
    )


def _policy_pack_with_attempts(max_attempts: int) -> PolicyPack:
    """Build a synthetic PolicyPack for tests, without touching the cached default."""

    return PolicyPack(
        policy_version="test-vN.N",
        policy_pack_lock="0" * 64,
        repair_retry_max_attempts=max_attempts,
        trust_level_promotion_to_trusted_instruction_requires_human_approval=True,
    )


@pytest.mark.parametrize("retry_count", [0, 1, 2])
def test_should_repair_before_retry_limit(retry_count: int) -> None:
    assert should_repair(_run(), retry_count) is True


def test_should_not_repair_at_retry_limit() -> None:
    assert should_repair(_run(), 3) is False


def test_should_not_repair_after_retry_limit() -> None:
    assert should_repair(_run(), 4) is False


def test_negative_retry_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="retry_count"):
        should_repair(_run(), -1)


def test_max_repair_retries_constant_is_three_and_cross_source_consistent() -> None:
    """`plan.py` default constant remains 3 for backward compatibility (Sprint 5.5)."""

    assert MAX_REPAIR_RETRIES == 3
    assert MAX_REPAIR_RETRIES == PLAN_MAX_REPAIR_RETRIES


def test_policy_pack_default_resolves_to_three_via_config_toml() -> None:
    """`config/policy_pack.toml` Sprint 5.5 baseline keeps the runtime upper bound at 3.

    This is the cross-source link Sprint 5.5 introduces: the constant lives in
    `plan.py` for legacy backward compat, while the runtime authority is
    PolicyPack.repair_retry_max_attempts loaded from
    ``config/policy_pack.toml``.
    """

    assert resolve_repair_retry_max_attempts() == 3
    assert get_policy_pack().repair_retry_max_attempts == 3


def test_should_repair_uses_injected_policy_pack_max_attempts() -> None:
    """policy_pack を inject すると runtime 上限が変わる (BL-0064 設計判断)。"""

    pack = _policy_pack_with_attempts(5)
    # retry_count=4 is below the injected limit of 5 but above the default 3.
    assert should_repair(_run(), 4, policy_pack=pack) is True
    assert should_repair(_run(), 5, policy_pack=pack) is False


def test_resolve_repair_retry_max_attempts_uses_injected_pack() -> None:
    pack = _policy_pack_with_attempts(7)
    assert resolve_repair_retry_max_attempts(pack) == 7

