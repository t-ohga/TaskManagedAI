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
from backend.app.db.models.approval_request import ApprovalRequest
from backend.app.db.session import create_engine
from backend.app.services.policy.self_approval_guard import SelfApprovalGuardService

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

REQUESTER_ACTOR_ID = UUID("00000000-0000-4000-8000-000000000801")
DECIDER_ACTOR_ID = UUID("00000000-0000-4000-8000-000000000802")
APPROVAL_REQUEST_ID = UUID("00000000-0000-4000-8000-000000000811")


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-self-approval-tests",
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
            raise AssertionError("Self-approval tests require a reachable test database.") from exc
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
        getattr(error.orig, 'constraint_name', None)
        or getattr(getattr(error.orig, '__cause__', None), 'constraint_name', None)
    )
    assert actual_constraint_name == constraint_name


async def _reset_approval_tables(session: AsyncSession) -> None:
    await session.execute(text("truncate policy_decisions, approval_requests restart identity cascade"))


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
              'self-approval-auth-context',
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
        stable_actor_id="human:self-approval-requester",
        display_name="Self Approval Requester",
    )
    await _insert_actor(
        session,
        tenant_id=1,
        actor_id=DECIDER_ACTOR_ID,
        stable_actor_id="human:self-approval-decider",
        display_name="Self Approval Decider",
    )
    await session.commit()


async def _insert_pending_approval(session: AsyncSession, approval_id: UUID) -> None:
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
              'pending',
              :requested_by_actor_id,
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {"id": approval_id, "requested_by_actor_id": REQUESTER_ACTOR_ID},
    )


@pytest.mark.asyncio
async def test_db_check_rejects_self_approval(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)

        with pytest.raises(IntegrityError) as exc_info:
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
                      'approved',
                      :actor_id,
                      :actor_id,
                      now(),
                      '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {"id": APPROVAL_REQUEST_ID, "actor_id": REQUESTER_ACTOR_ID},
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="approval_requests_ck_self_approval",
        )
        await session.rollback()


def test_service_guard_rejects_self_approval() -> None:
    approval = ApprovalRequest(
        id=uuid4(),
        tenant_id=1,
        action_class="task_write",
        resource_ref="task:TASK-1",
        risk_level="medium",
        policy_version="policy-v1",
        status="pending",
        requested_by_actor_id=REQUESTER_ACTOR_ID,
    )

    with pytest.raises(ValueError, match="self-approval is forbidden"):
        SelfApprovalGuardService.assert_not_self_approval(
            approval,
            REQUESTER_ACTOR_ID,
        )


@pytest.mark.asyncio
async def test_decided_at_consistency_check_constraint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)

        with pytest.raises(IntegrityError) as exc_info:
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
                      'pending',
                      :requested_by_actor_id,
                      now(),
                      '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {"id": APPROVAL_REQUEST_ID, "requested_by_actor_id": REQUESTER_ACTOR_ID},
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="approval_requests_ck_decided_at_consistency",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_self_approval_negative_with_pending_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        await _insert_pending_approval(session, APPROVAL_REQUEST_ID)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    update approval_requests
                    set
                      decided_by_actor_id = requested_by_actor_id,
                      decided_at = now()
                    where tenant_id = 1
                      and id = :id
                      and status = 'pending'
                    """
                ),
                {"id": APPROVAL_REQUEST_ID},
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="approval_requests_ck_self_approval",
        )
        await session.rollback()
