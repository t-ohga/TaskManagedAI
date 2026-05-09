from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from backend.app.services.agent_runtime import cancel as cancel_module

RUN_ID = UUID("00000000-0000-4000-8000-000000004901")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000004902")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000004903")


class _FakeSession:
    def __init__(self, status: str) -> None:
        self.run = SimpleNamespace(
            id=RUN_ID,
            tenant_id=1,
            project_id=PROJECT_ID,
            status=status,
            blocked_reason="budget_blocked" if status == "blocked" else None,
            completed_at=None,
        )
        self.refreshed: list[object] = []

    async def scalar(self, statement: object) -> object:
        return self.run

    async def refresh(self, instance: object) -> None:
        self.refreshed.append(instance)


class _FakePublisher:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> None:
        self.messages.append((channel, message))


@pytest.mark.parametrize("status", ["running", "blocked", "waiting_approval", "provider_incomplete"])
@pytest.mark.asyncio
async def test_cancel_cancelable_states_uses_transition_with_event(
    status: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher = _FakePublisher()
    session = _FakeSession(status=status)
    calls: list[dict[str, object]] = []

    async def transition_with_event(*args: object, **kwargs: object) -> object:
        calls.append(dict(kwargs))
        session.run.status = "cancelled"
        session.run.blocked_reason = None
        session.run.completed_at = datetime.now(tz=UTC)
        return object()

    monkeypatch.setattr(cancel_module, "transition_with_event", transition_with_event)

    run = await cancel_module.cancel_agent_run(
        session=session,  # type: ignore[arg-type]
        run_id=RUN_ID,
        reason=None,
        actor_id=ACTOR_ID,
        tenant_id=1,
        publisher=publisher,
    )

    assert run.status == "cancelled"
    assert run.completed_at is not None
    assert calls[0]["to_state"] == "cancelled"
    assert calls[0]["event_type"] == "run_cancelled"
    assert calls[0]["blocked_reason"] is None if "blocked_reason" in calls[0] else True
    assert publisher.messages[0][0] == f"cancel:run:{RUN_ID}"


@pytest.mark.asyncio
async def test_terminal_state_cannot_be_cancelled() -> None:
    session = _FakeSession(status="completed")

    with pytest.raises(ValueError, match="terminal AgentRun state cannot be cancelled"):
        await cancel_module.cancel_agent_run(
            session=session,  # type: ignore[arg-type]
            run_id=RUN_ID,
            reason=None,
            actor_id=ACTOR_ID,
            tenant_id=1,
            publisher=_FakePublisher(),
        )


@pytest.mark.asyncio
async def test_redis_publish_failure_does_not_rollback_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingPublisher:
        async def publish(self, channel: str, message: str) -> None:
            raise OSError("redis unavailable")

    session = _FakeSession(status="blocked")
    calls: list[dict[str, object]] = []

    async def transition_with_event(*args: object, **kwargs: object) -> object:
        calls.append(dict(kwargs))
        session.run.status = "cancelled"
        session.run.blocked_reason = None
        session.run.completed_at = datetime.now(tz=UTC)
        return object()

    monkeypatch.setattr(cancel_module, "transition_with_event", transition_with_event)

    run = await cancel_module.cancel_agent_run(
        session=session,  # type: ignore[arg-type]
        run_id=RUN_ID,
        reason="user_cancel",
        actor_id=ACTOR_ID,
        tenant_id=1,
        publisher=FailingPublisher(),
    )

    assert run.status == "cancelled"
    assert calls[0]["event_type"] == "run_cancelled"

