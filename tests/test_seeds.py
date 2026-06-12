from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.actor import Actor
from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.agent_run_event import AgentRunEvent
from backend.app.db.models.approval_request import ApprovalRequest
from backend.app.db.models.principal import Principal
from backend.app.db.models.project import Project
from backend.app.db.models.repository import Repository
from backend.app.db.models.tenant import Tenant
from backend.app.db.models.workspace import Workspace
from backend.app.db.session import create_engine
from backend.app.seeds.initial import (
    DEFAULT_ACTOR_ID,
    DEFAULT_ACTOR_STABLE_ID,
    DEFAULT_ACTOR_TYPE,
    DEFAULT_AGENT_ACTOR_ID,
    DEFAULT_AGENT_ACTOR_NAME,
    DEFAULT_AGENT_ACTOR_STABLE_ID,
    DEFAULT_AGENT_ACTOR_TYPE,
    DEFAULT_AGENT_RUN_ID,
    DEFAULT_AGENT_RUN_STATUS,
    DEFAULT_APPROVAL_ACTION_CLASS,
    DEFAULT_APPROVAL_POLICY_VERSION,
    DEFAULT_APPROVAL_REQUEST_ID,
    DEFAULT_APPROVAL_RESOURCE_REF,
    DEFAULT_APPROVAL_RISK_LEVEL,
    DEFAULT_APPROVAL_STATUS,
    DEFAULT_PRINCIPAL_ID,
    DEFAULT_PROJECT_ID,
    DEFAULT_PROJECT_NAME,
    DEFAULT_PROJECT_SLUG,
    DEFAULT_PROJECT_STATUS,
    DEFAULT_REPOSITORY_DEFAULT_BRANCH,
    DEFAULT_REPOSITORY_EXTERNAL_ID,
    DEFAULT_REPOSITORY_ID,
    DEFAULT_REPOSITORY_INSTALLATION_REF,
    DEFAULT_REPOSITORY_NAME,
    DEFAULT_REPOSITORY_OWNER_NAME,
    DEFAULT_REPOSITORY_PROVIDER,
    DEFAULT_TENANT_ID,
    DEFAULT_TENANT_NAME,
    DEFAULT_TICKET_ID,
    DEFAULT_USER_NAME,
    DEFAULT_WORKSPACE_ID,
    DEFAULT_WORKSPACE_NAME,
    DEFAULT_WORKSPACE_SLUG,
    seed_golden_flow_fixtures,
    seed_initial,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-seed-tests",
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
            raise AssertionError("Sprint 2 seed tests require a reachable test database.") from exc
        pytest.skip("Set TASKMANAGEDAI_RUN_DB_TESTS=1 with test PostgreSQL running.")
    finally:
        await engine.dispose()


async def _assert_core_tables_migrated(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            table_names = await connection.execute(
                text(
                    """
                    select table_name
                    from information_schema.tables
                    where table_schema = 'public'
                      and table_name in (
                        'tenants',
                        'actors',
                        'principals',
                        'workspaces',
                        'projects',
                        'repositories'
                      )
                    """
                )
            )
    finally:
        await engine.dispose()

    assert {str(row.table_name) for row in table_names} == {
        "tenants",
        "actors",
        "principals",
        "workspaces",
        "projects",
        "repositories",
    }


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    settings = _integration_settings()
    await _assert_database_available(settings)
    await asyncio.to_thread(_run_alembic_upgrade, settings.database_url)
    await _assert_core_tables_migrated(settings)

    engine = create_engine(settings.database_url)
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        yield factory
    finally:
        await engine.dispose()


async def _reset_seed_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate repositories, projects, workspaces, principals, actors, tenants
            restart identity cascade
            """
        )
    )
    await session.execute(text("delete from sprint1_seed_records"))


@pytest.mark.asyncio
async def test_seed_initial_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _reset_seed_tables(session)
        await seed_initial(session)
        await seed_initial(session)

    async with session_factory() as session:
        tenant_count = await session.scalar(select(func.count(Tenant.id)))
        actor_count = await session.scalar(select(func.count(Actor.id)))
        principal_count = await session.scalar(select(func.count(Principal.id)))
        workspace_count = await session.scalar(select(func.count(Workspace.id)))
        project_count = await session.scalar(select(func.count(Project.id)))
        repository_count = await session.scalar(select(func.count(Repository.id)))
        approval_count = await session.scalar(select(func.count(ApprovalRequest.id)))
        run_count = await session.scalar(select(func.count(AgentRun.id)))

    assert tenant_count == 1
    # base seed_initial は human actor 1 件のみ (golden-flow agent は test 専用 fixture へ分離)。
    assert actor_count == 1
    assert principal_count == 1
    assert workspace_count == 1
    assert project_count == 1
    assert repository_count == 1
    # 本番 seed (seed_initial 単体) は pending approval / run を作らない (Codex R2: 本番非汚染)。
    assert approval_count == 0
    assert run_count == 0


@pytest.mark.asyncio
async def test_seed_initial_creates_default_core_records(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _reset_seed_tables(session)
        await seed_initial(session)

    async with session_factory() as session:
        tenant = await session.scalar(
            select(Tenant).where(Tenant.id == DEFAULT_TENANT_ID)
        )
        actor = await session.scalar(
            select(Actor).where(
                Actor.tenant_id == DEFAULT_TENANT_ID,
                Actor.actor_id == DEFAULT_ACTOR_STABLE_ID,
            )
        )
        principal = await session.scalar(
            select(Principal).where(Principal.id == DEFAULT_PRINCIPAL_ID)
        )
        workspace = await session.scalar(
            select(Workspace).where(Workspace.id == DEFAULT_WORKSPACE_ID)
        )
        project = await session.scalar(
            select(Project).where(Project.id == DEFAULT_PROJECT_ID)
        )
        repository = await session.scalar(
            select(Repository).where(Repository.id == DEFAULT_REPOSITORY_ID)
        )

    assert tenant is not None
    assert tenant.id == DEFAULT_TENANT_ID
    assert tenant.name == DEFAULT_TENANT_NAME
    assert tenant.metadata_["rls_ready"] is True

    assert actor is not None
    assert actor.id == DEFAULT_ACTOR_ID
    assert actor.tenant_id == DEFAULT_TENANT_ID
    assert actor.actor_type == DEFAULT_ACTOR_TYPE
    assert actor.actor_id == DEFAULT_ACTOR_STABLE_ID
    assert actor.display_name == DEFAULT_USER_NAME
    assert actor.auth_context_hash is None
    assert actor.metadata_["rls_ready"] is True

    assert principal is not None
    assert principal.tenant_id == DEFAULT_TENANT_ID
    assert principal.actor_id == actor.id
    assert principal.principal_type == "session"
    assert principal.auth_context_hash == "dev-login:human:default"
    assert principal.metadata_["rls_ready"] is True

    assert workspace is not None
    assert workspace.tenant_id == DEFAULT_TENANT_ID
    assert workspace.slug == DEFAULT_WORKSPACE_SLUG
    assert workspace.name == DEFAULT_WORKSPACE_NAME
    assert workspace.owner_actor_id == actor.id
    assert workspace.metadata_["rls_ready"] is True

    assert project is not None
    assert project.tenant_id == DEFAULT_TENANT_ID
    assert project.workspace_id == workspace.id
    assert project.slug == DEFAULT_PROJECT_SLUG
    assert project.name == DEFAULT_PROJECT_NAME
    assert project.status == DEFAULT_PROJECT_STATUS
    assert project.policy_profile == "default"
    assert project.autonomy_level == "L0"
    assert project.metadata_["rls_ready"] is True

    assert repository is not None
    assert repository.tenant_id == DEFAULT_TENANT_ID
    assert repository.project_id == project.id
    assert repository.provider == DEFAULT_REPOSITORY_PROVIDER
    assert repository.external_id == DEFAULT_REPOSITORY_EXTERNAL_ID
    assert repository.owner_name == DEFAULT_REPOSITORY_OWNER_NAME
    assert repository.repo_name == DEFAULT_REPOSITORY_NAME
    assert repository.default_branch == DEFAULT_REPOSITORY_DEFAULT_BRANCH
    assert repository.installation_ref == DEFAULT_REPOSITORY_INSTALLATION_REF
    assert repository.metadata_["rls_ready"] is True
    assert repository.metadata_["placeholder"] is True
    assert repository.metadata_["integration_target"] == "repo_proxy_github_app_sprint8"


@pytest.mark.asyncio
async def test_seed_golden_flow_fixtures_creates_actionable_approval_and_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """SP-009 golden flow fixture (test 専用): agent actor が requester の actionable な
    pending approval + 完了 run + events を base seed の上に冪等追加する。"""
    async with session_factory.begin() as session:
        await _reset_seed_tables(session)
        await seed_initial(session)
        # base record の上に golden-flow fixture を重ねる。二重呼び出しでも冪等。
        await seed_golden_flow_fixtures(session)
        await seed_golden_flow_fixtures(session)

    async with session_factory() as session:
        agent_actor = await session.scalar(
            select(Actor).where(
                Actor.tenant_id == DEFAULT_TENANT_ID,
                Actor.actor_id == DEFAULT_AGENT_ACTOR_STABLE_ID,
            )
        )
        approval = await session.scalar(
            select(ApprovalRequest).where(
                ApprovalRequest.id == DEFAULT_APPROVAL_REQUEST_ID
            )
        )
        run = await session.scalar(
            select(AgentRun).where(AgentRun.id == DEFAULT_AGENT_RUN_ID)
        )
        events = (
            await session.scalars(
                select(AgentRunEvent)
                .where(AgentRunEvent.run_id == DEFAULT_AGENT_RUN_ID)
                .order_by(AgentRunEvent.seq_no)
            )
        ).all()
        # 二重呼び出し後も on_conflict_do_nothing で冪等 (actor=2: human + agent)。
        actor_count = await session.scalar(select(func.count(Actor.id)))
        approval_count = await session.scalar(select(func.count(ApprovalRequest.id)))
        run_count = await session.scalar(select(func.count(AgentRun.id)))
        event_count = await session.scalar(select(func.count(AgentRunEvent.id)))

    assert actor_count == 2
    assert approval_count == 1
    assert run_count == 1
    assert event_count == 3

    assert agent_actor is not None
    assert agent_actor.id == DEFAULT_AGENT_ACTOR_ID
    assert agent_actor.tenant_id == DEFAULT_TENANT_ID
    assert agent_actor.actor_type == DEFAULT_AGENT_ACTOR_TYPE
    assert agent_actor.actor_id == DEFAULT_AGENT_ACTOR_STABLE_ID
    assert agent_actor.display_name == DEFAULT_AGENT_ACTOR_NAME

    assert approval is not None
    assert approval.tenant_id == DEFAULT_TENANT_ID
    assert approval.status == DEFAULT_APPROVAL_STATUS
    assert approval.action_class == DEFAULT_APPROVAL_ACTION_CLASS
    assert approval.risk_level == DEFAULT_APPROVAL_RISK_LEVEL
    assert approval.policy_version == DEFAULT_APPROVAL_POLICY_VERSION
    assert approval.resource_ref == DEFAULT_APPROVAL_RESOURCE_REF
    assert approval.resource_ref == f"ticket:{DEFAULT_TICKET_ID}"
    # raw secret を持ち込まないこと (artifact / diff / fingerprint は seed では未設定)。
    assert approval.artifact_hash is None
    assert approval.diff_hash is None
    assert approval.provider_request_fingerprint is None
    # pending なので未決定。
    assert approval.decided_by_actor_id is None
    assert approval.decided_at is None
    # self-approval 禁止 (requester は agent、human DEFAULT_ACTOR が decide 可能)。
    assert approval.requested_by_actor_id == DEFAULT_AGENT_ACTOR_ID
    assert approval.requested_by_actor_id != DEFAULT_ACTOR_ID
    assert approval.metadata_["rls_ready"] is True

    # 完了済み AgentRun (terminal status、blocked_reason は null)。
    assert run is not None
    assert run.tenant_id == DEFAULT_TENANT_ID
    assert run.project_id == DEFAULT_PROJECT_ID
    assert run.ticket_id == DEFAULT_TICKET_ID
    assert run.status == DEFAULT_AGENT_RUN_STATUS
    assert run.status == "completed"
    assert run.blocked_reason is None

    # 追記専用 AgentRunEvent タイムライン (seq_no 1..3、event_type は enum 整合)。
    assert [event.seq_no for event in events] == [1, 2, 3]
    assert [event.event_type for event in events] == [
        "run_queued",
        "provider_responded",
        "run_completed",
    ]
    for event in events:
        assert event.run_id == DEFAULT_AGENT_RUN_ID

    # rollback-safety invariant (migration 0040 downgrade preflight): ticket-bound run の
    # 非 null ticket_id は canonical run_queued (seq_no 最小) event payload の ticket_id と
    # lossless 一致しなければ downgrade が拒否される。seed が rollback blocker にならないことを固定。
    queued_event = events[0]
    assert queued_event.event_type == "run_queued"
    assert queued_event.event_payload["ticket_id"] == str(run.ticket_id)
    assert queued_event.event_payload["ticket_id"] == str(DEFAULT_TICKET_ID)
    # provider_responded / run_completed は migration 非依存の最小 payload。
    for event in events[1:]:
        assert event.event_payload == {"note": "golden-flow-seed"}


@pytest.mark.asyncio
async def test_seed_golden_flow_fixtures_resets_decided_approval(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """reused test DB で approval が decide 済みでも reseed で pending へ戻す (state-repairing)。

    Codex adversarial R4 [medium]: insert-only だと一度 approve/reject された fixture が terminal の
    まま残り、golden-flow gate (pending filter で listed 要求) が reseed 後も fail する。
    """
    async with session_factory.begin() as session:
        await _reset_seed_tables(session)
        await seed_initial(session)
        await seed_golden_flow_fixtures(session)

    # fixture を approved へ遷移させる (decider は human DEFAULT_ACTOR、requester は agent なので
    # self-approval CHECK を満たす)。decided_at は requested_at 以降。
    async with session_factory.begin() as session:
        await session.execute(
            update(ApprovalRequest)
            .where(ApprovalRequest.id == DEFAULT_APPROVAL_REQUEST_ID)
            .values(
                status="approved",
                decided_by_actor_id=DEFAULT_ACTOR_ID,
                decided_at=func.now(),
                rationale="approved in test",
            )
        )

    # reseed すると state-repairing upsert で pending へ戻り decision fields が clear される。
    async with session_factory.begin() as session:
        await seed_golden_flow_fixtures(session)

    async with session_factory() as session:
        approval = await session.scalar(
            select(ApprovalRequest).where(ApprovalRequest.id == DEFAULT_APPROVAL_REQUEST_ID)
        )
        approval_count = await session.scalar(select(func.count(ApprovalRequest.id)))

    assert approval is not None
    assert approval.status == "pending"
    assert approval.decided_by_actor_id is None
    assert approval.decided_at is None
    assert approval.rationale is None
    # 物理削除でなく upsert なので件数は 1 のまま。
    assert approval_count == 1
