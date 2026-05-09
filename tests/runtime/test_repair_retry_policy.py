from __future__ import annotations

from uuid import uuid4

import pytest

from backend.app.db.models.agent_run import AgentRun
from backend.app.domain.artifact.plan import MAX_REPAIR_RETRIES as PLAN_MAX_REPAIR_RETRIES
from backend.app.services.agent_runtime.repair_policy import (
    MAX_REPAIR_RETRIES,
    should_repair,
)


def _run() -> AgentRun:
    return AgentRun(
        tenant_id=1,
        project_id=uuid4(),
        status="validation_failed",
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
    assert MAX_REPAIR_RETRIES == 3
    assert MAX_REPAIR_RETRIES == PLAN_MAX_REPAIR_RETRIES

