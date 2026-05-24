from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
from backend.app.seeds.initial import (
    DEFAULT_ACTOR_ID,
    DEFAULT_PROJECT_ID,
    DEFAULT_TENANT_ID,
    seed_initial,
)
from backend.app.services.metrics.agent_run_kpi import AgentRunKpiService

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

RUN_ID = UUID("00000000-0000-4000-8000-00000000f101")
MISSING_RUN_ID = UUID("00000000-0000-4000-8000-00000000ffff")


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-agent-run-kpi",
    )


def _run_alembic_upgrade(database_url: str) -> None:
    previous_database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        config = Config(str(_REPO_ROOT / "alembic.ini"))
        command.upgrade(config, "head")
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
            raise AssertionError("AgentRun KPI tests require PostgreSQL.") from exc
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


async def _reset_and_seed(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate
              agent_run_events,
              agent_runs,
              audit_events,
              notification_events,
              acceptance_criteria,
              tickets,
              repositories,
              projects,
              workspaces,
              principals,
              actors,
              tenants
            restart identity cascade
            """
        )
    )
    await seed_initial(session)


async def _insert_run(
    session: AsyncSession,
    *,
    run_id: UUID = RUN_ID,
    status: str = "completed",
    completed_at: datetime | None,
    created_at: datetime,
) -> None:
    await session.execute(
        text(
            """
            insert into agent_runs (
              id, tenant_id, project_id, status, completed_at, created_at, updated_at
            )
            values (
              :run_id, :tenant_id, :project_id, :status,
              :completed_at, :created_at, :created_at
            )
            """
        ),
        {
            "run_id": run_id,
            "tenant_id": DEFAULT_TENANT_ID,
            "project_id": DEFAULT_PROJECT_ID,
            "status": status,
            "completed_at": completed_at,
            "created_at": created_at,
        },
    )


async def _insert_event(
    session: AsyncSession,
    *,
    seq_no: int,
    event_type: str = "repo_pr_opened",
    created_at: datetime,
) -> None:
    await session.execute(
        text(
            """
            insert into agent_run_events (
              id, tenant_id, run_id, seq_no, event_type, event_payload,
              actor_id, idempotency_key, created_at
            )
            values (
              :event_id, :tenant_id, :run_id, :seq_no, :event_type,
              '{"repo_full_name": "t/example", "pr_number": 42}'::jsonb,
              :actor_id, :idempotency_key, :created_at
            )
            """
        ),
        {
            "event_id": UUID(f"00000000-0000-4000-8000-00000000f2{seq_no:02d}"),
            "tenant_id": DEFAULT_TENANT_ID,
            "run_id": RUN_ID,
            "seq_no": seq_no,
            "event_type": event_type,
            "actor_id": DEFAULT_ACTOR_ID,
            "idempotency_key": f"agent-run-kpi:{seq_no}",
            "created_at": created_at,
        },
    )


@pytest.mark.asyncio
async def test_agent_run_kpi_uses_first_repo_pr_opened_event_as_time_to_merge_source(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    base = datetime(2026, 5, 24, 9, 0, tzinfo=UTC)
    async with session_factory() as session:
        await _reset_and_seed(session)
        await _insert_run(
            session,
            completed_at=base + timedelta(hours=2),
            created_at=base,
        )
        await _insert_event(session, seq_no=1, created_at=base + timedelta(minutes=15))
        await _insert_event(
            session,
            seq_no=2,
            event_type="provider_responded",
            created_at=base + timedelta(minutes=20),
        )
        await _insert_event(session, seq_no=3, created_at=base + timedelta(minutes=45))
        await session.commit()

        result = await AgentRunKpiService(session).fetch(
            tenant_id=DEFAULT_TENANT_ID,
            run_id=RUN_ID,
        )

    assert result is not None
    assert result.project_id == DEFAULT_PROJECT_ID
    assert result.status == "completed"
    assert result.repo_pr_opened_event_count == 2
    assert result.first_repo_pr_opened_at == base + timedelta(minutes=15)
    assert result.time_to_merge_proxy_sample_count == 1
    assert result.time_to_merge_proxy_ms == pytest.approx(6_300_000.0)
    assert (
        result.time_to_merge_proxy_source
        == "repo_pr_opened_to_agent_run_completed"
    )


@pytest.mark.asyncio
async def test_agent_run_kpi_does_not_count_running_runs_as_time_to_merge_samples(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    base = datetime(2026, 5, 24, 9, 0, tzinfo=UTC)
    async with session_factory() as session:
        await _reset_and_seed(session)
        await _insert_run(
            session,
            status="running",
            completed_at=None,
            created_at=base,
        )
        await _insert_event(session, seq_no=1, created_at=base + timedelta(minutes=15))
        await session.commit()

        result = await AgentRunKpiService(session).fetch(
            tenant_id=DEFAULT_TENANT_ID,
            run_id=RUN_ID,
        )

    assert result is not None
    assert result.repo_pr_opened_event_count == 1
    assert result.first_repo_pr_opened_at == base + timedelta(minutes=15)
    assert result.time_to_merge_proxy_sample_count == 0
    assert result.time_to_merge_proxy_ms is None


@pytest.mark.asyncio
async def test_agent_run_kpi_rejects_negative_temporal_samples(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    base = datetime(2026, 5, 24, 9, 0, tzinfo=UTC)
    async with session_factory() as session:
        await _reset_and_seed(session)
        await _insert_run(
            session,
            completed_at=base + timedelta(minutes=10),
            created_at=base,
        )
        await _insert_event(session, seq_no=1, created_at=base + timedelta(minutes=15))
        await session.commit()

        result = await AgentRunKpiService(session).fetch(
            tenant_id=DEFAULT_TENANT_ID,
            run_id=RUN_ID,
        )

    assert result is not None
    assert result.repo_pr_opened_event_count == 1
    assert result.time_to_merge_proxy_sample_count == 0
    assert result.time_to_merge_proxy_ms is None


@pytest.mark.asyncio
async def test_agent_run_kpi_returns_none_for_missing_or_cross_tenant_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    base = datetime(2026, 5, 24, 9, 0, tzinfo=UTC)
    async with session_factory() as session:
        await _reset_and_seed(session)
        await _insert_run(
            session,
            completed_at=base + timedelta(hours=1),
            created_at=base,
        )
        await session.commit()

        missing = await AgentRunKpiService(session).fetch(
            tenant_id=DEFAULT_TENANT_ID,
            run_id=MISSING_RUN_ID,
        )

    async with session_factory() as session:
        cross_tenant = await AgentRunKpiService(session).fetch(
            tenant_id=DEFAULT_TENANT_ID + 1,
            run_id=RUN_ID,
        )

    assert missing is None
    assert cross_tenant is None
