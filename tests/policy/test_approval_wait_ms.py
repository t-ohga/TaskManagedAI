"""approval_wait_ms KPI metric service test (Sprint 3 Batch 4, BL-0038, AC-KPI-03)."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.services.metrics.approval_wait_ms import ApprovalWaitMsMetricService

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPORAL_CHECK_NAME = "approval_requests_ck_decided_at_after_requested_at"


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-approval-wait-ms",
        ),
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
            raise AssertionError(
                "approval_wait_ms metric tests require reachable test database."
            ) from exc
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


def _sqlstate(error: BaseException) -> str | None:
    queue: list[BaseException] = [error]
    seen: set[int] = set()

    while queue:
        current = queue.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))

        state = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if isinstance(state, str):
            return state

        cause = current.__cause__
        if cause is not None:
            queue.append(cause)

        context = current.__context__
        if context is not None:
            queue.append(context)

        for arg in getattr(current, "args", ()):
            if isinstance(arg, BaseException):
                queue.append(arg)

    return None


def _assert_integrity_error(
    error: IntegrityError,
    *,
    sqlstate: str,
    constraint_name: str,
) -> None:
    assert _sqlstate(error) == sqlstate
    assert constraint_name in str(error)


async def _restore_temporal_check_constraint(session: AsyncSession) -> None:
    if _TEMPORAL_CHECK_NAME != "approval_requests_ck_decided_at_after_requested_at":
        raise AssertionError("approval wait temporal check constraint name drifted.")

    await session.execute(
        text(
            """
            do $$
            begin
              if not exists (
                select 1
                from pg_constraint
                where conname = 'approval_requests_ck_decided_at_after_requested_at'
                  and conrelid = 'approval_requests'::regclass
              ) then
                alter table approval_requests
                  add constraint approval_requests_ck_decided_at_after_requested_at
                  check (decided_at is null or decided_at >= requested_at);
              end if;
            end
            $$;
            """
        )
    )


async def _seed_two_actors(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    a1 = uuid.UUID("00000000-0000-4000-8000-000000007e01")
    a2 = uuid.UUID("00000000-0000-4000-8000-000000007e02")
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (1, 'tenant-one', '{"rls_ready": true}'::jsonb)
            on conflict (id) do nothing
            """
        )
    )
    await session.execute(
        text(
            """
            insert into actors (
              id, tenant_id, actor_type, actor_id, display_name, auth_context_hash, metadata
            )
            values
              (:a1, 1, 'human', 'human:wait-ms-1', 'WM1', 'auth-1',
               '{"rls_ready": true}'::jsonb),
              (:a2, 1, 'human', 'human:wait-ms-2', 'WM2', 'auth-2',
               '{"rls_ready": true}'::jsonb)
            on conflict (tenant_id, actor_id) do nothing
            """
        ),
        {"a1": a1, "a2": a2},
    )
    return a1, a2


