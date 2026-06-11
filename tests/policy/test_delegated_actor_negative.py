"""BL-0035 delegated actor negative tests.

These tests cover same-human impersonation, merge/deploy P0 deny even with an
approval row, and the current actor self-impersonation schema limitation.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.approval_request import ApprovalRequest
from backend.app.db.session import create_engine
from backend.app.seeds.initial_policy_matrix import (
    INITIAL_POLICY_VERSION,
    seed_initial_policy_matrix,
)
from backend.app.services.policy.decision_service import ApprovalDecisionService

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

REQUESTER_ACTOR_ID = UUID("00000000-0000-4000-8000-000000006001")
DELEGATED_ACTOR_ID = UUID("00000000-0000-4000-8000-000000006002")
INDEPENDENT_ACTOR_ID = UUID("00000000-0000-4000-8000-000000006003")
SECOND_DELEGATED_ACTOR_ID = UUID("00000000-0000-4000-8000-000000006004")
APPROVAL_ID = UUID("00000000-0000-4000-8000-000000006011")


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-delegated-actor-negative",
        ),
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
            raise AssertionError(
                "Delegated actor negative tests require a reachable test database."
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


async def _reset_approval_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            "truncate notification_events, policy_decisions, approval_requests "
            "restart identity cascade"
        )
    )


async def _insert_tenant(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (1, 'tenant-one', '{"rls_ready": true}'::jsonb)
            on conflict (id) do update set
              name = excluded.name,
              metadata = excluded.metadata
            """
        )
    )


async def _insert_actor(
    session: AsyncSession,
    *,
    actor_id: UUID,
    actor_type: str,
    stable_actor_id: str,
    display_name: str,
    impersonated_by: UUID | None = None,
) -> None:
    await session.execute(
        text(
            """
            insert into actors (
              id,
              tenant_id,
              actor_type,
              actor_id,
              display_name,
              auth_context_hash,
              impersonated_by,
              metadata
            )
            values (
              :actor_uuid,
              1,
              :actor_type,
              :stable_actor_id,
              :display_name,
              'delegated-actor-auth-context',
              :impersonated_by,
              '{"rls_ready": true}'::jsonb
            )
            on conflict (id) do update set
              actor_type = excluded.actor_type,
              actor_id = excluded.actor_id,
              display_name = excluded.display_name,
              auth_context_hash = excluded.auth_context_hash,
              impersonated_by = excluded.impersonated_by,
              metadata = excluded.metadata
            """
        ),
        {
            "actor_uuid": actor_id,
            "actor_type": actor_type,
            "stable_actor_id": stable_actor_id,
            "display_name": display_name,
            "impersonated_by": impersonated_by,
        },
    )


async def _setup_actors(session: AsyncSession) -> None:
    await _reset_approval_tables(session)
    await _insert_tenant(session)
    await _insert_actor(
        session,
        actor_id=REQUESTER_ACTOR_ID,
        actor_type="human",
        stable_actor_id="human:delegated-requester",
        display_name="Delegated Requester",
    )
    await _insert_actor(
        session,
        actor_id=DELEGATED_ACTOR_ID,
        actor_type="service",
        stable_actor_id="service:approval-bot",
        display_name="Approval Bot",
        impersonated_by=REQUESTER_ACTOR_ID,
    )
    await _insert_actor(
        session,
        actor_id=SECOND_DELEGATED_ACTOR_ID,
        actor_type="service",
        stable_actor_id="service:approval-bot-secondary",
        display_name="Approval Bot Secondary",
        impersonated_by=REQUESTER_ACTOR_ID,
    )
    await _insert_actor(
        session,
        actor_id=INDEPENDENT_ACTOR_ID,
        actor_type="human",
        stable_actor_id="human:independent-reviewer",
        display_name="Independent Reviewer",
    )


