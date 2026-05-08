from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from arq.connections import RedisSettings

from backend.app.config import get_settings
from backend.app.workers.main import (
    WorkerContext,
    WorkerSettings,
    on_shutdown,
    on_startup,
    redis_settings_from_url,
)
from backend.app.workers.tasks import noop_task

_TEST_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:test-password@postgres:5432/taskmanagedai"
)


class FakePubSub:
    def __init__(self) -> None:
        self.subscribed_channels: list[str] = []
        self.get_message_kwargs: list[dict[str, object]] = []
        self.closed = False

    async def subscribe(self, *channels: str) -> None:
        self.subscribed_channels.extend(channels)

    async def get_message(
        self,
        ignore_subscribe_messages: bool = True,
        **kwargs: object,
    ) -> dict[str, Any] | None:
        self.get_message_kwargs.append(
            {"ignore_subscribe_messages": ignore_subscribe_messages, **kwargs}
        )
        await asyncio.sleep(3600)
        return None

    async def close(self) -> None:
        self.closed = True


class FakeRedis:
    def __init__(self, pubsub: FakePubSub) -> None:
        self._pubsub = pubsub

    def pubsub(self) -> FakePubSub:
        return self._pubsub


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_worker_settings_exports_noop_task() -> None:
    assert WorkerSettings.functions == [noop_task]
    assert WorkerSettings.queue_name == "taskmanagedai:jobs"
    assert WorkerSettings.job_timeout == 300
    assert WorkerSettings.max_jobs == 10


def test_redis_settings_from_url_parses_internal_redis_endpoint() -> None:
    redis_settings = redis_settings_from_url("redis://redis:6379/0")

    assert isinstance(redis_settings, RedisSettings)
    assert redis_settings.host == "redis"
    assert redis_settings.port == 6379
    assert redis_settings.database == 0


@pytest.mark.asyncio
async def test_worker_startup_initializes_cancel_pubsub_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TASKMANAGEDAI_ENVIRONMENT", "test")
    monkeypatch.setenv("TASKMANAGEDAI_DATABASE_URL", _TEST_DATABASE_URL)
    monkeypatch.setenv("TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET", "test-cookie-secret")
    monkeypatch.setenv("TASKMANAGEDAI_WORKER_CANCEL_CHANNEL", "taskmanagedai:test-cancel")
    get_settings.cache_clear()

    pubsub = FakePubSub()
    ctx: WorkerContext = {"redis": FakeRedis(pubsub)}

    await on_startup(ctx)
    task = ctx["cancel_listener_task"]
    await asyncio.sleep(0)

    try:
        assert ctx["cancel_channel"] == "taskmanagedai:test-cancel"
        assert pubsub.subscribed_channels == ["taskmanagedai:test-cancel"]
        assert pubsub.get_message_kwargs == [
            {"ignore_subscribe_messages": True, "timeout": 1.0}
        ]
        assert isinstance(task, asyncio.Task)
    finally:
        await on_shutdown(ctx)

    assert pubsub.closed is True
    assert "cancel_channel" not in ctx
    assert "cancel_pubsub" not in ctx
    assert "cancel_listener_task" not in ctx


@pytest.mark.asyncio
async def test_noop_task_returns_structured_payload() -> None:
    result = await noop_task({"request_id": "test-worker"})

    assert result == {
        "status": "ok",
        "task": "noop",
        "request_id": "test-worker",
    }