async def _insert_decided_approval(
    session: AsyncSession,
    *,
    approval_id: uuid.UUID,
    requester: uuid.UUID,
    decider: uuid.UUID,
    requested_at: datetime,
    decided_at: datetime,
    status: str = "approved",
) -> None:
    await session.execute(
        text(
            """
            insert into approval_requests (
              id, tenant_id, action_class, resource_ref, risk_level, status,
              requested_by_actor_id, decided_by_actor_id, requested_at, decided_at,
              policy_version, metadata
            )
            values (
              :id, 1, 'task_write', 'ticket:wait-ms', 'low', :status,
              :req, :dec, :rat, :dat,
              '2026-05-08-initial', '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "id": approval_id,
            "status": status,
            "req": requester,
            "dec": decider,
            "rat": requested_at,
            "dat": decided_at,
        },
    )


@pytest.mark.asyncio
async def test_approval_wait_ms_aggregate_returns_median_from_db(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await session.execute(text("truncate approval_requests cascade"))
        requester, decider = await _seed_two_actors(session)
        base = datetime(2026, 5, 1, 10, 0, 0, tzinfo=UTC)
        await _insert_decided_approval(
            session,
            approval_id=uuid.UUID("00000000-0000-4000-8000-000000007f01"),
            requester=requester,
            decider=decider,
            requested_at=base,
            decided_at=base + timedelta(minutes=30),
        )
        await _insert_decided_approval(
            session,
            approval_id=uuid.UUID("00000000-0000-4000-8000-000000007f02"),
            requester=requester,
            decider=decider,
            requested_at=base + timedelta(hours=1),
            decided_at=base + timedelta(hours=3),
        )
        await _insert_decided_approval(
            session,
            approval_id=uuid.UUID("00000000-0000-4000-8000-000000007f03"),
            requester=requester,
            decider=decider,
            requested_at=base + timedelta(hours=2),
            decided_at=base + timedelta(hours=6),
            status="rejected",
        )
        await session.commit()

        service = ApprovalWaitMsMetricService(session)
        result = await service.aggregate(tenant_id=1)

    assert result.sample_count == 3
    assert result.median_ms == pytest.approx(7_200_000.0, rel=1e-3)
    assert result.p95_ms == pytest.approx(13_680_000.0, rel=1e-3)
    assert result.min_ms == pytest.approx(1_800_000.0, rel=1e-3)
    assert result.max_ms == pytest.approx(14_400_000.0, rel=1e-3)


@pytest.mark.asyncio
async def test_approval_wait_ms_excludes_pending_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await session.execute(text("truncate approval_requests cascade"))
        requester, _decider = await _seed_two_actors(session)
        await session.execute(
            text(
                """
                insert into approval_requests (
                  id, tenant_id, action_class, resource_ref, risk_level, status,
                  requested_by_actor_id, requested_at, policy_version, metadata
                )
                values (
                  '00000000-0000-4000-8000-000000007f04', 1, 'task_write',
                  'ticket:pending', 'low', 'pending', :req,
                  '2026-05-01T10:00:00+00:00',
                  '2026-05-08-initial', '{"rls_ready": true}'::jsonb
                )
                """
            ),
            {"req": requester},
        )
        await session.commit()

        service = ApprovalWaitMsMetricService(session)
        result = await service.aggregate(tenant_id=1)

    assert result.sample_count == 0
    assert result.median_ms is None


@pytest.mark.asyncio
async def test_approval_wait_ms_period_filter(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await session.execute(text("truncate approval_requests cascade"))
        requester, decider = await _seed_two_actors(session)
        early = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)
        late = datetime(2026, 5, 1, 10, 0, 0, tzinfo=UTC)
        await _insert_decided_approval(
            session,
            approval_id=uuid.UUID("00000000-0000-4000-8000-000000007f05"),
            requester=requester,
            decider=decider,
            requested_at=early,
            decided_at=early + timedelta(hours=1),
        )
        await _insert_decided_approval(
            session,
            approval_id=uuid.UUID("00000000-0000-4000-8000-000000007f06"),
            requester=requester,
            decider=decider,
            requested_at=late,
            decided_at=late + timedelta(hours=2),
        )
        await session.commit()

        service = ApprovalWaitMsMetricService(session)
        result = await service.aggregate(
            tenant_id=1,
            period_start=datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC),
        )

    assert result.sample_count == 1
    assert result.median_ms == pytest.approx(2 * 60 * 60 * 1000, rel=1e-3)


@pytest.mark.asyncio
async def test_approval_wait_ms_empty_returns_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await session.execute(text("truncate approval_requests cascade"))
        await session.commit()

        service = ApprovalWaitMsMetricService(session)
        result = await service.aggregate(tenant_id=1)

    assert result.sample_count == 0
    assert result.median_ms is None
    assert result.min_ms is None


@pytest.mark.asyncio
async def test_approval_requests_rejects_decided_at_before_requested_at(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await session.execute(text("truncate approval_requests cascade"))
        requester, decider = await _seed_two_actors(session)
        base = datetime(2026, 5, 1, 10, 0, 0, tzinfo=UTC)

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_decided_approval(
                session,
                approval_id=uuid.UUID("00000000-0000-4000-8000-000000007f07"),
                requester=requester,
                decider=decider,
                requested_at=base,
                decided_at=base - timedelta(minutes=1),
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name=_TEMPORAL_CHECK_NAME,
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_approval_wait_ms_aggregate_excludes_negative_wait_ms_if_db_is_tampered(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    result = None

    async with session_factory() as session:
        await session.execute(text("truncate approval_requests cascade"))
        requester, decider = await _seed_two_actors(session)
        base = datetime(2026, 5, 1, 10, 0, 0, tzinfo=UTC)

        await session.execute(
            text(
                f"alter table approval_requests drop constraint if exists {_TEMPORAL_CHECK_NAME}"
            )
        )
        try:
            await _insert_decided_approval(
                session,
                approval_id=uuid.UUID("00000000-0000-4000-8000-000000007f08"),
                requester=requester,
                decider=decider,
                requested_at=base,
                decided_at=base + timedelta(hours=1),
            )
            await _insert_decided_approval(
                session,
                approval_id=uuid.UUID("00000000-0000-4000-8000-000000007f09"),
                requester=requester,
                decider=decider,
                requested_at=base + timedelta(hours=2),
                decided_at=base + timedelta(hours=1),
                status="rejected",
            )
            await session.commit()

            service = ApprovalWaitMsMetricService(session)
            result = await service.aggregate(tenant_id=1)
        finally:
            await session.rollback()
            await session.execute(text("delete from approval_requests"))
            await _restore_temporal_check_constraint(session)
            await session.commit()

    assert result is not None
    assert result.sample_count == 1
    assert result.median_ms == pytest.approx(3_600_000.0, rel=1e-3)
    assert result.p95_ms == pytest.approx(3_600_000.0, rel=1e-3)

