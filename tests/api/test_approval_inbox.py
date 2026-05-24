from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from asyncpg.exceptions import PostgresError  # type: ignore[import-untyped]
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.api.approval_inbox import ApprovalDetail, ApprovalListItem, get_db_session
from backend.app.config import Settings, get_settings
from backend.app.db.models.approval_request import ApprovalRequest
from backend.app.db.models.approval_revision_request import ApprovalRevisionRequest
from backend.app.db.models.audit_event import AuditEvent
from backend.app.db.models.notification_event import NotificationEvent
from backend.app.db.session import create_engine
from backend.app.main import create_app
from backend.app.repositories.approval_request import ApprovalRequestRepository
from backend.app.seeds.initial import DEFAULT_ACTOR_ID
from backend.app.services.policy.revision_request_service import (
    ApprovalRevisionRequestService,
    ApprovalRevisionValidationError,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

REQUESTER_ACTOR_ID = UUID("00000000-0000-4000-8000-000000003001")
APPROVAL_ID = UUID("00000000-0000-4000-8000-000000003011")
APPROVAL_ID_2 = UUID("00000000-0000-4000-8000-000000003012")
UNKNOWN_APPROVAL_ID = UUID("00000000-0000-4000-8000-000000003099")


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-approval-inbox-api",
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
    except (OSError, PostgresError, SQLAlchemyError, TimeoutError) as exc:
        if os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") == "1":
            raise AssertionError("Approval Inbox API tests require a reachable test database.") from exc
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


@pytest_asyncio.fixture
async def approval_api_client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    app = create_app(_integration_settings())

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def _reset_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            "truncate notification_events, audit_events, policy_decisions, "
            "approval_revision_requests, approval_requests restart identity cascade"
        )
    )


async def _insert_tenant(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (1, 'tenant-one', '{"rls_ready": true}'::jsonb)
            on conflict (id) do update set
              name = excluded.name,
              metadata = excluded.metadata
            """
        )
    )


async def _insert_actor(
    session: AsyncSession,
    *,
    actor_id: UUID,
    actor_type: str,
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
              impersonated_by,
              metadata
            )
            values (
              :actor_uuid,
              1,
              :actor_type,
              :stable_actor_id,
              :display_name,
              'approval-inbox-api-auth-context',
              null,
              '{"rls_ready": true}'::jsonb
            )
            on conflict (id) do update set
              actor_type = excluded.actor_type,
              actor_id = excluded.actor_id,
              display_name = excluded.display_name,
              auth_context_hash = excluded.auth_context_hash,
              impersonated_by = excluded.impersonated_by,
              metadata = excluded.metadata
            """
        ),
        {
            "actor_uuid": actor_id,
            "actor_type": actor_type,
            "stable_actor_id": stable_actor_id,
            "display_name": display_name,
        },
    )


async def _insert_approval(
    session: AsyncSession,
    *,
    approval_id: UUID,
    status: str = "pending",
    requested_by_actor_id: UUID = REQUESTER_ACTOR_ID,
) -> None:
    requested_at = datetime.now(tz=UTC)
    decided_by_actor_id = DEFAULT_ACTOR_ID if status in {"approved", "rejected"} else None
    decided_at = requested_at if decided_by_actor_id is not None else None

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
              requested_at,
              decided_by_actor_id,
              decided_at,
              metadata
            )
            values (
              :id,
              1,
              'task_write',
              :resource_ref,
              'medium',
              'artifact-a',
              'diff-a',
              'policy-v1',
              'pack-a',
              'provider-a',
              1,
              :status,
              :requested_by_actor_id,
              :requested_at,
              :decided_by_actor_id,
              :decided_at,
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "id": approval_id,
            "resource_ref": f"task:{approval_id}",
            "status": status,
            "requested_by_actor_id": requested_by_actor_id,
            "requested_at": requested_at,
            "decided_by_actor_id": decided_by_actor_id,
            "decided_at": decided_at,
        },
    )


