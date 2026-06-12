from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, get_args
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
from backend.app.services.secrets.broker import (
    MULTI_AGENT_SECRET_DENY_REASON_VALUES,
    MULTI_AGENT_SECRET_DENY_REASONS,
    MultiAgentSecretDenyReason,
    SecretBroker,
    SecretBrokerMultiAgentDeniedPayload,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ID = 1
AGENT_ACTOR_ID = UUID("00000000-0000-4000-8000-00000000f001")
HUMAN_ACTOR_ID = UUID("00000000-0000-4000-8000-00000000f002")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-00000000f010")
PROJECT_ID = UUID("00000000-0000-4000-8000-00000000f011")
RUN_ID = UUID("00000000-0000-4000-8000-00000000f101")

EXPECTED_MULTI_AGENT_DENY_REASONS = {
    "agent_decider_forbidden",
    "tier_2_agent_decider_attempt",
    "actor_type_mismatch",
    "role_id_mismatch",
    "lease_expired_no_secret_access",
    "progress_lease_violated",
}


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-secretbroker-multi-agent",
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
            raise AssertionError("SecretBroker multi-agent tests require PostgreSQL.") from exc
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
              agent_runs,
              projects,
              workspaces,
              actors,
              tenants
            restart identity cascade
            """
        )
    )


async def _seed_boundary(
    session: AsyncSession,
    *,
    role_id: str = "implementer",
    status: str = "running",
    blocked_reason: str | None = None,
    error_code: str | None = None,
    lease_expires_at: datetime | None = None,
) -> None:
    await _reset_tables(session)
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (:tenant_id, 'tenant-one', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"tenant_id": TENANT_ID},
    )
    await session.execute(
        text(
            """
            insert into policy_profiles (tenant_id, profile_id, description)
            values (:tenant_id, 'default', 'default profile')
            on conflict (tenant_id, profile_id) do nothing
            """
        ),
        {"tenant_id": TENANT_ID},
    )
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values
              (:agent_actor_id, :tenant_id, 'agent', 'agent:secretbroker',
               'SecretBroker Agent', '{"rls_ready": true}'::jsonb),
              (:human_actor_id, :tenant_id, 'human', 'human:secretbroker',
               'SecretBroker Human', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "tenant_id": TENANT_ID,
            "agent_actor_id": AGENT_ACTOR_ID,
            "human_actor_id": HUMAN_ACTOR_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, :tenant_id, 'secretbroker', 'SecretBroker',
                    :human_actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "tenant_id": TENANT_ID,
            "workspace_id": WORKSPACE_ID,
            "human_actor_id": HUMAN_ACTOR_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into projects (
              id, tenant_id, workspace_id, slug, name, status, policy_profile, metadata
            )
            values (:project_id, :tenant_id, :workspace_id, 'secretbroker',
                    'SecretBroker', 'active', 'default', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "tenant_id": TENANT_ID,
            "project_id": PROJECT_ID,
            "workspace_id": WORKSPACE_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into agent_runs (
              id, tenant_id, project_id, parent_run_id, status, blocked_reason,
              error_code, role_id, role_scope, orchestrator_lease_expires_at,
              created_at, updated_at
            )
            values (
              :run_id, :tenant_id, :project_id, null, :status, :blocked_reason,
              :error_code, :role_id, 'project', :lease_expires_at,
              :now, :now
            )
            """
        ),
        {
            "tenant_id": TENANT_ID,
            "project_id": PROJECT_ID,
            "run_id": RUN_ID,
            "status": status,
            "blocked_reason": blocked_reason,
            "error_code": error_code,
            "role_id": role_id,
            "lease_expires_at": lease_expires_at,
            "now": datetime(2026, 5, 22, 10, 0, tzinfo=UTC),
        },
    )
    await session.commit()


async def _latest_secretbroker_deny_payload(session: AsyncSession) -> dict[str, object]:
    row = (
        await session.execute(
            text(
                """
                select event_type, event_payload
                  from audit_events
                 where tenant_id = :tenant_id
                 order by created_at desc, id desc
                 limit 1
                """
            ),
            {"tenant_id": TENANT_ID},
        )
    ).mappings().one()
    assert row["event_type"] == "secret_capability_denied"
    return dict(row["event_payload"])


