"""SP-015 batch 0f inter-agent backup/restore drill regression."""

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
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.inter_agent_message import InterAgentMessage
from backend.app.db.session import create_engine
from backend.app.schemas.inter_agent import InterAgentConsumeRequest, InterAgentPublishRequest
from backend.app.services.inter_agent.consumer import InterAgentConsumerService
from backend.app.services.inter_agent.publisher import InterAgentPublisherService

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-000000015401")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000015402")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000015403")
PARENT_RUN_ID = UUID("00000000-0000-4000-8000-000000015410")
SENDER_RUN_ID = UUID("00000000-0000-4000-8000-000000015411")
RECEIVER_RUN_ID = UUID("00000000-0000-4000-8000-000000015412")
PROJECT_ROLE_ID = UUID("00000000-0000-4000-8000-000000015420")

pytestmark = pytest.mark.skipif(
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
        dev_login_cookie_secret="test-cookie-secret-inter-agent-backup-restore",
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
            raise AssertionError("inter-agent backup/restore tests require PostgreSQL.") from exc
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
              project_agent_roles,
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
            values (:actor_id, 1, 'human', 'human:inter-agent-restore',
                    'Inter Agent Restore Actor', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'inter-agent-restore-workspace',
                    'inter-agent-restore-workspace', :actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (:project_id, 1, :workspace_id, 'inter-agent-restore-project',
                    'inter-agent-restore-project', 'active', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"project_id": PROJECT_ID, "workspace_id": WORKSPACE_ID},
    )
    await session.execute(
        text(
            """
            insert into project_agent_roles (
              id, tenant_id, project_id, role_id, display_name, description,
              recommended_provider_tier, created_by_actor_id, deprecated_at, metadata
            )
            values (
              :role_row_id, 1, :project_id, 'custom_reviewer', 'Custom Reviewer',
              'Deprecated custom reviewer used by restore drill fixture',
              'balanced', :actor_id, :deprecated_at, '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "role_row_id": PROJECT_ROLE_ID,
            "project_id": PROJECT_ID,
            "actor_id": ACTOR_ID,
            "deprecated_at": datetime(2026, 5, 24, 8, 0, tzinfo=UTC),
        },
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
        {"config_hash": "8" * 64, "ruleset_hash": "9" * 64},
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
            insert into agent_runs (
              id, tenant_id, project_id, parent_run_id, status, role_id, role_scope
            )
            values
              (:sender_run_id, 1, :project_id, :parent_run_id,
               'running', 'implementer', 'global'),
              (:receiver_run_id, 1, :project_id, :parent_run_id,
               'running', 'reviewer', 'global')
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
            "payload": {"body": "restore drill body stays in artifact only"},
            "classification": {"external_origin": True},
            "idempotency_key": "inter-agent-restore-drill:message",
            "expires_at": _future_expiry(),
        }
    )


def _consume_request(message_id: UUID) -> InterAgentConsumeRequest:
    return InterAgentConsumeRequest(
        parent_run_id=PARENT_RUN_ID,
        message_id=message_id,
        consumer_run_id=RECEIVER_RUN_ID,
    )


@pytest.mark.asyncio
async def test_inter_agent_restore_drill_verifies_required_relationships(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            result = await InterAgentPublisherService(session).publish(
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                sender_actor_id=ACTOR_ID,
                request=_publish_request(),
            )
            await InterAgentConsumerService(session).consume(
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                actor_id=ACTOR_ID,
                request=_consume_request(result.message.id),
            )

        message = await session.scalar(
            select(InterAgentMessage).where(
                InterAgentMessage.tenant_id == TENANT_ID,
                InterAgentMessage.id == result.message.id,
            )
        )
        assert message is not None

        lineage = (
            await session.execute(
                text(
                    """
                    select count(*) as child_count
                      from agent_runs
                     where tenant_id = :tenant_id
                       and project_id = :project_id
                       and parent_run_id = :parent_run_id
                       and id in (:sender_run_id, :receiver_run_id)
                    """
                ),
                {
                    "tenant_id": TENANT_ID,
                    "project_id": PROJECT_ID,
                    "parent_run_id": PARENT_RUN_ID,
                    "sender_run_id": SENDER_RUN_ID,
                    "receiver_run_id": RECEIVER_RUN_ID,
                },
            )
        ).mappings().one()
        assert lineage["child_count"] == 2

        artifact_hash = await session.scalar(
            text(
                """
                select content_hash
                  from artifacts
                 where tenant_id = :tenant_id
                   and project_id = :project_id
                   and id = cast(replace(:artifact_ref, 'artifact://inter-agent/', '') as uuid)
                """
            ),
            {
                "tenant_id": TENANT_ID,
                "project_id": PROJECT_ID,
                "artifact_ref": message.artifact_ref,
            },
        )
        assert message.seq_no == 1
        assert message.previous_hash is None
        assert message.consumed_by_run_id == RECEIVER_RUN_ID
        assert message.payload_hash == artifact_hash

        deprecated_role_at = await session.scalar(
            text(
                """
                select deprecated_at
                  from project_agent_roles
                 where tenant_id = :tenant_id
                   and project_id = :project_id
                   and role_id = 'custom_reviewer'
                """
            ),
            {"tenant_id": TENANT_ID, "project_id": PROJECT_ID},
        )
        assert deprecated_role_at is not None

        memory_records_exist = await session.scalar(
            text("select to_regclass('public.memory_records') is not null")
        )
        if memory_records_exist:
            source_fk_columns = await session.scalar(
                text(
                    """
                    select count(*)
                      from information_schema.key_column_usage
                     where table_schema = 'public'
                       and table_name = 'memory_records'
                       and column_name like '%source%'
                    """
                )
            )
            assert int(source_fk_columns or 0) > 0
        else:
            assert memory_records_exist is False

        audit_rows = (
            await session.execute(
                text(
                    """
                    select event_type, event_payload, correlation_id
                      from audit_events
                     where tenant_id = :tenant_id
                       and event_type in (
                         'inter_agent_message_sent',
                         'inter_agent_message_consumed'
                       )
                     order by event_type
                    """
                ),
                {"tenant_id": TENANT_ID},
            )
        ).mappings().all()
        assert {row["event_type"] for row in audit_rows} == {
            "inter_agent_message_sent",
            "inter_agent_message_consumed",
        }
        assert {row["correlation_id"] for row in audit_rows} == {
            audit_rows[0]["correlation_id"]
        }
        for row in audit_rows:
            payload = dict(row["event_payload"])
            assert payload["payload_hash"] == message.payload_hash
            assert row["correlation_id"].startswith("inter-agent:")
