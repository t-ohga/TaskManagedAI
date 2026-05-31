"""ADR-00038 (L-3 SSE realtime): AgentRun 進捗 SSE stream service。

設計正本: docs/adr/00038_agentrun_realtime_sse.md (codex-plan-review R1-R11 approve)。

中核:
- 専用 asyncpg LISTEN pool (main transactional pool と分離、R6-R8)。
- capacity gate = atomic int counter (check-increment 間に await 無し = 真の非ブロッキング、
  R5 の timeout=0 罠を回避)。満杯なら DB を触らず 503 (R8: capacity → preflight の順)。
- dirty-signal queue (maxsize=1, coalesce、R1/R2)。notify は再 query 契機、真の source は DB。
- LISTEN 登録 → catch-up (drain-to-empty) → 無条件 status snapshot (R10) → wake-up ごと再 query。
- send 中は main pool session を保持しない (fetch→release→send、R6)。
- query 同時実行 cap = Semaphore (R7)、heartbeat に jitter (R7)。
- 全 SSE DTO allowlist (event/status/stream_end/error)、raw payload/secret を乗せない (R1/R9)。
- custom ASGI response の単一 __call__ で capacity/preflight/stream/release を try/finally (R3/R8)。
"""

from __future__ import annotations

import asyncio
import json
import logging
from secrets import SystemRandom
from typing import Any
from uuid import UUID

import asyncpg
from sqlalchemy import Row, select
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from backend.app.config import get_settings
from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.agent_run_event import AgentRunEvent
from backend.app.db.session import AsyncSessionFactory
from backend.app.domain.agent_runtime.active_scope import soft_deleted_ticket_run_exclusion
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret

logger = logging.getLogger(__name__)

NOTIFY_CHANNEL = "agent_run_event_appended"

TERMINAL_STATUSES = frozenset(
    {"completed", "failed", "cancelled", "provider_refused", "repair_exhausted"}
)

# stream_end の理由 (allowlist)。
STREAM_END_REASONS = frozenset({"terminal", "scope_revoked", "max_lifetime", "server_shutdown"})
# agent_run_error の理由 (allowlist、exception message は載せない)。
ERROR_REASONS = frozenset({"internal_error", "listen_unavailable"})

_EVENT_TAIL_LIMIT = 200
_jitter = SystemRandom()


# ---------------------------------------------------------------------------
# 専用 LISTEN pool + capacity counter + query concurrency semaphore
# ---------------------------------------------------------------------------
# capacity は atomic int counter (check と increment の間に await が無いため event loop 上で
# 不可分)。これにより「空きが無ければ即拒否、空きがあればブロックせず受理」を timeout=0 を
# 使わずに実現する (R5/R8)。pool / query semaphore は loop 依存のため lazy init + reset。
_pool: asyncpg.Pool | None = None
_query_sem: asyncio.Semaphore | None = None
_init_lock: asyncio.Lock | None = None
_max_streams: int = 0
_active_streams: int = 0


def _asyncpg_dsn() -> str:
    """SQLAlchemy URL (postgresql+asyncpg://...) を asyncpg 用 DSN (postgresql://...) に変換。"""
    url = get_settings().database_url
    return url.replace("postgresql+asyncpg://", "postgresql://", 1).replace(
        "postgresql+psycopg://", "postgresql://", 1
    )


async def _ensure_resources() -> tuple[asyncpg.Pool, asyncio.Semaphore]:
    global _pool, _query_sem, _init_lock, _max_streams
    if _pool is not None and _query_sem is not None:
        return _pool, _query_sem
    if _init_lock is None:
        # check→assign 間に await が無いため不可分 (同一 loop の coroutine 間で安全)。
        _init_lock = asyncio.Lock()
    async with _init_lock:
        if _pool is None or _query_sem is None:
            settings = get_settings()
            _max_streams = settings.agentrun_sse_listen_pool_max
            _query_sem = asyncio.Semaphore(settings.agentrun_sse_query_concurrency)
            _pool = await asyncpg.create_pool(
                dsn=_asyncpg_dsn(),
                min_size=0,
                max_size=settings.agentrun_sse_listen_pool_max,
            )
    if _pool is None or _query_sem is None:  # 不変条件 (到達しない)
        raise RuntimeError("agent_run_stream resources failed to initialize")
    return _pool, _query_sem