async def _setup_api_fixtures(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _reset_tables(session)
        await _insert_tenant(session)
        await _insert_actor(
            session,
            actor_id=DEFAULT_ACTOR_ID,
            actor_type="human",
            stable_actor_id="human:default",
            display_name="Default Human",
        )
        await _insert_actor(
            session,
            actor_id=REQUESTER_ACTOR_ID,
            actor_type="agent",
            stable_actor_id="agent:approval-requester",
            display_name="Approval Requester Agent",
        )


async def _approval_status(
    session_factory: async_sessionmaker[AsyncSession],
    approval_id: UUID,
) -> str:
    async with session_factory() as session:
        value = await session.scalar(
            select(ApprovalRequest.status).where(
                ApprovalRequest.tenant_id == 1,
                ApprovalRequest.id == approval_id,
            )
        )
    assert value is not None
    return value


async def _notification_count(
    session_factory: async_sessionmaker[AsyncSession],
    recipient_actor_id: UUID,
) -> int:
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count(NotificationEvent.id)).where(
                NotificationEvent.tenant_id == 1,
                NotificationEvent.recipient_actor_id == recipient_actor_id,
            )
        )
    return int(count or 0)


async def _table_count(
    session_factory: async_sessionmaker[AsyncSession],
    model: type[ApprovalRevisionRequest] | type[AuditEvent] | type[NotificationEvent],
) -> int:
    async with session_factory() as session:
        count = await session.scalar(select(func.count(model.id)).where(model.tenant_id == 1))
    return int(count or 0)


def test_list_pending_approvals_rejects_unknown_action_class() -> None:
    with pytest.raises(ValidationError):
        ApprovalListItem(
            id=uuid4(),
            action_class="unknown_action",
            resource_ref="task:unknown-action",
            risk_level="medium",
            status="pending",
            requested_by_actor_id=uuid4(),
            requested_at=datetime.now(tz=UTC),
        )


def test_approval_detail_contract_includes_decision_packet_fields() -> None:
    detail = ApprovalDetail(
        id=uuid4(),
        action_class="repo_write",
        resource_ref="repo:TaskManagedAI:decision-packet",
        risk_level="high",
        status="pending",
        requested_by_actor_id=uuid4(),
        decided_by_actor_id=None,
        requested_at=datetime.now(tz=UTC),
        decided_at=None,
        rationale=None,
        artifact_hash="a" * 64,
        diff_hash="b" * 64,
        policy_version="policy-v1",
        policy_pack_lock="c" * 64,
        provider_request_fingerprint="d" * 64,
        stale_after_event_seq=42,
    )

    payload = detail.model_dump()
    assert payload["artifact_hash"] == "a" * 64
    assert payload["diff_hash"] == "b" * 64
    assert payload["policy_version"] == "policy-v1"
    assert payload["policy_pack_lock"] == "c" * 64
    assert payload["provider_request_fingerprint"] == "d" * 64
    assert payload["stale_after_event_seq"] == 42


