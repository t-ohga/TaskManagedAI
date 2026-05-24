"""SP-015 batch 0b publisher + sanitizer contract tests."""

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
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.inter_agent_message import InterAgentMessage
from backend.app.db.session import create_engine
from backend.app.schemas.inter_agent import InterAgentPublishRequest
from backend.app.services.inter_agent.publisher import (
    InterAgentPublishError,
    InterAgentPublisherService,
)
from backend.app.services.inter_agent.sanitizer import sanitize_inter_agent_payload

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-000000015001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000015002")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000015003")
PARENT_RUN_ID = UUID("00000000-0000-4000-8000-000000015010")
SENDER_RUN_ID = UUID("00000000-0000-4000-8000-000000015011")
RECEIVER_RUN_ID = UUID("00000000-0000-4000-8000-000000015012")

db_required = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)


def _future_expiry() -> datetime:
    return datetime.now(tz=UTC) + timedelta(minutes=30)


def _request(**overrides: object) -> InterAgentPublishRequest:
    values: dict[str, object] = {
        "parent_run_id": PARENT_RUN_ID,
        "sender_run_id": SENDER_RUN_ID,
        "receiver_kind": "agent_run",
        "child_run_id": RECEIVER_RUN_ID,
        "payload": {"body": "please review this patch"},
        "classification": {"external_origin": True},
        "idempotency_key": "inter-agent-message:test:1",
        "expires_at": _future_expiry(),
    }
    values.update(overrides)
    return InterAgentPublishRequest.model_validate(values)


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-inter-agent-publisher",
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
            raise AssertionError("inter-agent publisher tests require PostgreSQL.") from exc
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
            values (:actor_id, 1, 'human', 'human:inter-agent-publisher',
                    'Inter Agent Publisher Actor', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'inter-agent-workspace',
                    'inter-agent-workspace', :actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (:project_id, 1, :workspace_id, 'inter-agent-project',
                    'inter-agent-project', 'active', '{"rls_ready": true}'::jsonb)
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
        {"config_hash": "0" * 64, "ruleset_hash": "1" * 64},
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


def test_publish_request_excludes_server_owned_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden|payload_data_class"):
        InterAgentPublishRequest.model_validate(
            {
                "parent_run_id": PARENT_RUN_ID,
                "sender_run_id": SENDER_RUN_ID,
                "receiver_kind": "agent_run",
                "child_run_id": RECEIVER_RUN_ID,
                "payload": {"body": "hello"},
                "payload_data_class": "pii",
                "idempotency_key": "message-1",
                "expires_at": _future_expiry(),
            }
        )

    with pytest.raises(ValidationError, match="extra_forbidden|payload_data_class"):
        _request(classification={"payload_data_class": "pii"})

    with pytest.raises(ValidationError, match="extra_forbidden|trust_level"):
        _request(trust_level="validated_artifact")


def test_publish_request_receiver_shape_is_fail_closed() -> None:
    with pytest.raises(ValidationError, match="child_run_id is required"):
        _request(child_run_id=None)

    with pytest.raises(ValidationError, match="receiver_ref must be null"):
        _request(receiver_ref="reviewer")

    with pytest.raises(ValidationError, match="receiver_ref is required"):
        _request(receiver_kind="role", child_run_id=None, receiver_ref=None)

    with pytest.raises(ValidationError, match="must be null"):
        _request(receiver_kind="broadcast", child_run_id=RECEIVER_RUN_ID)


def test_sanitizer_rejects_raw_secret_key_and_value() -> None:
    with pytest.raises(ValueError, match="prohibited key"):
        sanitize_inter_agent_payload(
            {"secret": "redacted"},
            schema_version="inter-agent-message.v1",
            sanitizer_policy_version="v1.0.0",
        )

    with pytest.raises(ValueError, match="raw secret pattern"):
        sanitize_inter_agent_payload(
            {"body": "sk-" + "a" * 24},
            schema_version="inter-agent-message.v1",
            sanitizer_policy_version="v1.0.0",
        )

    with pytest.raises(ValueError, match="server-owned claim key"):
        sanitize_inter_agent_payload(
            {"payload_data_class": "pii"},
            schema_version="inter-agent-message.v1",
            sanitizer_policy_version="v1.0.0",
        )


@pytest.mark.asyncio
@db_required
async def test_publish_creates_artifact_and_message_chain(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            service = InterAgentPublisherService(session)

            first = await service.publish(
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                sender_actor_id=ACTOR_ID,
                request=_request(idempotency_key="inter-agent-message:test:1"),
            )
            second = await service.publish(
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                sender_actor_id=ACTOR_ID,
                request=_request(
                    payload={"body": "second message"},
                    idempotency_key="inter-agent-message:test:2",
                ),
            )

        assert first.payload_data_class == "internal"
        assert first.artifact.exportable is False
        assert first.artifact.content_hash == first.message.payload_hash
        assert first.artifact.content_jsonb["sanitizer_policy_version"] == "v1.0.0"
        assert first.artifact.content_jsonb["payload"]["body"] == "please review this patch"
        assert first.message.seq_no == 1
        assert first.message.previous_hash is None
        assert first.message.trust_level == "untrusted_content"
        assert first.message.artifact_ref == f"artifact://inter-agent/{first.artifact.id}"

        assert second.message.seq_no == 2
        assert second.message.previous_hash == first.message.payload_hash

        rows = (
            await session.execute(
                select(InterAgentMessage).order_by(InterAgentMessage.seq_no)
            )
        ).scalars().all()
        assert [row.seq_no for row in rows] == [1, 2]
        assert rows[1].previous_hash == rows[0].payload_hash


@pytest.mark.asyncio
@db_required
async def test_publish_rejects_sender_outside_parent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            await session.execute(
                text(
                    """
                    update agent_runs
                       set parent_run_id = null
                     where tenant_id = 1
                       and project_id = :project_id
                       and id = :sender_run_id
                    """
                ),
                {"project_id": PROJECT_ID, "sender_run_id": SENDER_RUN_ID},
            )

            with pytest.raises(InterAgentPublishError, match="sender_run_id"):
                await InterAgentPublisherService(session).publish(
                    tenant_id=TENANT_ID,
                    project_id=PROJECT_ID,
                    sender_actor_id=ACTOR_ID,
                    request=_request(),
                )
