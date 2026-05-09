from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import unquote, urlparse
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import get_settings
from backend.app.db.models.agent_run import AgentRun
from backend.app.domain.agent_runtime.status import TERMINAL_STATES
from backend.app.services.agent_runtime.event_log import transition_with_event

logger = logging.getLogger(__name__)

_CANCELABLE_STATES = frozenset(
    {"running", "blocked", "waiting_approval", "provider_incomplete"}
)


class CancelPublisher(Protocol):
    async def publish(self, channel: str, message: str) -> object:
        ...


@dataclass(frozen=True, slots=True)
class CancelPublishResult:
    channel: str
    message: str


async def cancel_agent_run(
    session: AsyncSession,
    run_id: UUID,
    reason: str | None,
    actor_id: UUID,
    *,
    tenant_id: int | None = None,
    publisher: CancelPublisher | None = None,
) -> AgentRun:
    stmt = sa.select(AgentRun).where(AgentRun.id == run_id)
    if tenant_id is not None:
        stmt = stmt.where(AgentRun.tenant_id == tenant_id)

    run = await session.scalar(stmt.with_for_update())
    if run is None:
        raise LookupError("agent run not found")

    if run.status in TERMINAL_STATES:
        raise ValueError(f"terminal AgentRun state cannot be cancelled: {run.status!r}")
    if run.status not in _CANCELABLE_STATES:
        raise ValueError(f"AgentRun state cannot be cancelled: {run.status!r}")

    resolved_reason = reason or "user_cancel"
    await transition_with_event(
        session,
        run=run,
        to_state="cancelled",
        event_type="run_cancelled",
        actor_id=actor_id,
        payload={"reason": resolved_reason},
        tenant_id=run.tenant_id,
    )

    try:
        await publish_cancel_signal(
            run_id=run.id,
            reason=resolved_reason,
            publisher=publisher,
        )
    except Exception:
        logger.warning(
            "agent_run_cancel_publish_failed",
            extra={"run_id": str(run.id), "tenant_id": run.tenant_id},
            exc_info=True,
        )

    await session.refresh(run)
    return run


async def publish_cancel_signal(
    *,
    run_id: UUID,
    reason: str,
    publisher: CancelPublisher | None = None,
    redis_url: str | None = None,
) -> CancelPublishResult:
    channel = f"cancel:run:{run_id}"
    message = json.dumps(
        {
            "event_type": "run_cancelled",
            "reason": reason,
            "run_id": str(run_id),
        },
        separators=(",", ":"),
        sort_keys=True,
    )

    if publisher is not None:
        await publisher.publish(channel, message)
    else:
        await _redis_publish(redis_url or get_settings().redis_url, channel, message)

    return CancelPublishResult(channel=channel, message=message)


async def _redis_publish(redis_url: str, channel: str, message: str) -> None:
    parsed = urlparse(redis_url)
    if parsed.scheme not in {"redis", "rediss"}:
        raise ValueError("TASKMANAGEDAI_REDIS_URL must use redis or rediss scheme.")

    reader, writer = await asyncio.open_connection(
        parsed.hostname or "redis",
        parsed.port or 6379,
        ssl=parsed.scheme == "rediss",
    )
    try:
        if parsed.password:
            await _send_redis_command(reader, writer, "AUTH", unquote(parsed.password))
        database = parsed.path.lstrip("/")
        if database:
            await _send_redis_command(reader, writer, "SELECT", database)
        await _send_redis_command(reader, writer, "PUBLISH", channel, message)
    finally:
        writer.close()
        await writer.wait_closed()


async def _send_redis_command(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *parts: str,
) -> bytes:
    encoded = b"".join(
        [
            f"*{len(parts)}\r\n".encode("ascii"),
            *[
                f"${len(part.encode('utf-8'))}\r\n".encode("ascii")
                + part.encode("utf-8")
                + b"\r\n"
                for part in parts
            ],
        ]
    )
    writer.write(encoded)
    await writer.drain()
    response = await reader.readline()
    if not response:
        raise RuntimeError("Redis returned an empty response.")
    if response.startswith(b"-"):
        raise RuntimeError(response.decode("utf-8", errors="replace").strip())
    return response


__all__ = [
    "CancelPublishResult",
    "cancel_agent_run",
    "publish_cancel_signal",
]