async def _insert_approval(
    session: AsyncSession,
    *,
    approval_id: UUID = APPROVAL_ID,
    action_class: str = "merge",
    status: str = "pending",
    requested_by_actor_id: UUID = REQUESTER_ACTOR_ID,
    decided_by_actor_id: UUID | None = None,
) -> ApprovalRequest:
    decided_at = datetime.now(tz=UTC) if decided_by_actor_id is not None else None
    await session.execute(
        text(
            """
            insert into approval_requests (
              id,
              tenant_id,
              action_class,
              resource_ref,
              risk_level,
              artifact_hash,
              diff_hash,
              policy_version,
              policy_pack_lock,
              provider_request_fingerprint,
              stale_after_event_seq,
              status,
              requested_by_actor_id,
              decided_by_actor_id,
              decided_at,
              metadata
            )
            values (
              :id,
              1,
              :action_class,
              :resource_ref,
              'critical',
              'artifact-a',
              'diff-a',
              'policy-v1',
              'pack-a',
              'provider-a',
              1,
              :status,
              :requested_by_actor_id,
              :decided_by_actor_id,
              :decided_at,
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "id": approval_id,
            "action_class": action_class,
            "resource_ref": f"repo:main:{action_class}",
            "status": status,
            "requested_by_actor_id": requested_by_actor_id,
            "decided_by_actor_id": decided_by_actor_id,
            "decided_at": decided_at,
        },
    )
    approval = await session.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.tenant_id == 1,
            ApprovalRequest.id == approval_id,
        )
    )
    assert approval is not None
    return approval


async def _ensure_p0_policy_rule(session: AsyncSession, action_class: str) -> None:
    # 旧 ad-hoc INSERT (merge / deploy のみ 1 行ずつ deny insert) は drift の温床に加え、
    # `truncate cascade` で 7 行 seed が消えた状態で 2 行だけ残し、後続の
    # test_initial_policy_matrix の `assert 7 == len(rows)` を `2 == 7` で fail させていた。
    # 共通 seed module で 7 行揃え、`p0_merge_deploy_disabled` deny effect が含まれる
    # ことを assert で確認するパターンに変更。
    await seed_initial_policy_matrix(session)
    effects = await _p0_policy_effects(session, action_class)
    assert "deny" in effects


async def _p0_policy_effects(session: AsyncSession, action_class: str) -> list[str]:
    result = await session.execute(
        text(
            """
            select effect
            from policy_rules
            where tenant_id = 1
              and action_class = :action_class
              and policy_version = :policy_version
            order by created_at desc, id desc
            """
        ),
        {
            "action_class": action_class,
            "policy_version": INITIAL_POLICY_VERSION,
        },
    )
    return [str(row[0]) for row in result.all()]


@pytest.mark.asyncio
async def test_delegated_actor_forward_direction_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(
            session,
            action_class="merge",
            requested_by_actor_id=REQUESTER_ACTOR_ID,
        )
        await session.commit()

        with pytest.raises(ValueError, match="delegated self-approval forbidden"):
            await ApprovalDecisionService(session).approve(
                tenant_id=1,
                approval=approval,
                decided_by_actor_id=DELEGATED_ACTOR_ID,
                rationale="delegated approval attempt",
            )

        assert approval.status == "pending"


@pytest.mark.asyncio
async def test_delegated_actor_reverse_direction_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(
            session,
            action_class="merge",
            requested_by_actor_id=DELEGATED_ACTOR_ID,
        )
        await session.commit()

        with pytest.raises(ValueError, match="delegated self-approval forbidden"):
            await ApprovalDecisionService(session).approve(
                tenant_id=1,
                approval=approval,
                decided_by_actor_id=REQUESTER_ACTOR_ID,
                rationale="human approving delegated request",
            )

        assert approval.status == "pending"


@pytest.mark.asyncio
async def test_both_delegated_by_same_human_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(
            session,
            action_class="deploy",
            requested_by_actor_id=DELEGATED_ACTOR_ID,
        )
        await session.commit()

        with pytest.raises(ValueError, match="delegated self-approval forbidden"):
            await ApprovalDecisionService(session).approve(
                tenant_id=1,
                approval=approval,
                decided_by_actor_id=SECOND_DELEGATED_ACTOR_ID,
                rationale="same human through another delegated actor",
            )

        assert approval.status == "pending"


@pytest.mark.asyncio
async def test_independent_humans_pass_for_merge(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_actors(session)
        approval = await _insert_approval(
            session,
            action_class="merge",
            requested_by_actor_id=REQUESTER_ACTOR_ID,
        )
        await session.commit()

        updated = await ApprovalDecisionService(session).approve(
            tenant_id=1,
            approval=approval,
            decided_by_actor_id=INDEPENDENT_ACTOR_ID,
            rationale="independent human reviewer",
        )

        assert updated.status == "approved"
        assert updated.decided_by_actor_id == INDEPENDENT_ACTOR_ID


@pytest.mark.asyncio
async def test_merge_action_with_approval_still_denied_by_p0_policy(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _setup_actors(session)
        await _ensure_p0_policy_rule(session, "merge")
        approval = await _insert_approval(
            session,
            action_class="merge",
            status="approved",
            decided_by_actor_id=INDEPENDENT_ACTOR_ID,
        )
        effects = await _p0_policy_effects(session, "merge")

    assert approval.status == "approved"
    assert "deny" in effects


@pytest.mark.asyncio
async def test_deploy_action_with_approval_still_denied(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _setup_actors(session)
        await _ensure_p0_policy_rule(session, "deploy")
        approval = await _insert_approval(
            session,
            action_class="deploy",
            status="approved",
            decided_by_actor_id=INDEPENDENT_ACTOR_ID,
        )
        effects = await _p0_policy_effects(session, "deploy")

    assert approval.status == "approved"
    assert "deny" in effects


@pytest.mark.xfail(
    reason="Sprint 2 actors schema has no actors_impersonated_by_self check; Sprint 4 should add it.",
    strict=False,
)
@pytest.mark.asyncio
async def test_actors_impersonated_by_self_rejected_by_db_check(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_approval_tables(session)
        await _insert_tenant(session)

        with pytest.raises(IntegrityError):
            await _insert_actor(
                session,
                actor_id=REQUESTER_ACTOR_ID,
                actor_type="human",
                stable_actor_id="human:self-impersonation",
                display_name="Self Impersonation",
                impersonated_by=REQUESTER_ACTOR_ID,
            )
            await session.commit()

