"""SP-PHASE1 B3: emergency-stop latch service (ADR-00048 §B/B-1/B-3/A-3/A-5/A-6) DB-gated test。

検証 (must-ship):
- latch table 存在 + partial unique active ≤ 1。
- engage → block (running/policy_linted/diff_ready/waiting_approval のみ、pre_stop_status 保存) →
  clear → resume (pre_stop_status 復元表通り、一律 running 禁止)。
- generation CAS (stale clear reject)。
- 冪等性 (二重 engage = no-op + 同一 latch、agent 不在 engage = blocked_run_count=0)。
- cross-tenant 非干渉 (tenant 1 engage で tenant 2 の run/latch 無影響、tenant 2 新規活動 allow)。
- block source 限定 (非 block-source state は status 遷移させず latch 任せ)。
- post-stop 新規 deny (_assert_not_emergency_stopped が spawn を deny、clear 後 allow)。
- audit assert_no_raw_secret (pid/token 非含)。
- A-3: engage commit が active_registry freeze gate を bypass。
- advisory lock 直列化 (concurrent engage、同 generation を二重に作らない)。

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
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.audit_event import AuditEvent
from backend.app.db.session import create_engine
from backend.app.services.superintendent.agent_spawner import (
    _assert_not_emergency_stopped,
)
from backend.app.services.superintendent.emergency_stop import (
    EmergencyStopEngagedError,
    EmergencyStopService,
    EmergencyStopServiceError,
    NotEngagedError,
    StaleGenerationError,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ONE = 1
TENANT_TWO = 2
ACTOR_OWNER_1 = UUID("00000000-0000-4000-8000-0000000d5001")
ACTOR_AGENT_1 = UUID("00000000-0000-4000-8000-0000000d5002")
ACTOR_OWNER_2 = UUID("00000000-0000-4000-8000-0000000d5003")
WORKSPACE_1 = UUID("00000000-0000-4000-8000-0000000d5010")
WORKSPACE_2 = UUID("00000000-0000-4000-8000-0000000d5011")
PROJECT_1 = UUID("00000000-0000-4000-8000-0000000d5020")
PROJECT_2 = UUID("00000000-0000-4000-8000-0000000d5021")

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
        dev_login_cookie_secret="test-cookie-secret-for-emergency-stop-svc",
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
        raise AssertionError("emergency-stop service tests require PostgreSQL.") from exc
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
            "truncate superintendent_emergency_stops, agent_run_events, agent_runs, "
            "audit_events, projects, workspaces, actors, tenants restart identity cascade"
        )
    )
    await session.commit()


async def _seed(session: AsyncSession) -> None:
    """tenant 1+2 / owner actors / workspaces / projects を seed (run は test ごとに作る)。"""
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
              (:a1, 1, 'agent', 'agent:r1', 'Agent1', '{"rls_ready": true}'::jsonb),
              (:o2, 2, 'human', 'human:default', 'Owner2', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"o1": ACTOR_OWNER_1, "a1": ACTOR_AGENT_1, "o2": ACTOR_OWNER_2},
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


async def _make_run(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    status: str,
    run_id: UUID | None = None,
    run_mode: str = "production",
    pre_stop_status: str | None = None,
    ticket_id: UUID | None = None,
) -> UUID:
    rid = run_id or uuid4()
    blocked_reason = "runtime_blocked" if status == "blocked" else None
    await session.execute(
        text(
            "insert into agent_runs "
            "(id, tenant_id, project_id, status, blocked_reason, run_mode, "
            "pre_stop_status, ticket_id) "
            "values (:r, :t, :p, :s, :br, :rm, :pre, :tk)"
        ),
        {
            "r": rid,
            "t": tenant_id,
            "p": project_id,
            "s": status,
            "br": blocked_reason,
            "rm": run_mode,
            "pre": pre_stop_status,
            "tk": ticket_id,
        },
    )
    await session.commit()
    return rid


async def _make_ticket(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    slug: str,
    soft_deleted: bool = False,
) -> UUID:
    """active-scope test 用 ticket (soft_deleted=True で deleted_at を set)。"""
    tid = uuid4()
    await session.execute(
        text(
            "insert into tickets "
            "(id, tenant_id, project_id, slug, title, status, created_by_actor_id, "
            "metadata, deleted_at) "
            "values (:i, :t, :p, :slug, :title, 'open', :a, "
            "'{\"rls_ready\": true}'::jsonb, :del)"
        ),
        {
            "i": tid,
            "t": tenant_id,
            "p": project_id,
            "slug": slug,
            "title": f"ticket-{slug}",
            "a": ACTOR_OWNER_1 if tenant_id == 1 else ACTOR_OWNER_2,
            "del": "now()" if soft_deleted else None,
        },
    )
    if soft_deleted:
        # bind 後に soft-delete (deleted_at param 経路を確実にする)。
        await session.execute(
            text("update tickets set deleted_at = now() where id = :i"),
            {"i": tid},
        )
    await session.commit()
    return tid


async def _archive_project(session: AsyncSession, *, project_id: UUID) -> None:
    await session.execute(
        text("update projects set status = 'archived' where id = :p"),
        {"p": project_id},
    )
    await session.commit()


async def _run_status(session: AsyncSession, run_id: UUID) -> tuple[str, str | None, str | None]:
    row = (
        await session.execute(
            text(
                "select status, blocked_reason, pre_stop_status from agent_runs where id = :r"
            ),
            {"r": run_id},
        )
    ).one()
    return (row[0], row[1], row[2])


# --------------------------------------------------------------------------- #
# migration / table structure
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_latch_table_and_partial_unique(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        tbl = await session.execute(
            text(
                "select table_name from information_schema.tables "
                "where table_name = 'superintendent_emergency_stops'"
            )
        )
        assert tbl.scalar_one_or_none() == "superintendent_emergency_stops"
        idx = await session.execute(
            text(
                "select indexname from pg_indexes "
                "where indexname = 'superintendent_emergency_stops_uq_active'"
            )
        )
        assert idx.scalar_one_or_none() == "superintendent_emergency_stops_uq_active"

    # active ≤ 1: 2 件目の active row (cleared_at IS NULL) は partial unique で reject。
    async with session_factory() as session:
        await session.execute(
            text(
                "insert into superintendent_emergency_stops "
                "(id, tenant_id, generation, engaged_at, engaged_by_actor_id) "
                "values (:i, 1, 1, now(), :a)"
            ),
            {"i": uuid4(), "a": ACTOR_OWNER_1},
        )
        await session.commit()
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "insert into superintendent_emergency_stops "
                    "(id, tenant_id, generation, engaged_at, engaged_by_actor_id) "
                    "values (:i, 1, 2, now(), :a)"
                ),
                {"i": uuid4(), "a": ACTOR_OWNER_1},
            )
            await session.commit()
        await session.rollback()


# --------------------------------------------------------------------------- #
# engage -> block -> clear -> resume + state restore
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_engage_blocks_only_block_source_and_saves_pre_stop_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        # block source states (4) + 非 block-source states (latch 任せ、status 不変)。
        r_running = await _make_run(session, tenant_id=1, project_id=PROJECT_1, status="running")
        r_policy = await _make_run(session, tenant_id=1, project_id=PROJECT_1, status="policy_linted")
        r_diff = await _make_run(session, tenant_id=1, project_id=PROJECT_1, status="diff_ready")
        r_wait = await _make_run(
            session, tenant_id=1, project_id=PROJECT_1, status="waiting_approval"
        )
        r_queued = await _make_run(session, tenant_id=1, project_id=PROJECT_1, status="queued")
        r_gather = await _make_run(
            session, tenant_id=1, project_id=PROJECT_1, status="gathering_context"
        )

        service = EmergencyStopService(session)
        result = await service.engage(
            tenant_id=1, operator_actor_id=ACTOR_OWNER_1, reason="runaway agents"
        )
        await session.commit()

    assert result.engaged is True
    assert result.already_engaged is False
    assert result.generation == 1
    assert result.blocked_run_count == 4  # 4 block-source states のみ

    async with session_factory() as session:
        # block-source は blocked + pre_stop_status 保存。
        for rid, src in (
            (r_running, "running"),
            (r_policy, "policy_linted"),
            (r_diff, "diff_ready"),
            (r_wait, "waiting_approval"),
        ):
            st, br, pre = await _run_status(session, rid)
            assert st == "blocked"
            assert br == "runtime_blocked"
            assert pre == src
        # 非 block-source は status 不変 (latch 任せ)。
        for rid, src in ((r_queued, "queued"), (r_gather, "gathering_context")):
            st, br, pre = await _run_status(session, rid)
            assert st == src
            assert br is None
            assert pre is None


@pytest.mark.asyncio
async def test_clear_restores_pre_stop_status_not_uniform_running(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """clear は pre_stop_status 復元表通り (waiting_approval→waiting_approval 等、一律 running にしない)。"""
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        r_wait = await _make_run(
            session, tenant_id=1, project_id=PROJECT_1, status="waiting_approval"
        )
        r_diff = await _make_run(session, tenant_id=1, project_id=PROJECT_1, status="diff_ready")
        r_run = await _make_run(session, tenant_id=1, project_id=PROJECT_1, status="running")

        service = EmergencyStopService(session)
        engaged = await service.engage(tenant_id=1, operator_actor_id=ACTOR_OWNER_1)
        await session.commit()

    async with session_factory() as session:
        service = EmergencyStopService(session)
        cleared = await service.clear(
            tenant_id=1,
            operator_actor_id=ACTOR_OWNER_1,
            expected_generation=engaged.generation,
        )
        await session.commit()
    assert cleared.cleared is True
    assert cleared.resumed_run_count == 3

    async with session_factory() as session:
        # 復元表通り (gate skip しない): pre_stop_status に戻り pre_stop_status は NULL。
        for rid, restored in (
            (r_wait, "waiting_approval"),
            (r_diff, "diff_ready"),
            (r_run, "running"),
        ):
            st, br, pre = await _run_status(session, rid)
            assert st == restored
            assert br is None
            assert pre is None
        # latch は cleared (status engaged=false)。
        assert (await EmergencyStopService(session).get_active(1)) is None


# --------------------------------------------------------------------------- #
# generation CAS + idempotency
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_clear_stale_generation_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        service = EmergencyStopService(session)
        engaged = await service.engage(tenant_id=1, operator_actor_id=ACTOR_OWNER_1)
        await session.commit()
    assert engaged.generation == 1

    async with session_factory() as session:
        service = EmergencyStopService(session)
        with pytest.raises(StaleGenerationError):
            await service.clear(
                tenant_id=1,
                operator_actor_id=ACTOR_OWNER_1,
                expected_generation=999,  # stale
            )
        await session.rollback()
        # latch はまだ active (誤 clear されていない)。
        assert (await service.get_active(1)) is not None


@pytest.mark.asyncio
async def test_clear_without_active_latch_raises_not_engaged(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        service = EmergencyStopService(session)
        with pytest.raises(NotEngagedError):
            await service.clear(
                tenant_id=1, operator_actor_id=ACTOR_OWNER_1, expected_generation=1
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_double_engage_is_idempotent_no_op(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        await _make_run(session, tenant_id=1, project_id=PROJECT_1, status="running")
        service = EmergencyStopService(session)
        first = await service.engage(tenant_id=1, operator_actor_id=ACTOR_OWNER_1)
        await session.commit()
    assert first.already_engaged is False
    assert first.blocked_run_count == 1

    async with session_factory() as session:
        service = EmergencyStopService(session)
        second = await service.engage(tenant_id=1, operator_actor_id=ACTOR_OWNER_1)
        await session.commit()
    # 冪等 no-op: 同一 latch (同 generation)、block しない。
    assert second.already_engaged is True
    assert second.generation == first.generation
    assert second.blocked_run_count == 0

    # active latch は依然 1 件 (二重 active になっていない)。
    async with session_factory() as session:
        count = (
            await session.execute(
                text(
                    "select count(*) from superintendent_emergency_stops "
                    "where tenant_id = 1 and cleared_at is null"
                )
            )
        ).scalar_one()
        assert count == 1


@pytest.mark.asyncio
async def test_engage_with_no_active_runs_blocks_zero(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        service = EmergencyStopService(session)
        result = await service.engage(tenant_id=1, operator_actor_id=ACTOR_OWNER_1)
        await session.commit()
    assert result.engaged is True
    assert result.blocked_run_count == 0


@pytest.mark.asyncio
async def test_engage_generation_increments_across_engage_clear_cycles(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
    # engage(gen1) -> clear -> engage(gen2)。
    async with session_factory() as session:
        service = EmergencyStopService(session)
        g1 = await service.engage(tenant_id=1, operator_actor_id=ACTOR_OWNER_1)
        await session.commit()
    async with session_factory() as session:
        service = EmergencyStopService(session)
        await service.clear(
            tenant_id=1, operator_actor_id=ACTOR_OWNER_1, expected_generation=g1.generation
        )
        await session.commit()
    async with session_factory() as session:
        service = EmergencyStopService(session)
        g2 = await service.engage(tenant_id=1, operator_actor_id=ACTOR_OWNER_1)
        await session.commit()
    assert g1.generation == 1
    assert g2.generation == 2


# --------------------------------------------------------------------------- #
# cross-tenant non-interference
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_engage_is_tenant_scoped_no_cross_tenant_effect(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """tenant 1 engage で tenant 2 の run/latch 無影響、tenant 2 新規活動は allow。"""
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        r1 = await _make_run(session, tenant_id=1, project_id=PROJECT_1, status="running")
        r2 = await _make_run(session, tenant_id=2, project_id=PROJECT_2, status="running")
        service = EmergencyStopService(session)
        await service.engage(tenant_id=1, operator_actor_id=ACTOR_OWNER_1)
        await session.commit()

    async with session_factory() as session:
        # tenant 1 run は blocked。
        st1, _, _ = await _run_status(session, r1)
        assert st1 == "blocked"
        # tenant 2 run は無影響 (running のまま)。
        st2, br2, pre2 = await _run_status(session, r2)
        assert st2 == "running"
        assert br2 is None
        assert pre2 is None

    # tenant context は session 毎に pin される (set_tenant_context、1 request = 1 tenant)。
    # tenant 別の latch check / 新規活動許可は別 session で確認する (実 request の境界に整合)。
    async with session_factory() as session:
        assert await EmergencyStopService(session).is_engaged(1) is True
    async with session_factory() as session:
        # tenant 2 latch は engaged でない (新規活動 allow)。
        assert await EmergencyStopService(session).is_engaged(2) is False
    async with session_factory() as session:
        # tenant 2 spawn latch check は allow (deny されない)。
        await _assert_not_emergency_stopped(2, session)  # raise しない


# --------------------------------------------------------------------------- #
# post-stop new activity deny (spawn helper) + clear allow
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_assert_not_emergency_stopped_denies_when_engaged_allows_after_clear(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        service = EmergencyStopService(session)
        engaged = await service.engage(tenant_id=1, operator_actor_id=ACTOR_OWNER_1)
        await session.commit()

    # engaged: spawn latch check は deny。
    async with session_factory() as session:
        with pytest.raises(EmergencyStopEngagedError) as exc_info:
            await _assert_not_emergency_stopped(1, session)
        assert exc_info.value.reason_code == "emergency_stop_engaged"

    # clear。
    async with session_factory() as session:
        service = EmergencyStopService(session)
        await service.clear(
            tenant_id=1, operator_actor_id=ACTOR_OWNER_1, expected_generation=engaged.generation
        )
        await session.commit()

    # cleared: spawn latch check は allow。
    async with session_factory() as session:
        await _assert_not_emergency_stopped(1, session)  # raise しない


# --------------------------------------------------------------------------- #
# audit: no raw secret / pid
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_audit_emitted_without_raw_secret_or_pid(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        await _make_run(session, tenant_id=1, project_id=PROJECT_1, status="running")
        service = EmergencyStopService(session)
        await service.engage(
            tenant_id=1, operator_actor_id=ACTOR_OWNER_1, reason="manual stop"
        )
        await session.commit()

    async with session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "select event_type, event_payload::text from audit_events "
                    "where tenant_id = 1 order by created_at"
                )
            )
        ).all()
    assert rows, "engage must emit an audit event"
    blob = " ".join(r[1] for r in rows).lower()
    assert "reason_code" in blob
    assert "emergency_stop_engaged" in blob
    # pid / token / raw secret を含まない。
    assert "pid" not in blob
    assert "token" not in blob
    assert "sk-" not in blob


# --------------------------------------------------------------------------- #
# A-3: engage commit bypasses active-registry freeze gate
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_engage_commit_bypasses_active_registry_freeze_gate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A-3: freeze gate を attach した session でも engage commit は reject されない (安全弁不変)。"""
    from sqlalchemy.ext.asyncio import AsyncSession as _AS

    from backend.app.db.active_registry_mutation_gate import (
        ActiveRegistryGateRejectedCommit,
        attach_db_mutation_gate,
        detach_db_mutation_gate,
    )

    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        await _make_run(session, tenant_id=1, project_id=PROJECT_1, status="running")

    sync_class = _AS.sync_session_class

    def _always_reject(_host_id: str) -> bytes | None:
        return None

    # gate を attach: 通常 commit は reject される構成 (evaluate_gate が fail-closed)。
    listener = attach_db_mutation_gate(
        sync_class,
        config_dir=Path("/nonexistent-emergency-stop-gate-config"),
        host_id="emergency-stop-test-host",
        public_key_resolver=_always_reject,
    )
    try:
        # baseline: gate 下の通常 ORM mutation commit は reject される (gate が効いていることを確認)。
        # emergency-stop service と同じ ORM 経路 (session.add) で mutation を検出させる。
        async with session_factory() as session:
            session.add(
                AuditEvent(
                    tenant_id=1,
                    event_type="config_changed",
                    actor_id=ACTOR_OWNER_1,
                    event_payload={"rls_ready": True, "probe": "gate-baseline"},
                )
            )
            with pytest.raises(ActiveRegistryGateRejectedCommit):
                await session.commit()
            await session.rollback()

        # emergency-stop engage commit は同じ ORM mutation を含むが gate を bypass して成功する (A-3)。
        async with session_factory() as session:
            service = EmergencyStopService(session)
            result = await service.engage(tenant_id=1, operator_actor_id=ACTOR_OWNER_1)
            await session.commit()  # reject されない
        assert result.engaged is True
        assert result.blocked_run_count == 1
    finally:
        detach_db_mutation_gate(sync_class, listener)

    # latch が実際に永続化されている。
    async with session_factory() as session:
        assert await EmergencyStopService(session).is_engaged(1) is True


