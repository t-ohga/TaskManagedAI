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
from backend.app.repositories.ticket import TicketRepository

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

ACTOR_ID = UUID("00000000-0000-4000-8000-000000001001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000001002")
PROJECT_A_ID = UUID("00000000-0000-4000-8000-000000001003")
PROJECT_B_ID = UUID("00000000-0000-4000-8000-000000001004")
TICKET_A_ID = UUID("00000000-0000-4000-8000-000000001005")
TICKET_B_ID = UUID("00000000-0000-4000-8000-000000001006")
TICKET_EXTRA_ID = UUID("00000000-0000-4000-8000-000000001007")
RELATION_ID = UUID("00000000-0000-4000-8000-000000001008")
REPOSITORY_A_ID = UUID("00000000-0000-4000-8000-000000001009")
REPOSITORY_B_ID = UUID("00000000-0000-4000-8000-000000001010")
TENANT_2_ACTOR_ID = UUID("00000000-0000-4000-8000-000000001011")
TENANT_2_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000001012")
TENANT_2_PROJECT_ID = UUID("00000000-0000-4000-8000-000000001013")
TENANT_2_TICKET_ID = UUID("00000000-0000-4000-8000-000000001014")


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-ticket-boundary-tests",
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
            raise AssertionError("ticket boundary tests require a reachable test database.") from exc
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
    assert constraint_name in str(error)


