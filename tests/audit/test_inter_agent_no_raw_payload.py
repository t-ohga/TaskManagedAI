"""SP-015 batch 0e audit/timeline ref-only regression tests."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.agent_run_event import AgentRunEvent
from backend.app.db.models.audit_event import AuditEvent
from backend.app.db.session import create_engine
from backend.app.schemas.inter_agent import InterAgentConsumeRequest, InterAgentPublishRequest
from backend.app.services.inter_agent.consumer import (
    InterAgentConsumeDenied,
    InterAgentConsumerService,
)
from backend.app.services.inter_agent.event_writer import (
    InterAgentEventPayloadError,
    _assert_ref_only_payload,
)
from backend.app.services.inter_agent.publisher import InterAgentPublisherService

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-000000015301")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000015302")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000015303")
PARENT_RUN_ID = UUID("00000000-0000-4000-8000-000000015310")
SENDER_RUN_ID = UUID("00000000-0000-4000-8000-000000015311")
RECEIVER_RUN_ID = UUID("00000000-0000-4000-8000-000000015312")
RAW_BODY_SENTINEL = "RAW-BODY-MUST-NOT-LEAK"

db_required = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)


def _future_expiry() -> datetime:
    return datetime.now(tz=UTC) + timedelta(minutes=30)


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-inter-agent-audit",
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
            raise AssertionError("inter-agent audit tests require PostgreSQL.") from exc
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
              audit_events,
              inter_agent_messages,
              artifacts,
              agent_run_events,
              agent_runs,
              sanitizer_policy_versions,
              projects,
              workspaces,
              actors,
              tenants
            restart identity cascade
            """
        )
    )


async def _insert_fixture(session: AsyncSession) -> None:
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
            values (:actor_id, 1, 'human', 'human:inter-agent-audit',
                    'Inter Agent Audit Actor', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'inter-agent-audit-workspace',
                    'inter-agent-audit-workspace', :actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (:project_id, 1, :workspace_id, 'inter-agent-audit-project',
                    'inter-agent-audit-project', 'active', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"project_id": PROJECT_ID, "workspace_id": WORKSPACE_ID},
    )
    await session.execute(
        text(
            """
            insert into sanitizer_policy_versions (
              tenant_id, version, config_hash, ruleset_hash
            )
            values (1, 'v1.0.0', :config_hash, :ruleset_hash)
            """
        ),
        {"config_hash": "6" * 64, "ruleset_hash": "7" * 64},
    )
    await session.execute(
        text(
            """
            insert into agent_runs (id, tenant_id, project_id, status)
            values (:parent_run_id, 1, :project_id, 'running')
            """
        ),
        {"parent_run_id": PARENT_RUN_ID, "project_id": PROJECT_ID},
    )
    await session.execute(
        text(
            """
            insert into agent_runs (id, tenant_id, project_id, parent_run_id, status)
            values
              (:sender_run_id, 1, :project_id, :parent_run_id, 'running'),
              (:receiver_run_id, 1, :project_id, :parent_run_id, 'running')
            """
        ),
        {
            "sender_run_id": SENDER_RUN_ID,
            "receiver_run_id": RECEIVER_RUN_ID,
            "parent_run_id": PARENT_RUN_ID,
            "project_id": PROJECT_ID,
        },
    )


def _publish_request() -> InterAgentPublishRequest:
    return InterAgentPublishRequest.model_validate(
        {
            "parent_run_id": PARENT_RUN_ID,
            "sender_run_id": SENDER_RUN_ID,
            "receiver_kind": "agent_run",
            "child_run_id": RECEIVER_RUN_ID,
            "payload": {"body": RAW_BODY_SENTINEL, "nested": {"content": "artifact-only"}},
            "classification": {"external_origin": True},
            "idempotency_key": "inter-agent-audit:message",
            "expires_at": _future_expiry(),
        }
    )


