from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.agent_run_event import AgentRunEvent
from backend.app.db.session import create_engine
from backend.app.services.orchestrator.dispatcher import OrchestratorDispatcher
from backend.app.services.orchestrator.failover import OrchestratorFailover
from backend.app.services.orchestrator.kill_switch import OrchestratorKillSwitch
from backend.app.services.orchestrator.lease_manager import OrchestratorLeaseManager
from backend.app.services.orchestrator.progress_lease import OrchestratorProgressLease

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-000000014001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000014002")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000014003")
RUN_ID = UUID("00000000-0000-4000-8000-000000014004")
CHILD_RUN_ID = UUID("00000000-0000-4000-8000-000000014005")

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
        dev_login_cookie_secret="test-cookie-secret-orchestrator-lease",
    )


def _run_alembic_upgrade(database_url: str) -> None:
    previous_database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        command.upgrade(Config(os.path.join(_REPO_ROOT, "alembic.ini")), "head")
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
            raise AssertionError("orchestrator lease tests require PostgreSQL.") from exc
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
            truncate
              agent_run_events,
              agent_runs,
              project_agent_roles,
              projects,
              workspaces,
              actors,
              tenants
            restart identity cascade
            """
        )
    )


async def _insert_fixture_run(
    session: AsyncSession,
    *,
    run_id: UUID = RUN_ID,
    role_id: str = "orchestrator",
    role_scope: str = "global",
    status: str = "running",
    actor_type: str = "human",
    lease_token: UUID | None = None,
    lease_expires_at: datetime | None = None,
    last_progress_at: datetime | None = None,
) -> None:
    await _reset_tables(session)
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
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values (:actor_id, 1, :actor_type, :actor_ref,
                    'Orchestrator Test Actor', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "actor_id": ACTOR_ID,
            "actor_type": actor_type,
            "actor_ref": f"{actor_type}:orchestrator-test",
        },
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'orchestrator-workspace', 'orchestrator-workspace',
                    :actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (:project_id, 1, :workspace_id, 'orchestrator-project',
                    'orchestrator-project', 'active', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"project_id": PROJECT_ID, "workspace_id": WORKSPACE_ID},
    )
    await session.execute(
        text(
            """
            insert into agent_runs (
              id, tenant_id, project_id, status, role_id, role_scope,
              orchestrator_lease_token, orchestrator_lease_expires_at,
              last_progress_at
            )
            values (
              :run_id, 1, :project_id, :status, :role_id, :role_scope,
              :lease_token, :lease_expires_at, :last_progress_at
            )
            """
        ),
        {
            "run_id": run_id,
            "project_id": PROJECT_ID,
            "status": status,
            "role_id": role_id,
            "role_scope": role_scope,
            "lease_token": lease_token,
            "lease_expires_at": lease_expires_at,
            "last_progress_at": last_progress_at,
        },
    )


async def _load_run(session: AsyncSession, run_id: UUID = RUN_ID) -> AgentRun:
    run = await session.scalar(
        select(AgentRun).where(AgentRun.tenant_id == TENANT_ID, AgentRun.id == run_id)
    )
    assert run is not None
    return run


async def _event_count(session: AsyncSession, run_id: UUID = RUN_ID) -> int:
    result = await session.scalar(
        select(func.count()).select_from(AgentRunEvent).where(AgentRunEvent.run_id == run_id)
    )
    return int(result or 0)


async def _insert_child_run(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            insert into agent_runs (
              id, tenant_id, project_id, parent_run_id, status, role_id, role_scope
            )
            values (
              :child_run_id, 1, :project_id, :parent_run_id, 'queued',
              'implementer', 'global'
            )
            """
        ),
        {
            "child_run_id": CHILD_RUN_ID,
            "project_id": PROJECT_ID,
            "parent_run_id": RUN_ID,
        },
    )


