from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

BATCH1_TENANT_SCOPED_TABLES = frozenset(
    {
        "actors",
        "principals",
        "workspaces",
        "projects",
        "repositories",
    }
)
BATCH2_TENANT_SCOPED_TABLES = frozenset(
    {
        "tickets",
        "acceptance_criteria",
        "ticket_relations",
        "audit_events",
        "notification_events",
    }
)
TENANT_SCOPED_TABLES = BATCH1_TENANT_SCOPED_TABLES | BATCH2_TENANT_SCOPED_TABLES
METADATA_TABLES = frozenset(
    {
        "tenants",
        "actors",
        "principals",
        "workspaces",
        "projects",
        "repositories",
        "tickets",
        "acceptance_criteria",
        "ticket_relations",
    }
)
ALL_CORE_TABLES = TENANT_SCOPED_TABLES | {"tenants"}
ForeignKeySignature = tuple[str, tuple[str, ...], str, tuple[str, ...]]


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-schema-tests",
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
            raise AssertionError("DB schema tests require a reachable test database.") from exc
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


async def _foreign_key_signatures(session: AsyncSession) -> set[ForeignKeySignature]:
    result = await session.execute(
        text(
            """
            select
              rel.relname as table_name,
              array_agg(att.attname order by keys.ord) as constrained_columns,
              refrel.relname as referenced_table,
              array_agg(refatt.attname order by keys.ord) as referred_columns
            from pg_constraint con
            join pg_class rel on rel.oid = con.conrelid
            join pg_class refrel on refrel.oid = con.confrelid
            join unnest(con.conkey, con.confkey) with ordinality
              as keys(attnum, refattnum, ord) on true
            join pg_attribute att
              on att.attrelid = con.conrelid and att.attnum = keys.attnum
            join pg_attribute refatt
              on refatt.attrelid = con.confrelid and refatt.attnum = keys.refattnum
            where con.contype = 'f'
              and rel.relname = any(:table_names)
            group by con.conname, rel.relname, refrel.relname
            order by rel.relname, con.conname
            """
        ),
        {"table_names": sorted(TENANT_SCOPED_TABLES)},
    )
    signatures: set[ForeignKeySignature] = set()
    for row in result.mappings():
        signatures.add(
            (
                str(row["table_name"]),
                tuple(str(column) for column in row["constrained_columns"]),
                str(row["referenced_table"]),
                tuple(str(column) for column in row["referred_columns"]),
            )
        )
    return signatures


