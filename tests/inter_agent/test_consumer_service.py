"""SP-015 batch 0c consumer atomic consume contract tests."""

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
from backend.app.schemas.inter_agent import InterAgentConsumeRequest, InterAgentPublishRequest
from backend.app.services.inter_agent.consumer import (
    InterAgentConsumeDenied,
    InterAgentConsumerService,
)
from backend.app.services.inter_agent.publisher import InterAgentPublisherService

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-000000015101")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000015102")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000015103")
PARENT_RUN_ID = UUID("00000000-0000-4000-8000-000000015110")
SENDER_RUN_ID = UUID("00000000-0000-4000-8000-000000015111")
RECEIVER_RUN_ID = UUID("00000000-0000-4000-8000-000000015112")
OTHER_CHILD_RUN_ID = UUID("00000000-0000-4000-8000-000000015113")

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
        dev_login_cookie_secret="test-cookie-secret-inter-agent-consumer",
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
            raise AssertionError("inter-agent consumer tests require PostgreSQL.") from exc
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
            values (:actor_id, 1, 'human', 'human:inter-agent-consumer',
                    'Inter Agent Consumer Actor', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'inter-agent-consumer-workspace',
                    'inter-agent-consumer-workspace', :actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (:project_id, 1, :workspace_id, 'inter-agent-consumer-project',
                    'inter-agent-consumer-project', 'active', '{"rls_ready": true}'::jsonb)
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
        {"config_hash": "2" * 64, "ruleset_hash": "3" * 64},
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
               'running', 'reviewer', 'global'),
              (:other_child_run_id, 1, :project_id, :parent_run_id,
               'running', 'implementer', 'global')
            """
        ),
        {
            "sender_run_id": SENDER_RUN_ID,
            "receiver_run_id": RECEIVER_RUN_ID,
            "other_child_run_id": OTHER_CHILD_RUN_ID,
            "parent_run_id": PARENT_RUN_ID,
            "project_id": PROJECT_ID,
        },
    )


def _publish_request(**overrides: object) -> InterAgentPublishRequest:
    values: dict[str, object] = {
        "parent_run_id": PARENT_RUN_ID,
        "sender_run_id": SENDER_RUN_ID,
        "receiver_kind": "agent_run",
        "child_run_id": RECEIVER_RUN_ID,
        "payload": {"body": "please review this patch"},
        "classification": {"external_origin": True},
        "idempotency_key": f"inter-agent-consume:{datetime.now(tz=UTC).timestamp()}",
        "expires_at": _future_expiry(),
    }
    values.update(overrides)
    return InterAgentPublishRequest.model_validate(values)


def _consume_request(message_id: UUID, consumer_run_id: UUID) -> InterAgentConsumeRequest:
    return InterAgentConsumeRequest(
        parent_run_id=PARENT_RUN_ID,
        message_id=message_id,
        consumer_run_id=consumer_run_id,
    )


async def _publish(
    session: AsyncSession,
    *,
    request: InterAgentPublishRequest | None = None,
) -> InterAgentMessage:
    result = await InterAgentPublisherService(session).publish(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        sender_actor_id=ACTOR_ID,
        request=request or _publish_request(),
    )
    return result.message


def test_consume_request_excludes_server_owned_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden|tenant_id"):
        InterAgentConsumeRequest.model_validate(
            {
                "parent_run_id": PARENT_RUN_ID,
                "message_id": UUID("00000000-0000-4000-8000-000000015199"),
                "consumer_run_id": RECEIVER_RUN_ID,
                "tenant_id": TENANT_ID,
            }
        )


@pytest.mark.asyncio
@db_required
async def test_direct_consume_marks_message_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            message = await _publish(session)
            result = await InterAgentConsumerService(session).consume(
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                actor_id=ACTOR_ID,
                request=_consume_request(message.id, RECEIVER_RUN_ID),
            )

            assert result.seq_no == 1
            assert result.artifact_ref == message.artifact_ref
            assert result.message.consumed_by_run_id == RECEIVER_RUN_ID

            with pytest.raises(InterAgentConsumeDenied) as denied:
                await InterAgentConsumerService(session).consume(
                    tenant_id=TENANT_ID,
                    project_id=PROJECT_ID,
                    actor_id=ACTOR_ID,
                    request=_consume_request(message.id, RECEIVER_RUN_ID),
                )
            assert denied.value.reason_code == "already_consumed"


@pytest.mark.asyncio
@db_required
async def test_role_and_broadcast_receiver_eligibility(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            role_message = await _publish(
                session,
                request=_publish_request(
                    receiver_kind="role",
                    child_run_id=None,
                    receiver_ref="reviewer",
                    idempotency_key="inter-agent-consume:role",
                ),
            )
            broadcast_message = await _publish(
                session,
                request=_publish_request(
                    receiver_kind="broadcast",
                    child_run_id=None,
                    receiver_ref=None,
                    payload={"body": "broadcast"},
                    idempotency_key="inter-agent-consume:broadcast",
                ),
            )

            role_result = await InterAgentConsumerService(session).consume(
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                actor_id=ACTOR_ID,
                request=_consume_request(role_message.id, RECEIVER_RUN_ID),
            )
            broadcast_result = await InterAgentConsumerService(session).consume(
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                actor_id=ACTOR_ID,
                request=_consume_request(broadcast_message.id, OTHER_CHILD_RUN_ID),
            )

            assert role_result.message.consumed_by_run_id == RECEIVER_RUN_ID
            assert broadcast_result.message.consumed_by_run_id == OTHER_CHILD_RUN_ID


@pytest.mark.asyncio
@db_required
async def test_receiver_hijack_is_denied(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            message = await _publish(session)

            with pytest.raises(InterAgentConsumeDenied) as denied:
                await InterAgentConsumerService(session).consume(
                    tenant_id=TENANT_ID,
                    project_id=PROJECT_ID,
                    actor_id=ACTOR_ID,
                    request=_consume_request(message.id, OTHER_CHILD_RUN_ID),
                )

            assert denied.value.reason_code == "receiver_ineligible"


@pytest.mark.asyncio
@db_required
async def test_sender_self_consume_is_denied(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            message = await _publish(session)

            with pytest.raises(InterAgentConsumeDenied) as denied:
                await InterAgentConsumerService(session).consume(
                    tenant_id=TENANT_ID,
                    project_id=PROJECT_ID,
                    actor_id=ACTOR_ID,
                    request=_consume_request(message.id, SENDER_RUN_ID),
                )

            assert denied.value.reason_code == "sender_self_consume"


@pytest.mark.asyncio
@db_required
async def test_expired_message_is_denied(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            message = await _publish(session)
            await session.execute(
                text(
                    """
                    update inter_agent_messages
                       set created_at = now() - interval '2 hours',
                           expires_at = now() - interval '1 hour'
                     where tenant_id = 1
                       and id = :message_id
                    """
                ),
                {"message_id": message.id},
            )

            with pytest.raises(InterAgentConsumeDenied) as denied:
                await InterAgentConsumerService(session).consume(
                    tenant_id=TENANT_ID,
                    project_id=PROJECT_ID,
                    actor_id=ACTOR_ID,
                    request=_consume_request(message.id, RECEIVER_RUN_ID),
                )

            assert denied.value.reason_code == "expired"


@pytest.mark.asyncio
@db_required
async def test_previous_hash_mismatch_is_denied(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            first = await _publish(
                session,
                request=_publish_request(idempotency_key="inter-agent-consume:first"),
            )
            second = await _publish(
                session,
                request=_publish_request(
                    payload={"body": "second"},
                    idempotency_key="inter-agent-consume:second",
                ),
            )
            await session.execute(
                text(
                    """
                    update inter_agent_messages
                       set payload_hash = :payload_hash
                     where tenant_id = 1
                       and id = :message_id
                    """
                ),
                {"payload_hash": "f" * 64, "message_id": first.id},
            )

            with pytest.raises(InterAgentConsumeDenied) as denied:
                await InterAgentConsumerService(session).consume(
                    tenant_id=TENANT_ID,
                    project_id=PROJECT_ID,
                    actor_id=ACTOR_ID,
                    request=_consume_request(second.id, RECEIVER_RUN_ID),
                )

            assert denied.value.reason_code == "previous_hash_mismatch"


@pytest.mark.asyncio
@db_required
async def test_concurrent_consume_only_one_succeeds(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            message = await _publish(session)

    async def attempt() -> str:
        async with session_factory() as worker_session:
            async with worker_session.begin():
                try:
                    result = await InterAgentConsumerService(worker_session).consume(
                        tenant_id=TENANT_ID,
                        project_id=PROJECT_ID,
                        actor_id=ACTOR_ID,
                        request=_consume_request(message.id, RECEIVER_RUN_ID),
                    )
                except InterAgentConsumeDenied as exc:
                    return exc.reason_code
                return f"ok:{result.seq_no}"

    results = await asyncio.gather(*(attempt() for _ in range(100)))

    assert results.count("ok:1") == 1
    assert results.count("already_consumed") == 99

    async with session_factory() as session:
        consumed = await session.scalar(
            select(InterAgentMessage.consumed_by_run_id).where(
                InterAgentMessage.tenant_id == TENANT_ID,
                InterAgentMessage.id == message.id,
            )
        )
        assert consumed == RECEIVER_RUN_ID
