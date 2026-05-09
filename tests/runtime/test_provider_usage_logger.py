from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from backend.app.domain.agent_runtime.budget import BudgetCheckResult
from backend.app.domain.provider.result import ProviderUsage
from backend.app.services.agent_runtime import budget_guard
from backend.app.services.providers.usage_logger import record_provider_usage

RUN_ID = UUID("00000000-0000-4000-8000-000000006001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000006002")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000006003")
MATRIX_VERSION = "pcm-v1"


def _run(*, tenant_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=RUN_ID,
        tenant_id=tenant_id,
        project_id=PROJECT_ID,
        actor_id=ACTOR_ID,
        status="running",
        blocked_reason=None,
        cost_usd=None,
        tokens_input=None,
        tokens_output=None,
    )


def _budget(
    level: str,
    *,
    hard_usd_limit: str | None = None,
    soft_usd_threshold: str | None = None,
    hard_tokens_limit: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        level=level,
        hard_usd_limit=None if hard_usd_limit is None else Decimal(hard_usd_limit),
        soft_usd_threshold=None
        if soft_usd_threshold is None
        else Decimal(soft_usd_threshold),
        hard_tokens_limit=hard_tokens_limit,
        hard_wall_clock_ms=None,
        max_retries=None,
        global_kill_switch=None,
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
        return SimpleNamespace(id=UUID("00000000-0000-4000-8000-000000006099"))


@pytest.fixture(autouse=True)
def fake_budget_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeBudgetRepository.budgets = {}
    _FakeNotificationRepository.events = []
    monkeypatch.setattr(budget_guard, "BudgetRepository", _FakeBudgetRepository)
    monkeypatch.setattr(
        budget_guard,
        "NotificationEventRepository",
        _FakeNotificationRepository,
    )


@pytest.mark.asyncio
async def test_record_provider_usage_adds_cost_and_tokens() -> None:
    run = _run()

    result = await record_provider_usage(
        object(),
        run=run,
        usage=ProviderUsage(tokens_input=3, tokens_output=4, cost_usd=0.25),
        actor_id=ACTOR_ID,
        matrix_version=MATRIX_VERSION,
    )

    assert run.cost_usd == Decimal("0.25")
    assert run.tokens_input == 3
    assert run.tokens_output == 4
    assert result == BudgetCheckResult(
        level="agent_run",
        exceeded=False,
        current_usd=Decimal("0.25"),
        hard_limit_usd=None,
        soft_threshold_usd=None,
        reason=None,
        current_tokens=7,
        hard_limit_tokens=None,
        current_wall_clock_ms=0,
        hard_limit_wall_clock_ms=None,
        retry_count=0,
        max_retries=None,
    )


@pytest.mark.asyncio
async def test_record_provider_usage_hard_exceed_blocks_with_budget_blocked(
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

    result = await record_provider_usage(
        object(),
        run=_run(),
        usage=ProviderUsage(tokens_input=7, tokens_output=5, cost_usd=0.20),
        actor_id=ACTOR_ID,
        matrix_version=MATRIX_VERSION,
        current_wall_clock_ms=12,
        retry_count=0,
    )

    assert result.exceeded is True
    assert result.reason == "hard_tokens_exceeded"
    assert events[0]["to_state"] == "blocked"
    assert events[0]["event_type"] == "budget_blocked"
    assert events[0]["blocked_reason"] == "budget_blocked"
    assert events[0]["actor_id"] == ACTOR_ID


@pytest.mark.asyncio
async def test_record_provider_usage_soft_threshold_emits_warning_only() -> None:
    _FakeBudgetRepository.budgets = {
        "project": _budget(
            "project",
            hard_usd_limit="1.00",
            soft_usd_threshold="0.50",
        ),
    }

    result = await record_provider_usage(
        object(),
        run=_run(),
        usage=ProviderUsage(tokens_input=1, tokens_output=1, cost_usd=0.60),
        actor_id=ACTOR_ID,
        matrix_version=MATRIX_VERSION,
    )

    assert result.exceeded is False
    assert result.soft_threshold_usd == Decimal("0.50")
    assert len(_FakeNotificationRepository.events) == 1
    assert _FakeNotificationRepository.events[0]["event_type"] == (
        "budget_soft_threshold_warning"
    )


@pytest.mark.asyncio
async def test_record_provider_usage_rejects_cross_tenant_run() -> None:
    with pytest.raises(ValueError, match="expected_tenant_id"):
        await record_provider_usage(
            object(),
            run=_run(tenant_id=1),
            usage=ProviderUsage(tokens_input=1, tokens_output=1, cost_usd=0.01),
            actor_id=ACTOR_ID,
            matrix_version=MATRIX_VERSION,
            expected_tenant_id=2,
        )


@pytest.mark.asyncio
async def test_record_provider_usage_requires_actor_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(TypeError):
        await record_provider_usage(
            object(),
            run=_run(),
            usage=ProviderUsage(tokens_input=1, tokens_output=1, cost_usd=0.01),
            matrix_version=MATRIX_VERSION,
        )

    events: list[dict[str, object]] = []

    async def fake_transition_with_event(*args: object, **kwargs: object) -> object:
        events.append(dict(kwargs))
        return object()

    _FakeBudgetRepository.budgets = {
        "agent_run": _budget("agent_run", hard_tokens_limit=1),
    }
    monkeypatch.setattr(budget_guard, "transition_with_event", fake_transition_with_event)

    result = await record_provider_usage(
        object(),
        run=_run(),
        usage=ProviderUsage(tokens_input=1, tokens_output=1, cost_usd=0.01),
        actor_id=ACTOR_ID,
        matrix_version=MATRIX_VERSION,
    )

    assert result.exceeded is True
    assert events[0]["actor_id"] == ACTOR_ID
    assert events[0]["event_type"] == "budget_blocked"

