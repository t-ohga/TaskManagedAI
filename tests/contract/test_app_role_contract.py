from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.acceptance_criteria import AcceptanceCriteria
from backend.app.db.models.audit_event import AuditEvent
from backend.app.db.models.ticket import Ticket
from backend.app.db.models.ticket_relation import TicketRelation
from backend.app.db.session import create_engine
from backend.app.repositories.acceptance_criteria import AcceptanceCriteriaRepository
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.repositories.base import BaseRepository
from backend.app.repositories.ticket import TicketRepository
from backend.app.repositories.ticket_relation import TicketRelationRepository

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ONE_ACTOR_ID = UUID("00000000-0000-4000-8000-000000004001")
TENANT_TWO_ACTOR_ID = UUID("00000000-0000-4000-8000-000000004002")
TENANT_ONE_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000004011")
TENANT_TWO_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000004012")
TENANT_ONE_PROJECT_ID = UUID("00000000-0000-4000-8000-000000004021")
TENANT_TWO_PROJECT_ID = UUID("00000000-0000-4000-8000-000000004022")
TENANT_ONE_TICKET_ID = UUID("00000000-0000-4000-8000-000000004031")
TENANT_TWO_TICKET_ID = UUID("00000000-0000-4000-8000-000000004032")
ACCEPTANCE_CRITERIA_ID = UUID("00000000-0000-4000-8000-000000004041")
TICKET_RELATION_ID = UUID("00000000-0000-4000-8000-000000004051")


class _CapturedResult:
    def scalar_one_or_none(self) -> None:
        return None

    def scalars(self) -> _CapturedResult:
        return self

    def all(self) -> list[Any]:
        return []


class _CapturingSession:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> _CapturedResult:
        self.statements.append(statement)
        return _CapturedResult()

    async def scalar(self, statement: Any, *args: Any, **kwargs: Any) -> None:
        self.statements.append(statement)
        return None

    def only_statement(self) -> Any:
        assert len(self.statements) == 1
        return self.statements[0]

    def last_statement(self) -> Any:
        assert self.statements
        return self.statements[-1]


def _compile_sql(statement: Any) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def _normalize_sql(sql: str) -> str:
    return " ".join(sql.lower().split())


def _assert_sql_predicate(sql: str, *, table: str, column: str, value: int | UUID) -> None:
    normalized = _normalize_sql(sql)
    if isinstance(value, int):
        expected = f"{table}.{column} = {value}"
    else:
        expected = f"{table}.{column} = '{value}'"
    assert expected in normalized


def _disable_tenant_context_check(repository: BaseRepository[Any]) -> None:
    async def _ensure_tenant_context(tenant_id: int) -> None:
        BaseRepository._require_tenant_id(tenant_id)

    repository._ensure_tenant_context = _ensure_tenant_context  # type: ignore[method-assign]


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-app-role-contract-tests",
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
            raise AssertionError("app_role contract tests require a reachable test database.") from exc
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


