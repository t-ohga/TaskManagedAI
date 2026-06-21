"""SP-PHASE1 B4: supervisor host/tenant scope kill DB-gated test (ADR-00048 §F / A-2)。

実 DB (managed_agents + superintendent_emergency_stops) を使い、``supervisor_poll_once`` /
``kill_managed_agents_on_host`` が **engaged tenant × 自 host** の active 行のみ kill (mark_terminal) し、
別 host / 別 tenant / 非 engaged tenant を絶対に触らないことを検証する (os.killpg は mock、実 process は
spawn しない)。

DB 接続必要: TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
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
from backend.app.services.superintendent import supervisor as sup
from backend.app.services.superintendent.emergency_stop import EmergencyStopService
from backend.app.services.superintendent.managed_agent_registry import ManagedAgentRegistry

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

ACTOR_OWNER_1 = UUID("00000000-0000-4000-8000-0000000d6001")
ACTOR_OWNER_2 = UUID("00000000-0000-4000-8000-0000000d6003")
WORKSPACE_1 = UUID("00000000-0000-4000-8000-0000000d6010")
WORKSPACE_2 = UUID("00000000-0000-4000-8000-0000000d6011")
PROJECT_1 = UUID("00000000-0000-4000-8000-0000000d6020")
PROJECT_2 = UUID("00000000-0000-4000-8000-0000000d6021")

HOST_A = "host-a"
HOST_B = "host-b"
BOOT_X = "boot-x"

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
        dev_login_cookie_secret="test-cookie-secret-for-supervisor-db",
    )


def _run_alembic_upgrade(database_url: str) -> None:
    previous = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        command.upgrade(Config(str(_REPO_ROOT / "alembic.ini")), "head")
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
        raise AssertionError("supervisor DB tests require PostgreSQL.") from exc
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


async def _reset(session: AsyncSession) -> None:
    await session.execute(
        text(
            "truncate managed_agents, superintendent_emergency_stops, agent_runs, "
            "agent_run_events, audit_events, projects, workspaces, actors, tenants "
            "restart identity cascade"
        )
    )
    await session.commit()


async def _seed(session: AsyncSession) -> None:
    await session.execute(
        text(
            "insert into tenants (id, name, metadata) values "
            "(1, 'tenant-one', '{\"rls_ready\": true}'::jsonb),"
            "(2, 'tenant-two', '{\"rls_ready\": true}'::jsonb)"
        )
    )
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values
              (:o1, 1, 'human', 'human:default', 'Owner1', '{"rls_ready": true}'::jsonb),
              (:o2, 2, 'human', 'human:default', 'Owner2', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"o1": ACTOR_OWNER_1, "o2": ACTOR_OWNER_2},
    )
    await session.execute(
        text(
            "insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata) values "
            "(:w1, 1, 'ws1', 'ws1', :o1, '{\"rls_ready\": true}'::jsonb),"
            "(:w2, 2, 'ws2', 'ws2', :o2, '{\"rls_ready\": true}'::jsonb)"
        ),
        {"w1": WORKSPACE_1, "o1": ACTOR_OWNER_1, "w2": WORKSPACE_2, "o2": ACTOR_OWNER_2},
    )
    await session.execute(
        text(
            "insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata) values "
            "(:p1, 1, :w1, 'p1', 'p1', 'active', '{\"rls_ready\": true}'::jsonb),"
            "(:p2, 2, :w2, 'p2', 'p2', 'active', '{\"rls_ready\": true}'::jsonb)"
        ),
        {"p1": PROJECT_1, "w1": WORKSPACE_1, "p2": PROJECT_2, "w2": WORKSPACE_2},
    )
    await session.commit()


async def _make_managed(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    host_id: str,
    state: str = "running",
    pgid: int | None = 4321,
    pid: int | None = 4321,
    boot_id: str | None = BOOT_X,
) -> UUID:
    mid = uuid4()
    await session.execute(
        text(
            "insert into managed_agents "
            "(id, tenant_id, project_id, host_id, state, process_group_id, pid, boot_id, "
            "started_at) "
            "values (:i, :t, :p, :h, :s, :pg, :pid, :boot, now())"
        ),
        {
            "i": mid,
            "t": tenant_id,
            "p": project_id,
            "h": host_id,
            "s": state,
            "pg": pgid,
            "pid": pid,
            "boot": boot_id,
        },
    )
    await session.commit()
    return mid


async def _state_of(session: AsyncSession, managed_id: UUID) -> str:
    row = await session.scalar(
        text("select state from managed_agents where id = :i"), {"i": managed_id}
    )
    return str(row)


@pytest.mark.asyncio
async def test_poll_kills_only_engaged_tenant_and_host(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tenant 1 engage で host A の tenant 1 行のみ kill。tenant 2 / host B は不変 (A-2 scope)。"""
    killed_pgids: list[int] = []
    monkeypatch.setattr(sup.os, "killpg", lambda pgid, _sig: killed_pgids.append(pgid))
    monkeypatch.setattr(sup, "get_host_boot_id", lambda: BOOT_X)

    async with session_factory() as session:
        await _reset(session)
        await _seed(session)

    async with session_factory() as session:
        t1_hostA = await _make_managed(
            session, tenant_id=1, project_id=PROJECT_1, host_id=HOST_A, pgid=111
        )
        t2_hostA = await _make_managed(
            session, tenant_id=2, project_id=PROJECT_2, host_id=HOST_A, pgid=222
        )
        t1_hostB = await _make_managed(
            session, tenant_id=1, project_id=PROJECT_1, host_id=HOST_B, pgid=333
        )

    # tenant 1 を engage (latch row 作成 + commit)。
    async with session_factory() as session:
        await EmergencyStopService(session).engage(
            tenant_id=1, operator_actor_id=ACTOR_OWNER_1
        )
        await session.commit()

    # host A の supervisor poll: engaged tenant 1 × host A のみ kill。
    killed = await sup.supervisor_poll_once(session_factory=session_factory, host_id=HOST_A)

    assert {v.process_group_id for v in killed} == {111}
    assert killed_pgids == [111]

    async with session_factory() as session:
        assert await _state_of(session, t1_hostA) == "stopped"  # killed
        assert await _state_of(session, t2_hostA) == "running"  # 別 tenant、不変
        assert await _state_of(session, t1_hostB) == "running"  # 別 host、不変


