"""SP-015 batch 0d trusted_instruction approval binding tests."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.repositories.artifact import calculate_content_hash
from backend.app.schemas.inter_agent import InterAgentPublishRequest
from backend.app.services.inter_agent.publisher import (
    InterAgentPublishError,
    InterAgentPublisherService,
    TrustedInstructionGrant,
    TrustedInterAgentActionClass,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ID = 1
REQUESTER_ACTOR_ID = UUID("00000000-0000-4000-8000-000000015201")
DECIDER_ACTOR_ID = UUID("00000000-0000-4000-8000-000000015202")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000015203")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000015204")
PARENT_RUN_ID = UUID("00000000-0000-4000-8000-000000015210")
SENDER_RUN_ID = UUID("00000000-0000-4000-8000-000000015211")
RECEIVER_RUN_ID = UUID("00000000-0000-4000-8000-000000015212")
SOURCE_ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000015220")
APPROVAL_ID = UUID("00000000-0000-4000-8000-000000015230")
POLICY_VERSION = "policy-v-sp015"
PROVIDER_FINGERPRINT = "provider-fingerprint-sp015"
SOURCE_PAYLOAD: dict[str, object] = {"instruction": "approved instruction source"}
SOURCE_HASH = calculate_content_hash(SOURCE_PAYLOAD)

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
        "payload": {"instruction": "apply the approved plan"},
        "classification": {"content_sensitivity_hints": ["internal"]},
        "idempotency_key": f"inter-agent-trusted:{uuid4()}",
        "expires_at": _future_expiry(),
    }
    values.update(overrides)
    return InterAgentPublishRequest.model_validate(values)


def _grant(**overrides: object) -> TrustedInstructionGrant:
    values: dict[str, object] = {
        "approval_request_id": APPROVAL_ID,
        "source_artifact_id": SOURCE_ARTIFACT_ID,
        "artifact_hash": SOURCE_HASH,
        "policy_version": POLICY_VERSION,
        "provider_request_fingerprint": PROVIDER_FINGERPRINT,
        "action_class": "task_write",
    }
    values.update(overrides)
    return TrustedInstructionGrant(**values)  # type: ignore[arg-type]


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-inter-agent-trusted",
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
            raise AssertionError("trusted instruction tests require PostgreSQL.") from exc
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
              approval_requests,
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


async def _insert_fixture(session: AsyncSession, *, approval_status: str = "approved") -> None:
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
            values
              (:requester_actor_id, 1, 'agent', 'agent:trusted-requester',
               'Trusted Requester', '{"rls_ready": true}'::jsonb),
              (:decider_actor_id, 1, 'human', 'human:trusted-decider',
               'Trusted Decider', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "requester_actor_id": REQUESTER_ACTOR_ID,
            "decider_actor_id": DECIDER_ACTOR_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'inter-agent-trusted-workspace',
                    'inter-agent-trusted-workspace', :decider_actor_id,
                    '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "decider_actor_id": DECIDER_ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (:project_id, 1, :workspace_id, 'inter-agent-trusted-project',
                    'inter-agent-trusted-project', 'active', '{"rls_ready": true}'::jsonb)
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
        {"config_hash": "4" * 64, "ruleset_hash": "5" * 64},
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
    await session.execute(
        text(
            """
            insert into artifacts (
              id, tenant_id, run_id, project_id, kind, content_hash, content_jsonb,
              payload_data_class, trust_level, exportable
            )
            values (
              :artifact_id, 1, :sender_run_id, :project_id, 'other', :content_hash,
              cast(:content_jsonb as jsonb), 'internal', 'validated_artifact', false
            )
            """
        ),
        {
            "artifact_id": SOURCE_ARTIFACT_ID,
            "sender_run_id": SENDER_RUN_ID,
            "project_id": PROJECT_ID,
            "content_hash": SOURCE_HASH,
            "content_jsonb": json.dumps(SOURCE_PAYLOAD),
        },
    )
    await session.execute(
        text(
            """
            insert into approval_requests (
              id, tenant_id, run_id, action_class, resource_ref, risk_level,
              artifact_hash, policy_version, provider_request_fingerprint,
              status, requested_by_actor_id, decided_by_actor_id,
              requested_at, decided_at, metadata
            )
            values (
              :approval_id, 1, :sender_run_id, 'task_write',
              'artifact://trusted-source', 'medium', :artifact_hash,
              :policy_version, :provider_request_fingerprint, :status,
              :requester_actor_id, :decider_actor_id,
              now() - interval '10 minutes', now(), '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "approval_id": APPROVAL_ID,
            "sender_run_id": SENDER_RUN_ID,
            "artifact_hash": SOURCE_HASH,
            "policy_version": POLICY_VERSION,
            "provider_request_fingerprint": PROVIDER_FINGERPRINT,
            "status": approval_status,
            "requester_actor_id": REQUESTER_ACTOR_ID,
            "decider_actor_id": DECIDER_ACTOR_ID,
        },
    )


