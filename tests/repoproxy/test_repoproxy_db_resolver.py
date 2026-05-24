"""SP-008 Batch A2: DB-backed RepoProxy Draft PR resolver tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from asyncpg.exceptions import PostgresError  # type: ignore[import-untyped]
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.domain.agent_runtime.operation_context import canonical_json_dumps
from backend.app.services.repoproxy.draft_pr_resolver import DbDraftPRRequestResolver
from backend.app.services.repoproxy.repoproxy import (
    DraftPRBinding,
    DraftPRRequest,
    RepoProxyDenyReason,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ID = 1
OTHER_TENANT_ID = 2
REQUESTER_ACTOR_ID = UUID("00000000-0000-4000-8000-00000000b001")
DECIDER_ACTOR_ID = UUID("00000000-0000-4000-8000-00000000b002")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-00000000b011")
PROJECT_ID = UUID("00000000-0000-4000-8000-00000000b021")
RUN_ID = UUID("00000000-0000-4000-8000-00000000b031")
OTHER_RUN_ID = UUID("00000000-0000-4000-8000-00000000b032")
APPROVAL_ID = UUID("00000000-0000-4000-8000-00000000b041")
BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40
DIFF_HASH = "a" * 64
POLICY_VERSION = "policy-v1"
PROVIDER_PAYLOAD = {
    "model_resolved": "gpt-5.4",
    "api_version": "responses-v1",
    "sdk_version": "sdk-v1",
    "request_payload_hash": "b" * 64,
    "provider_compliance_matrix_version": "pcm-v1",
}
PROVIDER_FINGERPRINT = hashlib.sha256(
    canonical_json_dumps(PROVIDER_PAYLOAD).encode("utf-8")
).hexdigest()
RESOURCE_REF = (
    "repo:owner/repo:pr:main:codex/agent-run-abcd1234:"
    f"draft:commit:{HEAD_SHA}:state:{BASE_SHA}"
)


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-repoproxy-db-resolver",
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
            raise AssertionError(
                "RepoProxy DB resolver tests require a reachable test database."
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
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _setup_runtime_fixture(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate
              context_snapshots,
              approval_requests,
              agent_runs,
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
            values
              (1, 'tenant-one', '{"rls_ready": true}'::jsonb),
              (2, 'tenant-two', '{"rls_ready": true}'::jsonb)
            """
        )
    )
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values
              (:requester_actor_id, 1, 'human', 'human:repo-requester',
                'Repo Requester', '{"rls_ready": true}'::jsonb),
              (:decider_actor_id, 1, 'human', 'human:repo-decider',
                'Repo Decider', '{"rls_ready": true}'::jsonb)
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
            values (:workspace_id, 1, 'repo-workspace', 'repo-workspace',
                    :requester_actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "requester_actor_id": REQUESTER_ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (:project_id, 1, :workspace_id, 'repo-project', 'repo-project',
                    'active', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"project_id": PROJECT_ID, "workspace_id": WORKSPACE_ID},
    )
    await session.execute(
        text(
            """
            insert into agent_runs (id, tenant_id, project_id, status)
            values (:run_id, 1, :project_id, 'queued')
            """
        ),
        {"run_id": RUN_ID, "project_id": PROJECT_ID},
    )


