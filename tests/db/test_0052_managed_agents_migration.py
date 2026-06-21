"""SP-PHASE1 B2: migration 0052 (managed_agents + agent_runs.pre_stop_status) DB-gated test。

ADR-00048 §F/A-1/A-2/A-5 の registry schema を検証する:
- upgrade で managed_agents table + state CHECK + 複合 FK + pre_stop_status 列が作られる。
- downgrade で lossless に drop される (round-trip)。
- state CHECK が不正 state を reject する。
- tenant 複合 FK が cross-tenant / cross-project insert を reject する。
- registry service の lifecycle (register_spawning -> mark_running -> mark_terminal) + tenant scope。

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
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.services.superintendent.managed_agent_registry import (
    ManagedAgentRegistry,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

_DOWN_REVISION = "0051_phase1_event_type_39"

TENANT_ONE = 1
TENANT_TWO = 2
ACTOR_ID = UUID("00000000-0000-4000-8000-0000000a5201")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-0000000a5202")
PROJECT_A = UUID("00000000-0000-4000-8000-0000000a5203")
PROJECT_B = UUID("00000000-0000-4000-8000-0000000a5204")
RUN_ID = UUID("00000000-0000-4000-8000-0000000a5205")

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
        dev_login_cookie_secret="test-cookie-secret-for-0052-migration",
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
            raise AssertionError("0052 migration tests require PostgreSQL.") from exc
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
        await asyncio.to_thread(_run_alembic, settings.database_url, "upgrade", "head")
        await engine.dispose()


async def _seed_fk_chain(session: AsyncSession) -> None:
    """tenant 1+2 / actor / workspace / projects A(tenant1)/B(tenant2) / run(tenant1,projA) を seed。"""
    await session.execute(
        text(
            "insert into tenants (id, name, metadata) values "
            "(1, 'tenant-one', '{\"rls_ready\": true}'::jsonb),"
            "(2, 'tenant-two', '{\"rls_ready\": true}'::jsonb) on conflict (id) do nothing"
        )
    )
    await session.execute(
        text(
            "insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)"
            " values (:a, 1, 'human', 'human:default', 'Owner', '{\"rls_ready\": true}'::jsonb)"
            " on conflict (id) do nothing"
        ),
        {"a": ACTOR_ID},
    )
    await session.execute(
        text(
            "insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)"
            " values (:w, 1, 'ws52', 'ws52', :a, '{\"rls_ready\": true}'::jsonb)"
            " on conflict (id) do nothing"
        ),
        {"w": WORKSPACE_ID, "a": ACTOR_ID},
    )
    # project A は tenant 1。
    await session.execute(
        text(
            "insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)"
            " values (:p, 1, :w, 'projA52', 'projA52', 'active', '{\"rls_ready\": true}'::jsonb)"
            " on conflict (id) do nothing"
        ),
        {"p": PROJECT_A, "w": WORKSPACE_ID},
    )
    await session.execute(
        text(
            "insert into agent_runs (id, tenant_id, project_id, status) "
            "values (:r, 1, :p, 'queued')"
        ),
        {"r": RUN_ID, "p": PROJECT_A},
    )
    await session.commit()


async def _truncate(session: AsyncSession) -> None:
    await session.execute(
        text(
            "truncate managed_agents, agent_runs, projects, workspaces, actors, "
            "tenants restart identity cascade"
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_0052_creates_table_check_fk_and_pre_stop_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        # managed_agents table 存在
        tbl = await session.execute(
            text(
                "select table_name from information_schema.tables "
                "where table_name = 'managed_agents'"
            )
        )
        assert tbl.scalar_one_or_none() == "managed_agents"
        # state CHECK 存在
        ck = await session.execute(
            text(
                "select conname from pg_constraint "
                "where conrelid = 'managed_agents'::regclass "
                "and conname = 'managed_agents_ck_state'"
            )
        )
        assert ck.scalar_one_or_none() == "managed_agents_ck_state"
        # 複合 FK (tenant, project) + (tenant, project, agent_run) 存在
        fks = await session.execute(
            text(
                "select conname from pg_constraint "
                "where conrelid = 'managed_agents'::regclass and contype = 'f'"
            )
        )
        fk_names = {r[0] for r in fks}
        assert "managed_agents_project_fkey" in fk_names
        assert "managed_agents_agent_run_fkey" in fk_names
        # agent_runs.pre_stop_status 列
        cols = await session.execute(
            text(
                "select column_name from information_schema.columns "
                "where table_name = 'agent_runs' and column_name = 'pre_stop_status'"
            )
        )
        assert cols.scalar_one_or_none() == "pre_stop_status"


@pytest.mark.asyncio
async def test_0052_downgrade_then_upgrade_round_trip(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = _integration_settings()
    await asyncio.to_thread(_run_alembic, settings.database_url, "downgrade", _DOWN_REVISION)
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            tbl = await conn.execute(
                text(
                    "select table_name from information_schema.tables "
                    "where table_name = 'managed_agents'"
                )
            )
            assert tbl.scalar_one_or_none() is None  # table dropped
            cols = await conn.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_name = 'agent_runs' and column_name = 'pre_stop_status'"
                )
            )
            assert cols.scalar_one_or_none() is None  # column dropped
    finally:
        await engine.dispose()

    # 再 upgrade で復元 (lossless round-trip)。
    await asyncio.to_thread(_run_alembic, settings.database_url, "upgrade", "head")
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            tbl = await conn.execute(
                text(
                    "select table_name from information_schema.tables "
                    "where table_name = 'managed_agents'"
                )
            )
            assert tbl.scalar_one_or_none() == "managed_agents"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_0052_state_check_rejects_invalid_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _truncate(session)
        await _seed_fk_chain(session)
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "insert into managed_agents "
                    "(id, tenant_id, project_id, host_id, state) "
                    "values (:i, 1, :p, 'host-1', 'bogus_state')"
                ),
                {"i": uuid4(), "p": PROJECT_A},
            )
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
async def test_0052_tenant_fk_rejects_cross_tenant_project(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """tenant 2 で project A (tenant 1 所属) を参照する insert は複合 FK で reject。"""
    async with session_factory() as session:
        await _truncate(session)
        await _seed_fk_chain(session)
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "insert into managed_agents "
                    "(id, tenant_id, project_id, host_id, state) "
                    "values (:i, 2, :p, 'host-1', 'spawning')"
                ),
                {"i": uuid4(), "p": PROJECT_A},  # project A は tenant 1 → tenant 2 では FK 違反
            )
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
async def test_0052_agent_run_fk_rejects_cross_project_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """run は (tenant1, projA) だが managed_agent を project B として参照 → 複合 FK reject。"""
    async with session_factory() as session:
        await _truncate(session)
        await _seed_fk_chain(session)
        # project B (tenant 1、別 project) を作る。
        await session.execute(
            text(
                "insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)"
                " values (:p, 1, :w, 'projB52', 'projB52', 'active',"
                " '{\"rls_ready\": true}'::jsonb) on conflict (id) do nothing"
            ),
            {"p": PROJECT_B, "w": WORKSPACE_ID},
        )
        await session.commit()
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "insert into managed_agents "
                    "(id, tenant_id, project_id, agent_run_id, host_id, state) "
                    "values (:i, 1, :pb, :r, 'host-1', 'spawning')"
                ),
                {"i": uuid4(), "pb": PROJECT_B, "r": RUN_ID},  # run は projA → projB 不一致
            )
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
async def test_0052_registry_lifecycle_and_tenant_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """register_spawning -> mark_running -> mark_terminal の lifecycle + list tenant scope。"""
    async with session_factory() as session:
        await _truncate(session)
        await _seed_fk_chain(session)
        registry = ManagedAgentRegistry(session)

        managed_id = await registry.register_spawning(
            tenant_id=TENANT_ONE,
            project_id=PROJECT_A,
            host_id="host-1",
            agent_run_id=RUN_ID,
            supervisor_id="sup-1",
        )
        await session.commit()

        view = await registry.get(tenant_id=TENANT_ONE, managed_agent_id=managed_id)
        assert view is not None
        assert view.state == "spawning"
        assert view.pid is None

        ran = await registry.mark_running(
            tenant_id=TENANT_ONE,
            managed_agent_id=managed_id,
            pid=4321,
            process_group_id=4321,
            boot_id="boot-xyz",
        )
        await session.commit()
        assert ran is True

        view = await registry.get(tenant_id=TENANT_ONE, managed_agent_id=managed_id)
        assert view is not None
        assert view.state == "running"
        assert view.pid == 4321
        assert view.process_group_id == 4321
        assert view.boot_id == "boot-xyz"

        # active 列挙 (tenant scope)
        active = await registry.list_active_for_tenant(tenant_id=TENANT_ONE)
        assert {v.id for v in active} == {managed_id}
        # 別 tenant からは見えない
        active_t2 = await registry.list_active_for_tenant(tenant_id=TENANT_TWO)
        assert active_t2 == []

        # host scope 列挙
        on_host = await registry.list_active_on_host(host_id="host-1")
        assert {v.id for v in on_host} == {managed_id}
        on_other_host = await registry.list_active_on_host(host_id="host-2")
        assert on_other_host == []

        # terminalize
        done = await registry.mark_terminal(
            tenant_id=TENANT_ONE, managed_agent_id=managed_id, state="stopped"
        )
        await session.commit()
        assert done is True

        # terminal 後は active 列挙から消える
        active_after = await registry.list_active_for_tenant(tenant_id=TENANT_ONE)
        assert active_after == []
        # 二重 terminalize は no-op (rowcount 0)
        again = await registry.mark_terminal(
            tenant_id=TENANT_ONE, managed_agent_id=managed_id, state="stopped"
        )
        assert again is False


@pytest.mark.asyncio
async def test_0052_mark_running_requires_spawning_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """mark_running は spawning 行のみ遷移可 (terminalize 後の二重遷移を防ぐ)。"""
    async with session_factory() as session:
        await _truncate(session)
        await _seed_fk_chain(session)
        registry = ManagedAgentRegistry(session)
        managed_id = await registry.register_spawning(
            tenant_id=TENANT_ONE,
            project_id=PROJECT_A,
            host_id="host-1",
        )
        await registry.mark_terminal(
            tenant_id=TENANT_ONE, managed_agent_id=managed_id, state="failed"
        )
        await session.commit()
        # 既に failed → mark_running は no-op (False)
        ran = await registry.mark_running(
            tenant_id=TENANT_ONE,
            managed_agent_id=managed_id,
            pid=1,
            process_group_id=1,
            boot_id=None,
        )
        assert ran is False


@pytest.mark.asyncio
async def test_0052_pre_stop_status_check_rejects_invalid_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """MEDIUM-1 / LOW-5: pre_stop_status CHECK が block 不可な status を reject する。

    block source / resume 復元先 subset (running/policy_linted/diff_ready/waiting_approval) と NULL のみ許可。
    """
    async with session_factory() as session:
        await _truncate(session)
        await _seed_fk_chain(session)
        # valid: block source の 1 つは許可される。
        await session.execute(
            text(
                "update agent_runs set pre_stop_status = 'waiting_approval' where id = :r"
            ),
            {"r": RUN_ID},
        )
        await session.commit()
        # invalid: block 不可な status (completed / queued / blocked) は reject。
        for bad in ("completed", "queued", "blocked"):
            with pytest.raises(IntegrityError):
                await session.execute(
                    text("update agent_runs set pre_stop_status = :s where id = :r"),
                    {"s": bad, "r": RUN_ID},
                )
                await session.commit()
            await session.rollback()
        # NULL は許可 (clear/未 block の run)。
        await session.execute(
            text("update agent_runs set pre_stop_status = null where id = :r"),
            {"r": RUN_ID},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_0052_partial_unique_rejects_second_active_for_same_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """LOW-4: 同一 agent_run_id への 2 件目の active (spawning/running) row は partial unique で reject。

    1 件目を terminal 化すれば 2 件目 (再 spawn) は許可される (partial 条件が state を限定するため)。
    """
    async with session_factory() as session:
        await _truncate(session)
        await _seed_fk_chain(session)
        registry = ManagedAgentRegistry(session)
        first = await registry.register_spawning(
            tenant_id=TENANT_ONE,
            project_id=PROJECT_A,
            host_id="host-1",
            agent_run_id=RUN_ID,
        )
        await session.commit()
        # 同 run への 2 件目 active = reject。
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "insert into managed_agents "
                    "(id, tenant_id, project_id, agent_run_id, host_id, state) "
                    "values (:i, 1, :p, :r, 'host-2', 'running')"
                ),
                {"i": uuid4(), "p": PROJECT_A, "r": RUN_ID},
            )
            await session.commit()
        await session.rollback()
        # 1 件目を terminal 化 → 同 run の再 spawn (2 件目 active) は許可される。
        await registry.mark_terminal(
            tenant_id=TENANT_ONE, managed_agent_id=first, state="stopped"
        )
        await session.commit()
        second = await registry.register_spawning(
            tenant_id=TENANT_ONE,
            project_id=PROJECT_A,
            host_id="host-1",
            agent_run_id=RUN_ID,
        )
        await session.commit()
        assert second != first
        # run-less (agent_run_id NULL) 行は partial 条件 (agent_run_id IS NOT NULL) の対象外で
        # 複数 active 許可 (partial unique が NULL を巻き込まない)。
        await registry.register_spawning(
            tenant_id=TENANT_ONE, project_id=PROJECT_A, host_id="host-1"
        )
        await registry.register_spawning(
            tenant_id=TENANT_ONE, project_id=PROJECT_A, host_id="host-1"
        )
        await session.commit()
