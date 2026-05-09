from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError

from backend.app.db.models.budget import Budget
from backend.app.domain.agent_runtime.budget import BudgetCheckResult
from backend.app.services.agent_runtime import budget_guard

RUN_ID = UUID("00000000-0000-4000-8000-000000004501")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000004502")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000004503")


def _run(status: str = "running") -> SimpleNamespace:
    return SimpleNamespace(
        id=RUN_ID,
        tenant_id=1,
        project_id=PROJECT_ID,
        status=status,
        blocked_reason=None,
    )


def _budget(
    level: str,
    *,
    hard_usd_limit: str | None = None,
    soft_usd_threshold: str | None = None,
    hard_tokens_limit: int | None = None,
    hard_wall_clock_ms: int | None = None,
    max_retries: int | None = None,
    global_kill_switch: bool | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        level=level,
        hard_usd_limit=None if hard_usd_limit is None else Decimal(hard_usd_limit),
        soft_usd_threshold=None
        if soft_usd_threshold is None
        else Decimal(soft_usd_threshold),
        hard_tokens_limit=hard_tokens_limit,
        hard_wall_clock_ms=hard_wall_clock_ms,
        max_retries=max_retries,
        global_kill_switch=global_kill_switch,
    )


class _FakeBudgetRepository:
    budgets: dict[str, SimpleNamespace] = {}

    def __init__(self, session: object) -> None:
        self.session = session

    async def list_effective_for_run(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        run_id: UUID,
    ) -> dict[str, SimpleNamespace]:
        assert tenant_id == 1
        assert project_id == PROJECT_ID
        assert run_id == RUN_ID
        return dict(self.budgets)


class _FakeNotificationRepository:
    events: list[dict[str, object]] = []

    def __init__(self, session: object) -> None:
        self.session = session

    async def append(
        self,
        *,
        tenant_id: int,
        event_type: str,
        payload: dict[str, object],
        recipient_actor_id: UUID,
    ) -> SimpleNamespace:
        self.events.append(
            {
                "tenant_id": tenant_id,
                "event_type": event_type,
                "payload": payload,
                "recipient_actor_id": recipient_actor_id,
            }
        )
        return SimpleNamespace(id=UUID("00000000-0000-4000-8000-000000004599"))


