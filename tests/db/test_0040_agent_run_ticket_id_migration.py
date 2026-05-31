"""migration 0040 (ADR-00037 R12/R13/R14) round-trip + fail-closed downgrade test.

server-owned ``agent_runs.ticket_id`` column + 複合 FK
(tenant_id, project_id, ticket_id) -> tickets(tenant_id, project_id, id) + partial index の
upgrade/downgrade を検証する。特に **downgrade fail-closed** (Codex adversarial R14 #2):

- agent_runs.ticket_id が canonical run_queued event payload と lossless 一致するなら downgrade で
  column を drop (clean round-trip)。再 upgrade で backfill が同値を復元する。
- column が event payload と乖離する run が 1 件でもあれば downgrade は ACCESS EXCLUSIVE lock 後 count →
  RuntimeError で中断し、silent resurrection (再 upgrade 時に ticket-less 化し soft-deleted ticket bound
  run が集計復活) を起こさない。column は残る。

DB 接続必要: TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container 起動時のみ実行。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal
from uuid import UUID

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

_DOWN_REVISION = "0039_ticket_soft_delete"

ACTOR_ID = UUID("00000000-0000-4000-8000-0000000ff001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-0000000ff002")
PROJECT_ID = UUID("00000000-0000-4000-8000-0000000ff003")
TICKET_ID = UUID("00000000-0000-4000-8000-0000000ff004")
RUN_ID = UUID("00000000-0000-4000-8000-0000000ff005")

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
        dev_login_cookie_secret="test-cookie-secret-for-0040-migration",
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
            raise AssertionError("0040 migration tests require PostgreSQL.") from exc
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


async def _agent_run_columns(session: AsyncSession) -> set[str]:
    rows = await session.execute(
        text(
            "select column_name from information_schema.columns "
            "where table_name = 'agent_runs'"
        )
    )
    return {r[0] for r in rows}


async def _seed_run(session: AsyncSession, *, event_ticket_id: str | None) -> None:
    """FK chain + ticket + agent_run(ticket_id=TICKET_ID) + run_queued event を INSERT。

    ``event_ticket_id`` で run_queued event payload の ticket_id を制御する:
    - ``str(TICKET_ID)``: column と lossless 一致 (downgrade 可)。
    - 別 UUID / None: column と乖離 (downgrade fail-closed)。
    """
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
            values (:w, 1, 'ws40', 'ws40', :a, '{"rls_ready": true}'::jsonb)
            on conflict (id) do nothing
            """
        ),
        {"w": WORKSPACE_ID, "a": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (:p, 1, :w, 'proj40', 'proj40', 'active', '{"rls_ready": true}'::jsonb)
            on conflict (id) do nothing
            """
        ),
        {"p": PROJECT_ID, "w": WORKSPACE_ID},
    )
    await session.execute(
        text(
            """
            insert into tickets (id, tenant_id, project_id, slug, title, status,
              created_by_actor_id, metadata)
            values (:t, 1, :p, 'run-bound-1', 'Run Bound', 'open', :a, '{"rls_ready": true}'::jsonb)
            on conflict (id) do nothing
            """
        ),
        {"t": TICKET_ID, "p": PROJECT_ID, "a": ACTOR_ID},
    )
    await session.execute(
        text(
            "insert into agent_runs (id, tenant_id, project_id, ticket_id, status) "
            "values (:r, 1, :p, :t, 'queued')"
        ),
        {"r": RUN_ID, "p": PROJECT_ID, "t": TICKET_ID},
    )
    payload = '{"purpose": "work"}'
    if event_ticket_id is not None:
        payload = '{"purpose": "work", "ticket_id": "' + event_ticket_id + '"}'
    await session.execute(
        text(
            """
            insert into agent_run_events (tenant_id, run_id, seq_no, event_type,
              event_payload, actor_id)
            values (1, :r, 1, 'run_queued', cast(:payload as jsonb), :a)
            """
        ),
        {"r": RUN_ID, "payload": payload, "a": ACTOR_ID},
    )
    await session.commit()


async def _truncate(session: AsyncSession) -> None:
    await session.execute(
        text(
            "truncate agent_run_events, agent_runs, tickets, projects, workspaces, actors, "
            "tenants restart identity cascade"
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_0040_adds_ticket_id_column_fk_and_partial_index(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        columns = await _agent_run_columns(session)
        assert "ticket_id" in columns
        # 複合 FK が存在する
        fk_rows = await session.execute(
            text(
                "select conname from pg_constraint "
                "where conrelid = 'agent_runs'::regclass and conname = 'agent_runs_ticket_fkey'"
            )
        )
        assert fk_rows.scalar_one_or_none() == "agent_runs_ticket_fkey"
        # partial index (ticket_id IS NOT NULL)
        idx_rows = await session.execute(
            text(
                "select indexdef from pg_indexes "
                "where tablename = 'agent_runs' and indexname = 'agent_runs_idx_tenant_ticket'"
            )
        )
        idxdef = idx_rows.scalar_one_or_none()
        assert idxdef is not None
        assert "ticket_id IS NOT NULL" in idxdef


@pytest.mark.asyncio
async def test_0040_clean_downgrade_when_column_matches_event_payload(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """column == canonical run_queued event payload なら downgrade で drop、再 upgrade で復元。"""
    settings = _integration_settings()
    async with session_factory() as session:
        await _truncate(session)
        await _seed_run(session, event_ticket_id=str(TICKET_ID))  # lossless 一致

    await asyncio.to_thread(_run_alembic, settings.database_url, "downgrade", _DOWN_REVISION)
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_name = 'agent_runs'"
                )
            )
            columns = {r[0] for r in rows}
        assert "ticket_id" not in columns  # drop された
    finally:
        await engine.dispose()

    # 再 upgrade で backfill が event payload (== 旧 column 値) から復元する
    await asyncio.to_thread(_run_alembic, settings.database_url, "upgrade", "head")
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            restored = await conn.execute(
                text("select ticket_id from agent_runs where id = :r"), {"r": RUN_ID}
            )
            assert restored.scalar_one() == TICKET_ID
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_0040_downgrade_fails_closed_when_column_diverges_from_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """column が event payload と乖離 (payload 欠落) する run があれば downgrade は中断 (fail-closed)。

    無条件 drop すると再 upgrade で backfill が event payload しか見ないため ticket-less 化し、
    soft-deleted ticket bound run が集計復活する silent resurrection になる。それを防ぐ不変条件。
    """
    settings = _integration_settings()
    async with session_factory() as session:
        await _truncate(session)
        # column は TICKET_ID だが event payload に ticket_id 無し (乖離 = re-derive 不能)
        await _seed_run(session, event_ticket_id=None)

    with pytest.raises(Exception) as exc_info:
        await asyncio.to_thread(
            _run_alembic, settings.database_url, "downgrade", _DOWN_REVISION
        )
    assert "Refusing to downgrade 0040" in str(exc_info.value) or isinstance(
        exc_info.value, RuntimeError
    )

    # fail-closed: column は残り、binding も保持される (silent resurrection なし)
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_name = 'agent_runs'"
                )
            )
            columns = {r[0] for r in rows}
            bound = await conn.execute(
                text("select ticket_id from agent_runs where id = :r"), {"r": RUN_ID}
            )
        assert "ticket_id" in columns
        assert bound.scalar_one() == TICKET_ID
    finally:
        await engine.dispose()

    # cleanup (次 test 汚染防止)
    cleanup_engine = create_engine(settings.database_url)
    try:
        async with cleanup_engine.begin() as conn:
            await conn.execute(
                text(
                    "truncate agent_run_events, agent_runs, tickets, projects, workspaces, "
                    "actors, tenants restart identity cascade"
                )
            )
    finally:
        await cleanup_engine.dispose()


@pytest.mark.asyncio
async def test_0040_upgrade_fails_closed_on_unresolvable_binding(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """R21 (Codex adversarial): upgrade も fail-closed。run_queued event が ticket binding を主張する
    (canonical payload の ticket_id が UUID 形式) のに同一 project ticket へ解決できない run があると、
    backfill は ticket_id=NULL のまま残し、active-scope guard が ticket-less (可視・進行可) と誤認して
    soft-delete を迂回する fail-open になる。そのような「binding 主張・復元不能」run が 1 件でもあれば
    upgrade を RuntimeError で中断し silent resurrection を防ぐ (payload に ticket_id 無しの genuinely
    ticket-less run は対象外)。
    """
    settings = _integration_settings()
    nonexistent_ticket = "00000000-0000-4000-8000-0000000ff0ee"
    async with session_factory() as session:
        await _truncate(session)
    # 0039 (ticket_id column 無し) へ downgrade し、復元不能 binding を主張する run を直接 seed。
    await asyncio.to_thread(_run_alembic, settings.database_url, "downgrade", _DOWN_REVISION)
    engine = create_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "insert into tenants (id, name, metadata) values "
                    "(1, 'tenant-one', '{\"rls_ready\": true}'::jsonb) on conflict (id) do nothing"
                )
            )
            await conn.execute(
                text(
                    "insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)"
                    " values (:a, 1, 'human', 'human:default', 'Owner', '{\"rls_ready\": true}'::jsonb)"
                    " on conflict (id) do nothing"
                ),
                {"a": ACTOR_ID},
            )
            await conn.execute(
                text(
                    "insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)"
                    " values (:w, 1, 'ws40u', 'ws40u', :a, '{\"rls_ready\": true}'::jsonb)"
                    " on conflict (id) do nothing"
                ),
                {"w": WORKSPACE_ID, "a": ACTOR_ID},
            )
            await conn.execute(
                text(
                    "insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)"
                    " values (:p, 1, :w, 'proj40u', 'proj40u', 'active', '{\"rls_ready\": true}'::jsonb)"
                    " on conflict (id) do nothing"
                ),
                {"p": PROJECT_ID, "w": WORKSPACE_ID},
            )
            # run は ticket_id column 無し (0039)。run_queued payload は実在しない ticket を主張する。
            await conn.execute(
                text(
                    "insert into agent_runs (id, tenant_id, project_id, status) "
                    "values (:r, 1, :p, 'queued')"
                ),
                {"r": RUN_ID, "p": PROJECT_ID},
            )
            await conn.execute(
                text(
                    "insert into agent_run_events (tenant_id, run_id, seq_no, event_type,"
                    " event_payload, actor_id) values (1, :r, 1, 'run_queued',"
                    " cast(:payload as jsonb), :a)"
                ),
                {
                    "r": RUN_ID,
                    "payload": '{"purpose": "work", "ticket_id": "' + nonexistent_ticket + '"}',
                    "a": ACTOR_ID,
                },
            )
    finally:
        await engine.dispose()

    # upgrade → backfill が解決できず NULL → postcheck が中断。
    with pytest.raises(Exception) as exc_info:
        await asyncio.to_thread(_run_alembic, settings.database_url, "upgrade", "head")
    assert "Refusing to complete 0040" in str(exc_info.value) or isinstance(
        exc_info.value, RuntimeError
    )

    # fail-closed: upgrade は roll back され ticket_id column は付かない。bad data を消して fixture
    # teardown の upgrade head が成功するようにする。
    cleanup_engine = create_engine(settings.database_url)
    try:
        async with cleanup_engine.begin() as conn:
            cols = await conn.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_name = 'agent_runs' and column_name = 'ticket_id'"
                )
            )
            assert cols.first() is None  # column は付いていない (rolled back)
            await conn.execute(
                text(
                    "truncate agent_run_events, agent_runs, tickets, projects, workspaces, "
                    "actors, tenants restart identity cascade"
                )
            )
    finally:
        await cleanup_engine.dispose()