async def _insert_approval(
    session: AsyncSession,
    *,
    approval_id: UUID = APPROVAL_ID,
    status: str = "approved",
    resource_ref: str = RESOURCE_REF,
    diff_hash: str | None = DIFF_HASH,
    policy_version: str = POLICY_VERSION,
    provider_request_fingerprint: str | None = PROVIDER_FINGERPRINT,
    run_id: UUID | None = RUN_ID,
) -> None:
    params: dict[str, Any] = {
        "approval_id": approval_id,
        "run_id": run_id,
        "resource_ref": resource_ref,
        "diff_hash": diff_hash,
        "policy_version": policy_version,
        "provider_request_fingerprint": provider_request_fingerprint,
        "status": status,
        "requester_actor_id": REQUESTER_ACTOR_ID,
    }
    if status in {"approved", "rejected"}:
        params["decider_actor_id"] = DECIDER_ACTOR_ID
        await session.execute(
            text(
                """
                insert into approval_requests (
                  id, tenant_id, run_id, action_class, resource_ref, risk_level,
                  artifact_hash, diff_hash, policy_version, policy_pack_lock,
                  provider_request_fingerprint, status, requested_by_actor_id, metadata,
                  decided_by_actor_id, decided_at
                )
                values (
                  :approval_id, 1, :run_id, 'pr_open', :resource_ref, 'medium',
                  null, :diff_hash, :policy_version, null,
                  :provider_request_fingerprint, :status, :requester_actor_id,
                  '{"rls_ready": true}'::jsonb, :decider_actor_id, now()
                )
                """
            ),
            params,
        )
        return

    await session.execute(
        text(
            """
            insert into approval_requests (
              id, tenant_id, run_id, action_class, resource_ref, risk_level,
              artifact_hash, diff_hash, policy_version, policy_pack_lock,
              provider_request_fingerprint, status, requested_by_actor_id, metadata
            )
            values (
              :approval_id, 1, :run_id, 'pr_open', :resource_ref, 'medium',
              null, :diff_hash, :policy_version, null,
              :provider_request_fingerprint, :status, :requester_actor_id,
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        params,
    )


def _json(value: object) -> str:
    return json.dumps(value)


async def _insert_snapshot(
    session: AsyncSession,
    *,
    run_id: UUID = RUN_ID,
    created_at: datetime | None = None,
    repo_state: dict[str, object] | None = None,
    policy_version: str = POLICY_VERSION,
    provider_request_fingerprint: dict[str, object] | None = None,
) -> None:
    created_at = created_at or datetime.now(UTC)
    repo_state = repo_state or {
        "commit_sha": BASE_SHA,
        "branch": "main",
        "dirty": False,
        "diff_hash": DIFF_HASH,
    }
    if provider_request_fingerprint is None:
        provider_request_fingerprint = dict(PROVIDER_PAYLOAD)
    await session.execute(
        text(
            """
            insert into context_snapshots (
              id, tenant_id, run_id, prompt_pack_version, prompt_pack_lock,
              policy_version, policy_pack_lock, repo_state, tool_manifest,
              evidence_set_hash, provider_request_fingerprint, snapshot_kind, created_at
            )
            values (
              :snapshot_id, 1, :run_id, 'prompt-pack-v1', :prompt_pack_lock,
              :policy_version, :policy_pack_lock, cast(:repo_state as jsonb),
              cast(:tool_manifest as jsonb), :evidence_set_hash,
              cast(:provider_request_fingerprint as jsonb), 'post_tool', :created_at
            )
            """
        ),
        {
            "snapshot_id": uuid4(),
            "run_id": run_id,
            "prompt_pack_lock": "c" * 64,
            "policy_version": policy_version,
            "policy_pack_lock": "d" * 64,
            "repo_state": _json(repo_state),
            "tool_manifest": _json(
                {"registry_version": "tool-registry-v1", "allowlist_hash": "e" * 64}
            ),
            "evidence_set_hash": "f" * 64,
            "provider_request_fingerprint": _json(provider_request_fingerprint),
            "created_at": created_at,
        },
    )


async def _approval_status(session: AsyncSession) -> str | None:
    status = await session.scalar(
        text(
            """
            select status
            from approval_requests
            where tenant_id = 1 and id = :approval_id
            """
        ),
        {"approval_id": APPROVAL_ID},
    )
    return status if isinstance(status, str) else None


def _binding(
    *,
    tenant_id: int = TENANT_ID,
    approval_id: UUID = APPROVAL_ID,
    run_id: UUID = RUN_ID,
) -> DraftPRBinding:
    return DraftPRBinding(
        tenant_id=tenant_id,
        approval_id=approval_id,
        agent_run_id=run_id,
    )


@pytest.mark.asyncio
async def test_db_resolver_resolves_latest_server_owned_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await _insert_approval(session)
        await _insert_snapshot(
            session,
            created_at=datetime.now(UTC) - timedelta(minutes=1),
            repo_state={
                "commit_sha": "3" * 40,
                "branch": "main",
                "dirty": False,
                "diff_hash": DIFF_HASH,
            },
        )
        await _insert_snapshot(session, created_at=datetime.now(UTC))
        await session.commit()

        result = await DbDraftPRRequestResolver(session).resolve_draft_pr_request(
            _binding()
        )

        assert isinstance(result, DraftPRRequest)
        assert result.repo_full_name == "owner/repo"
        assert result.head_branch == "codex/agent-run-abcd1234"
        assert result.repo_state_commit_sha == BASE_SHA
        assert await _approval_status(session) == "approved"


@pytest.mark.asyncio
async def test_db_resolver_fails_closed_for_missing_approval(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await _insert_snapshot(session)
        await session.commit()

        result = await DbDraftPRRequestResolver(session).resolve_draft_pr_request(
            _binding(approval_id=UUID("00000000-0000-4000-8000-00000000b099"))
        )

        assert result == RepoProxyDenyReason.APPROVAL_NOT_GRANTED


@pytest.mark.asyncio
async def test_db_resolver_scopes_approval_by_tenant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await _insert_approval(session)
        await _insert_snapshot(session)
        await session.commit()

        result = await DbDraftPRRequestResolver(session).resolve_draft_pr_request(
            _binding(tenant_id=OTHER_TENANT_ID)
        )

        assert result == RepoProxyDenyReason.APPROVAL_NOT_GRANTED


@pytest.mark.asyncio
async def test_db_resolver_scopes_approval_by_agent_run_without_invalidating(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await _insert_approval(session)
        await _insert_snapshot(session)
        await session.commit()

        result = await DbDraftPRRequestResolver(session).resolve_draft_pr_request(
            _binding(run_id=OTHER_RUN_ID)
        )

        assert result == RepoProxyDenyReason.APPROVAL_NOT_GRANTED
        assert await _approval_status(session) == "approved"


@pytest.mark.asyncio
async def test_db_resolver_invalidates_approved_when_snapshot_missing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await _insert_approval(session)
        await session.commit()

        result = await DbDraftPRRequestResolver(session).resolve_draft_pr_request(
            _binding()
        )

        assert result == RepoProxyDenyReason.REPO_STATE_MISMATCH
        assert await _approval_status(session) == "invalidated"


@pytest.mark.asyncio
async def test_db_resolver_invalidates_approved_on_repo_state_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await _insert_approval(session)
        await _insert_snapshot(
            session,
            repo_state={
                "commit_sha": "3" * 40,
                "branch": "main",
                "dirty": False,
                "diff_hash": DIFF_HASH,
            },
        )
        await session.commit()

        result = await DbDraftPRRequestResolver(session).resolve_draft_pr_request(
            _binding()
        )

        assert result == RepoProxyDenyReason.REPO_STATE_MISMATCH
        assert await _approval_status(session) == "invalidated"


@pytest.mark.asyncio
async def test_db_resolver_keeps_pending_approval_pending(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await _insert_approval(session, status="pending")
        await _insert_snapshot(session)
        await session.commit()

        result = await DbDraftPRRequestResolver(session).resolve_draft_pr_request(
            _binding()
        )

        assert result == RepoProxyDenyReason.APPROVAL_NOT_GRANTED
        assert await _approval_status(session) == "pending"