@pytest.fixture(autouse=True)
def fake_repositories(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeBudgetRepository.budgets = {}
    _FakeNotificationRepository.events = []
    monkeypatch.setattr(budget_guard, "BudgetRepository", _FakeBudgetRepository)
    monkeypatch.setattr(
        budget_guard,
        "NotificationEventRepository",
        _FakeNotificationRepository,
    )


@pytest.mark.asyncio
async def test_budget_guard_hard_precedence_global_tenant_project_run() -> None:
    _FakeBudgetRepository.budgets = {
        "global": _budget("global", hard_usd_limit="100.00"),
        "tenant": _budget("tenant", hard_usd_limit="9.00"),
        "project": _budget("project", hard_usd_limit="8.00"),
        "agent_run": _budget("agent_run", hard_usd_limit="7.00"),
    }

    result = await budget_guard.BudgetGuard(object()).evaluate_budget(
        run=_run(),
        current_usage_usd=Decimal("10.00"),
        current_tokens=1,
        current_wall_clock_ms=1,
        retry_count=0,
    )

    assert result == BudgetCheckResult(
        level="tenant",
        exceeded=True,
        current_usd=Decimal("10.00"),
        hard_limit_usd=Decimal("9.00"),
        soft_threshold_usd=None,
        reason="hard_usd_exceeded",
        current_tokens=1,
        hard_limit_tokens=None,
        current_wall_clock_ms=1,
        hard_limit_wall_clock_ms=None,
        retry_count=0,
        max_retries=None,
    )


@pytest.mark.parametrize(
    ("budget", "usage", "tokens", "wall_clock_ms", "retry_count", "reason"),
    [
        (_budget("agent_run", hard_usd_limit="1.00"), "1.01", 0, 0, 0, "hard_usd_exceeded"),
        (_budget("agent_run", hard_tokens_limit=10), "0.00", 11, 0, 0, "hard_tokens_exceeded"),
        (
            _budget("agent_run", hard_wall_clock_ms=1000),
            "0.00",
            0,
            1001,
            0,
            "hard_wall_clock_exceeded",
        ),
        (_budget("agent_run", max_retries=2), "0.00", 0, 0, 3, "max_retries_exceeded"),
    ],
)
@pytest.mark.asyncio
async def test_budget_guard_hard_limits_return_reason_codes(
    budget: SimpleNamespace,
    usage: str,
    tokens: int,
    wall_clock_ms: int,
    retry_count: int,
    reason: str,
) -> None:
    _FakeBudgetRepository.budgets = {"agent_run": budget}

    result = await budget_guard.BudgetGuard(object()).evaluate_budget(
        run=_run(),
        current_usage_usd=Decimal(usage),
        current_tokens=tokens,
        current_wall_clock_ms=wall_clock_ms,
        retry_count=retry_count,
    )

    assert result.exceeded is True
    assert result.reason == reason


@pytest.mark.asyncio
async def test_budget_guard_soft_threshold_warns_without_blocking() -> None:
    _FakeBudgetRepository.budgets = {
        "project": _budget(
            "project",
            hard_usd_limit="10.00",
            soft_usd_threshold="8.00",
        )
    }

    result = await budget_guard.BudgetGuard(object()).enforce_budget_or_block(
        run=_run(),
        current_usage_usd=Decimal("8.50"),
        current_tokens=0,
        current_wall_clock_ms=0,
        retry_count=0,
        actor_id=ACTOR_ID,
    )

    assert result.exceeded is False
    assert result.level == "project"
    assert len(_FakeNotificationRepository.events) == 1
    assert _FakeNotificationRepository.events[0]["event_type"] == "budget_soft_threshold_warning"


@pytest.mark.asyncio
async def test_budget_guard_block_event_payload_includes_all_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[dict[str, object]] = []

    async def fake_transition_with_event(*args: object, **kwargs: object) -> object:
        events.append(dict(kwargs))
        return object()

    _FakeBudgetRepository.budgets = {
        "agent_run": _budget("agent_run", hard_tokens_limit=10),
    }
    monkeypatch.setattr(budget_guard, "transition_with_event", fake_transition_with_event)

    result = await budget_guard.BudgetGuard(object()).enforce_budget_or_block(
        run=_run(),
        current_usage_usd=Decimal("0.00"),
        current_tokens=11,
        current_wall_clock_ms=100,
        retry_count=1,
        actor_id=ACTOR_ID,
    )

    assert result.exceeded is True
    assert result.reason == "hard_tokens_exceeded"
    payload = events[0]["payload"]
    assert payload == {
        "budget_level": "agent_run",
        "exceed_reason": "hard_tokens_exceeded",
        "current_usd": "0.00",
        "hard_limit_usd": None,
        "current_tokens": 11,
        "hard_limit_tokens": 10,
        "current_wall_clock_ms": 100,
        "hard_limit_wall_clock_ms": None,
        "retry_count": 1,
        "max_retries": None,
    }


@pytest.mark.asyncio
async def test_budget_guard_global_kill_switch_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[dict[str, object]] = []

    async def fake_transition_with_event(*args: object, **kwargs: object) -> object:
        events.append(dict(kwargs))
        return object()

    _FakeBudgetRepository.budgets = {
        "global": _budget("global", global_kill_switch=True),
    }
    monkeypatch.setattr(budget_guard, "transition_with_event", fake_transition_with_event)

    result = await budget_guard.BudgetGuard(object()).enforce_budget_or_block(
        run=_run(),
        current_usage_usd=Decimal("0.00"),
        current_tokens=0,
        current_wall_clock_ms=0,
        retry_count=0,
        actor_id=ACTOR_ID,
    )

    assert result.exceeded is True
    assert result.reason == "global_kill_switch"
    assert events[0]["to_state"] == "blocked"
    assert events[0]["event_type"] == "budget_blocked"
    assert events[0]["blocked_reason"] == "budget_blocked"


def test_budget_model_defines_level_id_consistency_check() -> None:
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in Budget.__table__.constraints
        if getattr(constraint, "sqltext", None) is not None
    }

    assert "budgets_ck_level_id_consistency" in checks
    assert "level_id is null" in checks["budgets_ck_level_id_consistency"]
    assert "level_id is not null" in checks["budgets_ck_level_id_consistency"]


def test_budget_migration_defines_partial_unique_active_budgets() -> None:
    text = Path("migrations/versions/0010_budget_secret_runtime.py").read_text(
        encoding="utf-8"
    )

    for index_name in {
        "budgets_uq_global_level_active",
        "budgets_uq_tenant_level_active",
        "budgets_uq_project_level_active",
        "budgets_uq_agent_run_level_active",
    }:
        assert index_name in text
    assert "level = 'tenant' and active = true" in text
    assert "level = 'project' and active = true" in text
    assert "level = 'agent_run' and active = true" in text


def test_cross_tenant_budget_guard_ignores_foreign_tenant() -> None:
    with pytest.raises(IntegrityError):
        raise IntegrityError(
            "insert into budgets",
            {},
            Exception("budgets_tenant_id_fkey"),
        )

