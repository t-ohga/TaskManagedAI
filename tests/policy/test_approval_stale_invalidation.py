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
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.approval_request import ApprovalRequest
from backend.app.db.session import create_engine
from backend.app.services.policy.invalidation import (
    ApprovalStaleInvalidationService,
    StaleCheckPayload,
    StaleCheckReason,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

REQUESTER_ACTOR_ID = UUID("00000000-0000-4000-8000-000000000901")
DECIDER_ACTOR_ID = UUID("00000000-0000-4000-8000-000000000902")
APPROVAL_REQUEST_ID = UUID("00000000-0000-4000-8000-000000000911")


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-approval-stale-invalidation-tests",
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
                "Approval stale invalidation tests require a reachable test database."
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
              'approval-stale-auth-context',
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
        stable_actor_id="human:approval-stale-requester",
        display_name="Approval Stale Requester",
    )
    await _insert_actor(
        session,
        tenant_id=1,
        actor_id=DECIDER_ACTOR_ID,
        stable_actor_id="human:approval-stale-decider",
        display_name="Approval Stale Decider",
    )


async def _insert_approval(
    session: AsyncSession,
    *,
    approval_id: UUID = APPROVAL_REQUEST_ID,
    status: str = "pending",
    requested_by_actor_id: UUID = REQUESTER_ACTOR_ID,
    decided_by_actor_id: UUID | None = None,
    artifact_hash: str | None = "artifact-a",
    diff_hash: str | None = "diff-a",
    policy_version: str = "policy-v1",
    policy_pack_lock: str | None = "pack-a",
    provider_request_fingerprint: str | None = "provider-a",
) -> ApprovalRequest:
    decided_at: datetime | None = None
    if decided_by_actor_id is not None:
        decided_at = datetime(2030, 1, 1, tzinfo=UTC)

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
              :artifact_hash,
              :diff_hash,
              :policy_version,
              :policy_pack_lock,
              :provider_request_fingerprint,
              1,
              :status,
              :requested_by_actor_id,
              :decided_by_actor_id,
              cast(:decided_at as timestamptz),
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "id": approval_id,
            "artifact_hash": artifact_hash,
            "diff_hash": diff_hash,
            "policy_version": policy_version,
            "policy_pack_lock": policy_pack_lock,
            "provider_request_fingerprint": provider_request_fingerprint,
            "status": status,
            "requested_by_actor_id": requested_by_actor_id,
            "decided_by_actor_id": decided_by_actor_id,
            "decided_at": decided_at,
        },
    )
    approval = await session.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.tenant_id == 1,
            ApprovalRequest.id == approval_id,
        )
    )
    assert approval is not None
    return approval


def _payload_for(
    approval: ApprovalRequest,
    **overrides: str | None,
) -> StaleCheckPayload:
    values = {
        "artifact_hash": approval.artifact_hash,
        "diff_hash": approval.diff_hash,
        "policy_version": approval.policy_version,
        "policy_pack_lock": approval.policy_pack_lock,
        "provider_request_fingerprint": approval.provider_request_fingerprint,
    }
    values.update(overrides)
    return StaleCheckPayload(**values)


async def _invalidate_with_payload(
    session: AsyncSession,
    approval: ApprovalRequest,
    payload: StaleCheckPayload,
) -> list[StaleCheckReason]:
    service = ApprovalStaleInvalidationService(session)
    reasons = await service.invalidate_if_stale(tenant_id=1, approval=approval, payload=payload)
    await session.refresh(approval)
    return reasons


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


def _assert_single_reason(
    reasons: list[StaleCheckReason],
    *,
    field: str,
    old: str | None,
    new: str | None,
) -> None:
    assert reasons == [StaleCheckReason(field=field, old=old, new=new)]


@pytest.mark.asyncio
async def test_artifact_hash_change_invalidates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(session)

        reasons = await _invalidate_with_payload(
            session,
            approval,
            _payload_for(approval, artifact_hash="artifact-b"),
        )

    _assert_single_reason(reasons, field="artifact_hash", old="artifact-a", new="artifact-b")
    assert approval.status == "invalidated"


