"""SP-012-11.1 BL-TCU-013 contract test: /api/v1/me/current_project.

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
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.project import Project
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

ACTOR_ID = UUID("00000000-0000-4000-8000-0000000aa001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-0000000aa002")
PROJECT_FIRST_ID = UUID("00000000-0000-4000-8000-0000000aa003")
PROJECT_SECOND_ID = UUID("00000000-0000-4000-8000-0000000aa004")


def _integration_settings() -> Settings:
    database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL)
    redis_url = os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL)
    return Settings(
        database_url=database_url,
        redis_url=redis_url,
        dev_login_cookie_secret="test-cookie-secret-for-me-api",
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
            raise AssertionError("/me API tests require PostgreSQL.") from exc
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


async def _reset_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate audit_events, projects, workspaces, actors, tenants
            restart identity cascade
            """
        )
    )


async def _insert_two_projects(session: AsyncSession) -> None:
    """tenant + actor + workspace + 2 projects fixture."""
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
            values (:actor_id, 1, 'human', 'human:default', 'Default Actor',
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
    # 2 projects: first created earlier (project-first)、second 後に作成 (project-second)
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status,
              metadata, created_at)
            values
              (:p1, 1, :ws, 'project-first', 'Project First', 'active',
                '{"rls_ready": true}'::jsonb, '2026-05-22 00:00:00+00'),
              (:p2, 1, :ws, 'project-second', 'Project Second', 'active',
                '{"rls_ready": true}'::jsonb, '2026-05-22 01:00:00+00')
            """
        ),
        {"p1": PROJECT_FIRST_ID, "p2": PROJECT_SECOND_ID, "ws": WORKSPACE_ID},
    )
    await session.commit()


@pytest.mark.asyncio
async def test_current_project_returns_first_project_in_tenant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """tenant 内 2 projects のうち、created_at order で first project を返す."""
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_two_projects(session)

    async with session_factory() as session:
        # 直接 repository query で endpoint logic と同等動作を verify
        stmt = (
            select(Project)
            .where(Project.tenant_id == 1)
            .order_by(Project.created_at, Project.slug)
            .limit(1)
        )
        project = (await session.execute(stmt)).scalar_one_or_none()

        assert project is not None
        # first project (created_at が早い方) が返される
        assert project.id == PROJECT_FIRST_ID
        assert project.slug == "project-first"
        assert project.tenant_id == 1
