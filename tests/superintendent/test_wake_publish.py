"""SP-PHASE1 B4: emergency-stop wake publish (ADR-00048 §F hybrid supervisor) unit test。

- engage 後の wake publish は best-effort: 成功で True、publish 失敗 / publisher 不在で False
  (raise しない、DB poll fallback が回収するため)。
- payload は ``{"tenant_id": <int>}`` のみ (raw secret なし)、channel は server-owned 固定。
"""

from __future__ import annotations

import json

import pytest

from backend.app.services.superintendent.supervisor import SUPERVISOR_WAKE_CHANNEL
from backend.app.services.superintendent.wake_publish import publish_emergency_stop_wake


class _RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1


class _FailingPublisher:
    async def publish(self, channel: str, message: str) -> int:
        raise RuntimeError("redis down")


@pytest.mark.asyncio
async def test_publish_wake_success_payload_and_channel() -> None:
    pub = _RecordingPublisher()
    ok = await publish_emergency_stop_wake(tenant_id=7, publisher=pub)
    assert ok is True
    assert len(pub.published) == 1
    channel, message = pub.published[0]
    assert channel == SUPERVISOR_WAKE_CHANNEL
    assert json.loads(message) == {"tenant_id": 7}


@pytest.mark.asyncio
async def test_publish_wake_no_raw_secret_in_payload() -> None:
    pub = _RecordingPublisher()
    await publish_emergency_stop_wake(tenant_id=3, publisher=pub)
    _channel, message = pub.published[0]
    # payload は tenant_id のみ。secret-shaped key を含まない。
    assert set(json.loads(message).keys()) == {"tenant_id"}


@pytest.mark.asyncio
async def test_publish_wake_failure_is_best_effort_false() -> None:
    """publish 失敗でも raise せず False (DB poll fallback が回収)。"""
    ok = await publish_emergency_stop_wake(tenant_id=1, publisher=_FailingPublisher())
    assert ok is False


@pytest.mark.asyncio
async def test_publish_wake_no_publisher_and_no_url_returns_false() -> None:
    ok = await publish_emergency_stop_wake(tenant_id=1)
    assert ok is False


@pytest.mark.asyncio
async def test_publish_wake_connection_failure_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """redis_url から client 構築に失敗しても False (engage は成立済、DB poll fallback)。"""
    from backend.app.services.superintendent import wake_publish

    def _boom(_url: str) -> object:
        raise RuntimeError("cannot connect")

    monkeypatch.setattr(wake_publish, "_redis_publisher_from_url", _boom)
    ok = await publish_emergency_stop_wake(
        tenant_id=1, redis_url="redis://127.0.0.1:6379/0"
    )
    assert ok is False


class _ClosingPublisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self.closed = False

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_publish_wake_closes_internally_created_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LOW-5: redis_url から内部生成した client は publish 後に close される (leak 防止)。"""
    from backend.app.services.superintendent import wake_publish

    pub = _ClosingPublisher()
    monkeypatch.setattr(wake_publish, "_redis_publisher_from_url", lambda _url: pub)
    ok = await publish_emergency_stop_wake(
        tenant_id=5, redis_url="redis://127.0.0.1:6379/0"
    )
    assert ok is True
    assert pub.closed is True  # 内部生成 client は close される。


@pytest.mark.asyncio
async def test_publish_wake_does_not_close_injected_publisher() -> None:
    """LOW-5: injected publisher (caller 所有) は close しない (所有権は caller)。"""
    pub = _ClosingPublisher()
    ok = await publish_emergency_stop_wake(tenant_id=5, publisher=pub)
    assert ok is True
    assert pub.closed is False  # injected は触らない。


@pytest.mark.asyncio
async def test_publish_wake_closes_internal_client_even_on_publish_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LOW-5: publish 失敗時も内部生成 client を close する (finally で leak 防止)。"""
    from backend.app.services.superintendent import wake_publish

    class _FailPublishClosing(_ClosingPublisher):
        async def publish(self, channel: str, message: str) -> int:
            raise RuntimeError("publish failed")

    pub = _FailPublishClosing()
    monkeypatch.setattr(wake_publish, "_redis_publisher_from_url", lambda _url: pub)
    ok = await publish_emergency_stop_wake(
        tenant_id=5, redis_url="redis://127.0.0.1:6379/0"
    )
    assert ok is False
    assert pub.closed is True