def _consume_request(message_id: UUID) -> InterAgentConsumeRequest:
    return InterAgentConsumeRequest(
        parent_run_id=PARENT_RUN_ID,
        message_id=message_id,
        consumer_run_id=RECEIVER_RUN_ID,
    )


def _serialized(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True)


def _assert_no_raw_payload(payload: dict[str, Any]) -> None:
    serialized = _serialized(payload)
    assert RAW_BODY_SENTINEL not in serialized
    assert "artifact-only" not in serialized
    assert '"body"' not in serialized
    assert '"payload"' not in serialized
    assert '"content"' not in serialized


def test_event_writer_rejects_raw_message_body_keys() -> None:
    with pytest.raises(InterAgentEventPayloadError, match="ref-only"):
        _assert_ref_only_payload({"payload": {"body": RAW_BODY_SENTINEL}})


@pytest.mark.asyncio
@db_required
async def test_inter_agent_audit_and_run_events_are_ref_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            published = await InterAgentPublisherService(session).publish(
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                sender_actor_id=ACTOR_ID,
                request=_publish_request(),
            )
            await InterAgentConsumerService(session).consume(
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                actor_id=ACTOR_ID,
                request=_consume_request(published.message.id),
            )
            with pytest.raises(InterAgentConsumeDenied, match="already_consumed"):
                await InterAgentConsumerService(session).consume(
                    tenant_id=TENANT_ID,
                    project_id=PROJECT_ID,
                    actor_id=ACTOR_ID,
                    request=_consume_request(published.message.id),
                )

        audit_events = (
            await session.execute(
                select(AuditEvent)
            )
        ).scalars().all()
        run_events = (
            await session.execute(
                select(AgentRunEvent).order_by(AgentRunEvent.run_id, AgentRunEvent.seq_no)
            )
        ).scalars().all()

    audit_by_type = {event.event_type: event for event in audit_events}
    assert set(audit_by_type) == {
        "inter_agent_message_sent",
        "inter_agent_message_consumed",
        "inter_agent_message_denied",
    }
    assert [event.event_type for event in run_events] == [
        "inter_agent_message_sent_ref",
        "inter_agent_message_consumed_ref",
    ]

    sent_payload = audit_by_type["inter_agent_message_sent"].event_payload
    assert set(sent_payload) == {
        "tenant_id",
        "project_id",
        "parent_run_id",
        "sender_run_id",
        "sender_actor_id",
        "receiver_kind",
        "receiver_ref",
        "seq_no",
        "payload_hash",
        "payload_data_class",
        "trust_level",
        "schema_version",
        "redaction_status",
    }
    assert sent_payload["payload_hash"] == published.message.payload_hash

    consumed_payload = audit_by_type["inter_agent_message_consumed"].event_payload
    assert set(consumed_payload) == {
        "tenant_id",
        "project_id",
        "parent_run_id",
        "consumed_by_run_id",
        "message_id_hash",
        "seq_no",
        "previous_hash_match",
        "payload_hash",
        "redaction_status",
    }
    assert consumed_payload["message_id_hash"] != str(published.message.id)

    denied_payload = audit_by_type["inter_agent_message_denied"].event_payload
    assert set(denied_payload) == {
        "tenant_id",
        "project_id",
        "parent_run_id",
        "attempted_message_id_hash",
        "seq_no",
        "denial_reason",
        "redaction_status",
        "payload_hash",
    }
    assert denied_payload["denial_reason"] == "already_consumed"

    for audit_event in audit_events:
        assert audit_event.actor_id == ACTOR_ID
        assert audit_event.correlation_id is not None
        assert audit_event.correlation_id.startswith("inter-agent:")
        assert audit_event.event_payload["redaction_status"] == "ref_only"
        _assert_no_raw_payload(audit_event.event_payload)
    for run_event in run_events:
        assert run_event.actor_id == ACTOR_ID
        assert set(run_event.event_payload) == {
            "message_id",
            "payload_hash",
            "seq_no",
            "sender_run_id",
            "receiver_run_id",
            "redaction_status",
        }
        _assert_no_raw_payload(run_event.event_payload)