def test_publish_request_rejects_trusted_instruction_server_owned_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden|approval_request_id"):
        _request(approval_request_id=APPROVAL_ID)

    with pytest.raises(ValidationError, match="extra_forbidden|action_class"):
        _request(action_class="task_write")


@pytest.mark.asyncio
@db_required
async def test_publish_trusted_instruction_sets_server_owned_refs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            result = await InterAgentPublisherService(session).publish_trusted_instruction(
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                sender_actor_id=REQUESTER_ACTOR_ID,
                request=_request(),
                trusted_grant=_grant(),
            )

            assert result.message.trust_level == "trusted_instruction"
            assert result.message.approval_request_id == APPROVAL_ID
            assert result.message.source_artifact_id == SOURCE_ARTIFACT_ID
            assert result.message.artifact_hash == SOURCE_HASH
            assert result.message.policy_version == POLICY_VERSION
            assert result.message.provider_request_fingerprint == PROVIDER_FINGERPRINT
            assert result.message.action_class == "task_write"


@pytest.mark.asyncio
@db_required
@pytest.mark.parametrize(
    ("grant_override", "match"),
    [
        ({"artifact_hash": "a" * 64}, "artifact_hash"),
        ({"policy_version": "policy-v-other"}, "policy_version"),
        ({"provider_request_fingerprint": "provider-other"}, "provider_request_fingerprint"),
        ({"action_class": "repo_write"}, "action_class"),
        ({"approval_request_id": UUID("00000000-0000-4000-8000-000000015299")}, "approval_request_id"),
    ],
)
async def test_publish_trusted_instruction_rejects_approval_binding_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
    grant_override: dict[str, object],
    match: str,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            with pytest.raises(InterAgentPublishError, match=match):
                await InterAgentPublisherService(session).publish_trusted_instruction(
                    tenant_id=TENANT_ID,
                    project_id=PROJECT_ID,
                    sender_actor_id=REQUESTER_ACTOR_ID,
                    request=_request(),
                    trusted_grant=_grant(**grant_override),
                )


@pytest.mark.asyncio
@db_required
async def test_publish_trusted_instruction_rejects_expired_approval_reuse(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session, approval_status="expired")
            with pytest.raises(InterAgentPublishError, match="approved"):
                await InterAgentPublisherService(session).publish_trusted_instruction(
                    tenant_id=TENANT_ID,
                    project_id=PROJECT_ID,
                    sender_actor_id=REQUESTER_ACTOR_ID,
                    request=_request(),
                    trusted_grant=_grant(),
                )


@pytest.mark.asyncio
@db_required
async def test_publish_trusted_instruction_rejects_merge_deploy_action_class(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            with pytest.raises(InterAgentPublishError, match="action_class"):
                await InterAgentPublisherService(session).publish_trusted_instruction(
                    tenant_id=TENANT_ID,
                    project_id=PROJECT_ID,
                    sender_actor_id=REQUESTER_ACTOR_ID,
                    request=_request(),
                    trusted_grant=_grant(
                        action_class=cast(TrustedInterAgentActionClass, "merge")
                    ),
                )


@pytest.mark.asyncio
@db_required
async def test_publish_trusted_instruction_rejects_source_artifact_hash_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            await session.execute(
                text(
                    """
                    update artifacts
                       set content_hash = :content_hash
                     where tenant_id = 1
                       and id = :source_artifact_id
                    """
                ),
                {"content_hash": "e" * 64, "source_artifact_id": SOURCE_ARTIFACT_ID},
            )
            with pytest.raises(InterAgentPublishError, match="content_hash"):
                await InterAgentPublisherService(session).publish_trusted_instruction(
                    tenant_id=TENANT_ID,
                    project_id=PROJECT_ID,
                    sender_actor_id=REQUESTER_ACTOR_ID,
                    request=_request(),
                    trusted_grant=_grant(),
                )
