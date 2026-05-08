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

ACTOR_ID = UUID("00000000-0000-4000-8000-000000003001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000003002")
PROJECT_ONE_ID = UUID("00000000-0000-4000-8000-000000003011")
PROJECT_TWO_ID = UUID("00000000-0000-4000-8000-000000003012")
REPOSITORY_ONE_ID = UUID("00000000-0000-4000-8000-000000003021")
REPOSITORY_TWO_ID = UUID("00000000-0000-4000-8000-000000003022")
TICKET_ONE_ID = UUID("00000000-0000-4000-8000-000000003031")
TICKET_TWO_ID = UUID("00000000-0000-4000-8000-000000003032")
EXTRA_TICKET_ID = UUID("00000000-0000-4000-8000-000000003033")
ISOLATED_TICKET_ID = UUID("00000000-0000-4000-8000-000000003034")
ACCEPTANCE_CRITERIA_ID = UUID("00000000-0000-4000-8000-000000003041")
RELATION_ONE_ID = UUID("00000000-0000-4000-8000-000000003051")
RELATION_TWO_ID = UUID("00000000-0000-4000-8000-000000003052")


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-project-isolation-tests",
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
            raise AssertionError("Project isolation tests require a reachable test database.") from exc
        pytest.skip("Set TASKMANAGEDAI_RUN_DB_TESTS=1 with test PostgreSQL running.")
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    settings = _integration_settings()
    await _assert_database_available(settings)
    await asyncio.to_thread(_run_alembic_upgrade, settings.database_url)

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
            truncate
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


