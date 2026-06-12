from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.approval_request import ApprovalRequest
from backend.app.db.session import create_engine
from backend.app.repositories.approval_request import ApprovalRequestRepository
from backend.app.services.policy.decision_service import ApprovalDecisionService

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

REQUESTER_ACTOR_ID = UUID("00000000-0000-4000-8000-000000001001")
DECIDER_ACTOR_ID = UUID("00000000-0000-4000-8000-000000001002")
APPROVAL_REQUEST_ID = UUID("00000000-0000-4000-8000-000000001011")
APPROVAL_REQUEST_ID_2 = UUID("00000000-0000-4000-8000-000000001012")


class _DummySession:
    pass


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-approval-decision-service-tests",
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
                "Approval decision service tests require a reachable test database."
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
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

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
    actual_constraint_name = (
        getattr(error.orig, "constraint_name", None)
        or getattr(getattr(error.orig, "__cause__", None), "constraint_name", None)
    )
    assert actual_constraint_name == constraint_name


def _assert_integrity_error_with_any_constraint(
    error: IntegrityError,
    *,
    sqlstate: str,
    constraint_names: set[str],
) -> None:
    assert _sqlstate(error) == sqlstate
    actual_constraint_name = (
        getattr(error.orig, "constraint_name", None)
        or getattr(getattr(error.orig, "__cause__", None), "constraint_name", None)
    )
    assert actual_constraint_name in constraint_names


async def _reset_approval_tables(session: AsyncSession) -> None:
    await session.execute(
        text("truncate policy_decisions, approval_requests restart identity cascade")
    )


async def _insert_tenant(session: AsyncSession, tenant_id: int, name: str) -> None:
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (:tenant_id, :name, '{"rls_ready": true}'::jsonb)
            on conflict (id) do update set name = excluded.name
            """
        ),
        {"tenant_id": tenant_id, "name": name},
    )


async def _insert_actor(
    session: AsyncSession,
    *,
    tenant_id: int,
    actor_id: UUID,
    stable_actor_id: str,
    display_name: str,
) -> None:
    await session.execute(
        text(
            """
            insert into actors (
              id,
              tenant_id,
              actor_type,
              actor_id,
              display_name,
              auth_context_hash,
              metadata
            )
            values (
              :actor_uuid,
              :tenant_id,
              'human',
              :stable_actor_id,
              :display_name,
              'approval-decision-auth-context',
              '{"rls_ready": true}'::jsonb
            )
            on conflict (id) do update set
              actor_type = excluded.actor_type,
              actor_id = excluded.actor_id,
              display_name = excluded.display_name,
              auth_context_hash = excluded.auth_context_hash,
              metadata = excluded.metadata
            """
        ),
        {
            "actor_uuid": actor_id,
            "tenant_id": tenant_id,
            "stable_actor_id": stable_actor_id,
            "display_name": display_name,
        },
    )


async def _setup_actors(session: AsyncSession) -> None:
    await _reset_approval_tables(session)
    await _insert_tenant(session, 1, "tenant-one")
    await _insert_actor(
        session,
        tenant_id=1,
        actor_id=REQUESTER_ACTOR_ID,
        stable_actor_id="human:approval-decision-requester",
        display_name="Approval Decision Requester",
    )
    await _insert_actor(
        session,
        tenant_id=1,
        actor_id=DECIDER_ACTOR_ID,
        stable_actor_id="human:approval-decision-decider",
        display_name="Approval Decision Decider",
    )


async def _insert_approval(
    session: AsyncSession,
    *,
    approval_id: UUID = APPROVAL_REQUEST_ID,
    status: str = "pending",
    requested_by_actor_id: UUID = REQUESTER_ACTOR_ID,
    decided_by_actor_id: UUID | None = None,
    decided_at: datetime | None = None,
) -> ApprovalRequest:
    await _insert_raw_approval_for_check(
        session,
        approval_id=approval_id,
        status=status,
        requested_by_actor_id=requested_by_actor_id,
        decided_by_actor_id=decided_by_actor_id,
        decided_at=decided_at,
    )
    approval = await session.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.tenant_id == 1,
            ApprovalRequest.id == approval_id,
        )
    )
    assert approval is not None
    return approval


async def _insert_raw_approval_for_check(
    session: AsyncSession,
    *,
    approval_id: UUID,
    status: str,
    requested_by_actor_id: UUID = REQUESTER_ACTOR_ID,
    decided_by_actor_id: UUID | None = None,
    decided_at: datetime | None = None,
) -> None:
    await session.execute(
        text(
            """
            insert into approval_requests (
              id,
              tenant_id,
              action_class,
              resource_ref,
              risk_level,
              artifact_hash,
              diff_hash,
              policy_version,
              policy_pack_lock,
              provider_request_fingerprint,
              stale_after_event_seq,
              status,
              requested_by_actor_id,
              decided_by_actor_id,
              decided_at,
              metadata
            )
            values (
              :id,
              1,
              'task_write',
              'task:TASK-1',
              'medium',
              'artifact-a',
              'diff-a',
              'policy-v1',
              'pack-a',
              'provider-a',
              1,
              :status,
              :requested_by_actor_id,
              :decided_by_actor_id,
              :decided_at,
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "id": approval_id,
            "status": status,
            "requested_by_actor_id": requested_by_actor_id,
            "decided_by_actor_id": decided_by_actor_id,
            "decided_at": decided_at,
        },
    )