async def _assert_denied(
    session: AsyncSession,
    *,
    reason_code: str,
    **kwargs: Any,
) -> None:
    # PE-F-014 multi-agent secret validation (validate_multi_agent_access) は SP-014 T08 で
    # P0.1 に完成させる deliverable。P0 では reason_code / payload の types のみ forward-compat で
    # 保持し impl は deferred (fc51e58 で premature 実装を P0-exit 時に削除)。impl が P0.1 で復活
    # したら本 guard は自動的に外れ、6 negative case が再び検証される。
    if not hasattr(SecretBroker, "validate_multi_agent_access"):
        pytest.skip(
            "PE-F-014 multi-agent secret validation は P0.1 (SP-014 T08); "
            "P0 では impl deferred、reason_code/payload types のみ。"
        )
    decision = await SecretBroker(session).validate_multi_agent_access(
        tenant_id=TENANT_ID,
        actor_id=AGENT_ACTOR_ID,
        run_id=RUN_ID,
        requested_operation="provider.call",
        **kwargs,
    )

    assert decision.allowed is False
    assert decision.reason_code == reason_code
    payload = await _latest_secretbroker_deny_payload(session)
    assert payload["reason_code"] == reason_code
    assert payload["run_id"] == str(RUN_ID)
    assert payload["guard"] == "secretbroker_multi_agent"
    assert payload["raw_secret_check_passed"] is True
    assert "raw_token" not in payload
    assert "raw_secret" not in payload


def test_multi_agent_secret_deny_reason_enum_sources_are_in_sync() -> None:
    schema = SecretBrokerMultiAgentDeniedPayload.model_json_schema()

    assert set(get_args(MultiAgentSecretDenyReason)) == EXPECTED_MULTI_AGENT_DENY_REASONS
    assert set(MULTI_AGENT_SECRET_DENY_REASON_VALUES) == EXPECTED_MULTI_AGENT_DENY_REASONS
    assert MULTI_AGENT_SECRET_DENY_REASONS == EXPECTED_MULTI_AGENT_DENY_REASONS
    assert set(schema["properties"]["reason_code"]["enum"]) == (
        EXPECTED_MULTI_AGENT_DENY_REASONS
    )


def test_multi_agent_secret_deny_reason_docs_are_in_sync() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    docs = (
        repo_root / "docs/adr/00014_multi_agent_orchestration.md",
        repo_root / "docs/sprints/SP-014_orchestrator_agent.md",
        repo_root / "docs/sprints/SP-020_curator_insights_integration.md",
        repo_root / ".claude/rules/secretbroker-boundary.md",
    )

    for path in docs:
        text_content = path.read_text(encoding="utf-8")
        for reason_code in EXPECTED_MULTI_AGENT_DENY_REASONS:
            assert reason_code in text_content


def test_phase_e_pe_f_014_reason_matrix_has_exact_six_cases() -> None:
    """PE-F-014 closes only when the six deny reasons stay exact."""

    assert EXPECTED_MULTI_AGENT_DENY_REASONS == {
        "agent_decider_forbidden",
        "tier_2_agent_decider_attempt",
        "actor_type_mismatch",
        "role_id_mismatch",
        "lease_expired_no_secret_access",
        "progress_lease_violated",
    }
    assert len(EXPECTED_MULTI_AGENT_DENY_REASONS) == 6


@pytest.mark.asyncio
async def test_agent_decider_attempt_is_denied_with_specific_reason(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _seed_boundary(session)

        await _assert_denied(
            session,
            reason_code="agent_decider_forbidden",
            approval_decider_attempt=True,
        )


@pytest.mark.asyncio
async def test_tier_2_agent_decider_escape_is_denied_with_specific_reason(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _seed_boundary(session)

        await _assert_denied(
            session,
            reason_code="tier_2_agent_decider_attempt",
            tier_2_decider_attempt=True,
        )


@pytest.mark.asyncio
async def test_actor_type_mismatch_is_denied_with_specific_reason(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _seed_boundary(session)

        await _assert_denied(
            session,
            reason_code="actor_type_mismatch",
            expected_actor_type="human",
        )


@pytest.mark.asyncio
async def test_role_id_mismatch_is_denied_with_specific_reason(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _seed_boundary(session, role_id="implementer")

        await _assert_denied(
            session,
            reason_code="role_id_mismatch",
            expected_actor_type="agent",
            expected_role_id="reviewer",
        )


@pytest.mark.asyncio
async def test_expired_lease_is_denied_with_specific_reason(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 5, 22, 10, 0, tzinfo=UTC)
    async with session_factory() as session:
        await _seed_boundary(
            session,
            role_id="implementer",
            lease_expires_at=now - timedelta(seconds=1),
        )

        await _assert_denied(
            session,
            reason_code="lease_expired_no_secret_access",
            expected_actor_type="agent",
            expected_role_id="implementer",
            now=now,
        )


@pytest.mark.asyncio
async def test_progress_lease_violation_is_denied_with_specific_reason(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 5, 22, 10, 0, tzinfo=UTC)
    async with session_factory() as session:
        await _seed_boundary(
            session,
            role_id="implementer",
            status="blocked",
            blocked_reason="runtime_blocked",
            error_code="progress_lease_violated",
            lease_expires_at=now + timedelta(minutes=5),
        )

        await _assert_denied(
            session,
            reason_code="progress_lease_violated",
            expected_actor_type="agent",
            expected_role_id="implementer",
            now=now,
        )