async def _reset_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate notification_events, audit_events, ticket_relations,
              acceptance_criteria, tickets, repositories, projects, workspaces,
              principals, actors, tenants
            restart identity cascade
            """
        )
    )


async def _insert_project_boundary_fixture(session: AsyncSession) -> None:
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
              (:actor_id, 1, 'human', 'human:boundary', 'Boundary Actor',
                '{"rls_ready": true}'::jsonb),
              (:tenant_2_actor_id, 2, 'human', 'human:boundary', 'Tenant 2 Actor',
                '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID, "tenant_2_actor_id": TENANT_2_ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values
              (:workspace_id, 1, 'workspace', 'workspace', :actor_id,
                '{"rls_ready": true}'::jsonb),
              (:tenant_2_workspace_id, 2, 'workspace', 'workspace', :tenant_2_actor_id,
                '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "workspace_id": WORKSPACE_ID,
            "actor_id": ACTOR_ID,
            "tenant_2_workspace_id": TENANT_2_WORKSPACE_ID,
            "tenant_2_actor_id": TENANT_2_ACTOR_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values
              (:project_a_id, 1, :workspace_id, 'project-a', 'project-a', 'active',
                '{"rls_ready": true}'::jsonb),
              (:project_b_id, 1, :workspace_id, 'project-b', 'project-b', 'active',
                '{"rls_ready": true}'::jsonb),
              (:tenant_2_project_id, 2, :tenant_2_workspace_id, 'project-a', 'project-a',
                'active', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "project_a_id": PROJECT_A_ID,
            "project_b_id": PROJECT_B_ID,
            "workspace_id": WORKSPACE_ID,
            "tenant_2_project_id": TENANT_2_PROJECT_ID,
            "tenant_2_workspace_id": TENANT_2_WORKSPACE_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into repositories (
              id, tenant_id, project_id, provider, external_id, owner_name, repo_name,
              default_branch, metadata
            )
            values
              (:repository_a_id, 1, :project_a_id, 'github', 'repo-a', 'owner',
                'repo-a', 'main', '{"rls_ready": true}'::jsonb),
              (:repository_b_id, 1, :project_b_id, 'github', 'repo-b', 'owner',
                'repo-b', 'main', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "repository_a_id": REPOSITORY_A_ID,
            "repository_b_id": REPOSITORY_B_ID,
            "project_a_id": PROJECT_A_ID,
            "project_b_id": PROJECT_B_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into tickets (
              id, tenant_id, project_id, slug, title, status, created_by_actor_id, metadata
            )
            values
              (:ticket_a_id, 1, :project_a_id, 'ticket-a', 'Ticket A', 'open',
                :actor_id, '{"rls_ready": true}'::jsonb),
              (:ticket_b_id, 1, :project_b_id, 'ticket-b', 'Ticket B', 'open',
                :actor_id, '{"rls_ready": true}'::jsonb),
              (:tenant_2_ticket_id, 2, :tenant_2_project_id, 'ticket-a', 'Tenant 2 Ticket',
                'open', :tenant_2_actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "ticket_a_id": TICKET_A_ID,
            "ticket_b_id": TICKET_B_ID,
            "tenant_2_ticket_id": TENANT_2_TICKET_ID,
            "project_a_id": PROJECT_A_ID,
            "project_b_id": PROJECT_B_ID,
            "tenant_2_project_id": TENANT_2_PROJECT_ID,
            "actor_id": ACTOR_ID,
            "tenant_2_actor_id": TENANT_2_ACTOR_ID,
        },
    )


@pytest.mark.asyncio
async def test_ticket_repository_base_scope_methods_are_disabled() -> None:
    repository = TicketRepository(session=object())  # type: ignore[arg-type]

    with pytest.raises(NotImplementedError, match=r"Use get_in_project"):
        await repository.get(tenant_id=1, id=TICKET_A_ID)

    with pytest.raises(NotImplementedError, match=r"Use list_in_project"):
        await repository.list(tenant_id=1)

    with pytest.raises(NotImplementedError, match=r"Use update_in_project"):
        await repository.update(tenant_id=1, id=TICKET_A_ID, payload={"title": "updated"})

    with pytest.raises(NotImplementedError, match=r"Use delete_in_project"):
        await repository.delete(tenant_id=1, id=TICKET_A_ID)

    with pytest.raises(NotImplementedError, match=r"Use statement_for_\*_in_project"):
        repository.statement_for_get(tenant_id=1, id=TICKET_A_ID)

    with pytest.raises(NotImplementedError, match=r"Use statement_for_\*_in_project"):
        repository.statement_for_list(tenant_id=1)

    with pytest.raises(NotImplementedError, match=r"Use statement_for_\*_in_project"):
        repository.statement_for_update(
            tenant_id=1,
            id=TICKET_A_ID,
            payload={"title": "updated"},
        )

    with pytest.raises(NotImplementedError, match=r"Use statement_for_\*_in_project"):
        repository.statement_for_delete(tenant_id=1, id=TICKET_A_ID)


@pytest.mark.asyncio
async def test_ticket_select_from_other_project_returns_no_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _reset_tables(session)
        await _insert_project_boundary_fixture(session)

        repository = TicketRepository(session)
        cross_project_ticket = await repository.get_in_project(
            tenant_id=1,
            project_id=PROJECT_A_ID,
            ticket_id=TICKET_B_ID,
        )
        raw_rows = await session.execute(
            text(
                """
                select id
                from tickets
                where tenant_id = 1
                  and project_id = :project_a_id
                  and id = :ticket_b_id
                """
            ),
            {"project_a_id": PROJECT_A_ID, "ticket_b_id": TICKET_B_ID},
        )
        raw_ticket_rows = raw_rows.all()

    assert cross_project_ticket is None
    assert raw_ticket_rows == []


@pytest.mark.asyncio
async def test_ticket_select_from_other_tenant_returns_no_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _reset_tables(session)
        await _insert_project_boundary_fixture(session)

        repository = TicketRepository(session)
        cross_tenant_ticket = await repository.get_in_project(
            tenant_id=1,
            project_id=PROJECT_A_ID,
            ticket_id=TENANT_2_TICKET_ID,
        )
        raw_rows = await session.execute(
            text(
                """
                select id
                from tickets
                where tenant_id = 1
                  and project_id = :project_a_id
                  and id = :tenant_2_ticket_id
                """
            ),
            {"project_a_id": PROJECT_A_ID, "tenant_2_ticket_id": TENANT_2_TICKET_ID},
        )
        raw_ticket_rows = raw_rows.all()

    assert cross_tenant_ticket is None
    assert raw_ticket_rows == []


@pytest.mark.asyncio
async def test_cross_project_ticket_relation_insert_fails_by_composite_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_project_boundary_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into ticket_relations (
                      id, tenant_id, project_id, source_ticket_id, target_ticket_id,
                      relation_type, metadata
                    )
                    values (
                      :relation_id, 1, :project_a_id, :ticket_a_id, :ticket_b_id,
                      'blocks', '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {
                    "relation_id": RELATION_ID,
                    "project_a_id": PROJECT_A_ID,
                    "ticket_a_id": TICKET_A_ID,
                    "ticket_b_id": TICKET_B_ID,
                },
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="ticket_relations_target_ticket_fkey",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_cross_project_repository_on_ticket_insert_fails_by_composite_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_project_boundary_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into tickets (
                      id, tenant_id, project_id, repository_id, slug, title, status,
                      created_by_actor_id, metadata
                    )
                    values (
                      :ticket_id, 1, :project_a_id, :repository_b_id, 'wrong-repo',
                      'Wrong Repo', 'open', :actor_id, '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {
                    "ticket_id": TICKET_EXTRA_ID,
                    "project_a_id": PROJECT_A_ID,
                    "repository_b_id": REPOSITORY_B_ID,
                    "actor_id": ACTOR_ID,
                },
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="tickets_repository_project_fkey",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_ticket_slug_is_unique_within_project(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_project_boundary_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into tickets (
                      id, tenant_id, project_id, slug, title, status,
                      created_by_actor_id, metadata
                    )
                    values (
                      :ticket_id, 1, :project_a_id, 'ticket-a', 'Duplicate Slug',
                      'open', :actor_id, '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {
                    "ticket_id": TICKET_EXTRA_ID,
                    "project_a_id": PROJECT_A_ID,
                    "actor_id": ACTOR_ID,
                },
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23505",
            constraint_name="tickets_uq_tenant_project_slug",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_ticket_status_check_rejects_unknown_value(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_project_boundary_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into tickets (
                      id, tenant_id, project_id, slug, title, status,
                      created_by_actor_id, metadata
                    )
                    values (
                      :ticket_id, 1, :project_a_id, 'bad-status', 'Bad Status',
                      'done', :actor_id, '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {
                    "ticket_id": TICKET_EXTRA_ID,
                    "project_a_id": PROJECT_A_ID,
                    "actor_id": ACTOR_ID,
                },
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="tickets_ck_status",
        )
        await session.rollback()

