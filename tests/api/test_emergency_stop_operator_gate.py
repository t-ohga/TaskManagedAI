"""SP-PHASE1 B3: emergency-stop operator gate (ADR-00048 §C/A-10) の fail-closed test。

``require_emergency_stop_operator`` は ``_require_authenticated_owner`` (me.py) と同一 owner gate を
流用する (A-10)。検証:
- authenticated + human + configured owner (human:default) は許可。
- unauthenticated (dev/test fallback authenticated=False) は 401 (default owner として resolve されても)。
- 同 tenant 別 human / service / agent / provider / github_app は 403 (fail-closed)。
- route-level: cookie 無し request は 401/403 (middleware が authenticated=False を seed し gate が弾く)。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.api.approval_inbox import get_db_session
from backend.app.api.dependencies.emergency_stop_operator import (
    require_emergency_stop_operator,
)
from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.main import create_app
from backend.app.middleware.dev_actor import (
    DEV_SESSION_COOKIE_NAME,
    create_signed_session_cookie,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_COOKIE_SECRET = "test-cookie-secret-for-emergency-stop-gate"

ACTOR_OWNER_ID = UUID("00000000-0000-4000-8000-0000000c5001")
ACTOR_OTHER_HUMAN_ID = UUID("00000000-0000-4000-8000-0000000c5002")
ACTOR_SERVICE_ID = UUID("00000000-0000-4000-8000-0000000c5003")
ACTOR_AGENT_ID = UUID("00000000-0000-4000-8000-0000000c5004")
ACTOR_PROVIDER_ID = UUID("00000000-0000-4000-8000-0000000c5005")
ACTOR_GITHUB_APP_ID = UUID("00000000-0000-4000-8000-0000000c5006")

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)


def _fake_request(*, authenticated: bool) -> object:
    return SimpleNamespace(
        state=SimpleNamespace(authenticated=authenticated),
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(default_actor_id="human:default")
            )
        ),
    )


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=_COOKIE_SECRET,
    )


def _run_alembic_upgrade(database_url: str) -> None:
    previous = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        command.upgrade(Config(str(_REPO_ROOT / "alembic.ini")), "head")
    finally:
        if previous is None:
            os.environ.pop("TASKMANAGEDAI_DATABASE_URL", None)
        else:
            os.environ["TASKMANAGEDAI_DATABASE_URL"] = previous
        get_settings.cache_clear()


async def _assert_database_available(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
    except (OSError, SQLAlchemyError, TimeoutError) as exc:
        raise AssertionError("emergency-stop gate tests require PostgreSQL.") from exc
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    settings = _integration_settings()
    await _assert_database_available(settings)
    await asyncio.to_thread(_run_alembic_upgrade, settings.database_url)
    engine = create_engine(settings.database_url)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _reset_tables(session: AsyncSession) -> None:
    await session.execute(
        text("truncate actors, tenants restart identity cascade")
    )


async def _seed(session: AsyncSession) -> None:
    await session.execute(
        text(
            "insert into tenants (id, name, metadata) values "
            "(1, 'tenant-one', '{\"rls_ready\": true}'::jsonb)"
        )
    )
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values
              (:own, 1, 'human', 'human:default', 'Owner', '{"rls_ready": true}'::jsonb),
              (:oth, 1, 'human', 'human:other', 'Other Human', '{"rls_ready": true}'::jsonb),
              (:svc, 1, 'service', 'service:worker', 'Worker', '{"rls_ready": true}'::jsonb),
              (:agt, 1, 'agent', 'agent:runner', 'Agent', '{"rls_ready": true}'::jsonb),
              (:prv, 1, 'provider', 'provider:openai', 'Provider', '{"rls_ready": true}'::jsonb),
              (:gha, 1, 'github_app', 'github_app:repo', 'GitHub App', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "own": ACTOR_OWNER_ID,
            "oth": ACTOR_OTHER_HUMAN_ID,
            "svc": ACTOR_SERVICE_ID,
            "agt": ACTOR_AGENT_ID,
            "prv": ACTOR_PROVIDER_ID,
            "gha": ACTOR_GITHUB_APP_ID,
        },
    )
    await session.commit()


@pytest.mark.asyncio
async def test_operator_gate_allows_authenticated_owner(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed(session)
    async with session_factory() as session:
        resolved = await require_emergency_stop_operator(
            _fake_request(authenticated=True),  # type: ignore[arg-type]
            actor_id=ACTOR_OWNER_ID,
            tenant_id=1,
            session=session,
        )
        assert resolved == ACTOR_OWNER_ID


@pytest.mark.asyncio
async def test_operator_gate_rejects_unauthenticated_owner(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed(session)
    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            await require_emergency_stop_operator(
                _fake_request(authenticated=False),  # type: ignore[arg-type]
                actor_id=ACTOR_OWNER_ID,  # default owner として resolve されても
                tenant_id=1,
                session=session,
            )
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_operator_gate_rejects_non_owner_actors(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """同 tenant 別 human / service / agent / provider / github_app は全 403 (fail-closed)。"""
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed(session)
    non_owner_actors = (
        ACTOR_OTHER_HUMAN_ID,
        ACTOR_SERVICE_ID,
        ACTOR_AGENT_ID,
        ACTOR_PROVIDER_ID,
        ACTOR_GITHUB_APP_ID,
    )
    for actor in non_owner_actors:
        async with session_factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await require_emergency_stop_operator(
                    _fake_request(authenticated=True),  # type: ignore[arg-type]
                    actor_id=actor,
                    tenant_id=1,
                    session=session,
                )
            assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_emergency_stop_routes_reject_no_cookie(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """route-level: cookie 無し request は engage/clear/status とも 401/403 (fail-closed)。"""
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed(session)

    app = create_app(_integration_settings())

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        engage = await client.post("/api/v1/superintendent/emergency-stop", json={})
        clear = await client.post(
            "/api/v1/superintendent/emergency-stop/clear",
            json={"expected_generation": 1},
        )
        status_resp = await client.get("/api/v1/superintendent/emergency-stop")
    assert engage.status_code in (401, 403)
    assert clear.status_code in (401, 403)
    assert status_resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_emergency_stop_status_allows_owner_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """owner session cookie で GET status が 200 + engaged=false (latch 未設定) を返す。"""
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed(session)

    app = create_app(_integration_settings())

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = _override_session
    cookie_value, _expires = create_signed_session_cookie(secret=_COOKIE_SECRET)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={DEV_SESSION_COOKIE_NAME: cookie_value},
    ) as client:
        response = await client.get("/api/v1/superintendent/emergency-stop")

    assert response.status_code == 200
    payload = response.json()
    assert payload["engaged"] is False
    assert payload["generation"] is None
    # raw secret / pid / token を含まない。
    assert "pid" not in response.text
    assert "token" not in response.text.lower()
