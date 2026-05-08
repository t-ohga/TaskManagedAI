from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, HTTPException, Request, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.main import create_app
from backend.app.middleware.dev_actor import DEV_SESSION_COOKIE_NAME
from backend.app.seeds.initial import Sprint1SeedRecord
from backend.app.seeds.runner import seed_initial

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_TEST_DEV_LOGIN_TOKEN = "test-dev-login-token-for-ci-only"
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-e2e-smoke",
        ),
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
            raise AssertionError("Sprint 1 e2e smoke requires a reachable test database.") from exc
        pytest.skip("Set TASKMANAGEDAI_RUN_DB_TESTS=1 with test PostgreSQL running.")
    finally:
        await engine.dispose()


async def _assert_seed_table_migrated(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    table_ref: str | None = None
    try:
        async with engine.connect() as connection:
            table_ref = await connection.scalar(
                text("select to_regclass('public.sprint1_seed_records')::text")
            )
    finally:
        await engine.dispose()

    assert table_ref is not None, "Alembic migration must create sprint1_seed_records."


async def _seed_counts(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    async with session_factory() as session:
        result = await session.execute(
            select(Sprint1SeedRecord.entity_type, func.count())
            .group_by(Sprint1SeedRecord.entity_type)
            .order_by(Sprint1SeedRecord.entity_type)
        )
    return {str(entity_type): int(count) for entity_type, count in result.all()}


def _app_with_protected_context(settings: Settings) -> FastAPI:
    app = create_app(settings)

    @app.get("/_test/protected-context")
    async def protected_context(request: Request) -> dict[str, Any]:
        if getattr(request.state, "authenticated", False) is not True:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error_code": "unauthenticated",
                    "error_summary": "Authentication is required.",
                },
            )

        return {
            "tenant_id": request.state.tenant_id,
            "actor_id": request.state.actor_id,
            "principal_id": request.state.principal_id,
            "authenticated": request.state.authenticated,
        }

    return app


@pytest_asyncio.fixture
async def seeded_database() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    settings = _integration_settings()
    await _assert_database_available(settings)
    await asyncio.to_thread(_run_alembic_upgrade, settings.database_url)
    await _assert_seed_table_migrated(settings)

    engine = create_engine(settings.database_url)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        async with session_factory.begin() as session:
            await seed_initial(session)
        yield session_factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def full_stack_client(
    seeded_database: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    counts = await _seed_counts(seeded_database)
    assert counts == {
        "project": 1,
        "tenant": 1,
        "user": 1,
    }

    settings = _integration_settings()
    monkeypatch.setenv(
        "TASKMANAGEDAI_DEV_LOGIN_TOKEN",
        os.environ.get("TASKMANAGEDAI_DEV_LOGIN_TOKEN", _TEST_DEV_LOGIN_TOKEN),
    )

    app = _app_with_protected_context(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_healthz_returns_api_liveness(full_stack_client: AsyncClient) -> None:
    response = await full_stack_client.get("/healthz", headers={"x-request-id": "e2e-health"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "e2e-health"
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
        "service": "api",
    }


@pytest.mark.asyncio
async def test_readyz_reports_dependency_state(full_stack_client: AsyncClient) -> None:
    response = await full_stack_client.get("/readyz", headers={"x-request-id": "e2e-ready"})
    payload = response.json()

    assert response.headers["x-request-id"] == "e2e-ready"
    assert set(payload["dependencies"]) == {"postgres", "redis"}

    if response.status_code == 200:
        assert payload == {
            "status": "ready",
            "version": "0.1.0",
            "service": "api",
            "dependencies": {
                "postgres": {"status": "ok"},
                "redis": {"status": "ok"},
            },
        }
    else:
        assert response.status_code == 503
        assert payload["status"] == "not_ready"
        assert payload["version"] == "0.1.0"
        assert payload["service"] == "api"
        assert any(
            dependency["status"] == "error"
            for dependency in payload["dependencies"].values()
        )


@pytest.mark.asyncio
async def test_dev_login_cookie_binds_human_default_actor(
    full_stack_client: AsyncClient,
) -> None:
    login_response = await full_stack_client.post(
        "/auth/dev-login",
        json={"token": os.environ.get("TASKMANAGEDAI_DEV_LOGIN_TOKEN", _TEST_DEV_LOGIN_TOKEN)},
        headers={"x-request-id": "e2e-dev-login"},
    )
    cookie_value = login_response.cookies.get(DEV_SESSION_COOKIE_NAME)
    assert login_response.status_code == 200
    assert login_response.headers["x-request-id"] == "e2e-dev-login"
    assert login_response.json() == {
        "status": "ok",
        "actor_id": "human:default",
        "principal_type": "session",
    }
    assert cookie_value is not None
    assert cookie_value.count(".") == 1

    context_response = await full_stack_client.get(
        "/_test/protected-context",
        cookies={DEV_SESSION_COOKIE_NAME: cookie_value},
    )

    assert context_response.status_code == 200
    assert context_response.json() == {
        "tenant_id": 1,
        "actor_id": "human:default",
        "principal_id": "session",
        "authenticated": True,
    }