async def _approval_status(
    session: AsyncSession,
    approval_id: UUID = APPROVAL_REQUEST_ID,
) -> str:
    status = await session.scalar(
        select(ApprovalRequest.status).where(
            ApprovalRequest.tenant_id == 1,
            ApprovalRequest.id == approval_id,
        )
    )
    assert status is not None
    return status


@pytest.mark.asyncio
async def test_approve_transitions_pending_to_approved(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(session)
        decided_at = datetime(2030, 1, 1, tzinfo=UTC)

        result = await ApprovalDecisionService(session).approve(
            tenant_id=1,
            approval=approval,
            decided_by_actor_id=DECIDER_ACTOR_ID,
            rationale="approved by policy owner",
            decided_at=decided_at,
        )

        assert result is approval
        assert approval.status == "approved"
        assert approval.decided_by_actor_id == DECIDER_ACTOR_ID
        assert approval.decided_at == decided_at
        assert approval.rationale == "approved by policy owner"
        assert await _approval_status(session) == "approved"


@pytest.mark.asyncio
async def test_reject_transitions_pending_to_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(session)
        decided_at = datetime(2030, 1, 2, tzinfo=UTC)

        result = await ApprovalDecisionService(session).reject(
            tenant_id=1,
            approval=approval,
            decided_by_actor_id=DECIDER_ACTOR_ID,
            rationale="risk is too high",
            decided_at=decided_at,
        )

        assert result is approval
        assert approval.status == "rejected"
        assert approval.decided_by_actor_id == DECIDER_ACTOR_ID
        assert approval.decided_at == decided_at
        assert approval.rationale == "risk is too high"
        assert await _approval_status(session) == "rejected"


@pytest.mark.asyncio
async def test_approve_rejects_self_approval(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(session)

        with pytest.raises(ValueError, match="self-approval is forbidden"):
            await ApprovalDecisionService(session).approve(
                tenant_id=1,
                approval=approval,
                decided_by_actor_id=REQUESTER_ACTOR_ID,
            )

        assert approval.status == "pending"
        assert await _approval_status(session) == "pending"


@pytest.mark.asyncio
async def test_approve_rejects_non_pending_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(session, status="invalidated")

        with pytest.raises(ValueError, match="expected 'pending'"):
            await ApprovalDecisionService(session).approve(
                tenant_id=1,
                approval=approval,
                decided_by_actor_id=DECIDER_ACTOR_ID,
            )

        assert approval.status == "invalidated"
        assert await _approval_status(session) == "invalidated"


@pytest.mark.asyncio
async def test_approve_atomic_update_handles_concurrent_modification(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(session)

        await session.execute(
            text(
                """
                update approval_requests
                set status = 'invalidated'
                where tenant_id = 1
                  and id = :id
                """
            ),
            {"id": approval.id},
        )
        assert approval.status == "pending"

        with pytest.raises(ValueError, match="concurrently modified"):
            await ApprovalDecisionService(session).approve(
                tenant_id=1,
                approval=approval,
                decided_by_actor_id=DECIDER_ACTOR_ID,
            )

        assert await _approval_status(session) == "invalidated"


@pytest.mark.asyncio
async def test_repository_update_rejects_status_change() -> None:
    repo = ApprovalRequestRepository(_DummySession())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="status"):
        await repo.update(
            tenant_id=1,
            id=APPROVAL_REQUEST_ID,
            payload={"status": "approved"},
        )


@pytest.mark.asyncio
async def test_repository_update_rejects_decided_by_actor_id_change() -> None:
    repo = ApprovalRequestRepository(_DummySession())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="decided_by_actor_id"):
        await repo.update(
            tenant_id=1,
            id=APPROVAL_REQUEST_ID,
            payload={"decided_by_actor_id": DECIDER_ACTOR_ID},
        )


@pytest.mark.asyncio
async def test_db_check_rejects_approved_without_decided_by_actor_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_raw_approval_for_check(
                session,
                approval_id=APPROVAL_REQUEST_ID,
                status="approved",
                decided_by_actor_id=None,
                decided_at=None,
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="approval_requests_ck_decision_completeness",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_db_check_rejects_approved_without_decided_at(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_raw_approval_for_check(
                session,
                approval_id=APPROVAL_REQUEST_ID_2,
                status="approved",
                decided_by_actor_id=DECIDER_ACTOR_ID,
                decided_at=None,
            )
            await session.commit()

        _assert_integrity_error_with_any_constraint(
            exc_info.value,
            sqlstate="23514",
            constraint_names={
                "approval_requests_ck_decision_completeness",
                "approval_requests_ck_decided_at_consistency",
            },
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_db_check_allows_pending_with_null_decision_fields(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)

        await _insert_raw_approval_for_check(
            session,
            approval_id=APPROVAL_REQUEST_ID,
            status="pending",
            decided_by_actor_id=None,
            decided_at=None,
        )
        await session.commit()

        assert await _approval_status(session) == "pending"

