"""SP-014 batch 0c: policy_profile seed and server-owned boundary tests."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.domain.policy.profile import POLICY_PROFILE_ACTION_EFFECTS
from backend.app.repositories.project import ProjectRepository
from backend.app.schemas.project import ProjectCreate
from backend.app.seeds.initial_policy_profiles import seed_initial_policy_profiles
from backend.app.services.policy.profile_resolver import (
    resolve_policy_profile_action_effect,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-000000027001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000027002")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000027003")
TRIGGER_TENANT_ID = 77
MISSING_TENANT_A_ID = 7701
MISSING_TENANT_B_ID = 7702


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-policy-profile",
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
            raise AssertionError("policy profile tests require PostgreSQL.") from exc
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


async def _reset_project_fixture(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate
              policy_decisions,
              review_artifacts,
              artifacts,
              agent_run_events,
              agent_runs,
              approval_requests,
              project_agent_roles,
              projects,
              workspaces,
              actors
            restart identity cascade
            """
        )
    )
    await seed_initial_policy_profiles(session, tenant_id=TENANT_ID)
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values (:actor_id, 1, 'human', 'human:policy-profile-test',
                    'Policy Profile Test Actor', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'policy-profile-workspace',
                    'policy-profile-workspace', :actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )


def test_project_create_rejects_caller_supplied_policy_profile() -> None:
    with pytest.raises(ValidationError, match="policy_profile|extra_forbidden"):
        ProjectCreate.model_validate(
            {
                "workspace_id": WORKSPACE_ID,
                "slug": "project",
                "name": "project",
                "policy_profile": "low_risk_auto_allow",
            }
        )


