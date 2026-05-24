"""SP-015 batch 0f SecretBroker token pass-through negative tests."""

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
from backend.app.schemas.inter_agent import InterAgentPublishRequest
from backend.app.services.inter_agent.publisher import (
    InterAgentPublishError,
    InterAgentPublisherService,
)
from backend.app.services.inter_agent.sanitizer import (
    InterAgentPayloadRejected,
    sanitize_inter_agent_payload,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-000000015501")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000015502")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000015503")
PARENT_RUN_ID = UUID("00000000-0000-4000-8000-000000015510")
SENDER_RUN_ID = UUID("00000000-0000-4000-8000-000000015511")
RECEIVER_RUN_ID = UUID("00000000-0000-4000-8000-000000015512")
OPAQUE_CAPABILITY_TOKEN = "opaque-secretbroker-token-must-not-pass-through"

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
        dev_login_cookie_secret="test-cookie-secret-inter-agent-token",
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
            raise AssertionError("inter-agent SecretBroker token tests require PostgreSQL.") from exc
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
            values (:actor_id, 1, 'agent', 'agent:inter-agent-token',
                    'Inter Agent Token Actor', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'inter-agent-token-workspace',
                    'inter-agent-token-workspace', :actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (:project_id, 1, :workspace_id, 'inter-agent-token-project',
                    'inter-agent-token-project', 'active', '{"rls_ready": true}'::jsonb)
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
        {"config_hash": "a" * 64, "ruleset_hash": "b" * 64},
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
            "payload": {
                "body": "try to pass a SecretBroker token",
                "secret_capability_token": OPAQUE_CAPABILITY_TOKEN,
            },
            "classification": {"external_origin": True},
            "idempotency_key": "inter-agent-token-deny:message",
            "expires_at": _future_expiry(),
        }
    )


def test_sanitizer_rejects_inter_agent_secretbroker_token_with_exact_reason() -> None:
    with pytest.raises(InterAgentPayloadRejected) as rejected:
        sanitize_inter_agent_payload(
            {"secret_capability_token": OPAQUE_CAPABILITY_TOKEN},
            schema_version="inter-agent-message.v1",
            sanitizer_policy_version="v1.0.0",
        )
    assert rejected.value.reason_code == "inter_agent_message_token_payload"


@pytest.mark.asyncio
@db_required
async def test_publish_rejects_secretbroker_token_payload_and_audits_without_raw_token(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            with pytest.raises(
                InterAgentPublishError,
                match="inter_agent_message_token_payload",
            ):
                await InterAgentPublisherService(session).publish(
                    tenant_id=TENANT_ID,
                    project_id=PROJECT_ID,
                    sender_actor_id=ACTOR_ID,
                    request=_publish_request(),
                )

        rows = (
            await session.execute(
                text(
                    """
                    select event_type, event_payload, correlation_id
                      from audit_events
                     where tenant_id = :tenant_id
                    """
                ),
                {"tenant_id": TENANT_ID},
            )
        ).mappings().all()
        message_count = await session.scalar(text("select count(*) from inter_agent_messages"))
        artifact_count = await session.scalar(text("select count(*) from artifacts"))
        run_event_count = await session.scalar(text("select count(*) from agent_run_events"))

    assert len(rows) == 1
    row = rows[0]
    assert row["event_type"] == "inter_agent_message_denied"
    assert row["correlation_id"].startswith("inter-agent:")
    payload = dict(row["event_payload"])
    assert payload["denial_reason"] == "inter_agent_message_token_payload"
    assert payload["seq_no"] == 0
    assert payload["redaction_status"] == "ref_only"
    serialized_payload = repr(payload)
    assert OPAQUE_CAPABILITY_TOKEN not in serialized_payload
    assert "secret_capability_token" not in serialized_payload
    assert message_count == 0
    assert artifact_count == 0
    assert run_event_count == 0
