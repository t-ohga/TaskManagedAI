from __future__ import annotations

import asyncio
import inspect
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.session import create_engine
from backend.app.repositories.project import ProjectRepository

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000501")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000502")
OWNER_ACTOR_ID = UUID("00000000-0000-4000-8000-000000000503")

PROJECT_REPOSITORY_INHERITED_CONTEXT_METHODS = frozenset(
    {"create", "delete", "get", "list", "update"}
)
PROJECT_REPOSITORY_CUSTOM_CONTEXT_METHODS = frozenset(
    {"get_in_workspace", "workspace_exists"}
)


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-app-role-tests",
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
            raise AssertionError("app_role tests require a reachable test database.") from exc
        pytest.skip("Set TASKMANAGEDAI_RUN_DB_TESTS=1 with test PostgreSQL running.")
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    settings = _integration_settings()
    await _assert_database_available(settings)
    await asyncio.to_thread(_run_alembic_upgrade, settings.database_url)

    engine = create_engine(settings.database_url)
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        yield factory
    finally:
        await engine.dispose()


async def _reset_core_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate repositories, projects, workspaces, principals, actors, tenants
            restart identity cascade
            """
        )
    )


async def _insert_project_fixture(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (1, 'tenant-one', '{"rls_ready": true}'::jsonb)
            """
        )
    )
    await session.execute(
        text(
            """
            insert into actors (
              id,
              tenant_id,
              actor_type,
              actor_id,
              display_name,
              auth_context_hash,
              metadata
            )
            values (
              :owner_actor_id,
              1,
              'human',
              'human:default',
              'Tenant One Owner',
              null,
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {"owner_actor_id": OWNER_ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (
              id,
              tenant_id,
              slug,
              name,
              owner_actor_id,
              metadata
            )
            values (
              :workspace_id,
              1,
              'workspace-one',
              'workspace-one',
              :owner_actor_id,
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {"workspace_id": WORKSPACE_ID, "owner_actor_id": OWNER_ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (
              id,
              tenant_id,
              workspace_id,
              slug,
              name,
              status,
              policy_profile,
              metadata
            )
            values (
              :project_id,
              1,
              :workspace_id,
              'project-one',
              'project-one',
              'active',
              'default',
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {"project_id": PROJECT_ID, "workspace_id": WORKSPACE_ID},
    )


def test_project_repository_custom_context_methods_are_explicitly_covered() -> None:
    public_async_methods = {
        name
        for name, _ in inspect.getmembers(
            ProjectRepository,
            predicate=inspect.iscoroutinefunction,
        )
        if not name.startswith("_")
    }

    assert (
        public_async_methods - PROJECT_REPOSITORY_INHERITED_CONTEXT_METHODS
        == PROJECT_REPOSITORY_CUSTOM_CONTEXT_METHODS
    )


@pytest.mark.asyncio
async def test_set_and_get_tenant_context_uses_postgresql_session_variable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await set_tenant_context(session, 42)
        tenant_id = await get_tenant_context(session)

    assert tenant_id == 42


@pytest.mark.asyncio
async def test_assert_tenant_context_rejects_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await set_tenant_context(session, 1)

        with pytest.raises(ValueError, match="tenant context mismatch"):
            await assert_tenant_context(session, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "kwargs"),
    [
        ("get", {"tenant_id": 1, "id": PROJECT_ID}),
        ("list", {"tenant_id": 1}),
        (
            "update",
            {
                "tenant_id": 1,
                "id": PROJECT_ID,
                "payload": {"name": "blocked-cross-tenant-update"},
            },
        ),
        ("delete", {"tenant_id": 1, "id": PROJECT_ID}),
    ],
)
async def test_base_repository_methods_reject_cross_tenant_context(
    session_factory: async_sessionmaker[AsyncSession],
    method_name: str,
    kwargs: dict[str, Any],
) -> None:
    async with session_factory.begin() as session:
        await _reset_core_tables(session)
        await _insert_project_fixture(session)
        await set_tenant_context(session, 2)

        repository = ProjectRepository(session)
        method = getattr(repository, method_name)
        with pytest.raises(ValueError, match="tenant context mismatch"):
            await method(**kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "kwargs"),
    [
        (
            "get_in_workspace",
            {
                "tenant_id": 1,
                "workspace_id": WORKSPACE_ID,
                "project_id": PROJECT_ID,
            },
        ),
        (
            "workspace_exists",
            {
                "tenant_id": 1,
                "workspace_id": WORKSPACE_ID,
            },
        ),
    ],
)
async def test_project_repository_custom_methods_reject_cross_tenant_context(
    session_factory: async_sessionmaker[AsyncSession],
    method_name: str,
    kwargs: dict[str, Any],
) -> None:
    async with session_factory.begin() as session:
        await _reset_core_tables(session)
        await _insert_project_fixture(session)
        await set_tenant_context(session, 2)

        repository = ProjectRepository(session)
        method = getattr(repository, method_name)
        with pytest.raises(ValueError, match="tenant context mismatch"):
            await method(**kwargs)