async def _insert_standby_orchestrator(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            insert into agent_runs (
              id, tenant_id, project_id, status, role_id, role_scope
            )
            values (
              :child_run_id, 1, :project_id, 'queued',
              'orchestrator', 'global'
            )
            """
        ),
        {"child_run_id": CHILD_RUN_ID, "project_id": PROJECT_ID},
    )


@pytest.mark.asyncio
async def test_renew_lease_updates_token_and_appends_hash_only_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    old_token = uuid4()
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture_run(
                session,
                lease_token=old_token,
                lease_expires_at=now + timedelta(minutes=5),
            )

        async with session.begin():
            result = await OrchestratorLeaseManager(session).renew_lease(
                tenant_id=TENANT_ID,
                run_id=RUN_ID,
                actor_id=ACTOR_ID,
                current_lease_token=old_token,
                ttl=timedelta(seconds=60),
                now=now,
            )

        assert result is not None
        assert result.new_lease_token != old_token
        assert result.expires_at == now + timedelta(seconds=60)

        run = await _load_run(session)
        assert run.orchestrator_lease_token == result.new_lease_token
        assert run.orchestrator_lease_expires_at == result.expires_at

        event = await session.scalar(select(AgentRunEvent).where(AgentRunEvent.run_id == RUN_ID))
        assert event is not None
        assert event.event_type == "orchestrator_lease_renewed"
        assert event.event_payload["lease_token_hash"] == result.new_lease_token_hash
        assert old_token.hex not in str(event.event_payload)
        assert result.new_lease_token.hex not in str(event.event_payload)


@pytest.mark.asyncio
async def test_renew_lease_rejects_wrong_token_without_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    old_token = uuid4()
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture_run(
                session,
                lease_token=old_token,
                lease_expires_at=now + timedelta(minutes=5),
            )

        async with session.begin():
            result = await OrchestratorLeaseManager(session).renew_lease(
                tenant_id=TENANT_ID,
                run_id=RUN_ID,
                actor_id=ACTOR_ID,
                current_lease_token=uuid4(),
                now=now,
            )

        assert result is None
        run = await _load_run(session)
        assert run.orchestrator_lease_token == old_token
        assert await _event_count(session) == 0


@pytest.mark.asyncio
async def test_renew_lease_rejects_non_running_run_without_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    old_token = uuid4()
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture_run(
                session,
                status="queued",
                lease_token=old_token,
                lease_expires_at=now + timedelta(minutes=5),
            )

        async with session.begin():
            result = await OrchestratorLeaseManager(session).renew_lease(
                tenant_id=TENANT_ID,
                run_id=RUN_ID,
                actor_id=ACTOR_ID,
                current_lease_token=old_token,
                now=now,
            )

        assert result is None
        run = await _load_run(session)
        assert run.status == "queued"
        assert run.orchestrator_lease_token == old_token
        assert await _event_count(session) == 0


@pytest.mark.asyncio
async def test_non_orchestrator_run_cannot_renew_lease(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    token = uuid4()
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture_run(
                session,
                role_id="implementer",
                lease_token=token,
                lease_expires_at=now + timedelta(minutes=5),
            )

        async with session.begin():
            result = await OrchestratorLeaseManager(session).renew_lease(
                tenant_id=TENANT_ID,
                run_id=RUN_ID,
                actor_id=ACTOR_ID,
                current_lease_token=token,
                now=now,
            )

        assert result is None
        assert await _event_count(session) == 0


@pytest.mark.asyncio
async def test_expire_stale_lease_blocks_running_run_with_runtime_reason(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    token = uuid4()
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture_run(
                session,
                lease_token=token,
                lease_expires_at=now - timedelta(seconds=1),
            )

        async with session.begin():
            result = await OrchestratorLeaseManager(session).expire_stale_lease(
                tenant_id=TENANT_ID,
                run_id=RUN_ID,
                actor_id=ACTOR_ID,
                now=now,
            )

        assert result is not None
        run = await _load_run(session)
        assert run.status == "blocked"
        assert run.blocked_reason == "runtime_blocked"
        assert run.error_code == "lease_expired_no_secret_access"

        event = await session.scalar(select(AgentRunEvent).where(AgentRunEvent.run_id == RUN_ID))
        assert event is not None
        assert event.event_type == "orchestrator_lease_expired"
        assert event.event_payload["reason_code"] == "lease_expired_no_secret_access"
        assert token.hex not in str(event.event_payload)


@pytest.mark.asyncio
async def test_failover_promotes_queued_standby_and_appends_hash_only_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    token = uuid4()
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture_run(
                session,
                lease_token=token,
                lease_expires_at=now - timedelta(seconds=1),
            )
            await _insert_standby_orchestrator(session)

        async with session.begin():
            result = await OrchestratorFailover(session).trigger_existing_standby(
                tenant_id=TENANT_ID,
                expired_run_id=RUN_ID,
                standby_run_id=CHILD_RUN_ID,
                actor_id=ACTOR_ID,
                now=now,
            )

        assert result is not None
        expired_run = await _load_run(session)
        standby_run = await _load_run(session, CHILD_RUN_ID)
        assert expired_run.status == "blocked"
        assert expired_run.blocked_reason == "runtime_blocked"
        assert expired_run.error_code == "lease_expired_no_secret_access"
        assert standby_run.status == "running"
        assert standby_run.orchestrator_lease_token == result.new_lease_token

        events = (
            await session.execute(
                select(AgentRunEvent)
                .where(AgentRunEvent.run_id == RUN_ID)
                .order_by(AgentRunEvent.seq_no)
            )
        ).scalars().all()
        assert [event.event_type for event in events] == [
            "orchestrator_lease_expired",
            "orchestrator_failover_triggered",
        ]
        assert events[1].event_payload["new_orchestrator_run_id"] == str(CHILD_RUN_ID)
        assert events[1].event_payload["new_lease_hash"] == result.new_lease_token_hash
        assert token.hex not in str(events[0].event_payload)
        assert result.new_lease_token.hex not in str(events[1].event_payload)


@pytest.mark.asyncio
async def test_progress_lease_blocks_no_progress_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture_run(
                session,
                last_progress_at=now - timedelta(minutes=45),
            )

        async with session.begin():
            result = await OrchestratorProgressLease(session).block_no_progress(
                tenant_id=TENANT_ID,
                run_id=RUN_ID,
                actor_id=ACTOR_ID,
                now=now,
            )

        assert result is not None
        run = await _load_run(session)
        assert run.status == "blocked"
        assert run.blocked_reason == "runtime_blocked"
        assert run.error_code == "progress_lease_violated"

        event = await session.scalar(select(AgentRunEvent).where(AgentRunEvent.run_id == RUN_ID))
        assert event is not None
        assert event.event_payload["reason_code"] == "progress_lease_violated"


@pytest.mark.asyncio
async def test_record_progress_rejects_non_running_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture_run(session, status="waiting_approval")

        async with session.begin():
            result = await OrchestratorProgressLease(session).record_progress(
                tenant_id=TENANT_ID,
                run_id=RUN_ID,
                now=now,
            )

        assert result is None
        run = await _load_run(session)
        assert run.status == "waiting_approval"
        assert run.last_progress_at is None
        assert run.progress_seq == 0


@pytest.mark.asyncio
async def test_kill_switch_does_not_mutate_terminal_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture_run(session, status="completed")

        async with session.begin():
            result = await OrchestratorKillSwitch(session).engage(
                tenant_id=TENANT_ID,
                run_id=RUN_ID,
                actor_id=ACTOR_ID,
                reason="manual stop",
            )

        assert result is None
        run = await _load_run(session)
        assert run.status == "completed"
        assert await _event_count(session) == 0


@pytest.mark.asyncio
async def test_kill_switch_rejects_non_running_run_without_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture_run(session, status="queued")

        async with session.begin():
            result = await OrchestratorKillSwitch(session).engage(
                tenant_id=TENANT_ID,
                run_id=RUN_ID,
                actor_id=ACTOR_ID,
                reason="manual stop",
            )

        assert result is None
        run = await _load_run(session)
        assert run.status == "queued"
        assert await _event_count(session) == 0


@pytest.mark.asyncio
async def test_kill_switch_requires_human_actor_without_mutation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture_run(session, actor_type="service")

        with pytest.raises(ValueError, match="human actor"):
            async with session.begin():
                await OrchestratorKillSwitch(session).engage(
                    tenant_id=TENANT_ID,
                    run_id=RUN_ID,
                    actor_id=ACTOR_ID,
                    reason="manual stop",
                )

        run = await _load_run(session)
        assert run.status == "running"
        assert await _event_count(session) == 0


@pytest.mark.asyncio
async def test_record_local_dispatch_requires_existing_orchestrator_parent_and_child(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture_run(session)
            await _insert_child_run(session)

        async with session.begin():
            result = await OrchestratorDispatcher(session).record_local_dispatch(
                tenant_id=TENANT_ID,
                parent_run_id=RUN_ID,
                child_run_id=CHILD_RUN_ID,
                actor_id=ACTOR_ID,
                dispatch_reason="split implementation task",
                recommended_provider="balanced",
            )

        assert result.child_run_id == CHILD_RUN_ID
        event = await session.scalar(select(AgentRunEvent).where(AgentRunEvent.run_id == RUN_ID))
        assert event is not None
        assert event.event_type == "orchestrator_dispatched"
        assert event.event_payload["child_run_id"] == str(CHILD_RUN_ID)
        assert event.event_payload["role_id"] == "implementer"


@pytest.mark.asyncio
async def test_record_local_dispatch_rejects_non_running_parent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture_run(session, status="waiting_approval")
            await _insert_child_run(session)

        with pytest.raises(ValueError, match="running orchestrator"):
            async with session.begin():
                await OrchestratorDispatcher(session).record_local_dispatch(
                    tenant_id=TENANT_ID,
                    parent_run_id=RUN_ID,
                    child_run_id=CHILD_RUN_ID,
                    actor_id=ACTOR_ID,
                    dispatch_reason="split implementation task",
                    recommended_provider="balanced",
                )

        assert await _event_count(session) == 0