async def _insert_tenant_fixture(
    session: AsyncSession,
    *,
    tenant_id: int,
    actor_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    ticket_id: UUID,
    slug_suffix: str,
) -> None:
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (:tenant_id, :tenant_name, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"tenant_id": tenant_id, "tenant_name": f"tenant-{slug_suffix}"},
    )
    await session.execute(
        text(
            """
            insert into actors (
              id, tenant_id, actor_type, actor_id, display_name, auth_context_hash, metadata
            )
            values (
              :actor_id, :tenant_id, 'human', :stable_actor_id, :display_name,
              :auth_context_hash, '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "actor_id": actor_id,
            "tenant_id": tenant_id,
            "stable_actor_id": f"human:{slug_suffix}",
            "display_name": f"Tenant {slug_suffix} Actor",
            "auth_context_hash": f"tenant-{slug_suffix}-auth-context",
        },
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (
              :workspace_id, :tenant_id, :workspace_slug, :workspace_slug, :actor_id,
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "workspace_id": workspace_id,
            "tenant_id": tenant_id,
            "workspace_slug": f"workspace-{slug_suffix}",
            "actor_id": actor_id,
        },
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (
              :project_id, :tenant_id, :workspace_id, :project_slug, :project_slug,
              'active', '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "project_id": project_id,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "project_slug": f"project-{slug_suffix}",
        },
    )
    await session.execute(
        text(
            """
            insert into tickets (
              id, tenant_id, project_id, slug, title, status, created_by_actor_id, metadata
            )
            values (
              :ticket_id, :tenant_id, :project_id, :ticket_slug, :ticket_title,
              'open', :actor_id, '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "ticket_id": ticket_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "ticket_slug": f"ticket-{slug_suffix}",
            "ticket_title": f"Ticket {slug_suffix}",
            "actor_id": actor_id,
        },
    )


async def _setup_two_tenant_tickets(session: AsyncSession) -> None:
    await _reset_tables(session)
    await _insert_tenant_fixture(
        session,
        tenant_id=1,
        actor_id=TENANT_ONE_ACTOR_ID,
        workspace_id=TENANT_ONE_WORKSPACE_ID,
        project_id=TENANT_ONE_PROJECT_ID,
        ticket_id=TENANT_ONE_TICKET_ID,
        slug_suffix="one",
    )
    await _insert_tenant_fixture(
        session,
        tenant_id=2,
        actor_id=TENANT_TWO_ACTOR_ID,
        workspace_id=TENANT_TWO_WORKSPACE_ID,
        project_id=TENANT_TWO_PROJECT_ID,
        ticket_id=TENANT_TWO_TICKET_ID,
        slug_suffix="two",
    )


def test_base_repository_statement_for_list_predicates_include_tenant_id() -> None:
    repository = BaseRepository(cast(AsyncSession, object()), Ticket)

    sql = _compile_sql(repository.statement_for_list(tenant_id=1))

    _assert_sql_predicate(sql, table="tickets", column="tenant_id", value=1)


def test_base_repository_statement_for_update_includes_tenant_id_predicate() -> None:
    repository = BaseRepository(cast(AsyncSession, object()), Ticket)

    sql = _compile_sql(
        repository.statement_for_update(
            tenant_id=1,
            id=TENANT_ONE_TICKET_ID,
            payload={"title": "Updated title"},
        )
    )

    _assert_sql_predicate(sql, table="tickets", column="tenant_id", value=1)
    _assert_sql_predicate(sql, table="tickets", column="id", value=TENANT_ONE_TICKET_ID)


def test_base_repository_statement_for_delete_includes_tenant_id_predicate() -> None:
    repository = BaseRepository(cast(AsyncSession, object()), Ticket)

    sql = _compile_sql(repository.statement_for_delete(tenant_id=1, id=TENANT_ONE_TICKET_ID))

    _assert_sql_predicate(sql, table="tickets", column="tenant_id", value=1)
    _assert_sql_predicate(sql, table="tickets", column="id", value=TENANT_ONE_TICKET_ID)


@pytest.mark.asyncio
async def test_ticket_repository_in_project_statements_include_tenant_and_project_predicates() -> None:
    capture_session = _CapturingSession()
    repository = TicketRepository(cast(AsyncSession, capture_session))
    _disable_tenant_context_check(repository)

    await repository.list_in_project(tenant_id=1, project_id=TENANT_ONE_PROJECT_ID)
    list_sql = _compile_sql(capture_session.only_statement())

    capture_session.statements.clear()
    await repository.update_in_project(
        tenant_id=1,
        project_id=TENANT_ONE_PROJECT_ID,
        ticket_id=TENANT_ONE_TICKET_ID,
        payload={"title": "Updated title"},
    )
    update_sql = _compile_sql(capture_session.only_statement())

    capture_session.statements.clear()
    await repository.delete_in_project(
        tenant_id=1,
        project_id=TENANT_ONE_PROJECT_ID,
        ticket_id=TENANT_ONE_TICKET_ID,
    )
    delete_sql = _compile_sql(capture_session.only_statement())

    for sql in (list_sql, update_sql, delete_sql):
        _assert_sql_predicate(sql, table="tickets", column="tenant_id", value=1)
        _assert_sql_predicate(
            sql,
            table="tickets",
            column="project_id",
            value=TENANT_ONE_PROJECT_ID,
        )


@pytest.mark.asyncio
async def test_acceptance_criteria_repository_in_ticket_statements_include_boundary_predicates() -> None:
    capture_session = _CapturingSession()
    repository = AcceptanceCriteriaRepository(cast(AsyncSession, capture_session))
    _disable_tenant_context_check(repository)

    await repository.list_in_ticket(
        tenant_id=1,
        project_id=TENANT_ONE_PROJECT_ID,
        ticket_id=TENANT_ONE_TICKET_ID,
    )
    list_sql = _compile_sql(capture_session.only_statement())

    capture_session.statements.clear()
    await repository.update_in_ticket(
        tenant_id=1,
        project_id=TENANT_ONE_PROJECT_ID,
        ticket_id=TENANT_ONE_TICKET_ID,
        ac_id=ACCEPTANCE_CRITERIA_ID,
        payload={"status": "satisfied"},
    )
    update_sql = _compile_sql(capture_session.only_statement())

    capture_session.statements.clear()
    await repository.delete_in_ticket(
        tenant_id=1,
        project_id=TENANT_ONE_PROJECT_ID,
        ticket_id=TENANT_ONE_TICKET_ID,
        ac_id=ACCEPTANCE_CRITERIA_ID,
    )
    delete_sql = _compile_sql(capture_session.only_statement())

    for sql in (list_sql, update_sql, delete_sql):
        _assert_sql_predicate(sql, table="acceptance_criteria", column="tenant_id", value=1)
        _assert_sql_predicate(
            sql,
            table="acceptance_criteria",
            column="project_id",
            value=TENANT_ONE_PROJECT_ID,
        )
        _assert_sql_predicate(
            sql,
            table="acceptance_criteria",
            column="ticket_id",
            value=TENANT_ONE_TICKET_ID,
        )


@pytest.mark.asyncio
async def test_ticket_relation_repository_in_project_statements_include_boundary_predicates() -> None:
    capture_session = _CapturingSession()
    repository = TicketRelationRepository(cast(AsyncSession, capture_session))
    _disable_tenant_context_check(repository)

    await repository.list_in_project(tenant_id=1, project_id=TENANT_ONE_PROJECT_ID)
    list_sql = _compile_sql(capture_session.only_statement())

    capture_session.statements.clear()
    await repository.update_in_project(
        tenant_id=1,
        project_id=TENANT_ONE_PROJECT_ID,
        relation_id=TICKET_RELATION_ID,
        payload={"relation_type": "depends_on"},
    )
    update_sql = _compile_sql(capture_session.only_statement())

    capture_session.statements.clear()
    await repository.delete_in_project(
        tenant_id=1,
        project_id=TENANT_ONE_PROJECT_ID,
        relation_id=TICKET_RELATION_ID,
    )
    delete_sql = _compile_sql(capture_session.only_statement())

    for sql in (list_sql, update_sql, delete_sql):
        _assert_sql_predicate(sql, table="ticket_relations", column="tenant_id", value=1)
        _assert_sql_predicate(
            sql,
            table="ticket_relations",
            column="project_id",
            value=TENANT_ONE_PROJECT_ID,
        )


@pytest.mark.asyncio
async def test_set_and_get_tenant_context_round_trips_positive_integer(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await set_tenant_context(session, 1)
        tenant_id = await get_tenant_context(session)

    assert tenant_id == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant_id", [True, 0, -1, "1"])
async def test_set_tenant_context_rejects_invalid_tenant_id(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: object,
) -> None:
    async with session_factory.begin() as session:
        with pytest.raises(ValueError, match="tenant_id must be a positive integer"):
            await set_tenant_context(session, tenant_id)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_assert_tenant_context_without_prior_set_rejects(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        with pytest.raises(ValueError, match="tenant context mismatch"):
            await assert_tenant_context(session, 1)


@pytest.mark.asyncio
async def test_assert_tenant_context_rejects_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await set_tenant_context(session, 1)

        with pytest.raises(ValueError, match="tenant context mismatch"):
            await assert_tenant_context(session, 2)


@pytest.mark.asyncio
async def test_base_repository_get_runs_assert_tenant_context_for_matching_tenant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _setup_two_tenant_tickets(session)
        await set_tenant_context(session, 1)

        repository = BaseRepository(session, Ticket)
        ticket = await repository.get(tenant_id=1, id=TENANT_ONE_TICKET_ID)

    assert ticket.id == TENANT_ONE_TICKET_ID
    assert ticket.tenant_id == 1


@pytest.mark.asyncio
async def test_ticket_repository_get_in_project_rejects_cross_tenant_context(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _setup_two_tenant_tickets(session)
        await set_tenant_context(session, 1)

        repository = TicketRepository(session)
        with pytest.raises(ValueError, match="tenant context mismatch"):
            await repository.get_in_project(
                tenant_id=2,
                project_id=TENANT_TWO_PROJECT_ID,
                ticket_id=TENANT_TWO_TICKET_ID,
            )


@pytest.mark.asyncio
async def test_base_repository_get_rejects_bool_tenant_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _setup_two_tenant_tickets(session)

        repository = BaseRepository(session, Ticket)
        with pytest.raises(ValueError, match="tenant_id must be a positive integer"):
            await repository.get(tenant_id=True, id=TENANT_ONE_TICKET_ID)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_audit_event_repository_append_persists_only_requested_tenant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _setup_two_tenant_tickets(session)

        repository = AuditEventRepository(session)
        event = await repository.append(
            tenant_id=1,
            event_type="app_role.contract.audit_append",
            payload={"rls_ready": True, "result": "tenant-one-only"},
            actor_id=TENANT_ONE_ACTOR_ID,
            correlation_id="app-role-contract-audit-append",
        )
        tenant_one_count = await session.scalar(
            select(func.count(AuditEvent.id)).where(AuditEvent.tenant_id == 1)
        )
        tenant_two_count = await session.scalar(
            select(func.count(AuditEvent.id)).where(AuditEvent.tenant_id == 2)
        )

    assert event.tenant_id == 1
    assert event.actor_id == TENANT_ONE_ACTOR_ID
    assert tenant_one_count == 1
    assert tenant_two_count == 0


@pytest.mark.asyncio
async def test_tenant_context_is_transaction_local_across_commit_and_rollback(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await set_tenant_context(session, 1)
        before_commit = await get_tenant_context(session)
        await session.commit()

        after_commit = await get_tenant_context(session)
        await session.rollback()

        await set_tenant_context(session, 2)
        before_rollback = await get_tenant_context(session)
        await session.rollback()

        after_rollback = await get_tenant_context(session)
        await session.rollback()

    assert before_commit == 1
    assert after_commit is None
    assert before_rollback == 2
    assert after_rollback is None