@pytest.mark.asyncio
async def test_create_pending_approval_inserts_notification(
    approval_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_api_fixtures(session_factory)

    async with session_factory.begin() as session:
        approval = await ApprovalRequestRepository(session).create_pending_approval(
            tenant_id=1,
            action_class="task_write",
            resource_ref="task:notification-wiring",
            risk_level="medium",
            requested_by_actor_id=REQUESTER_ACTOR_ID,
            recipient_actor_id=DEFAULT_ACTOR_ID,
            policy_version="policy-v1",
            artifact_hash="artifact-a",
            diff_hash="diff-a",
            policy_pack_lock="pack-a",
            provider_request_fingerprint="provider-a",
            metadata={"rls_ready": True},
        )

    assert approval.status == "pending"

    response = await approval_api_client.get("/api/v1/notifications/badge_count")

    assert response.status_code == 200
    assert response.json() == {"unread_count": 1}


@pytest.mark.asyncio
async def test_pending_approval_creation_and_notification_atomic(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_api_fixtures(session_factory)

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await ApprovalRequestRepository(session).create_pending_approval(
                tenant_id=1,
                action_class="unknown_action",
                resource_ref="task:invalid-action",
                risk_level="medium",
                requested_by_actor_id=REQUESTER_ACTOR_ID,
                recipient_actor_id=DEFAULT_ACTOR_ID,
                policy_version="policy-v1",
                metadata={"rls_ready": True},
            )

        await session.rollback()

    assert await _notification_count(session_factory, DEFAULT_ACTOR_ID) == 0


@pytest.mark.asyncio
async def test_list_pending_approvals(
    approval_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_api_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_approval(session, approval_id=APPROVAL_ID)
        await _insert_approval(session, approval_id=APPROVAL_ID_2, status="approved")

    response = await approval_api_client.get("/api/v1/approvals")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == str(APPROVAL_ID)
    assert payload[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_get_approval_detail_returns_decision_packet_fields(
    approval_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_api_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_approval(session, approval_id=APPROVAL_ID)

    response = await approval_api_client.get(f"/api/v1/approvals/{APPROVAL_ID}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_hash"] == "artifact-a"
    assert payload["diff_hash"] == "diff-a"
    assert payload["policy_version"] == "policy-v1"
    assert payload["policy_pack_lock"] == "pack-a"
    assert payload["provider_request_fingerprint"] == "provider-a"
    assert payload["stale_after_event_seq"] == 1


@pytest.mark.asyncio
async def test_get_approval_detail_404_for_unknown_id(
    approval_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_api_fixtures(session_factory)

    response = await approval_api_client.get(f"/api/v1/approvals/{UNKNOWN_APPROVAL_ID}")

    assert response.status_code == 404
    assert response.json()["detail"] == "approval not found"


@pytest.mark.asyncio
async def test_decide_approve_returns_200_and_updates_status(
    approval_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_api_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_approval(session, approval_id=APPROVAL_ID)

    response = await approval_api_client.post(
        f"/api/v1/approvals/{APPROVAL_ID}/decide",
        json={"action": "approve", "rationale": "looks safe"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert await _approval_status(session_factory, APPROVAL_ID) == "approved"


@pytest.mark.asyncio
async def test_decide_reject_returns_200_and_updates_status(
    approval_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_api_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_approval(session, approval_id=APPROVAL_ID)

    response = await approval_api_client.post(
        f"/api/v1/approvals/{APPROVAL_ID}/decide",
        json={"action": "reject", "rationale": "risk too high"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert await _approval_status(session_factory, APPROVAL_ID) == "rejected"


@pytest.mark.asyncio
async def test_decide_self_approval_returns_409(
    approval_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_api_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_approval(
            session,
            approval_id=APPROVAL_ID,
            requested_by_actor_id=DEFAULT_ACTOR_ID,
        )

    response = await approval_api_client.post(
        f"/api/v1/approvals/{APPROVAL_ID}/decide",
        json={"action": "approve", "rationale": "self approve attempt"},
    )

    assert response.status_code == 409
    assert "self-approval is forbidden" in response.json()["detail"]
    assert await _approval_status(session_factory, APPROVAL_ID) == "pending"


@pytest.mark.asyncio
async def test_decide_invalid_action_returns_422(
    approval_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_api_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_approval(session, approval_id=APPROVAL_ID)

    response = await approval_api_client.post(
        f"/api/v1/approvals/{APPROVAL_ID}/decide",
        json={"action": "hold", "rationale": "not a valid decision"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_decide_non_pending_status_returns_409(
    approval_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_api_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_approval(session, approval_id=APPROVAL_ID, status="invalidated")

    response = await approval_api_client.post(
        f"/api/v1/approvals/{APPROVAL_ID}/decide",
        json={"action": "approve", "rationale": "stale approve attempt"},
    )

    assert response.status_code == 409
    assert "expected 'pending'" in response.json()["detail"]


@pytest.mark.asyncio
async def test_decide_unknown_id_returns_404(
    approval_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_api_fixtures(session_factory)

    response = await approval_api_client.post(
        f"/api/v1/approvals/{uuid4()}/decide",
        json={"action": "approve", "rationale": "unknown approval"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "approval not found"


@pytest.mark.asyncio
async def test_request_revision_invalidates_pending_approval_and_records_metadata_only_events(
    approval_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_api_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_approval(session, approval_id=APPROVAL_ID)

    response = await approval_api_client.post(
        f"/api/v1/approvals/{APPROVAL_ID}/request_revision",
        json={"rationale": "  Please update the acceptance criteria before proceeding.  "},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["approval"]["id"] == str(APPROVAL_ID)
    assert payload["approval"]["status"] == "invalidated"
    assert payload["approval"]["rationale"] is None
    assert await _approval_status(session_factory, APPROVAL_ID) == "invalidated"

    revision_request_id = UUID(payload["revision_request_id"])
    async with session_factory() as session:
        revision = await session.scalar(
            select(ApprovalRevisionRequest).where(
                ApprovalRevisionRequest.tenant_id == 1,
                ApprovalRevisionRequest.id == revision_request_id,
            )
        )
        audit_event = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.tenant_id == 1,
                AuditEvent.event_type == "approval_revision_requested",
            )
        )
        notification = await session.scalar(
            select(NotificationEvent).where(
                NotificationEvent.tenant_id == 1,
                NotificationEvent.event_type == "approval_revision_requested",
            )
        )

    assert revision is not None
    assert revision.approval_request_id == APPROVAL_ID
    assert revision.requested_by_actor_id == DEFAULT_ACTOR_ID
    assert revision.rationale == "Please update the acceptance criteria before proceeding."
    assert revision.artifact_hash == "artifact-a"
    assert revision.diff_hash == "diff-a"
    assert revision.policy_version == "policy-v1"
    assert revision.policy_pack_lock == "pack-a"
    assert revision.provider_request_fingerprint == "provider-a"
    assert revision.stale_after_event_seq == 1
    assert revision.superseded_by_approval_request_id is None

    assert audit_event is not None
    assert audit_event.actor_id == DEFAULT_ACTOR_ID
    assert audit_event.event_payload["approval_id"] == str(APPROVAL_ID)
    assert audit_event.event_payload["revision_request_id"] == str(revision_request_id)
    assert "rationale" not in audit_event.event_payload

    assert notification is not None
    assert notification.recipient_actor_id == REQUESTER_ACTOR_ID
    assert notification.severity == "medium"
    assert notification.required_action == "inspect_run"
    assert notification.payload == {
        "approval_id": str(APPROVAL_ID),
        "revision_request_id": str(revision_request_id),
    }


@pytest.mark.asyncio
async def test_request_revision_rejects_non_pending_approval(
    approval_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_api_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_approval(session, approval_id=APPROVAL_ID, status="approved")

    response = await approval_api_client.post(
        f"/api/v1/approvals/{APPROVAL_ID}/request_revision",
        json={"rationale": "needs another change"},
    )

    assert response.status_code == 409
    assert "expected 'pending'" in response.json()["detail"]
    assert await _approval_status(session_factory, APPROVAL_ID) == "approved"
    assert await _table_count(session_factory, ApprovalRevisionRequest) == 0
    assert await _table_count(session_factory, NotificationEvent) == 0
    assert await _table_count(session_factory, AuditEvent) == 0


@pytest.mark.asyncio
async def test_request_revision_rejects_self_approval_actor(
    approval_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_api_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_approval(
            session,
            approval_id=APPROVAL_ID,
            requested_by_actor_id=DEFAULT_ACTOR_ID,
        )

    response = await approval_api_client.post(
        f"/api/v1/approvals/{APPROVAL_ID}/request_revision",
        json={"rationale": "self revision request attempt"},
    )

    assert response.status_code == 409
    assert "self-approval is forbidden" in response.json()["detail"]
    assert await _approval_status(session_factory, APPROVAL_ID) == "pending"
    assert await _table_count(session_factory, ApprovalRevisionRequest) == 0


@pytest.mark.asyncio
async def test_request_revision_rejects_raw_secret_before_db_insert(
    approval_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_api_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_approval(session, approval_id=APPROVAL_ID)

    response = await approval_api_client.post(
        f"/api/v1/approvals/{APPROVAL_ID}/request_revision",
        json={"rationale": "Do not store sk-aaaaaaaaaaaaaaaaaaaa in rationale."},
    )

    assert response.status_code == 422
    assert "raw-secret scan" in response.json()["detail"]
    assert await _approval_status(session_factory, APPROVAL_ID) == "pending"
    assert await _table_count(session_factory, ApprovalRevisionRequest) == 0
    assert await _table_count(session_factory, NotificationEvent) == 0
    assert await _table_count(session_factory, AuditEvent) == 0


@pytest.mark.asyncio
async def test_request_revision_rejects_duplicate_open_revision_request(
    approval_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_api_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_approval(session, approval_id=APPROVAL_ID)
        await session.execute(
            text(
                """
                insert into approval_revision_requests (
                  tenant_id,
                  approval_request_id,
                  requested_by_actor_id,
                  rationale,
                  artifact_hash,
                  diff_hash,
                  policy_version,
                  policy_pack_lock,
                  provider_request_fingerprint,
                  stale_after_event_seq,
                  metadata
                )
                values (
                  1,
                  :approval_id,
                  :requested_by_actor_id,
                  'already open',
                  'artifact-a',
                  'diff-a',
                  'policy-v1',
                  'pack-a',
                  'provider-a',
                  1,
                  '{"rls_ready": true}'::jsonb
                )
                """
            ),
            {
                "approval_id": APPROVAL_ID,
                "requested_by_actor_id": DEFAULT_ACTOR_ID,
            },
        )

    response = await approval_api_client.post(
        f"/api/v1/approvals/{APPROVAL_ID}/request_revision",
        json={"rationale": "second request should not pass"},
    )

    assert response.status_code == 409
    assert "already has an open revision request" in response.json()["detail"]
    assert await _approval_status(session_factory, APPROVAL_ID) == "pending"
    assert await _table_count(session_factory, ApprovalRevisionRequest) == 1


@pytest.mark.asyncio
async def test_revised_artifact_handoff_creates_fresh_pending_approval_and_supersedes_revision(
    approval_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_api_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_approval(session, approval_id=APPROVAL_ID)

    response = await approval_api_client.post(
        f"/api/v1/approvals/{APPROVAL_ID}/request_revision",
        json={"rationale": "please revise the artifact"},
    )
    assert response.status_code == 200
    revision_request_id = UUID(response.json()["revision_request_id"])

    async with session_factory.begin() as session:
        revision_request = await session.scalar(
            select(ApprovalRevisionRequest).where(
                ApprovalRevisionRequest.tenant_id == 1,
                ApprovalRevisionRequest.id == revision_request_id,
            )
        )
        assert revision_request is not None
        result = await ApprovalRevisionRequestService(session).create_revised_approval(
            tenant_id=1,
            revision_request=revision_request,
            artifact_hash="  artifact-b  ",
            diff_hash="  diff-b  ",
            policy_version="policy-v1",
            policy_pack_lock="pack-a",
            provider_request_fingerprint="  provider-b  ",
            stale_after_event_seq=2,
        )
        replacement_approval_id = result.replacement_approval.id

    async with session_factory() as session:
        revision = await session.scalar(
            select(ApprovalRevisionRequest).where(
                ApprovalRevisionRequest.tenant_id == 1,
                ApprovalRevisionRequest.id == revision_request_id,
            )
        )
        replacement = await session.scalar(
            select(ApprovalRequest).where(
                ApprovalRequest.tenant_id == 1,
                ApprovalRequest.id == replacement_approval_id,
            )
        )

    assert revision is not None
    assert revision.superseded_by_approval_request_id == replacement_approval_id
    assert replacement is not None
    assert replacement.status == "pending"
    assert replacement.requested_by_actor_id == REQUESTER_ACTOR_ID
    assert replacement.decided_by_actor_id is None
    assert replacement.artifact_hash == "artifact-b"
    assert replacement.diff_hash == "diff-b"
    assert replacement.policy_version == "policy-v1"
    assert replacement.policy_pack_lock == "pack-a"
    assert replacement.provider_request_fingerprint == "provider-b"
    assert replacement.stale_after_event_seq == 2
    assert replacement.metadata_["revision_request_id"] == str(revision_request_id)
    assert replacement.metadata_["supersedes_approval_request_id"] == str(APPROVAL_ID)


@pytest.mark.asyncio
async def test_revised_artifact_handoff_rejects_stale_decision_packet(
    approval_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_api_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_approval(session, approval_id=APPROVAL_ID)

    response = await approval_api_client.post(
        f"/api/v1/approvals/{APPROVAL_ID}/request_revision",
        json={"rationale": "please revise with fresh hashes"},
    )
    assert response.status_code == 200
    revision_request_id = UUID(response.json()["revision_request_id"])

    async with session_factory.begin() as session:
        revision_request = await session.scalar(
            select(ApprovalRevisionRequest).where(
                ApprovalRevisionRequest.tenant_id == 1,
                ApprovalRevisionRequest.id == revision_request_id,
            )
        )
        assert revision_request is not None
        with pytest.raises(
            ApprovalRevisionValidationError,
            match="revised artifact_hash must differ",
        ):
            await ApprovalRevisionRequestService(session).create_revised_approval(
                tenant_id=1,
                revision_request=revision_request,
                artifact_hash="artifact-a",
                diff_hash="diff-b",
                policy_version="policy-v1",
                policy_pack_lock="pack-a",
                provider_request_fingerprint="provider-b",
                stale_after_event_seq=2,
            )

    async with session_factory() as session:
        revision = await session.scalar(
            select(ApprovalRevisionRequest).where(
                ApprovalRevisionRequest.tenant_id == 1,
                ApprovalRevisionRequest.id == revision_request_id,
            )
        )
        replacement_count = await session.scalar(
            select(func.count(ApprovalRequest.id)).where(
                ApprovalRequest.tenant_id == 1,
                ApprovalRequest.id != APPROVAL_ID,
            )
        )

    assert revision is not None
    assert revision.superseded_by_approval_request_id is None
    assert int(replacement_count or 0) == 0


@pytest.mark.asyncio
async def test_revised_artifact_handoff_rejects_non_advancing_event_seq(
    approval_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_api_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_approval(session, approval_id=APPROVAL_ID)

    response = await approval_api_client.post(
        f"/api/v1/approvals/{APPROVAL_ID}/request_revision",
        json={"rationale": "please revise with a newer event sequence"},
    )
    assert response.status_code == 200
    revision_request_id = UUID(response.json()["revision_request_id"])

    async with session_factory.begin() as session:
        revision_request = await session.scalar(
            select(ApprovalRevisionRequest).where(
                ApprovalRevisionRequest.tenant_id == 1,
                ApprovalRevisionRequest.id == revision_request_id,
            )
        )
        assert revision_request is not None
        with pytest.raises(
            ApprovalRevisionValidationError,
            match="stale_after_event_seq must advance",
        ):
            await ApprovalRevisionRequestService(session).create_revised_approval(
                tenant_id=1,
                revision_request=revision_request,
                artifact_hash="artifact-b",
                diff_hash="diff-b",
                policy_version="policy-v1",
                policy_pack_lock="pack-a",
                provider_request_fingerprint="provider-b",
                stale_after_event_seq=1,
            )
