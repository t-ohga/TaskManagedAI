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
from backend.app.repositories.acceptance_criteria import AcceptanceCriteriaRepository

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

ACTOR_ID = UUID("00000000-0000-4000-8000-000000002001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000002002")
PROJECT_A_ID = UUID("00000000-0000-4000-8000-000000002003")
PROJECT_B_ID = UUID("00000000-0000-4000-8000-000000002004")
TICKET_A_ID = UUID("00000000-0000-4000-8000-000000002005")
AC_ID = UUID("00000000-0000-4000-8000-000000002006")
BAD_AC_ID = UUID("00000000-0000-4000-8000-000000002007")


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-acceptance-criteria-tests",
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
            raise AssertionError("acceptance criteria tests require a reachable test database.") from exc
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


async def _insert_ticket_fixture(session: AsyncSession) -> None:
    await session.execute(
        text("insert into tenants (id, name, metadata) values (1, 'tenant-one', '{}')")
    )
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values (:actor_id, 1, 'human', 'human:ac', 'AC Actor',
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
            values (:ticket_id, 1, :project_a_id, 'ticket-a', 'Ticket A', 'open',
              :actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"ticket_id": TICKET_A_ID, "project_a_id": PROJECT_A_ID, "actor_id": ACTOR_ID},
    )


async def _insert_acceptance_criteria(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            insert into acceptance_criteria (
              id, tenant_id, project_id, ticket_id, description, status, metadata
            )
            values (
              :ac_id, 1, :project_a_id, :ticket_id, 'Criterion A', 'pending',
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {"ac_id": AC_ID, "project_a_id": PROJECT_A_ID, "ticket_id": TICKET_A_ID},
    )


@pytest.mark.asyncio
async def test_acceptance_criteria_repository_base_scope_methods_are_disabled() -> None:
    repository = AcceptanceCriteriaRepository(session=object())  # type: ignore[arg-type]

    with pytest.raises(NotImplementedError, match=r"Use get_in_ticket"):
        await repository.get(tenant_id=1, id=AC_ID)

    with pytest.raises(NotImplementedError, match=r"Use list_in_ticket"):
        await repository.list(tenant_id=1)

    with pytest.raises(NotImplementedError, match=r"Use update_in_ticket"):
        await repository.update(tenant_id=1, id=AC_ID, payload={"status": "satisfied"})

    with pytest.raises(NotImplementedError, match=r"Use delete_in_ticket"):
        await repository.delete(tenant_id=1, id=AC_ID)

    with pytest.raises(NotImplementedError, match=r"Use statement_for_\*_in_ticket"):
        repository.statement_for_get(tenant_id=1, id=AC_ID)

    with pytest.raises(NotImplementedError, match=r"Use statement_for_\*_in_ticket"):
        repository.statement_for_list(tenant_id=1)

    with pytest.raises(NotImplementedError, match=r"Use statement_for_\*_in_ticket"):
        repository.statement_for_update(
            tenant_id=1,
            id=AC_ID,
            payload={"status": "satisfied"},
        )

    with pytest.raises(NotImplementedError, match=r"Use statement_for_\*_in_ticket"):
        repository.statement_for_delete(tenant_id=1, id=AC_ID)


@pytest.mark.asyncio
async def test_acceptance_criteria_get_in_other_project_returns_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _reset_tables(session)
        await _insert_ticket_fixture(session)
        await _insert_acceptance_criteria(session)

        repository = AcceptanceCriteriaRepository(session)
        cross_project_result = await repository.get_in_ticket(
            tenant_id=1,
            project_id=PROJECT_B_ID,
            ticket_id=TICKET_A_ID,
            ac_id=AC_ID,
        )

    assert cross_project_result is None


@pytest.mark.asyncio
async def test_acceptance_criteria_insert_succeeds_through_project_boundary_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _reset_tables(session)
        await _insert_ticket_fixture(session)
        await _insert_acceptance_criteria(session)
        count = await session.scalar(text("select count(*) from acceptance_criteria"))

    assert count == 1


@pytest.mark.asyncio
async def test_cross_project_acceptance_criteria_insert_fails_by_composite_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_ticket_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into acceptance_criteria (
                      id, tenant_id, project_id, ticket_id, description, status, metadata
                    )
                    values (
                      :ac_id, 1, :project_b_id, :ticket_id, 'Cross Project AC',
                      'pending', '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {"ac_id": AC_ID, "project_b_id": PROJECT_B_ID, "ticket_id": TICKET_A_ID},
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="acceptance_criteria_ticket_fkey",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_acceptance_criteria_status_check_rejects_unknown_value(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_ticket_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into acceptance_criteria (
                      id, tenant_id, project_id, ticket_id, description, status, metadata
                    )
                    values (
                      :ac_id, 1, :project_a_id, :ticket_id, 'Bad Status',
                      'passed', '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {"ac_id": BAD_AC_ID, "project_a_id": PROJECT_A_ID, "ticket_id": TICKET_A_ID},
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="acceptance_criteria_ck_status",
        )
        await session.rollback()

