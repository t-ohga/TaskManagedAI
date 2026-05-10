from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.api.approval_inbox import get_db_session
from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.main import create_app
from backend.app.seeds.initial import DEFAULT_PROJECT_ID, seed_initial
from backend.app.services.agent_runtime import cancel as cancel_module

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

RUN_ID = UUID("00000000-0000-4000-8000-000000004a01")


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-agent-runs-cancel-api",
    )


def _run_alembic_upgrade(database_url: str) -> None:
    previous_database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        config = Config(str(_REPO_ROOT / "alembic.ini"))
        command.upgrade(config, "head")
    finally:
        if previous_database_url is None:
            os.environ.pop("TASKMANAGEDAI_DATABASE_URL", None)
        else:
            os.environ["TASKMANAGEDAI_DATABASE_URL"] = previous_database_url
        get_settings.cache_clear()


async def _assert_database_available(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
    except (OSError, SQLAlchemyError, TimeoutError) as exc:
        if os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") == "1":
            raise AssertionError("AgentRun cancel API tests require PostgreSQL.") from exc
        pytest.skip("Set TASKMANAGEDAI_RUN_DB_TESTS=1 with test PostgreSQL running.")
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


@pytest_asyncio.fixture
async def agent_runs_api_client(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    app = create_app(_integration_settings())

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    async def fake_redis_publish(redis_url: str, channel: str, message: str) -> None:
        return None

    app.dependency_overrides[get_db_session] = override_get_db_session
    monkeypatch.setattr(cancel_module, "_redis_publish", fake_redis_publish)

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def _setup_run(session_factory: async_sessionmaker[AsyncSession], status: str) -> None:
    async with session_factory.begin() as session:
        await session.execute(
            text(
                """
                truncate
                  agent_run_events,
                  agent_runs,
                  audit_events,
                  notification_events,
                  acceptance_criteria,
                  tickets,
                  repositories,
                  projects,
                  workspaces,
                  principals,
                  actors,
                  tenants
                restart identity cascade
                """
            )
        )
        await seed_initial(session)
        await session.execute(
            text(
                """
                insert into agent_runs (id, tenant_id, project_id, status, blocked_reason)
                values (:run_id, 1, :project_id, :status, :blocked_reason)
                """
            ),
            {
                "run_id": RUN_ID,
                "project_id": DEFAULT_PROJECT_ID,
                "status": status,
                "blocked_reason": "runtime_blocked" if status == "blocked" else None,
            },
        )


def test_agent_runs_cancel_route_is_registered() -> None:
    app = create_app(_integration_settings())
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/v1/agent_runs/{run_id}/cancel" in paths


@pytest.mark.asyncio
async def test_cancel_agent_run_endpoint_cancels_running_run(
    agent_runs_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_run(session_factory, status="running")

    response = await agent_runs_api_client.post(
        f"/api/v1/agent_runs/{RUN_ID}/cancel",
        json={"reason": "user_cancel"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(RUN_ID)
    assert payload["tenant_id"] == 1
    assert payload["project_id"] == str(DEFAULT_PROJECT_ID)
    assert payload["status"] == "cancelled"
    assert payload["blocked_reason"] is None

    async with session_factory() as session:
        status = await session.scalar(
            text("select status from agent_runs where tenant_id = 1 and id = :run_id"),
            {"run_id": RUN_ID},
        )
        event_type = await session.scalar(
            text(
                """
                select event_type
                  from agent_run_events
                 where tenant_id = 1 and run_id = :run_id
                 order by seq_no desc
                 limit 1
                """
            ),
            {"run_id": RUN_ID},
        )

    assert status == "cancelled"
    assert event_type == "run_cancelled"


@pytest.mark.asyncio
async def test_cancel_agent_run_endpoint_returns_404_for_missing_run(
    agent_runs_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_run(session_factory, status="running")
    missing_run_id = UUID("00000000-0000-4000-8000-000000004aff")

    response = await agent_runs_api_client.post(
        f"/api/v1/agent_runs/{missing_run_id}/cancel",
        json={"reason": "user_cancel"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "agent run not found"

