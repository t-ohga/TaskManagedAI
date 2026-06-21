from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
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
from backend.app.services.secrets.broker import BrokerRedeemDenied, SecretBroker

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-000000004801")
DECIDER_ID = UUID("00000000-0000-4000-8000-000000004802")
RUN_ID = UUID("00000000-0000-4000-8000-000000004803")
# SP-029 (Codex R3 F-1): repo.push capability は production run binding 必須になったため、
# repo.push を発行する negative test 用に production run を seed する。
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000004804")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000004805")
SECRET_REF_ID_1 = UUID("00000000-0000-4000-8000-000000004811")
SECRET_REF_ID_2 = UUID("00000000-0000-4000-8000-000000004812")
APPROVAL_ID_1 = UUID("00000000-0000-4000-8000-000000004821")
APPROVAL_ID_2 = UUID("00000000-0000-4000-8000-000000004822")


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-secret-broker-negative",
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
            raise AssertionError("SecretBroker negative tests require PostgreSQL.") from exc
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
              secret_capability_tokens,
              secret_refs,
              approval_requests,
              actors,
              tenants
            restart identity cascade
            """
        )
    )


async def _setup_actor_fixture(session: AsyncSession) -> None:
    await _reset_tables(session)
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (1, 'tenant-one', '{"rls_ready": true}'::jsonb)
            """
        )
    )
    for actor_id, stable_id in (
        (ACTOR_ID, "human:secret-broker-negative"),
        (DECIDER_ID, "human:secret-broker-decider"),
    ):
        await session.execute(
            text(
                """
                insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
                values (:actor_id, 1, 'human', :stable_id, :stable_id, '{"rls_ready": true}'::jsonb)
                """
            ),
            {"actor_id": actor_id, "stable_id": stable_id},
        )
    # SP-029 (Codex R3 F-1): repo.push capability の production-run binding 必須化に伴い、
    # repo.push を発行する negative test 用に production AgentRun を seed する
    # (workspace -> project -> agent_run、run_mode='production')。
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:id, 1, 'sbn-ws', 'sbn-ws', :owner, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"id": WORKSPACE_ID, "owner": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, metadata)
            values (:id, 1, :ws, 'sbn-proj', 'sbn-proj', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"id": PROJECT_ID, "ws": WORKSPACE_ID},
    )
    await session.execute(
        text(
            """
            insert into agent_runs (id, tenant_id, project_id, status, run_mode)
            values (:id, 1, :project, 'running', 'production')
            """
        ),
        {"id": RUN_ID, "project": PROJECT_ID},
    )


async def _insert_secret_ref(
    session: AsyncSession,
    *,
    secret_ref_id: UUID,
    name: str,
    operations: list[str],
) -> None:
    await session.execute(
        text(
            """
            insert into secret_refs (
              id,
              tenant_id,
              secret_uri,
              scope,
              name,
              version,
              status,
              runner_injectable,
              allowed_consumers,
              allowed_operations,
              owner_actor_id,
              metadata,
              material_state
            )
            values (
              :id,
              1,
              :secret_uri,
              'project',
              :name,
              'v1',
              'active',
              false,
              cast(:allowed_consumers as jsonb),
              cast(:allowed_operations as jsonb),
              :owner_actor_id,
              '{"rls_ready": true}'::jsonb,
              'present'
            )
            """
        ),
        {
            "id": secret_ref_id,
            "secret_uri": f"secret://sops/project/{name}#v1",
            "name": name,
            "allowed_consumers": json.dumps([str(ACTOR_ID)]),
            "allowed_operations": json.dumps(operations),
            "owner_actor_id": ACTOR_ID,
        },
    )


