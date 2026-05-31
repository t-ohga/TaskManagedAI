"""migration 0039 (ADR-00037 Q-3) round-trip test.

soft-delete columns (deleted_at / deleted_batch_id / deleted_by_actor_id) + partial index の
upgrade/downgrade を検証する。特に **downgrade fail-closed** (Codex plan R3/R4/R5):

- soft-deleted 行が無ければ downgrade で column を drop (clean round-trip)。
- soft-deleted 行が 1 件でもあれば downgrade は ACCESS EXCLUSIVE lock 後 count → RuntimeError で中断し、
  silent resurrection (削除済み ticket の復活) を起こさない。column は残る。

DB 接続必要: TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container 起動時のみ実行。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

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

_DOWN_REVISION = "0038_m3_project_description"
_SOFT_DELETE_COLUMNS = {"deleted_at", "deleted_batch_id", "deleted_by_actor_id"}

ACTOR_ID = UUID("00000000-0000-4000-8000-0000000ee001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-0000000ee002")
PROJECT_ID = UUID("00000000-0000-4000-8000-0000000ee003")
TICKET_ID = UUID("00000000-0000-4000-8000-0000000ee004")

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-0039-migration",
    )


def _run_alembic(
    database_url: str, direction: Literal["upgrade", "downgrade"], target: str
) -> None:
    previous = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        config = Config(str(_REPO_ROOT / "alembic.ini"))
        if direction == "upgrade":
            command.upgrade(config, target)
        else:
            command.downgrade(config, target)
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
        if os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") == "1":
            raise AssertionError("0039 migration tests require PostgreSQL.") from exc
        pytest.skip("Set TASKMANAGEDAI_RUN_DB_TESTS=1 with test PostgreSQL running.")
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    settings = _integration_settings()
    await _assert_database_available(settings)
    await asyncio.to_thread(_run_alembic, settings.database_url, "upgrade", "head")
    engine = create_engine(settings.database_url)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        # 他 test に影響しないよう必ず head へ戻す。
        await asyncio.to_thread(_run_alembic, settings.database_url, "upgrade", "head")
        await engine.dispose()


async def _ticket_columns(session: AsyncSession) -> set[str]:
    rows = await session.execute(
        text(
            "select column_name from information_schema.columns where table_name = 'tickets'"
        )
    )
    return {r[0] for r in rows}


async def _ticket_index_defs(session: AsyncSession) -> dict[str, str]:
    rows = await session.execute(
        text("select indexname, indexdef from pg_indexes where tablename = 'tickets'")
    )
    return {r[0]: r[1] for r in rows}


async def _seed_soft_deleted_ticket(session: AsyncSession) -> None:
    """FK chain (tenant/actor/workspace/project) + soft-deleted ticket 1 件を直接 INSERT。"""
    await session.execute(
        text(
            "insert into tenants (id, name, metadata) values "
            "(1, 'tenant-one', '{\"rls_ready\": true}'::jsonb) on conflict (id) do nothing"
        )
    )
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values (:a, 1, 'human', 'human:default', 'Owner', '{"rls_ready": true}'::jsonb)
            on conflict (id) do nothing
            """
        ),
        {"a": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:w, 1, 'ws39', 'ws39', :a, '{"rls_ready": true}'::jsonb)
            on conflict (id) do nothing
            """
        ),
        {"w": WORKSPACE_ID, "a": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (:p, 1, :w, 'proj39', 'proj39', 'active', '{"rls_ready": true}'::jsonb)
            on conflict (id) do nothing
            """
        ),
        {"p": PROJECT_ID, "w": WORKSPACE_ID},
    )
    await session.execute(
        text(
            """
            insert into tickets (id, tenant_id, project_id, slug, title, status,
              created_by_actor_id, deleted_at, deleted_batch_id, deleted_by_actor_id, metadata)
            values (:t, 1, :p, 'soft-deleted-1', 'Soft Deleted', 'open', :a,
              now(), :batch, :a, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"t": TICKET_ID, "p": PROJECT_ID, "a": ACTOR_ID, "batch": uuid4()},
    )
    await session.commit()


async def _truncate(session: AsyncSession) -> None:
    await session.execute(
        text(
            "truncate tickets, projects, workspaces, actors, tenants restart identity cascade"
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_0039_adds_soft_delete_columns_and_partial_indexes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        columns = await _ticket_columns(session)
        assert _SOFT_DELETE_COLUMNS <= columns
        indexes = await _ticket_index_defs(session)
        # active scope partial index (deleted_at IS NULL)
        assert "tickets_idx_active" in indexes
        assert "deleted_at IS NULL" in indexes["tickets_idx_active"]
        # batch restore partial index (deleted_at IS NOT NULL)
        assert "tickets_idx_deleted_batch" in indexes
        assert "deleted_at IS NOT NULL" in indexes["tickets_idx_deleted_batch"]


@pytest.mark.asyncio
async def test_0039_clean_downgrade_drops_columns_then_restores(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """soft-deleted 行が無ければ downgrade で column を drop、再 upgrade で復元 (clean round-trip)。"""
    settings = _integration_settings()
    async with session_factory() as session:
        await _truncate(session)  # soft-deleted 行が無い状態を保証

    await asyncio.to_thread(_run_alembic, settings.database_url, "downgrade", _DOWN_REVISION)
    # downgrade 直後の状態を確認するため fixture (再 upgrade head する) を介さず直接 engine を張る
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_name = 'tickets'"
                )
            )
            columns = {r[0] for r in rows}
        assert _SOFT_DELETE_COLUMNS.isdisjoint(columns)  # 全て drop された
    finally:
        await engine.dispose()

    # 再 upgrade で復元
    await asyncio.to_thread(_run_alembic, settings.database_url, "upgrade", "head")
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_name = 'tickets'"
                )
            )
            columns = {r[0] for r in rows}
        assert _SOFT_DELETE_COLUMNS <= columns
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_0039_downgrade_fails_closed_when_soft_deleted_rows_exist(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """soft-deleted 行があると downgrade は中断 (RuntimeError) し column を drop しない。

    silent resurrection (削除済み ticket が全 read path に復活) を防ぐ fail-closed 不変条件。
    """
    settings = _integration_settings()
    async with session_factory() as session:
        await _truncate(session)
        await _seed_soft_deleted_ticket(session)

    # downgrade は migration 内の RuntimeError で失敗する (lock-before-count → count>0 → raise)。
    with pytest.raises(Exception) as exc_info:
        await asyncio.to_thread(
            _run_alembic, settings.database_url, "downgrade", _DOWN_REVISION
        )
    # raise の起点は migration の RuntimeError (Refusing to downgrade ...)
    assert "Refusing to downgrade" in str(exc_info.value) or isinstance(
        exc_info.value, RuntimeError
    )

    # fail-closed: column は drop されず残っている (silent resurrection なし)
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_name = 'tickets'"
                )
            )
            columns = {r[0] for r in rows}
            # soft-deleted 行も残っている (drop されていない)
            remaining = await conn.execute(
                text("select count(*) from tickets where deleted_at is not null")
            )
            deleted_count = remaining.scalar_one()
        assert _SOFT_DELETE_COLUMNS <= columns
        assert deleted_count == 1
    finally:
        await engine.dispose()

    # cleanup (次 test 汚染防止)。fixture finally が upgrade head するが、ここでも明示 truncate。
    cleanup_engine = create_engine(settings.database_url)
    try:
        async with cleanup_engine.begin() as conn:
            await conn.execute(
                text(
                    "truncate tickets, projects, workspaces, actors, tenants "
                    "restart identity cascade"
                )
            )
    finally:
        await cleanup_engine.dispose()
