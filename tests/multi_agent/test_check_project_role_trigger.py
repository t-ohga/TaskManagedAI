"""SP-013 batch 0d contract test: check_project_role_link trigger function.

migration 0022_multi_agent_foundation_c で追加された PL/pgSQL function + trigger
の DB-level defense を verify (PE-F-012 mitigation)。

検証:
- role_scope='project' で project_agent_roles に row なし → INSERT reject
- role_scope='global' で standard_role_ids_mirror に role_id なし → INSERT reject
- 正常 case (role_id NULL / standard role / project role) は accept

DB 接続必要: TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container 起動時のみ実行。
"""

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
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)

ACTOR_ID = UUID("00000000-0000-4000-8000-0000000bb001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-0000000bb002")
PROJECT_ID = UUID("00000000-0000-4000-8000-0000000bb003")
AGENT_RUN_ID = UUID("00000000-0000-4000-8000-0000000bb010")
PROJECT_AGENT_ROLE_ID = UUID("00000000-0000-4000-8000-0000000bb020")


def _integration_settings() -> Settings:
    database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL)
    redis_url = os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL)
    return Settings(
        database_url=database_url,
        redis_url=redis_url,
        dev_login_cookie_secret="test-cookie-secret-trigger-defense",
    )


def _run_alembic_upgrade(database_url: str) -> None:
    previous_database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        command.upgrade(Config(str(_REPO_ROOT / "alembic.ini")), "head")
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
            raise AssertionError("trigger test requires PostgreSQL.") from exc
        pytest.skip("Set TASKMANAGEDAI_RUN_DB_TESTS=1 with test PostgreSQL running.")
    finally:
        await engine.dispose()


async def _reset_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate audit_events, agent_run_events, artifacts, agent_runs,
              project_agent_roles, projects, workspaces, actors, tenants
            restart identity cascade
            """
        )
    )


async def _insert_fixtures(session: AsyncSession) -> None:
    await session.execute(
        text(
            "insert into tenants (id, name, metadata) "
            "values (1, 'tenant-one', '{\"rls_ready\": true}'::jsonb)"
        )
    )
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values (:actor_id, 1, 'human', 'human:trigger-test', 'Trigger Actor',
              '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'workspace', 'workspace', :actor_id,
              '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (:project_id, 1, :workspace_id, 'project-trigger', 'project-trigger',
              'active', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"project_id": PROJECT_ID, "workspace_id": WORKSPACE_ID},
    )
    # project_agent_roles に 1 custom role 投入
    await session.execute(
        text(
            """
            insert into project_agent_roles
              (id, tenant_id, project_id, role_id, display_name, description,
               created_by_actor_id)
            values (:role_pk_id, 1, :project_id, 'my_custom_role',
                    'My Custom Role', 'Custom role for trigger test', :actor_id)
            """
        ),
        {
            "role_pk_id": PROJECT_AGENT_ROLE_ID,
            "project_id": PROJECT_ID,
            "actor_id": ACTOR_ID,
        },
    )
    await session.commit()


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


@pytest.mark.asyncio
async def test_agent_run_insert_with_null_role_ok(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """role_id / role_scope 両方 NULL は trigger 通過 (既存 agent_runs flow 互換)."""
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        await session.execute(
            text(
                """
                insert into agent_runs (id, tenant_id, project_id, status)
                values (:run_id, 1, :project_id, 'queued')
                """
            ),
            {"run_id": AGENT_RUN_ID, "project_id": PROJECT_ID},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_agent_run_insert_with_global_standard_role_ok(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """role_scope='global' + standard role (e.g., implementer) は accept."""
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        await session.execute(
            text(
                """
                insert into agent_runs (id, tenant_id, project_id, status,
                  role_id, role_scope)
                values (:run_id, 1, :project_id, 'queued',
                  'implementer', 'global')
                """
            ),
            {"run_id": AGENT_RUN_ID, "project_id": PROJECT_ID},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_agent_run_insert_with_global_non_standard_role_rejects(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """role_scope='global' + non-standard role (e.g., my_custom_role) は reject."""
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        with pytest.raises(DBAPIError, match="standard_role_ids_mirror|check_project_role_link"):
            await session.execute(
                text(
                    """
                    insert into agent_runs (id, tenant_id, project_id, status,
                      role_id, role_scope)
                    values (:run_id, 1, :project_id, 'queued',
                      'my_custom_role', 'global')
                    """
                ),
                {"run_id": AGENT_RUN_ID, "project_id": PROJECT_ID},
            )
            await session.commit()


@pytest.mark.asyncio
async def test_agent_run_insert_with_project_existing_custom_role_ok(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """role_scope='project' + project_agent_roles に存在する custom role は accept."""
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        await session.execute(
            text(
                """
                insert into agent_runs (id, tenant_id, project_id, status,
                  role_id, role_scope)
                values (:run_id, 1, :project_id, 'queued',
                  'my_custom_role', 'project')
                """
            ),
            {"run_id": AGENT_RUN_ID, "project_id": PROJECT_ID},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_agent_run_insert_with_project_nonexistent_role_rejects(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """role_scope='project' + project_agent_roles に存在しない role は reject (PE-F-012)."""
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        with pytest.raises(DBAPIError, match="project_agent_roles|check_project_role_link"):
            await session.execute(
                text(
                    """
                    insert into agent_runs (id, tenant_id, project_id, status,
                      role_id, role_scope)
                    values (:run_id, 1, :project_id, 'queued',
                      'nonexistent_role', 'project')
                    """
                ),
                {"run_id": AGENT_RUN_ID, "project_id": PROJECT_ID},
            )
            await session.commit()