@pytest.mark.asyncio
async def test_policy_profiles_seed_exact_two_profiles(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        rows = (
            await session.execute(
                text(
                    """
                    select profile_id from policy_profiles
                     where tenant_id = 1
                     order by profile_id
                    """
                )
            )
        ).scalars().all()

    assert rows == ["default", "low_risk_auto_allow"]


@pytest.mark.asyncio
async def test_seed_initial_policy_profiles_uses_unique_names_for_missing_tenants(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_params = {
        "tenant_a_id": MISSING_TENANT_A_ID,
        "tenant_b_id": MISSING_TENANT_B_ID,
    }
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                text("delete from tool_versions where tenant_id in (:tenant_a_id, :tenant_b_id)"),
                tenant_params,
            )
            await session.execute(
                text("delete from tool_network_policies where tenant_id in (:tenant_a_id, :tenant_b_id)"),
                tenant_params,
            )
            await session.execute(
                text("delete from tool_registry where tenant_id in (:tenant_a_id, :tenant_b_id)"),
                tenant_params,
            )
            await session.execute(
                text("delete from policy_profile_action_effects where tenant_id in (:tenant_a_id, :tenant_b_id)"),
                tenant_params,
            )
            await session.execute(
                text("delete from policy_profiles where tenant_id in (:tenant_a_id, :tenant_b_id)"),
                tenant_params,
            )
            await session.execute(
                text(
                    """
                    delete from tenants
                     where id in (:tenant_a_id, :tenant_b_id)
                    """
                ),
                tenant_params,
            )

            await seed_initial_policy_profiles(session, tenant_id=MISSING_TENANT_A_ID)
            await seed_initial_policy_profiles(session, tenant_id=MISSING_TENANT_B_ID)

        rows = (
            await session.execute(
                text(
                    """
                    select id, name
                      from tenants
                     where id in (:tenant_a_id, :tenant_b_id)
                     order by id
                    """
                ),
                tenant_params,
            )
        ).all()

    assert [(row.id, row.name) for row in rows] == [
        (MISSING_TENANT_A_ID, "default-tenant-7701"),
        (MISSING_TENANT_B_ID, "default-tenant-7702"),
    ]


@pytest.mark.asyncio
async def test_policy_profile_action_effects_seed_exact_14_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    expected = {
        (profile, action_class): (effect, require_review_artifact)
        for profile, actions in POLICY_PROFILE_ACTION_EFFECTS.items()
        for action_class, (effect, require_review_artifact) in actions.items()
    }
    async with session_factory() as session:
        rows = (
            await session.execute(
                text(
                    """
                    select profile_id, action_class, effect, require_review_artifact
                      from policy_profile_action_effects
                     where tenant_id = 1
                     order by profile_id, action_class
                    """
                )
            )
        ).all()

    actual = {
        (profile_id, action_class): (effect, require_review_artifact)
        for profile_id, action_class, effect, require_review_artifact in rows
    }
    assert actual == expected
    assert len(actual) == 14


@pytest.mark.asyncio
async def test_new_tenant_insert_seeds_policy_profiles(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                text("delete from policy_profile_action_effects where tenant_id = :tenant_id"),
                {"tenant_id": TRIGGER_TENANT_ID},
            )
            await session.execute(
                text("delete from policy_profiles where tenant_id = :tenant_id"),
                {"tenant_id": TRIGGER_TENANT_ID},
            )
            await session.execute(
                text("delete from tenants where id = :tenant_id"),
                {"tenant_id": TRIGGER_TENANT_ID},
            )
            await session.execute(
                text(
                    """
                    insert into tenants (id, name, metadata)
                    values (:tenant_id, 'trigger-policy-profile-tenant',
                            '{"rls_ready": true}'::jsonb)
                    """
                ),
                {"tenant_id": TRIGGER_TENANT_ID},
            )

        profiles = (
            await session.execute(
                text(
                    """
                    select profile_id from policy_profiles
                     where tenant_id = :tenant_id
                     order by profile_id
                    """
                ),
                {"tenant_id": TRIGGER_TENANT_ID},
            )
        ).scalars().all()
        action_effect_count = await session.scalar(
            text(
                """
                select count(*) from policy_profile_action_effects
                 where tenant_id = :tenant_id
                """
            ),
            {"tenant_id": TRIGGER_TENANT_ID},
        )

    assert profiles == ["default", "low_risk_auto_allow"]
    assert action_effect_count == 14


@pytest.mark.asyncio
async def test_project_policy_profile_defaults_and_rejects_unknown_profile(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _reset_project_fixture(session)
            await session.execute(
                text(
                    """
                    insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
                    values (:project_id, 1, :workspace_id, 'profile-default',
                            'profile-default', 'active', '{"rls_ready": true}'::jsonb)
                    """
                ),
                {"project_id": PROJECT_ID, "workspace_id": WORKSPACE_ID},
            )

        profile = await session.scalar(
            text("select policy_profile from projects where id = :project_id"),
            {"project_id": PROJECT_ID},
        )
        assert profile == "default"

        with pytest.raises(DBAPIError, match="projects_policy_profile_fkey"):
            await session.execute(
                text(
                    """
                    update projects
                       set policy_profile = 'unknown_profile'
                     where id = :project_id
                    """
                ),
                {"project_id": PROJECT_ID},
            )
            await session.commit()


@pytest.mark.asyncio
async def test_project_repository_rejects_policy_profile_payload(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _reset_project_fixture(session)
            repository = ProjectRepository(session)
            with pytest.raises(ValueError, match="policy_profile is server-owned"):
                await repository.create(
                    tenant_id=TENANT_ID,
                    payload={
                        "id": PROJECT_ID,
                        "workspace_id": WORKSPACE_ID,
                        "slug": "repo-project",
                        "name": "repo-project",
                        "policy_profile": "low_risk_auto_allow",
                    },
                )


@pytest.mark.asyncio
async def test_policy_profile_resolver_fail_closed_for_unknown_or_missing_seed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        unknown = await resolve_policy_profile_action_effect(
            session,
            tenant_id=TENANT_ID,
            policy_profile="unknown_profile",
            action_class="task_write",
        )
        assert unknown.effect == "deny"
        assert unknown.reason_code == "unknown_policy_profile_denied"

        try:
            await session.execute(
                text(
                    """
                    delete from policy_profile_action_effects
                     where tenant_id = 1
                       and profile_id = 'low_risk_auto_allow'
                       and action_class = 'task_write'
                    """
                )
            )
            await session.commit()

            missing = await resolve_policy_profile_action_effect(
                session,
                tenant_id=TENANT_ID,
                policy_profile="low_risk_auto_allow",
                action_class="task_write",
            )
            assert missing.effect == "deny"
            assert missing.reason_code == "missing_policy_profile_action_effect_denied"
        finally:
            await seed_initial_policy_profiles(session, tenant_id=TENANT_ID)
            await session.commit()


@pytest.mark.asyncio
async def test_policy_decisions_profile_columns_default_from_trigger(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    decision_id = UUID("00000000-0000-4000-8000-000000027010")
    async with session_factory() as session:
        async with session.begin():
            await _reset_project_fixture(session)
            await session.execute(
                text(
                    """
                    insert into policy_decisions (
                      id, tenant_id, actor_id, action_class, decision,
                      reason_code, policy_version, input_hash
                    )
                    values (
                      :decision_id, 1, :actor_id, 'task_write', 'deny',
                      'policy_profile_trigger_test', 'policy-v1', :input_hash
                    )
                    """
                ),
                {
                    "decision_id": decision_id,
                    "actor_id": ACTOR_ID,
                    "input_hash": "a" * 64,
                },
            )

        row = (
            await session.execute(
                text(
                    """
                    select policy_profile, profile_resolved_effect
                      from policy_decisions
                     where id = :decision_id
                    """
                ),
                {"decision_id": decision_id},
            )
        ).one()

    assert row.policy_profile == "default"
    assert row.profile_resolved_effect == "deny"
