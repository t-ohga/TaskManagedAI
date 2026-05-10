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
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ONE_ACTOR_ID = UUID("00000000-0000-4000-8000-000000006001")
TENANT_TWO_ACTOR_ID = UUID("00000000-0000-4000-8000-000000006002")
TENANT_ONE_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000006011")
TENANT_TWO_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000006012")
PROJECT_A_ID = UUID("00000000-0000-4000-8000-000000006021")
PROJECT_B_ID = UUID("00000000-0000-4000-8000-000000006022")
TENANT_TWO_PROJECT_ID = UUID("00000000-0000-4000-8000-000000006023")
PARENT_RUN_ID = UUID("00000000-0000-4000-8000-000000006031")
CROSS_PROJECT_CHILD_RUN_ID = UUID("00000000-0000-4000-8000-000000006032")
SAME_PROJECT_CHILD_RUN_ID = UUID("00000000-0000-4000-8000-000000006033")
TOP_LEVEL_RUN_ID = UUID("00000000-0000-4000-8000-000000006034")
CROSS_TENANT_CHILD_RUN_ID = UUID("00000000-0000-4000-8000-000000006035")


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-parent-run-boundary-tests",
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
                "AgentRun parent_run_id boundary tests require a reachable test database."
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


def _sqlstate(error: BaseException) -> str | None:
    queue: list[BaseException] = [error]
    seen: set[int] = set()
    while queue:
        current = queue.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))

        state = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if isinstance(state, str):
            return state

        if current.__cause__ is not None:
            queue.append(current.__cause__)
        if current.__context__ is not None:
            queue.append(current.__context__)
        for arg in getattr(current, "args", ()):
            if isinstance(arg, BaseException):
                queue.append(arg)
    return None


def _assert_integrity_error(
    error: IntegrityError,
    *,
    sqlstate: str,
    constraint_name: str,
) -> None:
    assert _sqlstate(error) == sqlstate
    actual_constraint_name = (
        getattr(error.orig, 'constraint_name', None)
        or getattr(getattr(error.orig, '__cause__', None), 'constraint_name', None)
    )
    assert actual_constraint_name == constraint_name


async def _reset_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate
              agent_run_events,
              agent_runs,
              secret_capability_tokens,
              secret_refs,
              notification_events,
              audit_events,
              ticket_relations,
              acceptance_criteria,
              tickets,
              repositories,
              projects,
              workspaces,
              principals,
              actors,
              tenants
            restart identity cascade
            """
        )
    )


async def _setup_parent_run_fixture(session: AsyncSession) -> None:
    await _reset_tables(session)
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
              (:tenant_one_actor_id, 1, 'human', 'human:parent-run-tenant-one',
                'Parent Run Tenant One Actor', '{"rls_ready": true}'::jsonb),
              (:tenant_two_actor_id, 2, 'human', 'human:parent-run-tenant-two',
                'Parent Run Tenant Two Actor', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "tenant_one_actor_id": TENANT_ONE_ACTOR_ID,
            "tenant_two_actor_id": TENANT_TWO_ACTOR_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values
              (:tenant_one_workspace_id, 1, 'tenant-one-workspace', 'tenant-one-workspace',
                :tenant_one_actor_id, '{"rls_ready": true}'::jsonb),
              (:tenant_two_workspace_id, 2, 'tenant-two-workspace', 'tenant-two-workspace',
                :tenant_two_actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "tenant_one_workspace_id": TENANT_ONE_WORKSPACE_ID,
            "tenant_two_workspace_id": TENANT_TWO_WORKSPACE_ID,
            "tenant_one_actor_id": TENANT_ONE_ACTOR_ID,
            "tenant_two_actor_id": TENANT_TWO_ACTOR_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values
              (:project_a_id, 1, :tenant_one_workspace_id, 'project-a', 'project-a',
                'active', '{"rls_ready": true}'::jsonb),
              (:project_b_id, 1, :tenant_one_workspace_id, 'project-b', 'project-b',
                'active', '{"rls_ready": true}'::jsonb),
              (:tenant_two_project_id, 2, :tenant_two_workspace_id, 'project-c', 'project-c',
                'active', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "project_a_id": PROJECT_A_ID,
            "project_b_id": PROJECT_B_ID,
            "tenant_two_project_id": TENANT_TWO_PROJECT_ID,
            "tenant_one_workspace_id": TENANT_ONE_WORKSPACE_ID,
            "tenant_two_workspace_id": TENANT_TWO_WORKSPACE_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into agent_runs (id, tenant_id, project_id, parent_run_id, status)
            values (:parent_run_id, 1, :project_a_id, null, 'queued')
            """
        ),
        {
            "parent_run_id": PARENT_RUN_ID,
            "project_a_id": PROJECT_A_ID,
        },
    )


async def _insert_agent_run(
    session: AsyncSession,
    *,
    run_id: UUID,
    tenant_id: int,
    project_id: UUID,
    parent_run_id: UUID | None,
) -> None:
    await session.execute(
        text(
            """
            insert into agent_runs (id, tenant_id, project_id, parent_run_id, status)
            values (:run_id, :tenant_id, :project_id, :parent_run_id, 'queued')
            """
        ),
        {
            "run_id": run_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "parent_run_id": parent_run_id,
        },
    )


@pytest.mark.asyncio
async def test_cross_project_parent_run_insert_fails_by_composite_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_parent_run_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_agent_run(
                session,
                run_id=CROSS_PROJECT_CHILD_RUN_ID,
                tenant_id=1,
                project_id=PROJECT_B_ID,
                parent_run_id=PARENT_RUN_ID,
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="agent_runs_parent_run_fkey",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_same_project_parent_run_insert_succeeds(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_parent_run_fixture(session)

        await _insert_agent_run(
            session,
            run_id=SAME_PROJECT_CHILD_RUN_ID,
            tenant_id=1,
            project_id=PROJECT_A_ID,
            parent_run_id=PARENT_RUN_ID,
        )
        await session.commit()

        parent_run_id = await session.scalar(
            text(
                """
                select parent_run_id
                from agent_runs
                where tenant_id = 1 and id = :run_id
                """
            ),
            {"run_id": SAME_PROJECT_CHILD_RUN_ID},
        )
        assert parent_run_id == PARENT_RUN_ID


@pytest.mark.asyncio
async def test_null_parent_run_id_insert_succeeds_for_top_level_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_parent_run_fixture(session)

        await _insert_agent_run(
            session,
            run_id=TOP_LEVEL_RUN_ID,
            tenant_id=1,
            project_id=PROJECT_B_ID,
            parent_run_id=None,
        )
        await session.commit()

        parent_run_id = await session.scalar(
            text(
                """
                select parent_run_id
                from agent_runs
                where tenant_id = 1 and id = :run_id
                """
            ),
            {"run_id": TOP_LEVEL_RUN_ID},
        )
        assert parent_run_id is None


@pytest.mark.asyncio
async def test_cross_tenant_parent_run_insert_fails_by_composite_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_parent_run_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_agent_run(
                session,
                run_id=CROSS_TENANT_CHILD_RUN_ID,
                tenant_id=2,
                project_id=TENANT_TWO_PROJECT_ID,
                parent_run_id=PARENT_RUN_ID,
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="agent_runs_parent_run_fkey",
        )
        await session.rollback()
