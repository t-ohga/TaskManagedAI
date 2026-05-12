"""Sprint 6 Batch 2: cancel propagation の registry / Redis channel 契約テスト。"""

from __future__ import annotations

import asyncio
import os

import pytest

from backend.app.services.cli_artifact.cancel_propagation import (
    CancelKey,
    CancelRegistry,
    CancelSubscriberDriver,
    RedisCancelDispatcher,
    _parse_channel,
)

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
RUN_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
ACTOR_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


@pytest.fixture(autouse=True)
def _skip_windows() -> None:
    """asyncio signal propagation の実運用境界に合わせて POSIX のみ確認する。"""

    if os.name == "nt":
        pytest.skip("cancel_propagation tests are POSIX-only in this sprint")


class _RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.calls.append((channel, message))
        return 1


def _key() -> CancelKey:
    return CancelKey(tenant_id=TENANT_ID, run_id=RUN_ID)


async def _wait_until_cancelled(registry: CancelRegistry, key: CancelKey) -> None:
    for _ in range(50):
        if registry.is_cancelled(key):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("cancel signal was not observed")


@pytest.mark.parametrize("bad_tenant_id", ["", ";rm", "a" * 65])
def test_cancel_key_rejects_invalid_tenant_id(bad_tenant_id: str) -> None:
    with pytest.raises(ValueError, match="tenant_id"):
        CancelKey(tenant_id=bad_tenant_id, run_id=RUN_ID)


@pytest.mark.parametrize("bad_run_id", ["", ";rm", "b" * 65])
def test_cancel_key_rejects_invalid_run_id(bad_run_id: str) -> None:
    with pytest.raises(ValueError, match="run_id"):
        CancelKey(tenant_id=TENANT_ID, run_id=bad_run_id)


def test_cancel_key_redis_channel_format() -> None:
    key = _key()

    assert key.redis_channel == f"cli_cancel:{TENANT_ID}:{RUN_ID}"


def test_cancel_key_is_frozen() -> None:
    key = _key()

    with pytest.raises(AttributeError):
        key.run_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"


def test_cancel_registry_register_returns_same_event_for_same_key() -> None:
    registry = CancelRegistry()
    key = _key()

    first = registry.register(key)
    second = registry.register(key)

    assert first is second
    assert first.is_set() is False


def test_cancel_registry_signal_sets_event() -> None:
    registry = CancelRegistry()
    key = _key()
    event = registry.register(key)

    signalled = registry.signal(key)

    assert signalled is True
    assert event.is_set() is True


def test_cancel_registry_signal_returns_true_on_first_call_false_thereafter() -> None:
    registry = CancelRegistry()
    key = _key()
    registry.register(key)

    assert registry.signal(key) is True
    assert registry.signal(key) is False


def test_cancel_registry_signal_future_proof_for_unknown_key() -> None:
    registry = CancelRegistry()
    key = _key()

    assert registry.signal(key) is True
    assert registry.is_cancelled(key) is True


@pytest.mark.asyncio
async def test_wait_for_cancel_completes_when_signalled() -> None:
    registry = CancelRegistry()
    key = _key()
    wait_task = asyncio.create_task(registry.wait_for_cancel(key))
    await asyncio.sleep(0)

    registry.signal(key)

    await asyncio.wait_for(wait_task, timeout=1.0)
    assert wait_task.done() is True


@pytest.mark.asyncio
async def test_wait_for_cancel_blocks_until_signalled() -> None:
    registry = CancelRegistry()
    key = _key()

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(registry.wait_for_cancel(key), timeout=0.1)


def test_cancel_registry_is_cancelled() -> None:
    registry = CancelRegistry()
    key = _key()

    assert registry.is_cancelled(key) is False
    registry.signal(key)
    assert registry.is_cancelled(key) is True


def test_cancel_registry_unregister_clears_event() -> None:
    registry = CancelRegistry()
    key = _key()
    registry.signal(key)

    registry.unregister(key)

    assert registry.is_cancelled(key) is False


@pytest.mark.asyncio
async def test_redis_dispatcher_publishes_to_correct_channel() -> None:
    registry = CancelRegistry()
    publisher = _RecordingPublisher()
    dispatcher = RedisCancelDispatcher(publisher=publisher, registry=registry)
    key = _key()

    published = await dispatcher.signal_remote(key, actor_id=ACTOR_ID)

    assert published == 1
    assert len(publisher.calls) == 1
    assert publisher.calls[0][0] == key.redis_channel
    assert publisher.calls[0][1].startswith(ACTOR_ID + ":")


@pytest.mark.asyncio
async def test_redis_dispatcher_signals_local_registry_first() -> None:
    registry = CancelRegistry()
    key = _key()

    class _AssertingPublisher:
        async def publish(self, channel: str, message: str) -> int:
            assert channel == key.redis_channel
            assert message.startswith(ACTOR_ID + ":")
            assert registry.is_cancelled(key) is True
            return 1

    dispatcher = RedisCancelDispatcher(
        publisher=_AssertingPublisher(),
        registry=registry,
    )

    assert await dispatcher.signal_remote(key, actor_id=ACTOR_ID) == 1


@pytest.mark.asyncio
async def test_redis_dispatcher_rejects_invalid_actor_id() -> None:
    registry = CancelRegistry()
    publisher = _RecordingPublisher()
    dispatcher = RedisCancelDispatcher(publisher=publisher, registry=registry)

    with pytest.raises(ValueError, match="actor_id"):
        await dispatcher.signal_remote(_key(), actor_id="actor;rm")

    assert publisher.calls == []


@pytest.mark.asyncio
async def test_subscriber_driver_signals_registry_on_message() -> None:
    registry = CancelRegistry()
    driver = CancelSubscriberDriver(registry=registry)
    messages: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
    key = _key()
    task = asyncio.create_task(driver.drive_from_messages(messages))

    try:
        await messages.put((key.redis_channel, "body"))
        await _wait_until_cancelled(registry, key)
        assert registry.is_cancelled(key) is True
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_subscriber_driver_ignores_invalid_channel() -> None:
    registry = CancelRegistry()
    driver = CancelSubscriberDriver(registry=registry)
    messages: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
    key = _key()
    task = asyncio.create_task(driver.drive_from_messages(messages))

    try:
        await messages.put(("other_prefix:" + TENANT_ID + ":" + RUN_ID, "body"))
        await asyncio.sleep(0.05)
        assert registry.is_cancelled(key) is False
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_parse_channel_returns_valid_key() -> None:
    key = _key()

    parsed = _parse_channel(key.redis_channel)

    assert parsed == key


def test_parse_channel_returns_none_for_unknown_prefix() -> None:
    assert _parse_channel(f"other:{TENANT_ID}:{RUN_ID}") is None


def test_parse_channel_returns_none_for_malformed_channel() -> None:
    assert _parse_channel("cli_cancel:missing-run-id") is None
    assert _parse_channel("cli_cancel:not-valid:also-not-valid") is None