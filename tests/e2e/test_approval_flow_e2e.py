"""Approval Inbox backend flow integration tests (Sprint 3 Batch 3 R4 fix)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.api.approval_inbox import get_db_session
from backend.app.config import Settings, get_settings
from backend.app.db.models.approval_request import ApprovalRequest
from backend.app.db.session import create_engine
from backend.app.main import create_app
from backend.app.repositories.approval_request import ApprovalRequestRepository

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

REQUESTER_ACTOR_ID = UUID("00000000-0000-4000-8000-000000007a01")
DECIDER_ACTOR_ID = UUID("00000000-0000-4000-8000-000000007a02")


def _integration_settings(*, default_actor_id: str = "human:default") -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-approval-flow-e2e",
        ),
        default_actor_id=default_actor_id,
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
            raise AssertionError("Approval flow E2E requires reachable test database.") from exc
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


@asynccontextmanager
async def _api_client(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    actor_reference: str,
) -> AsyncIterator[AsyncClient]:
    app = create_app(_integration_settings(default_actor_id=actor_reference))

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


async def _reset_flow_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            "truncate notification_events, policy_decisions, "
            "approval_requests restart identity cascade"
        )
    )


async def _ensure_tenant(session: AsyncSession) -> None:
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


async def _seed_two_actors(session: AsyncSession) -> tuple[UUID, UUID]:
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
            values
              (
                :requester_id,
                1,
                'human',
                'human:e2e-requester',
                'E2E Requester',
                'approval-flow-requester-auth-context',
                null,
                '{"rls_ready": true}'::jsonb
              ),
              (
                :decider_id,
                1,
                'human',
                'human:e2e-decider',
                'E2E Decider',
                'approval-flow-decider-auth-context',
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
            "requester_id": REQUESTER_ACTOR_ID,
            "decider_id": DECIDER_ACTOR_ID,
        },
    )
    return REQUESTER_ACTOR_ID, DECIDER_ACTOR_ID


async def _setup_approval_flow_fixtures(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID]:
    async with session_factory.begin() as session:
        await _reset_flow_tables(session)
        await _ensure_tenant(session)
        return await _seed_two_actors(session)


async def _create_pending_approval(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    resource_ref: str,
    requested_by_actor_id: UUID,
    recipient_actor_id: UUID,
    risk_level: str = "medium",
) -> UUID:
    async with session_factory.begin() as session:
        approval = await ApprovalRequestRepository(session).create_pending_approval(
            tenant_id=1,
            action_class="task_write",
            resource_ref=resource_ref,
            risk_level=risk_level,
            requested_by_actor_id=requested_by_actor_id,
            recipient_actor_id=recipient_actor_id,
            policy_version="2026-05-08-initial",
            metadata={"rls_ready": True},
        )
        return approval.id


async def _get_approval(
    session_factory: async_sessionmaker[AsyncSession],
    approval_id: UUID,
) -> ApprovalRequest:
    async with session_factory() as session:
        approval = await session.scalar(
            select(ApprovalRequest).where(
                ApprovalRequest.tenant_id == 1,
                ApprovalRequest.id == approval_id,
            )
        )
    assert approval is not None
    return approval


@pytest.mark.asyncio
async def test_approval_flow_create_list_detail_decide_approve(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    requester_id, decider_id = await _setup_approval_flow_fixtures(session_factory)
    approval_id = await _create_pending_approval(
        session_factory,
        resource_ref="ticket:e2e-flow-approve",
        requested_by_actor_id=requester_id,
        recipient_actor_id=decider_id,
    )

    async with _api_client(session_factory, actor_reference=str(decider_id)) as client:
        list_resp = await client.get("/api/v1/approvals")
        assert list_resp.status_code == 200
        items = list_resp.json()
        assert any(item["id"] == str(approval_id) for item in items), (
            f"approval {approval_id} not in pending list: {items}"
        )

        detail_resp = await client.get(f"/api/v1/approvals/{approval_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["id"] == str(approval_id)
        assert detail["status"] == "pending"

        decide_resp = await client.post(
            f"/api/v1/approvals/{approval_id}/decide",
            json={"action": "approve", "rationale": "approved via E2E"},
        )
        assert decide_resp.status_code == 200, decide_resp.text
        body = decide_resp.json()
        assert body["status"] == "approved"
        assert body["decided_by_actor_id"] == str(decider_id)
        assert body["decided_at"] is not None
        assert body["rationale"] == "approved via E2E"

    persisted = await _get_approval(session_factory, approval_id)
    assert persisted.status == "approved"
    assert persisted.decided_by_actor_id == decider_id
    assert persisted.decided_at is not None
    assert persisted.rationale == "approved via E2E"


@pytest.mark.asyncio
async def test_approval_flow_self_approval_returns_409(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    requester_id, _ = await _setup_approval_flow_fixtures(session_factory)
    approval_id = await _create_pending_approval(
        session_factory,
        resource_ref="ticket:e2e-flow-self-approval",
        requested_by_actor_id=requester_id,
        recipient_actor_id=requester_id,
        risk_level="low",
    )

    async with _api_client(session_factory, actor_reference=str(requester_id)) as client:
        resp = await client.post(
            f"/api/v1/approvals/{approval_id}/decide",
            json={"action": "approve"},
        )

    assert resp.status_code == 409, resp.text
    assert "self-approval" in resp.json().get("detail", "").lower()

    persisted = await _get_approval(session_factory, approval_id)
    assert persisted.status == "pending"
    assert persisted.decided_by_actor_id is None
    assert persisted.decided_at is None


@pytest.mark.asyncio
async def test_approval_flow_notification_badge_increments(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    requester_id, decider_id = await _setup_approval_flow_fixtures(session_factory)

    async with _api_client(session_factory, actor_reference=str(decider_id)) as client:
        before = await client.get("/api/v1/notifications/badge_count")
        assert before.status_code == 200
        before_count = before.json()["unread_count"]

        await _create_pending_approval(
            session_factory,
            resource_ref="ticket:e2e-flow-badge-increment",
            requested_by_actor_id=requester_id,
            recipient_actor_id=decider_id,
            risk_level="low",
        )

        after = await client.get("/api/v1/notifications/badge_count")
        assert after.status_code == 200
        after_count = after.json()["unread_count"]

    assert after_count == before_count + 1, (
        f"expected badge_count {before_count + 1}, got {after_count}"
    )
