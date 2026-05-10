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
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.audit_event import AuditEvent
from backend.app.db.session import create_engine
from backend.app.repositories.audit_event import AuditEventRepository

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

ACTOR_ID = UUID("00000000-0000-4000-8000-000000004001")
PRINCIPAL_ID = UUID("00000000-0000-4000-8000-000000004002")
OTHER_ACTOR_ID = UUID("00000000-0000-4000-8000-000000004003")
OTHER_PRINCIPAL_ID = UUID("00000000-0000-4000-8000-000000004004")
AUDIT_EVENT_ID = UUID("00000000-0000-4000-8000-000000004005")
AUDIT_EVENT_CHECK_ID = UUID("00000000-0000-4000-8000-000000004006")


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-audit-event-tests",
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
            raise AssertionError("audit event tests require a reachable test database.") from exc
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


async def _insert_actor_principal_fixture(session: AsyncSession) -> None:
    await session.execute(
        text("insert into tenants (id, name, metadata) values (1, 'tenant-one', '{}')")
    )
    await session.execute(
        text(
            """
            insert into actors (
              id, tenant_id, actor_type, actor_id, display_name,
              auth_context_hash, metadata
            )
            values
              (
                :actor_id, 1, 'human', 'human:audit', 'Audit Actor',
                'audit-auth-context', '{"rls_ready": true}'::jsonb
              ),
              (
                :other_actor_id, 1, 'human', 'human:audit-other', 'Other Audit Actor',
                'audit-auth-context-other', '{"rls_ready": true}'::jsonb
              )
            """
        ),
        {"actor_id": ACTOR_ID, "other_actor_id": OTHER_ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into principals (
              id, tenant_id, actor_id, principal_type, auth_context_hash, metadata
            )
            values
              (
                :principal_id, 1, :actor_id, 'session', 'audit-auth-context',
                '{"rls_ready": true}'::jsonb
              ),
              (
                :other_principal_id, 1, :other_actor_id, 'session',
                'audit-auth-context-other', '{"rls_ready": true}'::jsonb
              )
            """
        ),
        {
            "principal_id": PRINCIPAL_ID,
            "actor_id": ACTOR_ID,
            "other_principal_id": OTHER_PRINCIPAL_ID,
            "other_actor_id": OTHER_ACTOR_ID,
        },
    )


@pytest.mark.asyncio
async def test_audit_event_repository_append_succeeds(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _reset_tables(session)
        await _insert_actor_principal_fixture(session)

        repository = AuditEventRepository(session)
        event = await repository.append(
            tenant_id=1,
            event_type="ticket_status_changed",
            payload={"ticket_id": "TCK-1", "from": "open", "to": "review"},
            actor_id=ACTOR_ID,
            principal_id=PRINCIPAL_ID,
            correlation_id="corr-audit-test",
        )

    async with session_factory() as session:
        persisted = await session.scalar(select(AuditEvent).where(AuditEvent.id == event.id))

    assert persisted is not None
    assert persisted.tenant_id == 1
    assert persisted.event_type == "ticket_status_changed"
    assert persisted.event_payload["to"] == "review"
    assert persisted.actor_id == ACTOR_ID
    assert persisted.principal_id == PRINCIPAL_ID
    assert persisted.correlation_id == "corr-audit-test"


@pytest.mark.asyncio
async def test_audit_event_repository_append_succeeds_with_null_principal(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _reset_tables(session)
        await _insert_actor_principal_fixture(session)

        repository = AuditEventRepository(session)
        event = await repository.append(
            tenant_id=1,
            event_type="system_heartbeat",
            payload={"status": "ok"},
            actor_id=None,
            principal_id=None,
        )

    async with session_factory() as session:
        persisted = await session.scalar(select(AuditEvent).where(AuditEvent.id == event.id))

    assert persisted is not None
    assert persisted.actor_id is None
    assert persisted.principal_id is None


@pytest.mark.asyncio
async def test_audit_event_repository_rejects_mismatched_actor_principal_before_flush(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _reset_tables(session)
        await _insert_actor_principal_fixture(session)

        repository = AuditEventRepository(session)
        with pytest.raises(ValueError, match=r"principal_id must belong to actor_id"):
            await repository.append(
                tenant_id=1,
                event_type="mismatched_actor_principal",
                payload={"status": "blocked"},
                actor_id=ACTOR_ID,
                principal_id=OTHER_PRINCIPAL_ID,
            )


@pytest.mark.asyncio
async def test_audit_events_reject_mismatched_actor_principal_by_composite_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_actor_principal_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into audit_events (
                      id, tenant_id, event_type, event_payload, actor_id, principal_id
                    )
                    values (
                      :event_id, 1, 'mismatched_actor_principal', '{"status":"blocked"}'::jsonb,
                      :actor_id, :other_principal_id
                    )
                    """
                ),
                {
                    "event_id": AUDIT_EVENT_ID,
                    "actor_id": ACTOR_ID,
                    "other_principal_id": OTHER_PRINCIPAL_ID,
                },
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="audit_events_actor_principal_fkey",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_audit_events_reject_principal_without_actor_by_check_constraint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_actor_principal_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into audit_events (
                      id, tenant_id, event_type, event_payload, actor_id, principal_id
                    )
                    values (
                      :event_id, 1, 'principal_without_actor', '{"status":"blocked"}'::jsonb,
                      null, :principal_id
                    )
                    """
                ),
                {"event_id": AUDIT_EVENT_CHECK_ID, "principal_id": PRINCIPAL_ID},
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="audit_events_ck_principal_requires_actor",
        )
        await session.rollback()


def test_audit_event_repository_does_not_expose_update_or_delete_methods() -> None:
    repository = AuditEventRepository(session=object())  # type: ignore[arg-type]

    assert not hasattr(repository, "update")
    assert not hasattr(repository, "delete")
    with pytest.raises(AttributeError):
        _ = repository.update
    with pytest.raises(AttributeError):
        _ = repository.delete


@pytest.mark.asyncio
async def test_audit_events_schema_has_required_columns(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    expected_columns = {
        "id",
        "tenant_id",
        "event_type",
        "event_payload",
        "actor_id",
        "principal_id",
        "correlation_id",
        "trace_id",
        "created_at",
    }

    async with session_factory() as session:
        result = await session.execute(
            text(
                """
                select column_name, is_nullable, data_type
                from information_schema.columns
                where table_schema = 'public'
                  and table_name = 'audit_events'
                """
            )
        )

    columns = {str(row["column_name"]): dict(row) for row in result.mappings()}

    assert expected_columns <= set(columns)
    assert columns["tenant_id"]["is_nullable"] == "NO"
    assert columns["tenant_id"]["data_type"] == "bigint"
    assert columns["event_type"]["is_nullable"] == "NO"
    assert columns["event_payload"]["is_nullable"] == "NO"
    assert columns["actor_id"]["is_nullable"] == "YES"
    assert columns["principal_id"]["is_nullable"] == "YES"
    assert columns["created_at"]["is_nullable"] == "NO"