@pytest.mark.asyncio
async def test_poll_no_kill_when_not_engaged(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """engage 無しなら kill しない (latch 権威、fail-closed の逆 = engaged でないと触らない)。"""
    killed_pgids: list[int] = []
    monkeypatch.setattr(sup.os, "killpg", lambda pgid, _sig: killed_pgids.append(pgid))
    monkeypatch.setattr(sup, "get_host_boot_id", lambda: BOOT_X)

    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
    async with session_factory() as session:
        mid = await _make_managed(
            session, tenant_id=1, project_id=PROJECT_1, host_id=HOST_A, pgid=111
        )

    killed = await sup.supervisor_poll_once(session_factory=session_factory, host_id=HOST_A)
    assert killed == []
    assert killed_pgids == []
    async with session_factory() as session:
        assert await _state_of(session, mid) == "running"


@pytest.mark.asyncio
async def test_kill_skips_spawning_pgid_none_in_db(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """spawning (pgid IS NULL) 行は kill / terminalize しない (次 poll で running 化後に kill)。"""
    killed_pgids: list[int] = []
    monkeypatch.setattr(sup.os, "killpg", lambda pgid, _sig: killed_pgids.append(pgid))
    monkeypatch.setattr(sup, "get_host_boot_id", lambda: BOOT_X)

    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
    async with session_factory() as session:
        spawning = await _make_managed(
            session,
            tenant_id=1,
            project_id=PROJECT_1,
            host_id=HOST_A,
            state="spawning",
            pgid=None,
            pid=None,
            boot_id=None,
        )

    async with session_factory() as session:
        registry = ManagedAgentRegistry(session)
        killed = await sup.kill_managed_agents_on_host(
            registry=registry, tenant_id=1, host_id=HOST_A
        )
        await session.commit()

    assert killed == []
    assert killed_pgids == []
    async with session_factory() as session:
        assert await _state_of(session, spawning) == "spawning"  # 不変 (terminalize しない)


@pytest.mark.asyncio
async def test_pgid_check_rejects_zero(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """HIGH-2: DB CHECK が process_group_id <= 0 を reject する (migration 0054)。"""
    from sqlalchemy.exc import IntegrityError

    async with session_factory() as session:
        await _reset(session)
        await _seed(session)

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            await _make_managed(
                session, tenant_id=1, project_id=PROJECT_1, host_id=HOST_A, pgid=0
            )


@pytest.mark.asyncio
async def test_pgid_check_rejects_negative(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """HIGH-2: DB CHECK が負 pgid を reject する。"""
    from sqlalchemy.exc import IntegrityError

    async with session_factory() as session:
        await _reset(session)
        await _seed(session)

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            await _make_managed(
                session, tenant_id=1, project_id=PROJECT_1, host_id=HOST_A, pgid=-5
            )


@pytest.mark.asyncio
async def test_pgid_check_allows_null_and_positive(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """HIGH-2: NULL pgid (spawning) と正 pgid (running) は CHECK を満たす。"""
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
    async with session_factory() as session:
        spawning = await _make_managed(
            session, tenant_id=1, project_id=PROJECT_1, host_id=HOST_A,
            state="spawning", pgid=None, pid=None, boot_id=None,
        )
        running = await _make_managed(
            session, tenant_id=1, project_id=PROJECT_1, host_id=HOST_A, pgid=4321
        )
    async with session_factory() as session:
        assert await _state_of(session, spawning) == "spawning"
        assert await _state_of(session, running) == "running"


@pytest.mark.asyncio
async def test_kill_skips_when_latch_cleared_real_db(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P2-2: engage→clear 後の kill tx は latch re-read (FOR UPDATE) で cleared を観測し kill しない。

    engage で latch 作成 → managed row 作成 → clear (latch cleared) → kill_managed_agents_on_host を
    engaged 当時の前提で呼ぶと、kill tx 内 latch re-read が cleared を観測して **kill skip** する
    (clear→kill TOCTOU の実 DB serialization)。
    """
    killed_pgids: list[int] = []
    monkeypatch.setattr(sup.os, "killpg", lambda pgid, _sig: killed_pgids.append(pgid))
    monkeypatch.setattr(sup, "get_host_boot_id", lambda: BOOT_X)

    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
    async with session_factory() as session:
        mid = await _make_managed(
            session, tenant_id=1, project_id=PROJECT_1, host_id=HOST_A, pgid=111
        )

    # engage → generation 取得 → clear (latch cleared_at set)。
    async with session_factory() as session:
        result = await EmergencyStopService(session).engage(
            tenant_id=1, operator_actor_id=ACTOR_OWNER_1
        )
        await session.commit()
    async with session_factory() as session:
        await EmergencyStopService(session).clear(
            tenant_id=1,
            operator_actor_id=ACTOR_OWNER_1,
            expected_generation=result.generation,
        )
        await session.commit()

    # cleared 後に「engaged 当時」の kill を試みる: latch re-read で cleared を観測 → skip。
    async with session_factory() as session:
        registry = ManagedAgentRegistry(session)
        killed = await sup.kill_managed_agents_on_host(
            registry=registry, tenant_id=1, host_id=HOST_A, session=session
        )
        await session.commit()

    assert killed == []
    assert killed_pgids == []
    async with session_factory() as session:
        assert await _state_of(session, mid) == "running"  # cleared → kill されず running 維持。
