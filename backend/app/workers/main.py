from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from contextlib import suppress
from inspect import isawaitable
from typing import Any, ClassVar, Protocol, cast
from urllib.parse import unquote, urlparse

from arq.connections import RedisSettings

from backend.app.config import Settings, get_settings
from backend.app.observability import setup_logging, setup_otel
from backend.app.workers.tasks import noop_task

logger = logging.getLogger(__name__)

WorkerContext = MutableMapping[str, object]
WorkerResult = dict[str, str]
WorkerFunction = Callable[[WorkerContext], Awaitable[WorkerResult]]
CancelMessage = Mapping[str, Any]


class PubSubConnection(Protocol):
    async def subscribe(self, *channels: str) -> object:
        ...

    async def get_message(
        self,
        ignore_subscribe_messages: bool = True,
        **kwargs: object,
    ) -> CancelMessage | None:
        ...


class RedisPubSubConnection(Protocol):
    def pubsub(self) -> PubSubConnection:
        ...


def redis_settings_from_url(redis_url: str) -> RedisSettings:
    parsed = urlparse(redis_url)
    if parsed.scheme not in {"redis", "rediss"}:
        raise ValueError("TASKMANAGEDAI_REDIS_URL must use redis or rediss scheme.")

    database = int(parsed.path.lstrip("/") or "0")
    password = unquote(parsed.password) if parsed.password is not None else None

    return RedisSettings(
        host=parsed.hostname or "redis",
        port=parsed.port or 6379,
        database=database,
        password=password,
        ssl=parsed.scheme == "rediss",
    )


def _redis_from_context(ctx: WorkerContext) -> RedisPubSubConnection:
    redis = ctx.get("redis")
    if redis is None or not hasattr(redis, "pubsub"):
        raise RuntimeError("arq worker startup requires redis pub/sub in worker context.")
    return cast(RedisPubSubConnection, redis)


async def _close_pubsub(pubsub: PubSubConnection) -> None:
    close = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
    if close is None:
        return

    result = close()
    if isawaitable(result):
        await result


async def propagate_agent_run_cancel(message: CancelMessage, cancel_channel: str) -> None:
    logger.info(
        "cancel_message_received",
        extra={
            "cancel_channel": cancel_channel,
            "message_type": message.get("type", "unknown"),
        },
    )


async def _cancel_pubsub_listener(pubsub: PubSubConnection, cancel_channel: str) -> None:
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None:
                continue
            await propagate_agent_run_cancel(message, cancel_channel)
    except asyncio.CancelledError:
        logger.info("cancel_pubsub_listener_stopped", extra={"cancel_channel": cancel_channel})
        raise


async def on_startup(ctx: WorkerContext) -> None:
    settings = get_settings()

    # Sprint 11.5 batch 1 BL-0133: structured logging (JSON Lines) for Loki shipping.
    # setup_otel より先に call (logger init の JSON 化).
    setup_logging(role="worker")

    # Sprint 11.5 batch 0 BL-0131: worker process に OTel auto-instrument
    # (httpx / SQLAlchemy / Redis). FastAPI instrumentor は role="worker" で skip.
    setup_otel(role="worker")

    ctx["cancel_channel"] = settings.worker_cancel_channel

    pubsub = _redis_from_context(ctx).pubsub()
    await pubsub.subscribe(settings.worker_cancel_channel)
    ctx["cancel_pubsub"] = pubsub
    ctx["cancel_listener_task"] = asyncio.create_task(
        _cancel_pubsub_listener(pubsub, settings.worker_cancel_channel)
    )

    logger.info(
        "cancel_pubsub_subscribed",
        extra={"cancel_channel": settings.worker_cancel_channel},
    )
    logger.info(
        "worker_startup",
        extra={
            "queue_name": settings.arq_queue_name,
            "cancel_channel": settings.worker_cancel_channel,
        },
    )


async def on_shutdown(ctx: WorkerContext) -> None:
    task = ctx.pop("cancel_listener_task", None)
    if isinstance(task, asyncio.Task):
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    pubsub = ctx.pop("cancel_pubsub", None)
    if pubsub is not None:
        await _close_pubsub(cast(PubSubConnection, pubsub))

    ctx.pop("cancel_channel", None)
    logger.info("worker_shutdown")


class WorkerSettings:
    settings: ClassVar[Settings] = get_settings()
    functions: ClassVar[list[WorkerFunction]] = [noop_task]
    redis_settings: ClassVar[RedisSettings] = redis_settings_from_url(settings.redis_url)
    queue_name: ClassVar[str] = settings.arq_queue_name
    on_startup: ClassVar[Callable[[WorkerContext], Awaitable[None]]] = on_startup
    on_shutdown: ClassVar[Callable[[WorkerContext], Awaitable[None]]] = on_shutdown
    max_jobs: ClassVar[int] = 10
    job_timeout: ClassVar[int] = 300
    keep_result: ClassVar[int] = 3600

