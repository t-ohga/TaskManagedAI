"""Sprint 6 BL-0070: cancel propagation (in-process registry + Redis pub/sub).

設計 (DD-03 cancel + ADR-00003 §A boundary):

- ``CancelRegistry`` は同一 worker / event loop 内で run_id 単位の
  ``asyncio.Event`` を管理する **in-process** registry。launch_cli_agent を
  call する task は ``wait_for_cancel(run_id)`` と subprocess 完了を
  ``asyncio.wait(..., return_when=FIRST_COMPLETED)`` で race し、cancel が
  先に発火した場合 task を ``cancel()`` する。launcher 側の
  ``_terminate_with_grace`` (R2 で実装済) が process group へ SIGTERM →
  SIGKILL を伝播する。
- ``RedisCancelDispatcher`` は arq worker 群が複数 process / node にまたがる
  ケース用に Redis pub/sub channel ``cli_cancel:{tenant_id}:{run_id}`` で
  cancel signal を broadcast する。各 worker は subscribe して
  ``CancelRegistry.signal()`` を呼ぶ。
- AgentRunEvent は orchestrator (Sprint 6 batch 2 wiring) が
  ``run_cancelled`` / ``cli_process_completed`` を append する。本 module は
  signal propagation のみに集中し、event store / DB は触らない。

server-owned-boundary §1 不変条件:

- signal の **発行** には actor_id + run_id + tenant_id を必須にし、caller-
  supplied free-form key を受け付けない (Redis channel name は server 側で
  format する)。
- run_id は UUID hex のみ allow (path injection / channel-name injection
  防御)。
"""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from typing import Protocol

# Codex SP6B2 R1 F-004 (HIGH) adopt: tenant_id は DB BigInteger (str cast で
# "1") も受ける形に緩和、ただし Redis channel injection (`:` `/` `\n`) は
# 物理削除。actor_id / run_id は UUID-like を保つ (audit trace 用)。
_TENANT_ID_RE = re.compile(r"\A[0-9a-zA-Z_-]{1,64}\Z")
_RUN_ID_RE = re.compile(r"\A[0-9a-fA-F-]{8,64}\Z")
_ACTOR_ID_RE = re.compile(r"\A[0-9a-fA-F-]{8,64}\Z")


def _validate_tenant_id(value: str) -> str:
    if not value or not _TENANT_ID_RE.fullmatch(value):
        raise ValueError(
            "tenant_id must be 1-64 chars of [0-9a-zA-Z_-] (got "
            f"{value!r}); Redis channel injection を防ぐため `:` `/` `\\n` を含まない"
        )
    return value


def _validate_run_id(value: str) -> str:
    if not value or not _RUN_ID_RE.fullmatch(value):
        raise ValueError(
            f"run_id must be a hex / uuid-like identifier (8-64 chars, "
            f"[0-9a-fA-F-]); got {value!r}"
        )
    return value


def _validate_actor_id(value: str) -> str:
    if not value or not _ACTOR_ID_RE.fullmatch(value):
        raise ValueError(
            f"actor_id must be a hex / uuid-like identifier (8-64 chars, "
            f"[0-9a-fA-F-]); got {value!r}"
        )
    return value


@dataclass(frozen=True, slots=True)
class CancelKey:
    tenant_id: str
    run_id: str

    def __post_init__(self) -> None:
        _validate_tenant_id(self.tenant_id)
        _validate_run_id(self.run_id)

    @property
    def redis_channel(self) -> str:
        # tenant_id / run_id は __post_init__ で hex/uuid 制約済、injection
        # 防御を server 側で完結。
        return f"cli_cancel:{self.tenant_id}:{self.run_id}"