async def _setup_one_tenant_two_projects(session: AsyncSession) -> None:
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
            values (
              :actor_id, 1, 'human', 'human:project-boundary',
              'Project Boundary Actor', '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (
              :workspace_id, 1, 'workspace-one', 'workspace-one', :actor_id,
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values
              (:project_one_id, 1, :workspace_id, 'project-one', 'project-one',
                'active', '{"rls_ready": true}'::jsonb),
              (:project_two_id, 1, :workspace_id, 'project-two', 'project-two',
                'active', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "project_one_id": PROJECT_ONE_ID,
            "project_two_id": PROJECT_TWO_ID,
            "workspace_id": WORKSPACE_ID,
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
              (:repository_one_id, 1, :project_one_id, 'github', 'repo-one',
                'owner', 'repo-one', 'main', '{"rls_ready": true}'::jsonb),
              (:repository_two_id, 1, :project_two_id, 'github', 'repo-two',
                'owner', 'repo-two', 'main', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "repository_one_id": REPOSITORY_ONE_ID,
            "repository_two_id": REPOSITORY_TWO_ID,
            "project_one_id": PROJECT_ONE_ID,
            "project_two_id": PROJECT_TWO_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into tickets (
              id, tenant_id, project_id, repository_id, slug, title, status,
              created_by_actor_id, metadata
            )
            values
              (:ticket_one_id, 1, :project_one_id, :repository_one_id,
                'ticket-one', 'Ticket One', 'open', :actor_id,
                '{"rls_ready": true}'::jsonb),
              (:ticket_two_id, 1, :project_two_id, :repository_two_id,
                'ticket-two', 'Ticket Two', 'open', :actor_id,
                '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "ticket_one_id": TICKET_ONE_ID,
            "ticket_two_id": TICKET_TWO_ID,
            "project_one_id": PROJECT_ONE_ID,
            "project_two_id": PROJECT_TWO_ID,
            "repository_one_id": REPOSITORY_ONE_ID,
            "repository_two_id": REPOSITORY_TWO_ID,
            "actor_id": ACTOR_ID,
        },
    )


async def _insert_isolated_ticket(
    session: AsyncSession,
    *,
    ticket_id: UUID,
    slug: str,
) -> None:
    await session.execute(
        text(
            """
            insert into tickets (
              id, tenant_id, project_id, repository_id, slug, title, status,
              created_by_actor_id, metadata
            )
            values (
              :ticket_id, 1, :project_one_id, null, :slug, :title, 'open',
              :actor_id, '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "ticket_id": ticket_id,
            "project_one_id": PROJECT_ONE_ID,
            "slug": slug,
            "title": slug.replace("-", " ").title(),
            "actor_id": ACTOR_ID,
        },
    )


@pytest.mark.asyncio
async def test_cross_project_repository_on_ticket_insert_fails_by_composite_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_one_tenant_two_projects(session)
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
                      :ticket_id, 1, :project_one_id, :repository_two_id,
                      'cross-project-repo', 'Cross Project Repo', 'open',
                      :actor_id, '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {
                    "ticket_id": EXTRA_TICKET_ID,
                    "project_one_id": PROJECT_ONE_ID,
                    "repository_two_id": REPOSITORY_TWO_ID,
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
async def test_cross_project_acceptance_criteria_insert_fails_by_ticket_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_one_tenant_two_projects(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into acceptance_criteria (
                      id, tenant_id, project_id, ticket_id, description, status, metadata
                    )
                    values (
                      :acceptance_criteria_id, 1, :project_one_id, :ticket_two_id,
                      'Cross-project ticket must be blocked', 'pending',
                      '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {
                    "acceptance_criteria_id": ACCEPTANCE_CRITERIA_ID,
                    "project_one_id": PROJECT_ONE_ID,
                    "ticket_two_id": TICKET_TWO_ID,
                },
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="acceptance_criteria_ticket_fkey",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_cross_project_relation_target_insert_fails_by_target_ticket_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_one_tenant_two_projects(session)
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
                      :relation_id, 1, :project_one_id, :ticket_one_id, :ticket_two_id,
                      'blocks', '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {
                    "relation_id": RELATION_ONE_ID,
                    "project_one_id": PROJECT_ONE_ID,
                    "ticket_one_id": TICKET_ONE_ID,
                    "ticket_two_id": TICKET_TWO_ID,
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
async def test_cross_project_relation_source_insert_fails_by_source_ticket_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_one_tenant_two_projects(session)
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
                      :relation_id, 1, :project_one_id, :ticket_two_id, :ticket_one_id,
                      'depends_on', '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {
                    "relation_id": RELATION_TWO_ID,
                    "project_one_id": PROJECT_ONE_ID,
                    "ticket_one_id": TICKET_ONE_ID,
                    "ticket_two_id": TICKET_TWO_ID,
                },
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="ticket_relations_source_ticket_fkey",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_cross_project_repository_on_ticket_update_fails_by_composite_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_one_tenant_two_projects(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    update tickets
                    set repository_id = :repository_two_id
                    where tenant_id = 1
                      and project_id = :project_one_id
                      and id = :ticket_one_id
                    """
                ),
                {
                    "repository_two_id": REPOSITORY_TWO_ID,
                    "project_one_id": PROJECT_ONE_ID,
                    "ticket_one_id": TICKET_ONE_ID,
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
async def test_cross_project_ticket_repository_link_via_composite_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """repository_id remains project-one, so project_id movement violates its composite FK."""

    async with session_factory() as session:
        await _setup_one_tenant_two_projects(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    update tickets
                    set project_id = :project_two_id
                    where tenant_id = 1
                      and project_id = :project_one_id
                      and id = :ticket_one_id
                    """
                ),
                {
                    "project_two_id": PROJECT_TWO_ID,
                    "project_one_id": PROJECT_ONE_ID,
                    "ticket_one_id": TICKET_ONE_ID,
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
async def test_cross_project_ticket_with_acceptance_criteria_blocked_by_child_fkey(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """repository_id null still cannot move project_id when a child AC row exists."""

    async with session_factory() as session:
        await _setup_one_tenant_two_projects(session)
        await _insert_isolated_ticket(
            session,
            ticket_id=EXTRA_TICKET_ID,
            slug="isolated-ticket-with-ac",
        )
        await session.execute(
            text(
                """
                insert into acceptance_criteria (
                  id, tenant_id, project_id, ticket_id, description, status, metadata
                )
                values (
                  :acceptance_criteria_id, 1, :project_one_id, :ticket_id,
                  'Child AC keeps ticket project boundary closed', 'pending',
                  '{"rls_ready": true}'::jsonb
                )
                """
            ),
            {
                "acceptance_criteria_id": ACCEPTANCE_CRITERIA_ID,
                "project_one_id": PROJECT_ONE_ID,
                "ticket_id": EXTRA_TICKET_ID,
            },
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    update tickets
                    set project_id = :project_two_id
                    where tenant_id = 1
                      and project_id = :project_one_id
                      and id = :ticket_id
                    """
                ),
                {
                    "project_two_id": PROJECT_TWO_ID,
                    "project_one_id": PROJECT_ONE_ID,
                    "ticket_id": EXTRA_TICKET_ID,
                },
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="acceptance_criteria_ticket_fkey",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_isolated_ticket_project_id_change_succeeds_documents_p0_limitation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """P0 limitation: repository_id null and no child rows allow a project_id move.

    Sprint 4 should consider a project_id immutability trigger; see ADR-00002 future work.
    """

    async with session_factory() as session:
        await _setup_one_tenant_two_projects(session)
        await _insert_isolated_ticket(
            session,
            ticket_id=ISOLATED_TICKET_ID,
            slug="isolated-ticket-no-child",
        )
        await session.commit()

        await session.execute(
            text(
                """
                update tickets
                set project_id = :project_two_id
                where tenant_id = 1
                  and project_id = :project_one_id
                  and id = :ticket_id
                """
            ),
            {
                "project_two_id": PROJECT_TWO_ID,
                "project_one_id": PROJECT_ONE_ID,
                "ticket_id": ISOLATED_TICKET_ID,
            },
        )
        await session.commit()
        moved_project_id = await session.scalar(
            text("select project_id from tickets where tenant_id = 1 and id = :ticket_id"),
            {"ticket_id": ISOLATED_TICKET_ID},
        )

    assert moved_project_id == PROJECT_TWO_ID