async def _table_columns(
    session: AsyncSession,
    table_name: str,
    column_names: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    result = await session.execute(
        text(
            """
            select column_name, is_nullable, column_default, data_type
            from information_schema.columns
            where table_schema = 'public'
              and table_name = :table_name
              and column_name = any(:column_names)
            """
        ),
        {"table_name": table_name, "column_names": list(column_names)},
    )
    return {str(row["column_name"]): dict(row) for row in result.mappings()}


async def _constraint_columns(
    session: AsyncSession,
    *,
    table_name: str,
    constraint_name: str,
    constraint_type: str,
) -> tuple[str, ...]:
    result = await session.execute(
        text(
            """
            select array_agg(att.attname order by keys.ord) as constrained_columns
            from pg_constraint con
            join pg_class rel on rel.oid = con.conrelid
            join unnest(con.conkey) with ordinality as keys(attnum, ord) on true
            join pg_attribute att
              on att.attrelid = con.conrelid and att.attnum = keys.attnum
            where con.contype = :constraint_type
              and rel.relname = :table_name
              and con.conname = :constraint_name
            group by con.conname
            """
        ),
        {
            "constraint_type": constraint_type,
            "table_name": table_name,
            "constraint_name": constraint_name,
        },
    )
    columns = result.scalar_one_or_none()
    if columns is None:
        return ()
    return tuple(str(column) for column in columns)


async def _constraint_definition(
    session: AsyncSession,
    *,
    table_name: str,
    constraint_name: str,
) -> str:
    definition = await session.scalar(
        text(
            """
            select pg_get_constraintdef(con.oid)
            from pg_constraint con
            join pg_class rel on rel.oid = con.conrelid
            where rel.relname = :table_name
              and con.conname = :constraint_name
            """
        ),
        {"table_name": table_name, "constraint_name": constraint_name},
    )
    assert isinstance(definition, str)
    return definition


@pytest.mark.asyncio
async def test_tenant_scoped_tables_have_tenant_id_not_null(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        result = await session.execute(
            text(
                """
                select table_name, is_nullable, column_default, data_type
                from information_schema.columns
                where table_schema = 'public'
                  and table_name = any(:table_names)
                  and column_name = 'tenant_id'
                """
            ),
            {"table_names": sorted(TENANT_SCOPED_TABLES)},
        )

    columns = {str(row["table_name"]): dict(row) for row in result.mappings()}

    assert set(columns) == TENANT_SCOPED_TABLES
    for table_name in sorted(TENANT_SCOPED_TABLES):
        column = columns[table_name]
        assert column["is_nullable"] == "NO"
        assert column["data_type"] == "bigint"


@pytest.mark.asyncio
async def test_tenant_scoped_tables_have_tenant_id_default_one(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        result = await session.execute(
            text(
                """
                select table_name, column_default
                from information_schema.columns
                where table_schema = 'public'
                  and table_name = any(:table_names)
                  and column_name = 'tenant_id'
                """
            ),
            {"table_names": sorted(TENANT_SCOPED_TABLES)},
        )

    defaults = {str(row["table_name"]): str(row["column_default"]) for row in result.mappings()}

    assert set(defaults) == TENANT_SCOPED_TABLES
    for table_name in sorted(TENANT_SCOPED_TABLES):
        assert defaults[table_name] == "1", table_name


@pytest.mark.asyncio
async def test_metadata_columns_have_rls_ready_default(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        result = await session.execute(
            text(
                """
                select c.relname as table_name, pg_get_expr(d.adbin, d.adrelid) as default_expr
                from pg_class c
                join pg_namespace n on n.oid = c.relnamespace
                join pg_attribute a on a.attrelid = c.oid and a.attname = 'metadata'
                join pg_attrdef d on d.adrelid = c.oid and d.adnum = a.attnum
                where n.nspname = 'public'
                  and c.relname = any(:table_names)
                order by c.relname
                """
            ),
            {"table_names": sorted(METADATA_TABLES)},
        )

    defaults = {str(row["table_name"]): str(row["default_expr"]) for row in result.mappings()}

    assert set(defaults) == METADATA_TABLES
    for table_name, default_expr in defaults.items():
        assert "rls_ready" in default_expr, table_name
        assert "true" in default_expr, table_name


@pytest.mark.asyncio
async def test_required_composite_foreign_keys_exist(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    expected: set[ForeignKeySignature] = {
        ("actors", ("tenant_id", "impersonated_by"), "actors", ("tenant_id", "id")),
        ("principals", ("tenant_id", "actor_id"), "actors", ("tenant_id", "id")),
        ("workspaces", ("tenant_id", "owner_actor_id"), "actors", ("tenant_id", "id")),
        ("projects", ("tenant_id", "workspace_id"), "workspaces", ("tenant_id", "id")),
        ("repositories", ("tenant_id", "project_id"), "projects", ("tenant_id", "id")),
        ("tickets", ("tenant_id", "project_id"), "projects", ("tenant_id", "id")),
        ("tickets", ("tenant_id", "repository_id"), "repositories", ("tenant_id", "id")),
        (
            "tickets",
            ("tenant_id", "project_id", "repository_id"),
            "repositories",
            ("tenant_id", "project_id", "id"),
        ),
        ("tickets", ("tenant_id", "assignee_actor_id"), "actors", ("tenant_id", "id")),
        ("tickets", ("tenant_id", "created_by_actor_id"), "actors", ("tenant_id", "id")),
        (
            "acceptance_criteria",
            ("tenant_id", "project_id"),
            "projects",
            ("tenant_id", "id"),
        ),
        (
            "acceptance_criteria",
            ("tenant_id", "project_id", "ticket_id"),
            "tickets",
            ("tenant_id", "project_id", "id"),
        ),
        ("ticket_relations", ("tenant_id", "project_id"), "projects", ("tenant_id", "id")),
        (
            "ticket_relations",
            ("tenant_id", "project_id", "source_ticket_id"),
            "tickets",
            ("tenant_id", "project_id", "id"),
        ),
        (
            "ticket_relations",
            ("tenant_id", "project_id", "target_ticket_id"),
            "tickets",
            ("tenant_id", "project_id", "id"),
        ),
        ("audit_events", ("tenant_id", "actor_id"), "actors", ("tenant_id", "id")),
        (
            "audit_events",
            ("tenant_id", "actor_id", "principal_id"),
            "principals",
            ("tenant_id", "actor_id", "id"),
        ),
        (
            "notification_events",
            ("tenant_id", "recipient_actor_id"),
            "actors",
            ("tenant_id", "id"),
        ),
    }

    async with session_factory() as session:
        actual = await _foreign_key_signatures(session)

    assert expected <= actual


@pytest.mark.asyncio
async def test_id_only_foreign_keys_to_tenant_scoped_tables_are_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        result = await session.execute(
            text(
                """
                select
                  con.conname,
                  rel.relname as table_name,
                  array_agg(att.attname order by keys.ord) as constrained_columns,
                  refrel.relname as referenced_table,
                  array_agg(refatt.attname order by keys.ord) as referred_columns
                from pg_constraint con
                join pg_class rel on rel.oid = con.conrelid
                join pg_class refrel on refrel.oid = con.confrelid
                join unnest(con.conkey, con.confkey) with ordinality
                  as keys(attnum, refattnum, ord) on true
                join pg_attribute att
                  on att.attrelid = con.conrelid and att.attnum = keys.attnum
                join pg_attribute refatt
                  on refatt.attrelid = con.confrelid and refatt.attnum = keys.refattnum
                where con.contype = 'f'
                  and rel.relname = any(:table_names)
                group by con.conname, rel.relname, refrel.relname
                order by rel.relname, con.conname
                """
            ),
            {"table_names": sorted(TENANT_SCOPED_TABLES)},
        )

    bad_constraints: list[dict[str, Any]] = []
    for row in result.mappings():
        referenced_table = str(row["referenced_table"])
        constrained_columns = tuple(str(column) for column in row["constrained_columns"])
        referred_columns = tuple(str(column) for column in row["referred_columns"])

        if referenced_table != "tenants" and (
            constrained_columns == ("id",)
            or "tenant_id" not in constrained_columns
            or referred_columns == ("id",)
        ):
            bad_constraints.append(dict(row))

    assert bad_constraints == []


@pytest.mark.asyncio
async def test_actors_have_stable_actor_id_and_auth_context_hash_contract(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        columns = await _table_columns(session, "actors", ("actor_id", "auth_context_hash"))
        unique_columns = await _constraint_columns(
            session,
            table_name="actors",
            constraint_name="actors_uq_tenant_actor_id",
            constraint_type="u",
        )

    assert set(columns) == {"actor_id", "auth_context_hash"}
    assert columns["actor_id"]["data_type"] == "text"
    assert columns["actor_id"]["is_nullable"] == "NO"
    assert columns["auth_context_hash"]["data_type"] == "text"
    assert columns["auth_context_hash"]["is_nullable"] == "YES"
    assert unique_columns == ("tenant_id", "actor_id")


@pytest.mark.asyncio
async def test_principals_have_actor_principal_binding_unique_constraint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        unique_columns = await _constraint_columns(
            session,
            table_name="principals",
            constraint_name="principals_uq_tenant_actor_principal_id",
            constraint_type="u",
        )

    assert unique_columns == ("tenant_id", "actor_id", "id")


@pytest.mark.asyncio
async def test_workspace_project_repository_contract_columns_and_constraints(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        workspace_columns = await _table_columns(session, "workspaces", ("slug", "owner_actor_id"))
        project_columns = await _table_columns(session, "projects", ("slug", "status", "policy_profile"))
        repository_columns = await _table_columns(
            session,
            "repositories",
            (
                "provider",
                "external_id",
                "owner_name",
                "repo_name",
                "default_branch",
                "installation_ref",
            ),
        )
        workspace_unique = await _constraint_columns(
            session,
            table_name="workspaces",
            constraint_name="workspaces_uq_tenant_slug",
            constraint_type="u",
        )
        project_unique = await _constraint_columns(
            session,
            table_name="projects",
            constraint_name="projects_uq_tenant_workspace_slug",
            constraint_type="u",
        )
        repository_unique = await _constraint_columns(
            session,
            table_name="repositories",
            constraint_name="repositories_uq_tenant_provider_external",
            constraint_type="u",
        )
        repository_project_unique = await _constraint_columns(
            session,
            table_name="repositories",
            constraint_name="repositories_uq_tenant_project_id",
            constraint_type="u",
        )
        project_status_check = await _constraint_definition(
            session,
            table_name="projects",
            constraint_name="projects_ck_status",
        )
        repository_provider_check = await _constraint_definition(
            session,
            table_name="repositories",
            constraint_name="repositories_ck_provider",
        )

    assert workspace_columns["slug"]["data_type"] == "text"
    assert workspace_columns["slug"]["is_nullable"] == "NO"
    assert workspace_columns["owner_actor_id"]["data_type"] == "uuid"
    assert workspace_columns["owner_actor_id"]["is_nullable"] == "NO"
    assert workspace_unique == ("tenant_id", "slug")

    assert project_columns["slug"]["data_type"] == "text"
    assert project_columns["slug"]["is_nullable"] == "NO"
    assert project_columns["status"]["data_type"] == "text"
    assert project_columns["status"]["is_nullable"] == "NO"
    assert "active" in str(project_columns["status"]["column_default"])
    assert project_columns["policy_profile"]["data_type"] == "text"
    assert project_columns["policy_profile"]["is_nullable"] == "YES"
    assert project_unique == ("tenant_id", "workspace_id", "slug")
    assert "active" in project_status_check
    assert "archived" in project_status_check

    assert repository_columns["provider"]["data_type"] == "text"
    assert repository_columns["provider"]["is_nullable"] == "NO"
    assert repository_columns["external_id"]["data_type"] == "text"
    assert repository_columns["external_id"]["is_nullable"] == "NO"
    assert repository_columns["owner_name"]["data_type"] == "text"
    assert repository_columns["owner_name"]["is_nullable"] == "NO"
    assert repository_columns["repo_name"]["data_type"] == "text"
    assert repository_columns["repo_name"]["is_nullable"] == "NO"
    assert repository_columns["default_branch"]["data_type"] == "text"
    assert repository_columns["default_branch"]["is_nullable"] == "NO"
    assert "main" in str(repository_columns["default_branch"]["column_default"])
    assert repository_columns["installation_ref"]["data_type"] == "text"
    assert repository_columns["installation_ref"]["is_nullable"] == "YES"
    assert repository_unique == ("tenant_id", "provider", "external_id")
    assert repository_project_unique == ("tenant_id", "project_id", "id")
    assert "github" in repository_provider_check
    assert "gitlab" in repository_provider_check
    assert "bitbucket" in repository_provider_check


@pytest.mark.asyncio
async def test_ticket_acceptance_relation_contract_columns_and_constraints(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        ticket_columns = await _table_columns(
            session,
            "tickets",
            (
                "project_id",
                "repository_id",
                "slug",
                "title",
                "description",
                "status",
                "priority",
                "assignee_actor_id",
                "created_by_actor_id",
            ),
        )
        acceptance_columns = await _table_columns(
            session,
            "acceptance_criteria",
            ("ticket_id", "project_id", "description", "status", "evidence_ref"),
        )
        relation_columns = await _table_columns(
            session,
            "ticket_relations",
            ("project_id", "source_ticket_id", "target_ticket_id", "relation_type"),
        )
        ticket_project_unique = await _constraint_columns(
            session,
            table_name="tickets",
            constraint_name="tickets_uq_tenant_project_id",
            constraint_type="u",
        )
        ticket_slug_unique = await _constraint_columns(
            session,
            table_name="tickets",
            constraint_name="tickets_uq_tenant_project_slug",
            constraint_type="u",
        )
        relation_project_unique = await _constraint_columns(
            session,
            table_name="ticket_relations",
            constraint_name="ticket_relations_uq_tenant_project_id",
            constraint_type="u",
        )
        relation_unique = await _constraint_columns(
            session,
            table_name="ticket_relations",
            constraint_name="ticket_relations_uq_edge",
            constraint_type="u",
        )
        ticket_status_check = await _constraint_definition(
            session,
            table_name="tickets",
            constraint_name="tickets_ck_status",
        )
        ticket_priority_check = await _constraint_definition(
            session,
            table_name="tickets",
            constraint_name="tickets_ck_priority",
        )
        acceptance_status_check = await _constraint_definition(
            session,
            table_name="acceptance_criteria",
            constraint_name="acceptance_criteria_ck_status",
        )
        relation_type_check = await _constraint_definition(
            session,
            table_name="ticket_relations",
            constraint_name="ticket_relations_ck_relation_type",
        )
        relation_self_loop_check = await _constraint_definition(
            session,
            table_name="ticket_relations",
            constraint_name="ticket_relations_ck_no_self_loop",
        )

    assert ticket_columns["project_id"]["data_type"] == "uuid"
    assert ticket_columns["project_id"]["is_nullable"] == "NO"
    assert ticket_columns["repository_id"]["data_type"] == "uuid"
    assert ticket_columns["repository_id"]["is_nullable"] == "YES"
    assert ticket_columns["slug"]["data_type"] == "text"
    assert ticket_columns["slug"]["is_nullable"] == "NO"
    assert ticket_columns["title"]["data_type"] == "text"
    assert ticket_columns["title"]["is_nullable"] == "NO"
    assert ticket_columns["description"]["data_type"] == "text"
    assert ticket_columns["description"]["is_nullable"] == "YES"
    assert ticket_columns["status"]["data_type"] == "text"
    assert ticket_columns["status"]["is_nullable"] == "NO"
    assert "open" in str(ticket_columns["status"]["column_default"])
    assert ticket_columns["priority"]["data_type"] == "text"
    assert ticket_columns["priority"]["is_nullable"] == "YES"
    assert ticket_columns["assignee_actor_id"]["data_type"] == "uuid"
    assert ticket_columns["assignee_actor_id"]["is_nullable"] == "YES"
    assert ticket_columns["created_by_actor_id"]["data_type"] == "uuid"
    assert ticket_columns["created_by_actor_id"]["is_nullable"] == "NO"
    assert ticket_project_unique == ("tenant_id", "project_id", "id")
    assert ticket_slug_unique == ("tenant_id", "project_id", "slug")
    for status in ("open", "in_progress", "blocked", "review", "closed", "cancelled"):
        assert status in ticket_status_check
    for priority in ("low", "medium", "high", "critical"):
        assert priority in ticket_priority_check

    assert acceptance_columns["ticket_id"]["data_type"] == "uuid"
    assert acceptance_columns["ticket_id"]["is_nullable"] == "NO"
    assert acceptance_columns["project_id"]["data_type"] == "uuid"
    assert acceptance_columns["project_id"]["is_nullable"] == "NO"
    assert acceptance_columns["description"]["data_type"] == "text"
    assert acceptance_columns["description"]["is_nullable"] == "NO"
    assert acceptance_columns["status"]["data_type"] == "text"
    assert acceptance_columns["status"]["is_nullable"] == "NO"
    assert "pending" in str(acceptance_columns["status"]["column_default"])
    assert acceptance_columns["evidence_ref"]["data_type"] == "text"
    assert acceptance_columns["evidence_ref"]["is_nullable"] == "YES"
    for status in ("pending", "satisfied", "rejected", "deferred"):
        assert status in acceptance_status_check

    assert relation_columns["project_id"]["data_type"] == "uuid"
    assert relation_columns["project_id"]["is_nullable"] == "NO"
    assert relation_columns["source_ticket_id"]["data_type"] == "uuid"
    assert relation_columns["source_ticket_id"]["is_nullable"] == "NO"
    assert relation_columns["target_ticket_id"]["data_type"] == "uuid"
    assert relation_columns["target_ticket_id"]["is_nullable"] == "NO"
    assert relation_columns["relation_type"]["data_type"] == "text"
    assert relation_columns["relation_type"]["is_nullable"] == "NO"
    assert relation_project_unique == ("tenant_id", "project_id", "id")
    assert relation_unique == (
        "tenant_id",
        "project_id",
        "source_ticket_id",
        "target_ticket_id",
        "relation_type",
    )
    for relation_type in ("blocks", "blocked_by", "duplicates", "relates_to", "depends_on"):
        assert relation_type in relation_type_check
    assert "source_ticket_id" in relation_self_loop_check
    assert "target_ticket_id" in relation_self_loop_check


@pytest.mark.asyncio
async def test_audit_notification_contract_columns_and_constraints(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        audit_columns = await _table_columns(
            session,
            "audit_events",
            (
                "event_type",
                "event_payload",
                "actor_id",
                "principal_id",
                "correlation_id",
                "trace_id",
                "created_at",
            ),
        )
        notification_columns = await _table_columns(
            session,
            "notification_events",
            ("event_type", "payload", "recipient_actor_id", "read_at", "created_at"),
        )
        audit_unique = await _constraint_columns(
            session,
            table_name="audit_events",
            constraint_name="audit_events_uq_tenant_id",
            constraint_type="u",
        )
        notification_unique = await _constraint_columns(
            session,
            table_name="notification_events",
            constraint_name="notification_events_uq_tenant_id",
            constraint_type="u",
        )
        audit_principal_requires_actor_check = await _constraint_definition(
            session,
            table_name="audit_events",
            constraint_name="audit_events_ck_principal_requires_actor",
        )

    assert audit_columns["event_type"]["data_type"] == "text"
    assert audit_columns["event_type"]["is_nullable"] == "NO"
    assert audit_columns["event_payload"]["data_type"] == "jsonb"
    assert audit_columns["event_payload"]["is_nullable"] == "NO"
    assert audit_columns["actor_id"]["data_type"] == "uuid"
    assert audit_columns["actor_id"]["is_nullable"] == "YES"
    assert audit_columns["principal_id"]["data_type"] == "uuid"
    assert audit_columns["principal_id"]["is_nullable"] == "YES"
    assert audit_columns["correlation_id"]["data_type"] == "text"
    assert audit_columns["correlation_id"]["is_nullable"] == "YES"
    assert audit_columns["trace_id"]["data_type"] == "text"
    assert audit_columns["trace_id"]["is_nullable"] == "YES"
    assert audit_columns["created_at"]["is_nullable"] == "NO"
    assert audit_unique == ("tenant_id", "id")
    assert "principal_id" in audit_principal_requires_actor_check
    assert "actor_id" in audit_principal_requires_actor_check

    assert notification_columns["event_type"]["data_type"] == "text"
    assert notification_columns["event_type"]["is_nullable"] == "NO"
    assert notification_columns["payload"]["data_type"] == "jsonb"
    assert notification_columns["payload"]["is_nullable"] == "NO"
    assert notification_columns["recipient_actor_id"]["data_type"] == "uuid"
    assert notification_columns["recipient_actor_id"]["is_nullable"] == "NO"
    assert notification_columns["read_at"]["is_nullable"] == "YES"
    assert notification_columns["created_at"]["is_nullable"] == "NO"
    assert notification_unique == ("tenant_id", "id")

