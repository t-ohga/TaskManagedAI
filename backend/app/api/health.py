from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Literal
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine as create_database_engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

DependencyState = Literal["ok", "error"]


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = Field(description="Process liveness status.")
    version: str = Field(min_length=1, description="Application version.")
    service: Literal["api"] = "api"


class DependencyStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: DependencyState
    error_code: str | None = None
    error_summary: str | None = None


class ReadinessDependencies(BaseModel):
    model_config = ConfigDict(frozen=True)

    postgres: DependencyStatus
    redis: DependencyStatus


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ready", "not_ready"]
    version: str = Field(min_length=1, description="Application version.")
    service: Literal["api"] = "api"
    dependencies: ReadinessDependencies


def settings_from_request(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, Settings):
        return settings
    return get_settings()


async def check_postgres(settings: Settings) -> DependencyStatus:
    engine: AsyncEngine | None = None
    try:
        engine = create_database_engine(settings.database_url)
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        logger.warning("readiness_postgres_unavailable", exc_info=True)
        return DependencyStatus(
            status="error",
            error_code="postgres_unavailable",
            error_summary="PostgreSQL readiness check failed.",
        )
    finally:
        if engine is not None:
            await engine.dispose()

    return DependencyStatus(status="ok")


def _encode_redis_command(parts: tuple[str, ...]) -> bytes:
    encoded_parts = [part.encode("utf-8") for part in parts]
    command = bytearray(f"*{len(encoded_parts)}\r\n".encode("ascii"))
    for part in encoded_parts:
        command.extend(f"${len(part)}\r\n".encode("ascii"))
        command.extend(part)
        command.extend(b"\r\n")
    return bytes(command)


async def _read_redis_simple_response(reader: asyncio.StreamReader) -> bytes:
    line = await asyncio.wait_for(reader.readline(), timeout=2.0)
    if not line:
        raise RuntimeError("Redis readiness check returned an empty response.")
    if line.startswith(b"-"):
        raise RuntimeError("Redis readiness check returned an error response.")
    return line


async def _send_redis_command(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *parts: str,
) -> bytes:
    writer.write(_encode_redis_command(parts))
    await asyncio.wait_for(writer.drain(), timeout=2.0)
    return await _read_redis_simple_response(reader)


def _redis_database_index(path: str) -> int | None:
    normalized = path.lstrip("/")
    if normalized == "":
        return None

    database_index = int(normalized)
    if database_index < 0:
        raise ValueError("Redis database index must be non-negative.")
    return database_index


async def check_redis(settings: Settings) -> DependencyStatus:
    writer: asyncio.StreamWriter | None = None

    try:
        parsed = urlparse(settings.redis_url)
        if parsed.scheme not in {"redis", "rediss"}:
            raise ValueError("TASKMANAGEDAI_REDIS_URL must use redis or rediss scheme.")

        reader, opened_writer = await asyncio.wait_for(
            asyncio.open_connection(
                parsed.hostname or "redis",
                parsed.port or 6379,
                ssl=parsed.scheme == "rediss",
            ),
            timeout=2.0,
        )
        writer = opened_writer

        if parsed.password is not None:
            password = unquote(parsed.password)
            if parsed.username:
                await _send_redis_command(
                    reader,
                    opened_writer,
                    "AUTH",
                    unquote(parsed.username),
                    password,
                )
            else:
                await _send_redis_command(reader, opened_writer, "AUTH", password)

        database_index = _redis_database_index(parsed.path)
        if database_index is not None:
            await _send_redis_command(reader, opened_writer, "SELECT", str(database_index))

        response = await _send_redis_command(reader, opened_writer, "PING")
        if response.strip() != b"+PONG":
            raise RuntimeError("Redis readiness check did not return PONG.")
    except Exception:
        logger.warning("readiness_redis_unavailable", exc_info=True)
        return DependencyStatus(
            status="error",
            error_code="redis_unavailable",
            error_summary="Redis readiness check failed.",
        )
    finally:
        if writer is not None:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()

    return DependencyStatus(status="ok")


@router.get("/healthz", response_model=HealthResponse, summary="Process liveness")
async def healthz(request: Request) -> HealthResponse:
    settings = settings_from_request(request)
    return HealthResponse(status="ok", version=settings.app_version)


@router.get(
    "/readyz",
    response_model=ReadinessResponse,
    response_model_exclude_none=True,
    summary="Dependency readiness",
)
async def readyz(request: Request, response: Response) -> ReadinessResponse:
    settings = settings_from_request(request)
    postgres_status, redis_status = await asyncio.gather(
        check_postgres(settings),
        check_redis(settings),
    )

    dependencies = ReadinessDependencies(
        postgres=postgres_status,
        redis=redis_status,
    )
    readiness_status: Literal["ready", "not_ready"] = (
        "ready"
        if postgres_status.status == "ok" and redis_status.status == "ok"
        else "not_ready"
    )

    if readiness_status == "not_ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status=readiness_status,
        version=settings.app_version,
        dependencies=dependencies,
    )