async def reset_stream_resources() -> None:
    """test teardown / app shutdown 用。pool を閉じ lazy state を初期化する。"""
    global _pool, _query_sem, _init_lock, _max_streams, _active_streams
    pool = _pool
    _pool = None
    _query_sem = None
    _init_lock = None
    _max_streams = 0
    _active_streams = 0
    if pool is not None:
        await pool.close()


# ---------------------------------------------------------------------------
# SSE framing + DTO (allowlist redaction)
# ---------------------------------------------------------------------------
_HEARTBEAT_FRAME = b": keepalive\n\n"


def _frame(event: str, data: dict[str, Any], *, sse_id: int | None = None) -> bytes:
    lines: list[str] = []
    if sse_id is not None:
        lines.append(f"id: {sse_id}")
    lines.append(f"event: {event}")
    lines.append("data: " + json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def _event_dto(event: AgentRunEvent) -> dict[str, Any]:
    payload = event.event_payload or {}
    try:
        assert_no_raw_secret(payload, path="$sse_event_payload")
        payload_keys = sorted(payload.keys())
        redaction = "keys_only"
    except ValueError:
        payload_keys = []
        redaction = "blocked_by_secret_scan"
    return {
        "event_id": str(event.id),
        "seq_no": event.seq_no,
        "event_type": event.event_type,
        "actor_id": str(event.actor_id),
        "payload_keys": payload_keys,
        "payload_redaction_status": redaction,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _status_dto(row: Row[Any]) -> dict[str, Any]:
    """status 最小 allowlist。error_summary raw / provider metadata / cost は載せない (R1/R9)。"""
    return {
        "status": row.status,
        "blocked_reason": row.blocked_reason,
        "terminal": row.status in TERMINAL_STATUSES,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "error_code": row.error_code,
    }


def _status_key(row: Row[Any]) -> tuple[Any, ...]:
    return (row.status, row.blocked_reason, row.completed_at, row.error_code)


# ---------------------------------------------------------------------------
# DB query (active-scope 込み、main pool 短命 session)
# ---------------------------------------------------------------------------
async def _fetch_status(
    tenant_id: int, run_id: UUID, query_sem: asyncio.Semaphore
) -> Row[Any] | None:
    """current status snapshot。active-scope 外 / 不在なら None (scope_revoked / 404)。"""
    async with query_sem:
        async with AsyncSessionFactory() as session:
            return (
                await session.execute(
                    select(
                        AgentRun.status,
                        AgentRun.blocked_reason,
                        AgentRun.completed_at,
                        AgentRun.error_code,
                    ).where(
                        AgentRun.tenant_id == tenant_id,
                        AgentRun.id == run_id,
                        soft_deleted_ticket_run_exclusion(),
                    )
                )
            ).one_or_none()


async def _fetch_event_page(
    tenant_id: int, run_id: UUID, after_seq: int, query_sem: asyncio.Semaphore
) -> list[AgentRunEvent]:
    """active-scope 込みの 1 page (seq_no > after_seq)。run が scope 外なら空 (status 側で停止判定)。"""
    async with query_sem:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(AgentRunEvent)
                .where(
                    AgentRunEvent.tenant_id == tenant_id,
                    AgentRunEvent.run_id == run_id,
                    AgentRunEvent.seq_no > after_seq,
                    select(AgentRun.id)
                    .where(
                        AgentRun.tenant_id == tenant_id,
                        AgentRun.id == run_id,
                        soft_deleted_ticket_run_exclusion(),
                    )
                    .exists(),
                )
                .order_by(AgentRunEvent.seq_no)
                .limit(_EVENT_TAIL_LIMIT)
            )
            return list(result.scalars())


# ---------------------------------------------------------------------------
# Custom ASGI streaming response
# ---------------------------------------------------------------------------
class AgentRunStreamResponse(Response):
    """capacity → preflight → LISTEN → stream → release を単一 __call__ try/finally で所有する。

    Starlette ``Response`` を継承するのは、FastAPI が ``isinstance(raw_response, Response)`` で
    直返し (serialize せず ``await response(scope, receive, send)``) すると判定するため。body 描画は
    使わず ``__call__`` を完全 override し、capacity/preflight/stream/release を 1 scope で所有する
    (``StreamingResponse`` factory への handoff leak 窓 = R3 を排除)。
    """

    def __init__(self, *, tenant_id: int, run_id: UUID, last_event_id: int) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        self.last_event_id = last_event_id
        # Response.__init__ は呼ばない (body/header は __call__ で送る)。FastAPI が参照する属性のみ用意。
        self.status_code = 200
        self.background = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        global _active_streams
        pool, query_sem = await _ensure_resources()

        # (i) capacity gate (atomic、DB を触らず判定)。満杯なら 503 (R8)。
        if _active_streams >= _max_streams:
            await _send_simple(send, 503, [(b"retry-after", b"5")])
            return
        _active_streams += 1
        conn: asyncpg.Connection | None = None
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
        # response phase: ASGI http.response.start の二重送出を防ぐ (code-review #3)。
        #   "none"       = まだ start 未送出 → 失敗時に 503 を送れる
        #   "non_stream" = 404/503 を送出済 (非 stream) → 失敗時は再送せず cleanup のみ
        #   "stream"     = 200 SSE header 送出済 → 失敗時は SSE agent_run_error + stream_end
        phase = "none"

        def _on_notify(
            _conn: asyncpg.Connection, _pid: int, _channel: str, payload: str
        ) -> None:
            try:
                data = json.loads(payload)
            except (ValueError, TypeError):
                return
            if data.get("tenant_id") == self.tenant_id and str(data.get("run_id")) == str(
                self.run_id
            ):
                try:
                    queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass  # coalesce: 既に dirty。次の DB 再 query で回収。

        try:
            # (ii) LISTEN connection 取得 (capacity gate 済なので空きあり、短い正の timeout)。
            conn = await pool.acquire(timeout=5)
            await conn.add_listener(NOTIFY_CHANNEL, _on_notify)

            # (iii) preflight: scope/存在判定 (active-scope)。scope 外/不在は 404。
            status_row = await _fetch_status(self.tenant_id, self.run_id, query_sem)
            if status_row is None:
                phase = "non_stream"
                await _send_simple(send, 404)
                return

            # (iv) 200 SSE header。proxy buffering 無効化。これ以降は SSE frame で閉じる。
            phase = "stream"
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"text/event-stream; charset=utf-8"),
                        (b"cache-control", b"no-cache"),
                        (b"x-accel-buffering", b"no"),
                        (b"connection", b"keep-alive"),
                    ],
                }
            )
            await self._run_stream(send, query_sem, queue, loop, status_row)
        except asyncio.CancelledError:
            raise  # client disconnect / shutdown → finally で cleanup
        except Exception:  # noqa: BLE001
            logger.exception("agent_run_stream_error", extra={"run_id": str(self.run_id)})
            try:
                if phase == "none":
                    await _send_simple(send, 503, [(b"retry-after", b"5")])
                elif phase == "stream":
                    await _send_body(
                        send,
                        _frame(
                            "agent_run_error", {"reason": "internal_error", "retryable": True}
                        ),
                    )
                    await _send_body(
                        send, _frame("stream_end", {"reason": "server_shutdown"}), more=False
                    )
                # phase == "non_stream": start 送出済 → http.response.start を再送しない (二重 start 防止)。
            except Exception:  # noqa: BLE001, S110 - error 通知の best-effort (client 既切断等)
                pass
        finally:
            # capacity slot は cleanup の成否に関わらず必ず戻す (code-review #1: release 例外/
            # cancellation で decrement が skip されると slot leak → 恒久 503)。
            try:
                if conn is not None:
                    try:
                        await conn.remove_listener(NOTIFY_CHANNEL, _on_notify)
                    except Exception:  # noqa: BLE001, S110 - cleanup の best-effort
                        pass
                    try:
                        await pool.release(conn)
                    except Exception:  # noqa: BLE001 - release 失敗は terminate + log
                        logger.warning(
                            "agent_run_stream_release_failed",
                            extra={"run_id": str(self.run_id)},
                        )
                        try:
                            conn.terminate()
                        except Exception:  # noqa: BLE001, S110
                            pass
            finally:
                _active_streams -= 1

    async def _run_stream(
        self,
        send: Send,
        query_sem: asyncio.Semaphore,
        queue: asyncio.Queue[None],
        loop: asyncio.AbstractEventLoop,
        status_row: Row[Any],
    ) -> None:
        settings = get_settings()
        # catch-up (drain-to-empty)。
        last_sent = await self._drain_events(send, query_sem, self.last_event_id)
        # 無条件 status snapshot (R10)。
        await _send_body(send, _frame("agent_run_status", _status_dto(status_row)))
        last_status = _status_key(status_row)
        if status_row.status in TERMINAL_STATUSES:
            await _send_body(send, _frame("stream_end", {"reason": "terminal"}), more=False)
            return

        deadline = loop.time() + settings.agentrun_sse_max_lifetime_seconds
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                await _send_body(send, _frame("stream_end", {"reason": "max_lifetime"}), more=False)
                return
            heartbeat = settings.agentrun_sse_heartbeat_seconds + _jitter.uniform(
                0.0, settings.agentrun_sse_heartbeat_jitter_seconds
            )
            woke_by_signal = True
            try:
                await asyncio.wait_for(queue.get(), timeout=min(heartbeat, remaining))
            except TimeoutError:
                woke_by_signal = False

            # drain events (dirty-signal でも heartbeat でも DB を真の source に再 query)。
            last_sent = await self._drain_events(send, query_sem, last_sent)

            # status 再 query (scope 失効 / terminal を idle でも heartbeat 以内に検知、R2/R10)。
            current_status = await _fetch_status(self.tenant_id, self.run_id, query_sem)
            if current_status is None:
                await _send_body(
                    send, _frame("stream_end", {"reason": "scope_revoked"}), more=False
                )
                return
            skey = _status_key(current_status)
            if skey != last_status:
                await _send_body(send, _frame("agent_run_status", _status_dto(current_status)))
                last_status = skey
            if current_status.status in TERMINAL_STATUSES:
                await _send_body(send, _frame("stream_end", {"reason": "terminal"}), more=False)
                return
            if not woke_by_signal:
                await _send_body(send, _HEARTBEAT_FRAME)

    async def _drain_events(
        self, send: Send, query_sem: asyncio.Semaphore, after_seq: int
    ) -> int:
        """1 wake-up で `seq_no > last_sent` を取得 < limit まで drain (burst > N でも落とさない、R2)。

        fetch (短命 session) と send を分離し、slow client の間 main pool session を保持しない (R6)。
        """
        last = after_seq
        while True:
            page = await _fetch_event_page(self.tenant_id, self.run_id, last, query_sem)
            if not page:
                break
            for event in page:
                await _send_body(send, _frame("agent_run_event", _event_dto(event), sse_id=event.seq_no))
                last = event.seq_no
            if len(page) < _EVENT_TAIL_LIMIT:
                break
        return last


async def _send_simple(
    send: Send, status_code: int, extra_headers: list[tuple[bytes, bytes]] | None = None
) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": extra_headers or [],
        }
    )
    await send({"type": "http.response.body", "body": b"", "more_body": False})


async def _send_body(send: Send, body: bytes, *, more: bool = True) -> None:
    await send({"type": "http.response.body", "body": body, "more_body": more})


__all__ = [
    "AgentRunStreamResponse",
    "NOTIFY_CHANNEL",
    "TERMINAL_STATUSES",
    "reset_stream_resources",
]