# --------------------------------------------------------------------------- #
# advisory lock serialization (concurrent engage)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_concurrent_engage_serialized_single_active_latch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """concurrent な 2 engage が advisory lock で直列化され、active latch は 1 件のみになる。"""
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)

    async def _engage() -> int:
        async with session_factory() as session:
            service = EmergencyStopService(session)
            result = await service.engage(tenant_id=1, operator_actor_id=ACTOR_OWNER_1)
            await session.commit()
            return result.generation

    g1, g2 = await asyncio.gather(_engage(), _engage())
    # 同 advisory lock で直列化され、片方は新規 (gen=1)、片方は冪等 no-op (同 gen=1)。
    assert {g1, g2} == {1}

    async with session_factory() as session:
        count = (
            await session.execute(
                text(
                    "select count(*) from superintendent_emergency_stops "
                    "where tenant_id = 1 and cleared_at is null"
                )
            )
        ).scalar_one()
        assert count == 1


# --------------------------------------------------------------------------- #
# HIGH: engage event idempotency_key per-generation (fail-open regression)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_engage_clear_engage_cycle_reblocks_same_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """HIGH regression: engage→clear→engage の 2 回目が同一 run を再 block できる (fail-open 防止)。

    engage event の idempotency_key が constant だと、clear で running 復元した同一 run を 2 回目
    engage で再 block する際 partial unique (tenant_id, run_id, idempotency_key) UniqueViolation →
    engage transaction 全 rollback → latch 巻き戻り = kill switch が engage せず fail-open になる。
    generation を key に混ぜることで cycle ごとに unique 化し、2 回目 engage が成功することを assert。
    """
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        run_id = await _make_run(
            session, tenant_id=1, project_id=PROJECT_1, status="running"
        )

    # 1 回目 engage (gen=1): run を block。
    async with session_factory() as session:
        service = EmergencyStopService(session)
        g1 = await service.engage(tenant_id=1, operator_actor_id=ACTOR_OWNER_1)
        await session.commit()
    assert g1.generation == 1
    assert g1.blocked_run_count == 1
    async with session_factory() as session:
        st, _, _ = await _run_status(session, run_id)
        assert st == "blocked"

    # clear (gen=1): run を running へ復元。
    async with session_factory() as session:
        service = EmergencyStopService(session)
        await service.clear(
            tenant_id=1, operator_actor_id=ACTOR_OWNER_1, expected_generation=g1.generation
        )
        await session.commit()
    async with session_factory() as session:
        st, _, _ = await _run_status(session, run_id)
        assert st == "running"

    # 2 回目 engage (gen=2): 同一 run を **再 block できる** (constant key なら IntegrityError で失敗)。
    async with session_factory() as session:
        service = EmergencyStopService(session)
        g2 = await service.engage(tenant_id=1, operator_actor_id=ACTOR_OWNER_1)
        await session.commit()  # IntegrityError にならない
    assert g2.generation == 2
    assert g2.blocked_run_count == 1  # 再 block 成功

    async with session_factory() as session:
        # latch が実際に engage されている (fail-open でない)。
        assert await EmergencyStopService(session).is_engaged(1) is True
        st, br, pre = await _run_status(session, run_id)
        assert st == "blocked"
        assert br == "runtime_blocked"
        assert pre == "running"

    # engage event が 2 件 (gen=1 と gen=2、別 idempotency_key) 蓄積している。
    async with session_factory() as session:
        engage_event_count = (
            await session.execute(
                text(
                    "select count(*) from agent_run_events "
                    "where run_id = :r and event_type = 'emergency_stop_engaged'"
                ),
                {"r": run_id},
            )
        ).scalar_one()
        assert engage_event_count == 2


# --------------------------------------------------------------------------- #
# LOW-3: block/resume use run-correct run_mode (shadow confinement preserved)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_block_and_resume_use_run_mode_correct_validation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """LOW-3: block/resume が run の実 run_mode で validate する (production hardcode しない)。

    shadow run の block (running->blocked) + resume (blocked->running) は mode-correct で成功する。
    一方、shadow run の pre_stop_status を pipeline-entry state (diff_ready、shadow では到達不能) に
    直接 set した状態で resume すると、mode-correct validation が SHADOW_FORBIDDEN
    (blocked->diff_ready を shadow で禁止) を効かせて reject する。production hardcode のままだと
    この shadow guard が無視され通ってしまう (latent confinement gap)。
    """
    # (a) shadow run の正常 block→resume (running 復元、mode-correct で成功)。
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        shadow_run = await _make_run(
            session,
            tenant_id=1,
            project_id=PROJECT_1,
            status="running",
            run_mode="shadow",
        )
    async with session_factory() as session:
        service = EmergencyStopService(session)
        engaged = await service.engage(tenant_id=1, operator_actor_id=ACTOR_OWNER_1)
        await session.commit()
    assert engaged.blocked_run_count == 1
    async with session_factory() as session:
        st, _, pre = await _run_status(session, shadow_run)
        assert st == "blocked"
        assert pre == "running"
    async with session_factory() as session:
        service = EmergencyStopService(session)
        cleared = await service.clear(
            tenant_id=1,
            operator_actor_id=ACTOR_OWNER_1,
            expected_generation=engaged.generation,
        )
        await session.commit()
    assert cleared.resumed_run_count == 1
    async with session_factory() as session:
        st, _, _ = await _run_status(session, shadow_run)
        assert st == "running"  # shadow run は running へ復元 (mode-correct)

    # (b) shadow run で pre_stop_status=diff_ready (shadow では到達不能な pipeline-entry) を直接構築し
    #     resume すると mode-correct validation が SHADOW_FORBIDDEN を効かせ reject する。
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        # blocked + runtime_blocked + pre_stop_status=diff_ready + run_mode=shadow を直接構築。
        await _make_run(
            session,
            tenant_id=1,
            project_id=PROJECT_1,
            status="blocked",
            run_mode="shadow",
            pre_stop_status="diff_ready",
        )
        # latch を 1 件作る (clear が active latch を要求するため)。
        await session.execute(
            text(
                "insert into superintendent_emergency_stops "
                "(id, tenant_id, generation, engaged_at, engaged_by_actor_id) "
                "values (:i, 1, 1, now(), :a)"
            ),
            {"i": uuid4(), "a": ACTOR_OWNER_1},
        )
        await session.commit()
    async with session_factory() as session:
        service = EmergencyStopService(session)
        # mode-correct validation: shadow の blocked->diff_ready は SHADOW_FORBIDDEN で reject。
        # production hardcode のままだと通ってしまう (本 fix がないと ValueError が出ない)。
        with pytest.raises(ValueError, match="not allowed"):
            await service.clear(
                tenant_id=1, operator_actor_id=ACTOR_OWNER_1, expected_generation=1
            )
        await session.rollback()


# --------------------------------------------------------------------------- #
# LOW-2: A-3 bypass guard rejects unrelated ORM mutation
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_bypass_guard_rejects_unrelated_model_mutation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """LOW-2: bypass-flagged session に emergency-stop 無関係の ORM model を混ぜると fail-closed reject。

    ``mark_emergency_stop_bypass`` した session で allowlist 外 model (Ticket) を session.add して
    commit すると、before_commit の scope guard が ``EmergencyStopBypassScopeViolation`` で reject する
    (whole-commit scope の blast radius を構造的に閉じる)。emergency-stop 関連 model のみなら通る。
    """
    from sqlalchemy.ext.asyncio import AsyncSession as _AS

    from backend.app.db.active_registry_mutation_gate import (
        EmergencyStopBypassScopeViolation,
        attach_db_mutation_gate,
        detach_db_mutation_gate,
        mark_emergency_stop_bypass,
    )
    from backend.app.db.models.ticket import Ticket

    async with session_factory() as session:
        await _reset(session)
        await _seed(session)

    sync_class = _AS.sync_session_class

    def _resolver(_host_id: str) -> bytes | None:
        return None

    listener = attach_db_mutation_gate(
        sync_class,
        config_dir=Path("/nonexistent-emergency-stop-bypass-guard"),
        host_id="emergency-stop-bypass-guard-host",
        public_key_resolver=_resolver,
    )
    try:
        # allowlist 外 model (Ticket) を bypass session に混ぜる → fail-closed reject。
        async with session_factory() as session:
            mark_emergency_stop_bypass(session)
            session.add(
                Ticket(
                    tenant_id=1,
                    project_id=PROJECT_1,
                    slug="es-bypass-guard",
                    title="unrelated",
                    status="open",
                    created_by_actor_id=ACTOR_OWNER_1,
                    metadata_={"rls_ready": True},
                )
            )
            with pytest.raises(EmergencyStopBypassScopeViolation):
                await session.commit()
            await session.rollback()

        # allowlist 内 model (AuditEvent) のみの bypass commit は通る。
        async with session_factory() as session:
            mark_emergency_stop_bypass(session)
            session.add(
                AuditEvent(
                    tenant_id=1,
                    event_type="config_changed",
                    actor_id=ACTOR_OWNER_1,
                    event_payload={"rls_ready": True, "probe": "bypass-allowed"},
                )
            )
            await session.commit()  # reject されない
    finally:
        detach_db_mutation_gate(sync_class, listener)


# --------------------------------------------------------------------------- #
# P2-6: operator reason secret scan before DB boundary
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_engage_rejects_reason_with_raw_secret_before_db(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """P2-6: raw token を含む reason は latch row flush の **前** に reject され DB 境界を越えない。"""
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)

    async with session_factory() as session:
        service = EmergencyStopService(session)
        with pytest.raises(EmergencyStopServiceError, match="secret pattern"):
            await service.engage(
                tenant_id=1,
                operator_actor_id=ACTOR_OWNER_1,
                reason="stop now sk-proj-ABCDEFGHIJKLMNOP1234567890 leaked",
            )
        await session.rollback()

    # latch row が **作られていない** (rejected input が DB へ flush されていない)。
    async with session_factory() as session:
        count = (
            await session.execute(
                text("select count(*) from superintendent_emergency_stops where tenant_id = 1")
            )
        ).scalar_one()
        assert count == 0
        assert await EmergencyStopService(session).is_engaged(1) is False


# --------------------------------------------------------------------------- #
# P2-5: resume rechecks active-scope (soft-deleted ticket / archived project)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_resume_skips_non_actionable_runs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """P2-5: engaged 中に ticket soft-delete / project archive された run は復元せず blocked のまま。

    - actionable run (active ticket bound) は resume される。
    - soft-deleted ticket bound run は skip (blocked のまま、skipped に計上)。
    - archived project の run も skip。
    """
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        active_ticket = await _make_ticket(
            session, tenant_id=1, project_id=PROJECT_1, slug="active-t"
        )
        del_ticket = await _make_ticket(
            session, tenant_id=1, project_id=PROJECT_1, slug="del-t"
        )
        r_actionable = await _make_run(
            session, tenant_id=1, project_id=PROJECT_1, status="running",
            ticket_id=active_ticket,
        )
        r_deleted = await _make_run(
            session, tenant_id=1, project_id=PROJECT_1, status="running",
            ticket_id=del_ticket,
        )

    # engage: 両 run を block。
    async with session_factory() as session:
        service = EmergencyStopService(session)
        engaged = await service.engage(tenant_id=1, operator_actor_id=ACTOR_OWNER_1)
        await session.commit()
    assert engaged.blocked_run_count == 2

    # engaged 中に del_ticket を soft-delete (active-scope を破壊)。
    async with session_factory() as session:
        await session.execute(
            text("update tickets set deleted_at = now() where id = :i"),
            {"i": del_ticket},
        )
        await session.commit()

    # clear: actionable は resume、non-actionable は skip。
    async with session_factory() as session:
        service = EmergencyStopService(session)
        cleared = await service.clear(
            tenant_id=1,
            operator_actor_id=ACTOR_OWNER_1,
            expected_generation=engaged.generation,
        )
        await session.commit()
    assert cleared.resumed_run_count == 1
    assert cleared.skipped_run_count == 1

    async with session_factory() as session:
        # actionable run は running へ復元。
        st_a, _, pre_a = await _run_status(session, r_actionable)
        assert st_a == "running"
        assert pre_a is None
        # non-actionable run は blocked のまま (pre_stop_status 保持、resume されていない)。
        st_d, br_d, pre_d = await _run_status(session, r_deleted)
        assert st_d == "blocked"
        assert br_d == "runtime_blocked"
        assert pre_d == "running"


@pytest.mark.asyncio
async def test_resume_skips_runs_in_archived_project(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """P2-5: engaged 中に project が archived になった run (ticket-less) も復元 skip。"""
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        run_id = await _make_run(
            session, tenant_id=1, project_id=PROJECT_1, status="waiting_approval"
        )

    async with session_factory() as session:
        service = EmergencyStopService(session)
        engaged = await service.engage(tenant_id=1, operator_actor_id=ACTOR_OWNER_1)
        await session.commit()
    assert engaged.blocked_run_count == 1

    async with session_factory() as session:
        await _archive_project(session, project_id=PROJECT_1)

    async with session_factory() as session:
        service = EmergencyStopService(session)
        cleared = await service.clear(
            tenant_id=1, operator_actor_id=ACTOR_OWNER_1,
            expected_generation=engaged.generation,
        )
        await session.commit()
    assert cleared.resumed_run_count == 0
    assert cleared.skipped_run_count == 1

    async with session_factory() as session:
        st, br, pre = await _run_status(session, run_id)
        assert st == "blocked"  # archived project の run は復元されない
        assert pre == "waiting_approval"


# --------------------------------------------------------------------------- #
# P2-4: clear always audits (emergency_stop_cleared) even with 0 resumed runs
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_clear_audits_even_with_zero_resumed_runs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """P2-4: resume が 0 件でも latch clear が emergency_stop_cleared で監査に残る。"""
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        # active run 無しで engage (block 0 件)。
        service = EmergencyStopService(session)
        engaged = await service.engage(tenant_id=1, operator_actor_id=ACTOR_OWNER_1)
        await session.commit()
    assert engaged.blocked_run_count == 0

    # clear (resume 0 件)。
    async with session_factory() as session:
        service = EmergencyStopService(session)
        cleared = await service.clear(
            tenant_id=1, operator_actor_id=ACTOR_OWNER_1,
            expected_generation=engaged.generation,
        )
        await session.commit()
    assert cleared.resumed_run_count == 0

    # clear audit (emergency_stop_cleared) が残っている (resume 0 件でも消えない)。
    async with session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "select event_payload::text from audit_events "
                    "where tenant_id = 1 order by created_at"
                )
            )
        ).all()
    blob = " ".join(r[0] for r in rows)
    assert "emergency_stop_cleared" in blob
    # engage の emergency_stop_engaged audit + clear の emergency_stop_cleared audit (2 件)。
    assert "emergency_stop_engaged" in blob


# --------------------------------------------------------------------------- #
# P1-2: spawn holds advisory lock → engage serialized with spawn
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_spawn_holds_advisory_lock_serializing_engage(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """P1-2: spawn が advisory lock を保持し、engage は spawn の commit まで待つ (TOCTOU race 排除)。

    spawn session が ``acquire_emergency_stop_lock`` を取得して保持中、別 session の engage は同一
    lock key を待つ。spawn が commit して lock を解放するまで engage の latch row 作成は進めない。
    spawn 完了後に engage すれば latch が立ち、以後の spawn latch check が deny する (A-1 直列化)。
    """
    from backend.app.services.superintendent.emergency_stop import (
        acquire_emergency_stop_lock,
    )

    async with session_factory() as session:
        await _reset(session)
        await _seed(session)

    engage_started = asyncio.Event()
    engage_completed = asyncio.Event()
    spawn_committed = asyncio.Event()
    order: list[str] = []

    async def _spawn_lock_holder() -> None:
        # spawn の critical section を模す: lock 取得 → 保持 → (engage の待機を観測) → commit。
        async with session_factory() as session:
            await session.execute(
                text("select set_config('app.tenant_id', '1', true)")
            )
            await acquire_emergency_stop_lock(session, 1)
            order.append("spawn_lock_acquired")
            engage_started.set()  # engage を起動してよい
            # engage が lock 待ちで block していることを観測するため少し待つ。
            await asyncio.sleep(0.3)
            order.append("spawn_commit")
            await session.commit()  # lock 解放
            spawn_committed.set()

    async def _engage_waiter() -> None:
        await engage_started.wait()
        async with session_factory() as session:
            service = EmergencyStopService(session)
            # spawn が lock を保持中なので、この engage は lock 待ちで block する。
            await service.engage(tenant_id=1, operator_actor_id=ACTOR_OWNER_1)
            order.append("engage_done")
            await session.commit()
            engage_completed.set()

    await asyncio.gather(_spawn_lock_holder(), _engage_waiter())
    assert engage_completed.is_set()
    # engage は spawn の commit (lock 解放) より **後** に完了する (直列化された)。
    assert order.index("spawn_commit") < order.index("engage_done")

    # engage 後は latch が立ち、spawn latch check は deny する (A-1 直列化の効果)。
    async with session_factory() as session:
        with pytest.raises(EmergencyStopEngagedError):
            await _assert_not_emergency_stopped(1, session)
