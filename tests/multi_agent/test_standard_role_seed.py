"""SP-013 batch 0b: standard_role_ids_mirror seed contract test.

migration 0020_multi_agent_foundation_a で投入される 10 standard role seed が
domain layer (taxonomy.py) STANDARD_ROLE_IDS と完全一致することを verify。
5+ source 整合 (cross-source-enum-integrity §1 pattern) の DB layer (source 5)
を機械検査。

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
from backend.app.domain.agent_role.taxonomy import STANDARD_ROLE_IDS

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
        dev_login_cookie_secret="test-cookie-secret-for-standard-role-seed",
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
            raise AssertionError("standard role seed test requires PostgreSQL.") from exc
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


@pytest.mark.asyncio
async def test_standard_role_ids_mirror_seed_matches_taxonomy(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """DB seed = STANDARD_ROLE_IDS frozenset (5+ source 整合の DB layer verify)."""
    async with session_factory() as session:
        result = await session.execute(
            text("select role_id from standard_role_ids_mirror order by role_id")
        )
        db_role_ids = frozenset(row[0] for row in result.all())

        assert db_role_ids == STANDARD_ROLE_IDS, (
            f"DB seed drift: db={sorted(db_role_ids)}, "
            f"taxonomy={sorted(STANDARD_ROLE_IDS)}"
        )


@pytest.mark.asyncio
async def test_standard_role_ids_mirror_count_is_exactly_10(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """DB seed が 10 役職 (drift 検出)."""
    async with session_factory() as session:
        result = await session.execute(
            text("select count(*) from standard_role_ids_mirror")
        )
        count = result.scalar()
        assert count == 10, f"standard_role_ids_mirror seed count != 10: {count}"


@pytest.mark.asyncio
async def test_project_agent_roles_table_exists(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """project_agent_roles table が migration で作成済."""
    async with session_factory() as session:
        result = await session.execute(
            text(
                """
                select table_name from information_schema.tables
                 where table_schema = 'public'
                   and table_name = 'project_agent_roles'
                """
            )
        )
        assert result.scalar() == "project_agent_roles"
