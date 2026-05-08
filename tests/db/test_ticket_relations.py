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
from backend.app.repositories.ticket_relation import TicketRelationRepository

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

ACTOR_ID = UUID("00000000-0000-4000-8000-000000003001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000003002")
PROJECT_A_ID = UUID("00000000-0000-4000-8000-000000003003")
PROJECT_B_ID = UUID("00000000-0000-4000-8000-000000003004")
SOURCE_TICKET_ID = UUID("00000000-0000-4000-8000-000000003005")
TARGET_TICKET_ID = UUID("00000000-0000-4000-8000-000000003006")
PROJECT_B_TICKET_ID = UUID("00000000-0000-4000-8000-000000003007")
RELATION_ID = UUID("00000000-0000-4000-8000-000000003008")
DUPLICATE_RELATION_ID = UUID("00000000-0000-4000-8000-000000003009")


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-ticket-relations-tests",
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
            raise AssertionError("ticket relation tests require a reachable test database.") from exc
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


async def _insert_relation_fixture(session: AsyncSession) -> None:
    await session.execute(
        text("insert into tenants (id, name, metadata) values (1, 'tenant-one', '{}')")
    )
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values (:actor_id, 1, 'human', 'human:relations', 'Relation Actor',
              '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'workspace', 'workspace', :actor_id,
              '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values
              (:project_a_id, 1, :workspace_id, 'project-a', 'project-a', 'active',
                '{"rls_ready": true}'::jsonb),
              (:project_b_id, 1, :workspace_id, 'project-b', 'project-b', 'active',
                '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "project_a_id": PROJECT_A_ID,
            "project_b_id": PROJECT_B_ID,
            "workspace_id": WORKSPACE_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into tickets (
              id, tenant_id, project_id, slug, title, status, created_by_actor_id, metadata
            )
            values
              (:source_ticket_id, 1, :project_a_id, 'source', 'Source', 'open',
                :actor_id, '{"rls_ready": true}'::jsonb),
              (:target_ticket_id, 1, :project_a_id, 'target', 'Target', 'open',
                :actor_id, '{"rls_ready": true}'::jsonb),
              (:project_b_ticket_id, 1, :project_b_id, 'project-b-ticket',
                'Project B Ticket', 'open', :actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "source_ticket_id": SOURCE_TICKET_ID,
            "target_ticket_id": TARGET_TICKET_ID,
            "project_b_ticket_id": PROJECT_B_TICKET_ID,
            "project_a_id": PROJECT_A_ID,
            "project_b_id": PROJECT_B_ID,
            "actor_id": ACTOR_ID,
        },
    )


async def _insert_valid_relation(session: AsyncSession, relation_id: UUID = RELATION_ID) -> None:
    await session.execute(
        text(
            """
            insert into ticket_relations (
              id, tenant_id, project_id, source_ticket_id, target_ticket_id,
              relation_type, metadata
            )
            values (
              :relation_id, 1, :project_a_id, :source_ticket_id, :target_ticket_id,
              'blocks', '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "relation_id": relation_id,
            "project_a_id": PROJECT_A_ID,
            "source_ticket_id": SOURCE_TICKET_ID,
            "target_ticket_id": TARGET_TICKET_ID,
        },
    )


@pytest.mark.asyncio
async def test_ticket_relation_repository_base_scope_methods_are_disabled() -> None:
    repository = TicketRelationRepository(session=object())  # type: ignore[arg-type]

    with pytest.raises(NotImplementedError, match=r"Use get_in_project"):
        await repository.get(tenant_id=1, id=RELATION_ID)

    with pytest.raises(NotImplementedError, match=r"Use list_in_project"):
        await repository.list(tenant_id=1)

    with pytest.raises(NotImplementedError, match=r"Use update_in_project"):
        await repository.update(
            tenant_id=1,
            id=RELATION_ID,
            payload={"relation_type": "depends_on"},
        )

    with pytest.raises(NotImplementedError, match=r"Use delete_in_project"):
        await repository.delete(tenant_id=1, id=RELATION_ID)

    with pytest.raises(NotImplementedError, match=r"Use statement_for_\*_in_project"):
        repository.statement_for_get(tenant_id=1, id=RELATION_ID)

    with pytest.raises(NotImplementedError, match=r"Use statement_for_\*_in_project"):
        repository.statement_for_list(tenant_id=1)

    with pytest.raises(NotImplementedError, match=r"Use statement_for_\*_in_project"):
        repository.statement_for_update(
            tenant_id=1,
            id=RELATION_ID,
            payload={"relation_type": "depends_on"},
        )

    with pytest.raises(NotImplementedError, match=r"Use statement_for_\*_in_project"):
        repository.statement_for_delete(tenant_id=1, id=RELATION_ID)


@pytest.mark.asyncio
async def test_ticket_relation_get_in_other_project_returns_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _reset_tables(session)
        await _insert_relation_fixture(session)
        await _insert_valid_relation(session)

        repository = TicketRelationRepository(session)
        cross_project_relation = await repository.get_in_project(
            tenant_id=1,
            project_id=PROJECT_B_ID,
            relation_id=RELATION_ID,
        )

    assert cross_project_relation is None


@pytest.mark.asyncio
async def test_ticket_relation_self_loop_check_rejects_same_ticket(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_relation_fixture(session)
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
                      :relation_id, 1, :project_a_id, :source_ticket_id, :source_ticket_id,
                      'blocks', '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {
                    "relation_id": RELATION_ID,
                    "project_a_id": PROJECT_A_ID,
                    "source_ticket_id": SOURCE_TICKET_ID,
                },
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="ticket_relations_ck_no_self_loop",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_ticket_relation_type_check_rejects_unknown_value(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_relation_fixture(session)
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
                      :relation_id, 1, :project_a_id, :source_ticket_id, :target_ticket_id,
                      'parent', '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {
                    "relation_id": RELATION_ID,
                    "project_a_id": PROJECT_A_ID,
                    "source_ticket_id": SOURCE_TICKET_ID,
                    "target_ticket_id": TARGET_TICKET_ID,
                },
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="ticket_relations_ck_relation_type",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_ticket_relation_unique_edge_rejects_duplicates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_relation_fixture(session)
        await _insert_valid_relation(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_valid_relation(session, relation_id=DUPLICATE_RELATION_ID)
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23505",
            constraint_name="ticket_relations_uq_edge",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_ticket_relation_cross_project_target_fails_by_composite_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_relation_fixture(session)
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
                      :relation_id, 1, :project_a_id, :source_ticket_id,
                      :project_b_ticket_id, 'depends_on', '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {
                    "relation_id": RELATION_ID,
                    "project_a_id": PROJECT_A_ID,
                    "source_ticket_id": SOURCE_TICKET_ID,
                    "project_b_ticket_id": PROJECT_B_TICKET_ID,
                },
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="ticket_relations_target_ticket_fkey",
        )
        await session.rollback()