@pytest.mark.asyncio
async def test_diff_hash_change_invalidates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(session)

        reasons = await _invalidate_with_payload(
            session,
            approval,
            _payload_for(approval, diff_hash="diff-b"),
        )

    _assert_single_reason(reasons, field="diff_hash", old="diff-a", new="diff-b")
    assert approval.status == "invalidated"


@pytest.mark.asyncio
async def test_policy_version_change_invalidates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(session)

        reasons = await _invalidate_with_payload(
            session,
            approval,
            _payload_for(approval, policy_version="policy-v2"),
        )

    _assert_single_reason(reasons, field="policy_version", old="policy-v1", new="policy-v2")
    assert approval.status == "invalidated"


@pytest.mark.asyncio
async def test_policy_pack_lock_change_invalidates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(session)

        reasons = await _invalidate_with_payload(
            session,
            approval,
            _payload_for(approval, policy_pack_lock="pack-b"),
        )

    _assert_single_reason(reasons, field="policy_pack_lock", old="pack-a", new="pack-b")
    assert approval.status == "invalidated"


@pytest.mark.asyncio
async def test_provider_request_fingerprint_change_invalidates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(session)

        reasons = await _invalidate_with_payload(
            session,
            approval,
            _payload_for(approval, provider_request_fingerprint="provider-b"),
        )

    _assert_single_reason(
        reasons,
        field="provider_request_fingerprint",
        old="provider-a",
        new="provider-b",
    )
    assert approval.status == "invalidated"


@pytest.mark.asyncio
async def test_no_change_returns_empty_reasons(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(session)

        reasons = await _invalidate_with_payload(session, approval, _payload_for(approval))

    assert reasons == []
    assert approval.status == "pending"


@pytest.mark.asyncio
async def test_already_invalidated_skipped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(session, status="invalidated")

        reasons = await _invalidate_with_payload(
            session,
            approval,
            _payload_for(approval, artifact_hash="artifact-b"),
        )

    assert reasons == []
    assert approval.status == "invalidated"


@pytest.mark.asyncio
async def test_already_expired_skipped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(session, status="expired")

        reasons = await _invalidate_with_payload(
            session,
            approval,
            _payload_for(approval, diff_hash="diff-b"),
        )

    assert reasons == []
    assert approval.status == "expired"


@pytest.mark.asyncio
async def test_pending_status_invalidated(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(session, status="pending")

        reasons = await _invalidate_with_payload(
            session,
            approval,
            _payload_for(approval, policy_version="policy-v2"),
        )

    _assert_single_reason(reasons, field="policy_version", old="policy-v1", new="policy-v2")
    assert approval.status == "invalidated"


@pytest.mark.asyncio
async def test_approved_status_invalidated(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(
            session,
            status="approved",
            decided_by_actor_id=DECIDER_ACTOR_ID,
        )

        reasons = await _invalidate_with_payload(
            session,
            approval,
            _payload_for(approval, artifact_hash="artifact-b"),
        )

    _assert_single_reason(reasons, field="artifact_hash", old="artifact-a", new="artifact-b")
    assert approval.status == "invalidated"


@pytest.mark.asyncio
async def test_concurrent_invalidation_returns_empty_reasons(
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

        reasons = await ApprovalStaleInvalidationService(session).invalidate_if_stale(
            tenant_id=1,
            approval=approval,
            payload=_payload_for(approval, artifact_hash="artifact-b"),
        )

        assert reasons == []
        assert await _approval_status(session) == "invalidated"


@pytest.mark.asyncio
async def test_concurrent_expired_returns_empty_reasons(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(session)

        await session.execute(
            text(
                """
                update approval_requests
                set status = 'expired'
                where tenant_id = 1
                  and id = :id
                """
            ),
            {"id": approval.id},
        )
        assert approval.status == "pending"

        reasons = await ApprovalStaleInvalidationService(session).invalidate_if_stale(
            tenant_id=1,
            approval=approval,
            payload=_payload_for(approval, diff_hash="diff-b"),
        )

        assert reasons == []
        assert await _approval_status(session) == "expired"


@pytest.mark.asyncio
async def test_tenant_mismatch_returns_empty_reasons(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(session)

        reasons = await ApprovalStaleInvalidationService(session).invalidate_if_stale(
            tenant_id=2,
            approval=approval,
            payload=_payload_for(approval, policy_version="policy-v2"),
        )

        assert reasons == []
        assert await _approval_status(session) == "pending"
