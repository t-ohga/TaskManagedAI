"""SP-013 batch 0c contract test: agent_runs role/lease/progress columns.

migration 0021_multi_agent_foundation_b で追加された 8 columns + 2 CHECK +
index の構造を verify。

DB 接続必要: TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container 起動時のみ実行。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
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


def _integration_settings() -> Settings:
    database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL)
    redis_url = os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL)
    return Settings(
        database_url=database_url,
        redis_url=redis_url,
        dev_login_cookie_secret="test-cookie-secret-agent-runs-role-columns",
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
            raise AssertionError("agent_runs role columns test requires PostgreSQL.") from exc
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


EXPECTED_NEW_COLUMNS = frozenset(
    {
        "role_id",
        "role_scope",
        "orchestrator_lease_token",
        "orchestrator_lease_expires_at",
        "lease_renewed_at",
        "orchestrator_kill_at",
        "last_progress_at",
        "progress_seq",
    }
)


@pytest.mark.asyncio
async def test_agent_runs_has_all_new_columns(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """migration 0021 で追加された 8 columns 全件存在."""
    async with session_factory() as session:
        result = await session.execute(
            text(
                """
                select column_name from information_schema.columns
                 where table_schema = 'public'
                   and table_name = 'agent_runs'
                """
            )
        )
        columns = frozenset(row[0] for row in result.all())
        missing = EXPECTED_NEW_COLUMNS - columns
        assert not missing, f"agent_runs missing columns: {sorted(missing)}"


@pytest.mark.asyncio
async def test_agent_runs_role_consistency_check_constraint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """agent_runs_role_consistency CHECK constraint 存在 verify."""
    async with session_factory() as session:
        result = await session.execute(
            text(
                """
                select conname from pg_constraint
                 where conrelid = 'agent_runs'::regclass
                   and conname = 'agent_runs_role_consistency'
                   and contype = 'c'
                """
            )
        )
        assert result.scalar() == "agent_runs_role_consistency"


@pytest.mark.asyncio
async def test_agent_runs_ck_role_scope_check_constraint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """agent_runs_ck_role_scope CHECK constraint 存在 verify."""
    async with session_factory() as session:
        result = await session.execute(
            text(
                """
                select conname from pg_constraint
                 where conrelid = 'agent_runs'::regclass
                   and conname = 'agent_runs_ck_role_scope'
                   and contype = 'c'
                """
            )
        )
        assert result.scalar() == "agent_runs_ck_role_scope"


@pytest.mark.asyncio
async def test_agent_runs_idx_lease_expires_exists(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """agent_runs_idx_lease_expires partial index 存在 verify."""
    async with session_factory() as session:
        result = await session.execute(
            text(
                """
                select indexname from pg_indexes
                 where schemaname = 'public'
                   and tablename = 'agent_runs'
                   and indexname = 'agent_runs_idx_lease_expires'
                """
            )
        )
        assert result.scalar() == "agent_runs_idx_lease_expires"