@dataclass(slots=True)
class CancelRegistry:
    """In-process cancel signal registry (1 worker / 1 event loop 内).

    Codex SP6B2 R1 F-006 (MEDIUM) adopt: 未登録 key への signal は
    ``_pending_signals`` set で track し、registry 永続 event を作らない。
    register 時に pending signal が存在すれば即 set 済 event を返し、
    pending set から consume する。これにより:
    - 未登録 key の signal 蓄積による memory leak を防止
    - launcher 起動前の signal を `register` で消費する future-proof semantics
      は維持
    """

    _events: dict[CancelKey, asyncio.Event] = field(default_factory=dict)
    _pending_signals: set[CancelKey] = field(default_factory=set)
    # Codex SP6B2 R2 update: pending_signals は bounded set (LRU-ish drop)。
    # multi-worker broadcast で非担当 worker 側に shower される signal が
    # 蓄積する経路を物理的に塞ぐ。
    _pending_signals_max: int = 1024

    def register(self, key: CancelKey) -> asyncio.Event:
        event = self._events.get(key)
        if event is None:
            event = asyncio.Event()
            self._events[key] = event
            if key in self._pending_signals:
                event.set()
                self._pending_signals.discard(key)
        return event

    def signal(self, key: CancelKey) -> bool:
        """Mark the given run as cancelled. Returns True if it was the first
        time the event was set or registered as pending."""

        event = self._events.get(key)
        if event is None:
            # 未登録: pending_signals に置く (memory bounded、register 時に
            # consume される)
            if key in self._pending_signals:
                return False
            # bounded: 上限到達時は最古 (FIFO 近似) を drop
            if len(self._pending_signals) >= self._pending_signals_max:
                # set has no insertion order, but pop() drops an arbitrary
                # element which is acceptable for bounded GC.
                self._pending_signals.pop()
            self._pending_signals.add(key)
            return True
        if event.is_set():
            return False
        event.set()
        return True

    async def wait_for_cancel(self, key: CancelKey) -> None:
        """register 済の event を await する。caller (launcher task) は本
        coroutine と subprocess 完了 を race させる。"""

        event = self.register(key)
        await event.wait()

    def unregister(self, key: CancelKey) -> None:
        """launcher task 完了後に event entry を破棄 (memory leak 防止)。
        pending_signals に残った key も clean up する。"""

        self._events.pop(key, None)
        self._pending_signals.discard(key)

    def is_cancelled(self, key: CancelKey) -> bool:
        event = self._events.get(key)
        if event is not None and event.is_set():
            return True
        return key in self._pending_signals

    def pending_count(self) -> int:
        """memory leak 監視用: 未消費 pending signal の件数."""

        return len(self._pending_signals)


class _RedisPublisherProtocol(Protocol):
    """Minimal protocol for redis.asyncio.Redis publish/subscribe usage.

    本 module は test で in-memory 実装に差し替えられるよう protocol を定義。
    """

    async def publish(self, channel: str, message: str) -> int: ...


@dataclass(slots=True)
class RedisCancelDispatcher:
    """Cross-process cancel broadcaster (Redis pub/sub channel)."""

    publisher: _RedisPublisherProtocol
    registry: CancelRegistry

    async def signal_remote(
        self,
        key: CancelKey,
        *,
        actor_id: str,
    ) -> int:
        """Publish a cancel signal to other workers + signal locally.

        actor_id は audit 用に message body へ含めるが、本 module は audit
        event は emit しない (orchestrator が ``run_cancelled`` event を
        append する)。"""

        _validate_actor_id(actor_id)
        self.registry.signal(key)
        message = f"{actor_id}:{uuid.uuid4().hex}"
        return await self.publisher.publish(key.redis_channel, message)


@dataclass(slots=True)
class CancelSubscriberDriver:
    """``redis.asyncio.PubSub`` 風 subscriber を駆動する helper.

    arq worker 起動時に背後 task として走らせ、Redis から受信した cancel
    signal を local ``CancelRegistry`` へ反映する。"""

    registry: CancelRegistry

    async def drive_from_messages(
        self,
        messages: asyncio.Queue[tuple[str, str]],
    ) -> None:
        """テスト / 駆動 loop。``(channel, body)`` queue を読み続け、
        channel から CancelKey を復元して signal する。

        本 helper は loop だけを提供し、redis.asyncio PubSub の listener と
        繋ぐのは orchestrator (Sprint 6 batch 3 wiring) の責任。
        """

        while True:
            channel, _body = await messages.get()
            key = _parse_channel(channel)
            if key is not None:
                self.registry.signal(key)


def _parse_channel(channel: str) -> CancelKey | None:
    if not channel.startswith("cli_cancel:"):
        return None
    parts = channel.split(":", 2)
    if len(parts) != 3:
        return None
    _, tenant_id, run_id = parts
    try:
        return CancelKey(tenant_id=tenant_id, run_id=run_id)
    except ValueError:
        return None


__all__ = [
    "CancelKey",
    "CancelRegistry",
    "CancelSubscriberDriver",
    "RedisCancelDispatcher",
    "_RedisPublisherProtocol",
    "_parse_channel",
]
