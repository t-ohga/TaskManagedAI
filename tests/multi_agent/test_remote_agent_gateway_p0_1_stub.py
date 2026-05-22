"""SP-014 batch 0e: remote_agent_gateway P0.1 deny-only stub tests."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
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
from backend.app.db.models.audit_event import AuditEvent
from backend.app.db.session import create_engine
from backend.app.services.remote_agent_gateway import (
    RemoteAgentDispatchRequest,
    RemoteAgentGateway,
    RemoteAgentGatewayError,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-000000029001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000029002")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000029003")
RUN_ID = UUID("00000000-0000-4000-8000-000000029004")


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-remote-agent-gateway",
    )


def _run_alembic_upgrade(database_url: str) -> None:
    previous_database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        command.upgrade(Config(str(_REPO_ROOT / "alembic.ini")), "head")
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
            raise AssertionError("remote agent gateway tests require PostgreSQL.") from exc
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


async def _reset_fixture(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate
              audit_events,
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
            values (:actor_id, 1, 'agent', 'agent:orchestrator',
                    'Remote Gateway Test Agent', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'remote-gateway-workspace',
                    'remote-gateway-workspace', :actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (:project_id, 1, :workspace_id, 'remote-gateway-project',
                    'remote-gateway-project', 'active', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"project_id": PROJECT_ID, "workspace_id": WORKSPACE_ID},
    )
    await session.execute(
        text(
            """
            insert into agent_runs (id, tenant_id, project_id, status, role_id, role_scope)
            values (:run_id, 1, :project_id, 'running', 'orchestrator', 'global')
            """
        ),
        {"run_id": RUN_ID, "project_id": PROJECT_ID},
    )


def _dispatch_request(**overrides: object) -> RemoteAgentDispatchRequest:
    values: dict[str, object] = {
        "tenant_id": TENANT_ID,
        "actor_id": ACTOR_ID,
        "role_id": "orchestrator",
        "requested_remote_role": "implementer",
        "capability_class": "remote_child_run",
        "project_id": PROJECT_ID,
        "run_id": RUN_ID,
        "correlation_id": "remote-gateway-correlation",
        "trace_id": "remote-gateway-trace",
    }
    values.update(overrides)
    return RemoteAgentDispatchRequest(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_remote_agent_gateway_denies_and_records_audit_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _reset_fixture(session)
            gateway = RemoteAgentGateway(session)
            decision = await gateway.deny_dispatch(_dispatch_request())

        audit_event = await session.scalar(
            select(AuditEvent).where(AuditEvent.id == decision.audit_event_id)
        )

    assert decision.decision == "deny"
    assert decision.reason_code == "p0_1_stub"
    assert audit_event is not None
    assert audit_event.event_type == "remote_agent_dispatch_denied"
    assert audit_event.actor_id == ACTOR_ID
    assert audit_event.correlation_id == "remote-gateway-correlation"
    assert audit_event.trace_id == "remote-gateway-trace"
    assert audit_event.event_payload == {
        "reason_code": "p0_1_stub",
        "gateway_kind": "remote_agent",
        "decision": "deny",
        "tenant_id": TENANT_ID,
        "actor_id": str(ACTOR_ID),
        "project_id": str(PROJECT_ID),
        "run_id": str(RUN_ID),
        "role_id": "orchestrator",
        "requested_remote_role": "implementer",
        "capability_class": "remote_child_run",
        "payload_data_class": "internal",
        "raw_secret_check_passed": True,
    }


@pytest.mark.asyncio
async def test_remote_agent_gateway_rejects_raw_secret_like_payload(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _reset_fixture(session)
            gateway = RemoteAgentGateway(session)
            with pytest.raises(ValueError, match="raw secret pattern|prohibited key"):
                await gateway.deny_dispatch(
                    _dispatch_request(requested_remote_role="sk-" + "x" * 24)
                )

        audit_count = await session.scalar(
            text("select count(*) from audit_events where event_type='remote_agent_dispatch_denied'")
        )

    assert audit_count == 0


@pytest.mark.asyncio
async def test_remote_agent_gateway_rejects_empty_role_fields(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _reset_fixture(session)
            gateway = RemoteAgentGateway(session)
            with pytest.raises(RemoteAgentGatewayError, match="requested_remote_role"):
                await gateway.deny_dispatch(_dispatch_request(requested_remote_role=" "))


@pytest.mark.asyncio
async def test_remote_agent_gateway_requires_tenant_context_match(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _reset_fixture(session)
            await session.execute(text("select set_config('app.tenant_id', '2', true)"))
            gateway = RemoteAgentGateway(session)
            with pytest.raises(ValueError, match="tenant context mismatch"):
                await gateway.deny_dispatch(_dispatch_request())