async def _insert_approval(
    session: AsyncSession,
    *,
    approval_id: UUID,
    resource_ref: str,
    diff_hash: str,
    action_class: str = "repo_write",
    run_id: UUID | None = RUN_ID,
) -> None:
    # SP-029 (Codex R6 F-2): repo mutation approval は capability と同一 production run に
    # binding 必須になったため、seed 済 production RUN_ID を default で紐付ける。
    await session.execute(
        text(
            """
            insert into approval_requests (
              id,
              tenant_id,
              action_class,
              resource_ref,
              risk_level,
              diff_hash,
              policy_version,
              status,
              requested_by_actor_id,
              decided_by_actor_id,
              decided_at,
              run_id,
              metadata
            )
            values (
              :id,
              1,
              :action_class,
              :resource_ref,
              'medium',
              :diff_hash,
              'policy-v1',
              'approved',
              :requested_by_actor_id,
              :decided_by_actor_id,
              :decided_at,
              :run_id,
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "id": approval_id,
            "action_class": action_class,
            "resource_ref": resource_ref,
            "diff_hash": diff_hash,
            "run_id": run_id,
            "requested_by_actor_id": ACTOR_ID,
            "decided_by_actor_id": DECIDER_ID,
            "decided_at": datetime.now(tz=UTC),
        },
    )


async def _assert_token_still_issued(session: AsyncSession, token_id: UUID) -> None:
    row = (
        await session.execute(
            text(
                """
                select status, used_at
                  from secret_capability_tokens
                 where tenant_id = 1 and id = :token_id
                """
            ),
            {"token_id": token_id},
        )
    ).mappings().one()
    assert row["status"] == "issued"
    assert row["used_at"] is None


@pytest.mark.asyncio
async def test_operation_substitution_fingerprint_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actor_fixture(session)
        await _insert_secret_ref(
            session,
            secret_ref_id=SECRET_REF_ID_1,
            name="provider-openai",
            operations=["provider.call"],
        )
        broker = SecretBroker(session=session)
        issue_result = await broker.issue_capability_token(
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            run_id=RUN_ID,
            secret_ref_id=SECRET_REF_ID_1,
            requested_operation="provider.call",
            target={
                "provider": "openai",
                "api_or_feature": "chat",
                "model_resolved": "gpt-5.5",
            },
            payload_hash="0" * 64,
            policy_version="policy-v1",
            provider_compliance_matrix_version="2026-05-08",
        )
        await session.commit()

        result = await broker.redeem_capability_token(
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            run_id=RUN_ID,
            raw_token=issue_result.raw_token,
            requested_operation="repo.push",
            target={"repo_full_name": "owner/repo", "branch": "main", "commit_sha": "a" * 40},
            payload_hash="0" * 64,
            policy_version="policy-v1",
        )

        assert isinstance(result, BrokerRedeemDenied)
        assert result.reason_code == "fingerprint_mismatch"
        await _assert_token_still_issued(session, issue_result.token_id)


@pytest.mark.asyncio
async def test_target_substitution_fingerprint_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actor_fixture(session)
        await _insert_secret_ref(
            session,
            secret_ref_id=SECRET_REF_ID_1,
            name="repo-push",
            operations=["repo.push"],
        )
        payload_hash = "a" * 64
        target_a = {"repo_full_name": "owner/repoA", "branch": "main", "commit_sha": "a" * 40}
        target_b = {"repo_full_name": "owner/repoB", "branch": "main", "commit_sha": "a" * 40}
        await _insert_approval(
            session,
            approval_id=APPROVAL_ID_1,
            resource_ref="repo:owner/repoA:main",
            diff_hash=payload_hash,
        )

        broker = SecretBroker(session=session)
        issue_result = await broker.issue_capability_token(
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            run_id=RUN_ID,
            secret_ref_id=SECRET_REF_ID_1,
            requested_operation="repo.push",
            target=target_a,
            payload_hash=payload_hash,
            approval_id=APPROVAL_ID_1,
            policy_version="policy-v1",
        )
        await session.commit()

        result = await broker.redeem_capability_token(
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            run_id=RUN_ID,
            raw_token=issue_result.raw_token,
            requested_operation="repo.push",
            target=target_b,
            payload_hash=payload_hash,
            approval_id=APPROVAL_ID_1,
            policy_version="policy-v1",
        )

        assert isinstance(result, BrokerRedeemDenied)
        assert result.reason_code == "fingerprint_mismatch"
        await _assert_token_still_issued(session, issue_result.token_id)


@pytest.mark.asyncio
async def test_payload_substitution_fingerprint_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actor_fixture(session)
        await _insert_secret_ref(
            session,
            secret_ref_id=SECRET_REF_ID_1,
            name="repo-diff",
            operations=["repo.push"],
        )
        target = {"repo_full_name": "owner/repo", "branch": "main", "commit_sha": "a" * 40}
        await _insert_approval(
            session,
            approval_id=APPROVAL_ID_1,
            resource_ref="repo:owner/repo:main",
            diff_hash="a" * 64,
        )

        broker = SecretBroker(session=session)
        issue_result = await broker.issue_capability_token(
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            run_id=RUN_ID,
            secret_ref_id=SECRET_REF_ID_1,
            requested_operation="repo.push",
            target=target,
            payload_hash="a" * 64,
            approval_id=APPROVAL_ID_1,
            policy_version="policy-v1",
        )
        await session.commit()

        result = await broker.redeem_capability_token(
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            run_id=RUN_ID,
            raw_token=issue_result.raw_token,
            requested_operation="repo.push",
            target=target,
            payload_hash="b" * 64,
            approval_id=APPROVAL_ID_1,
            policy_version="policy-v1",
        )

        assert isinstance(result, BrokerRedeemDenied)
        assert result.reason_code == "fingerprint_mismatch"
        await _assert_token_still_issued(session, issue_result.token_id)


@pytest.mark.asyncio
async def test_approval_substitution_fingerprint_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actor_fixture(session)
        await _insert_secret_ref(
            session,
            secret_ref_id=SECRET_REF_ID_1,
            name="repo-approval",
            operations=["repo.push"],
        )
        target = {"repo_full_name": "owner/repo", "branch": "main", "commit_sha": "a" * 40}
        for approval_id in (APPROVAL_ID_1, APPROVAL_ID_2):
            await _insert_approval(
                session,
                approval_id=approval_id,
                resource_ref="repo:owner/repo:main",
                diff_hash="a" * 64,
            )

        broker = SecretBroker(session=session)
        issue_result = await broker.issue_capability_token(
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            run_id=RUN_ID,
            secret_ref_id=SECRET_REF_ID_1,
            requested_operation="repo.push",
            target=target,
            payload_hash="a" * 64,
            approval_id=APPROVAL_ID_1,
            policy_version="policy-v1",
        )
        await session.commit()

        result = await broker.redeem_capability_token(
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            run_id=RUN_ID,
            raw_token=issue_result.raw_token,
            requested_operation="repo.push",
            target=target,
            payload_hash="a" * 64,
            approval_id=APPROVAL_ID_2,
            policy_version="policy-v1",
        )

        assert isinstance(result, BrokerRedeemDenied)
        assert result.reason_code == "fingerprint_mismatch"
        await _assert_token_still_issued(session, issue_result.token_id)


@pytest.mark.asyncio
async def test_secret_ref_substitution_fingerprint_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actor_fixture(session)
        await _insert_secret_ref(
            session,
            secret_ref_id=SECRET_REF_ID_1,
            name="verify-one",
            operations=["secret.verify"],
        )
        await _insert_secret_ref(
            session,
            secret_ref_id=SECRET_REF_ID_2,
            name="verify-two",
            operations=["secret.verify"],
        )

        broker = SecretBroker(session=session)
        issue_result = await broker.issue_capability_token(
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            run_id=RUN_ID,
            secret_ref_id=SECRET_REF_ID_1,
            requested_operation="secret.verify",
            target={"secret_ref_id": str(SECRET_REF_ID_1), "version": "v1"},
            payload_hash="0" * 64,
            policy_version="policy-v1",
        )
        await session.commit()

        result = await broker.redeem_capability_token(
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            run_id=RUN_ID,
            raw_token=issue_result.raw_token,
            requested_operation="secret.verify",
            target={"secret_ref_id": str(SECRET_REF_ID_2), "version": "v1"},
            payload_hash="0" * 64,
            policy_version="policy-v1",
        )

        assert isinstance(result, BrokerRedeemDenied)
        assert result.reason_code == "fingerprint_mismatch"
        await _assert_token_still_issued(session, issue_result.token_id)

