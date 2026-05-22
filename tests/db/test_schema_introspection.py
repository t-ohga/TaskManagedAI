from __future__ import annotations

import asyncio
import os
import re
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
BATCH3_TENANT_SCOPED_TABLES = frozenset(
    {
        "policy_rules",
    }
)
BATCH4_TENANT_SCOPED_TABLES = frozenset(
    {
        "approval_requests",
        "policy_decisions",
    }
)
TENANT_SCOPED_TABLES = (
    BATCH1_TENANT_SCOPED_TABLES
    | BATCH2_TENANT_SCOPED_TABLES
    | BATCH3_TENANT_SCOPED_TABLES
    | BATCH4_TENANT_SCOPED_TABLES
)
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
        "policy_rules",
        "approval_requests",
        "policy_decisions",
    }
)
POLICY_ACTION_CLASSES = frozenset(
    {
        "task_write",
        "repo_write",
        "pr_open",
        "secret_access",
        "merge",
        "deploy",
        "provider_call",
    }
)
POLICY_EFFECTS = frozenset({"allow", "deny", "require_approval"})
APPROVAL_STATUSES = frozenset({"pending", "approved", "rejected", "expired", "invalidated"})
RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})
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


async def _foreign_key_signatures(
    session: AsyncSession,
    tables: frozenset[str] | None = None,
) -> set[ForeignKeySignature]:
    target_tables = sorted(tables if tables is not None else TENANT_SCOPED_TABLES)
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
        {"table_names": target_tables},
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
    # pg_constraint.contype は PostgreSQL "char" 型 (1-byte 内部単一バイト型、引用符付き)。
    # asyncpg の prepared statement type inference が `con.contype = $1` から $1 を "char"
    # と推論し、Python str を bytes-like として encode しようとして
    # `invalid input for query argument: 'u' (a bytes-like object is required)` で fail。
    # 解決: column 側を text に cast して比較すれば、$1 の type は text として推論される。
    result = await session.execute(
        text(
            """
            select array_agg(att.attname order by keys.ord) as constrained_columns
            from pg_constraint con
            join pg_class rel on rel.oid = con.conrelid
            join unnest(con.conkey) with ordinality as keys(attnum, ord) on true
            join pg_attribute att
              on att.attrelid = con.conrelid and att.attnum = keys.attnum
            where con.contype::text = :constraint_type
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


async def _index_definitions(
    session: AsyncSession,
    table_names: frozenset[str],
) -> dict[str, str]:
    result = await session.execute(
        text(
            """
            select indexname, indexdef
            from pg_indexes
            where schemaname = 'public'
              and tablename = any(:table_names)
            """
        ),
        {"table_names": sorted(table_names)},
    )
    return {str(row["indexname"]): str(row["indexdef"]) for row in result.mappings()}


def _check_constraint_values(definition: str) -> set[str]:
    return set(re.findall(r"'([^']+)'", definition))


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
        ("policy_rules", ("tenant_id", "project_id"), "projects", ("tenant_id", "id")),
        (
            "approval_requests",
            ("tenant_id", "requested_by_actor_id"),
            "actors",
            ("tenant_id", "id"),
        ),
        (
            "approval_requests",
            ("tenant_id", "decided_by_actor_id"),
            "actors",
            ("tenant_id", "id"),
        ),
        (
            "policy_decisions",
            ("tenant_id", "approval_request_id"),
            "approval_requests",
            ("tenant_id", "id"),
        ),
        ("policy_decisions", ("tenant_id", "actor_id"), "actors", ("tenant_id", "id")),
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
async def test_policy_rules_has_tenant_id_and_composite_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    policy_rule_column_names = (
        "id",
        "tenant_id",
        "project_id",
        "action_class",
        "effect",
        "rule_json",
        "policy_version",
        "metadata",
        "created_at",
        "updated_at",
    )

    async with session_factory() as session:
        policy_rule_columns = await _table_columns(
            session,
            "policy_rules",
            policy_rule_column_names,
        )
        policy_rule_unique = await _constraint_columns(
            session,
            table_name="policy_rules",
            constraint_name="policy_rules_uq_tenant_id",
            constraint_type="u",
        )
        actual = await _foreign_key_signatures(session)
        indexes = await _index_definitions(session, frozenset({"policy_rules"}))

    assert set(policy_rule_columns) == set(policy_rule_column_names)
    assert policy_rule_columns["id"]["data_type"] == "uuid"
    assert policy_rule_columns["id"]["is_nullable"] == "NO"
    assert "uuid_generate_v4" in str(policy_rule_columns["id"]["column_default"])
    assert policy_rule_columns["tenant_id"]["data_type"] == "bigint"
    assert policy_rule_columns["tenant_id"]["is_nullable"] == "NO"
    assert policy_rule_columns["tenant_id"]["column_default"] == "1"
    assert policy_rule_columns["project_id"]["data_type"] == "uuid"
    assert policy_rule_columns["project_id"]["is_nullable"] == "YES"
    assert policy_rule_columns["action_class"]["data_type"] == "text"
    assert policy_rule_columns["action_class"]["is_nullable"] == "NO"
    assert policy_rule_columns["effect"]["data_type"] == "text"
    assert policy_rule_columns["effect"]["is_nullable"] == "NO"
    assert policy_rule_columns["rule_json"]["data_type"] == "jsonb"
    assert policy_rule_columns["rule_json"]["is_nullable"] == "NO"
    assert policy_rule_columns["policy_version"]["data_type"] == "text"
    assert policy_rule_columns["policy_version"]["is_nullable"] == "NO"
    assert policy_rule_columns["metadata"]["data_type"] == "jsonb"
    assert policy_rule_columns["metadata"]["is_nullable"] == "NO"
    assert "rls_ready" in str(policy_rule_columns["metadata"]["column_default"])
    assert policy_rule_columns["created_at"]["is_nullable"] == "NO"
    assert policy_rule_columns["updated_at"]["is_nullable"] == "NO"
    assert policy_rule_unique == ("tenant_id", "id")

    assert ("policy_rules", ("tenant_id",), "tenants", ("id",)) in actual
    assert ("policy_rules", ("tenant_id", "project_id"), "projects", ("tenant_id", "id")) in actual

    policy_rule_bad_fks: list[ForeignKeySignature] = []
    for signature in actual:
        table_name, constrained_columns, referenced_table, referred_columns = signature
        if table_name == "policy_rules" and referenced_table != "tenants" and (
            constrained_columns == ("id",)
            or "tenant_id" not in constrained_columns
            or referred_columns == ("id",)
        ):
            policy_rule_bad_fks.append(signature)

    assert policy_rule_bad_fks == []

    assert indexes["policy_rules_idx_tenant_action_class"].startswith("CREATE INDEX")
    assert "(tenant_id, action_class)" in indexes["policy_rules_idx_tenant_action_class"]
    assert indexes["policy_rules_idx_policy_version"].startswith("CREATE INDEX")
    assert "(tenant_id, policy_version)" in indexes["policy_rules_idx_policy_version"]


@pytest.mark.asyncio
async def test_policy_rules_action_class_check_enum(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        action_class_check = await _constraint_definition(
            session,
            table_name="policy_rules",
            constraint_name="policy_rules_ck_action_class",
        )

    assert _check_constraint_values(action_class_check) == POLICY_ACTION_CLASSES


@pytest.mark.asyncio
async def test_policy_rules_effect_check_enum(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        effect_check = await _constraint_definition(
            session,
            table_name="policy_rules",
            constraint_name="policy_rules_ck_effect",
        )

    assert _check_constraint_values(effect_check) == POLICY_EFFECTS


@pytest.mark.asyncio
async def test_approval_requests_has_tenant_id_and_composite_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    approval_column_names = (
        "id",
        "tenant_id",
        "run_id",
        "action_class",
        "resource_ref",
        "risk_level",
        "artifact_hash",
        "diff_hash",
        "policy_version",
        "policy_pack_lock",
        "provider_request_fingerprint",
        "stale_after_event_seq",
        "status",
        "requested_by_actor_id",
        "decided_by_actor_id",
        "requested_at",
        "decided_at",
        "rationale",
        "metadata",
    )

    async with session_factory() as session:
        approval_columns = await _table_columns(
            session,
            "approval_requests",
            approval_column_names,
        )
        approval_unique = await _constraint_columns(
            session,
            table_name="approval_requests",
            constraint_name="approval_requests_uq_tenant_id",
            constraint_type="u",
        )
        actual = await _foreign_key_signatures(session)
        indexes = await _index_definitions(session, frozenset({"approval_requests"}))

    assert set(approval_columns) == set(approval_column_names)
    assert approval_columns["id"]["data_type"] == "uuid"
    assert approval_columns["id"]["is_nullable"] == "NO"
    assert "uuid_generate_v4" in str(approval_columns["id"]["column_default"])
    assert approval_columns["tenant_id"]["data_type"] == "bigint"
    assert approval_columns["tenant_id"]["is_nullable"] == "NO"
    assert approval_columns["tenant_id"]["column_default"] == "1"
    assert approval_columns["run_id"]["data_type"] == "uuid"
    assert approval_columns["run_id"]["is_nullable"] == "YES"
    assert approval_columns["action_class"]["data_type"] == "text"
    assert approval_columns["action_class"]["is_nullable"] == "NO"
    assert approval_columns["resource_ref"]["data_type"] == "text"
    assert approval_columns["resource_ref"]["is_nullable"] == "NO"
    assert approval_columns["risk_level"]["data_type"] == "text"
    assert approval_columns["risk_level"]["is_nullable"] == "NO"
    assert approval_columns["artifact_hash"]["data_type"] == "text"
    assert approval_columns["artifact_hash"]["is_nullable"] == "YES"
    assert approval_columns["diff_hash"]["data_type"] == "text"
    assert approval_columns["diff_hash"]["is_nullable"] == "YES"
    assert approval_columns["policy_version"]["data_type"] == "text"
    assert approval_columns["policy_version"]["is_nullable"] == "NO"
    assert approval_columns["policy_pack_lock"]["data_type"] == "text"
    assert approval_columns["policy_pack_lock"]["is_nullable"] == "YES"
    assert approval_columns["provider_request_fingerprint"]["data_type"] == "text"
    assert approval_columns["provider_request_fingerprint"]["is_nullable"] == "YES"
    assert approval_columns["stale_after_event_seq"]["data_type"] == "bigint"
    assert approval_columns["stale_after_event_seq"]["is_nullable"] == "YES"
    assert approval_columns["status"]["data_type"] == "text"
    assert approval_columns["status"]["is_nullable"] == "NO"
    assert approval_columns["requested_by_actor_id"]["data_type"] == "uuid"
    assert approval_columns["requested_by_actor_id"]["is_nullable"] == "NO"
    assert approval_columns["decided_by_actor_id"]["data_type"] == "uuid"
    assert approval_columns["decided_by_actor_id"]["is_nullable"] == "YES"
    assert approval_columns["requested_at"]["is_nullable"] == "NO"
    assert "now()" in str(approval_columns["requested_at"]["column_default"])
    assert approval_columns["decided_at"]["is_nullable"] == "YES"
    assert approval_columns["rationale"]["data_type"] == "text"
    assert approval_columns["rationale"]["is_nullable"] == "YES"
    assert approval_columns["metadata"]["data_type"] == "jsonb"
    assert approval_columns["metadata"]["is_nullable"] == "NO"
    assert "rls_ready" in str(approval_columns["metadata"]["column_default"])
    assert approval_unique == ("tenant_id", "id")

    assert ("approval_requests", ("tenant_id",), "tenants", ("id",)) in actual
    assert (
        "approval_requests",
        ("tenant_id", "requested_by_actor_id"),
        "actors",
        ("tenant_id", "id"),
    ) in actual
    assert (
        "approval_requests",
        ("tenant_id", "decided_by_actor_id"),
        "actors",
        ("tenant_id", "id"),
    ) in actual
    assert not any(
        table_name == "approval_requests" and constrained_columns == ("tenant_id", "run_id")
        for table_name, constrained_columns, _referenced_table, _referred_columns in actual
    )

    assert indexes["approval_requests_idx_tenant_status"].startswith("CREATE INDEX")
    assert "(tenant_id, status)" in indexes["approval_requests_idx_tenant_status"]
    assert indexes["approval_requests_idx_tenant_run"].startswith("CREATE INDEX")
    assert "(tenant_id, run_id)" in indexes["approval_requests_idx_tenant_run"]
    # `.upper()` で全文 upper case 化するので、検索 substring も upper case に揃える
    # (`run_id` (lowercase) は upper case 化された string と match しない test bug 修正)。
    assert "RUN_ID IS NOT NULL" in indexes["approval_requests_idx_tenant_run"].upper()
    assert indexes["approval_requests_idx_requested_at"].startswith("CREATE INDEX")
    assert "(tenant_id, requested_at)" in indexes["approval_requests_idx_requested_at"]


@pytest.mark.asyncio
async def test_approval_requests_action_class_check_enum(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        action_class_check = await _constraint_definition(
            session,
            table_name="approval_requests",
            constraint_name="approval_requests_ck_action_class",
        )

    assert _check_constraint_values(action_class_check) == POLICY_ACTION_CLASSES


@pytest.mark.asyncio
async def test_approval_requests_status_check_enum(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        status_check = await _constraint_definition(
            session,
            table_name="approval_requests",
            constraint_name="approval_requests_ck_status",
        )
        risk_check = await _constraint_definition(
            session,
            table_name="approval_requests",
            constraint_name="approval_requests_ck_risk_level",
        )

    assert _check_constraint_values(status_check) == APPROVAL_STATUSES
    assert _check_constraint_values(risk_check) == RISK_LEVELS


@pytest.mark.asyncio
async def test_approval_requests_self_approval_check_constraint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        self_approval_check = await _constraint_definition(
            session,
            table_name="approval_requests",
            constraint_name="approval_requests_ck_self_approval",
        )
        decided_at_check = await _constraint_definition(
            session,
            table_name="approval_requests",
            constraint_name="approval_requests_ck_decided_at_consistency",
        )

    assert "requested_by_actor_id" in self_approval_check
    assert "decided_by_actor_id" in self_approval_check
    assert "<>" in self_approval_check or "!=" in self_approval_check
    assert "decided_by_actor_id" in decided_at_check
    assert "decided_at" in decided_at_check


@pytest.mark.asyncio
async def test_policy_decisions_has_tenant_id_and_composite_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    policy_decision_column_names = (
        "id",
        "tenant_id",
        "run_id",
        "approval_request_id",
        "actor_id",
        "action_class",
        "decision",
        "reason_code",
        "policy_version",
        "input_hash",
        "metadata",
        "created_at",
    )

    async with session_factory() as session:
        policy_decision_columns = await _table_columns(
            session,
            "policy_decisions",
            policy_decision_column_names,
        )
        policy_decision_unique = await _constraint_columns(
            session,
            table_name="policy_decisions",
            constraint_name="policy_decisions_uq_tenant_id",
            constraint_type="u",
        )
        actual = await _foreign_key_signatures(session)
        indexes = await _index_definitions(session, frozenset({"policy_decisions"}))

    assert set(policy_decision_columns) == set(policy_decision_column_names)
    assert policy_decision_columns["id"]["data_type"] == "uuid"
    assert policy_decision_columns["id"]["is_nullable"] == "NO"
    assert "uuid_generate_v4" in str(policy_decision_columns["id"]["column_default"])
    assert policy_decision_columns["tenant_id"]["data_type"] == "bigint"
    assert policy_decision_columns["tenant_id"]["is_nullable"] == "NO"
    assert policy_decision_columns["tenant_id"]["column_default"] == "1"
    assert policy_decision_columns["run_id"]["data_type"] == "uuid"
    assert policy_decision_columns["run_id"]["is_nullable"] == "YES"
    assert policy_decision_columns["approval_request_id"]["data_type"] == "uuid"
    assert policy_decision_columns["approval_request_id"]["is_nullable"] == "YES"
    assert policy_decision_columns["actor_id"]["data_type"] == "uuid"
    assert policy_decision_columns["actor_id"]["is_nullable"] == "NO"
    assert policy_decision_columns["action_class"]["data_type"] == "text"
    assert policy_decision_columns["action_class"]["is_nullable"] == "NO"
    assert policy_decision_columns["decision"]["data_type"] == "text"
    assert policy_decision_columns["decision"]["is_nullable"] == "NO"
    assert policy_decision_columns["reason_code"]["data_type"] == "text"
    assert policy_decision_columns["reason_code"]["is_nullable"] == "NO"
    assert policy_decision_columns["policy_version"]["data_type"] == "text"
    assert policy_decision_columns["policy_version"]["is_nullable"] == "NO"
    assert policy_decision_columns["input_hash"]["data_type"] == "text"
    assert policy_decision_columns["input_hash"]["is_nullable"] == "NO"
    assert policy_decision_columns["metadata"]["data_type"] == "jsonb"
    assert policy_decision_columns["metadata"]["is_nullable"] == "NO"
    assert "rls_ready" in str(policy_decision_columns["metadata"]["column_default"])
    assert policy_decision_columns["created_at"]["is_nullable"] == "NO"
    assert "now()" in str(policy_decision_columns["created_at"]["column_default"])
    assert policy_decision_unique == ("tenant_id", "id")

    assert ("policy_decisions", ("tenant_id",), "tenants", ("id",)) in actual
    assert (
        "policy_decisions",
        ("tenant_id", "approval_request_id"),
        "approval_requests",
        ("tenant_id", "id"),
    ) in actual
    assert ("policy_decisions", ("tenant_id", "actor_id"), "actors", ("tenant_id", "id")) in actual
    assert not any(
        table_name == "policy_decisions" and constrained_columns == ("tenant_id", "run_id")
        for table_name, constrained_columns, _referenced_table, _referred_columns in actual
    )

    assert indexes["policy_decisions_idx_tenant_action_class"].startswith("CREATE INDEX")
    assert "(tenant_id, action_class)" in indexes["policy_decisions_idx_tenant_action_class"]
    assert indexes["policy_decisions_idx_tenant_approval"].startswith("CREATE INDEX")
    assert "(tenant_id, approval_request_id)" in indexes["policy_decisions_idx_tenant_approval"]
    assert "APPROVAL_REQUEST_ID IS NOT NULL" in indexes[
        "policy_decisions_idx_tenant_approval"
    ].upper()
    assert indexes["policy_decisions_idx_created_at"].startswith("CREATE INDEX")
    assert "(tenant_id, created_at)" in indexes["policy_decisions_idx_created_at"]


@pytest.mark.asyncio
async def test_policy_decisions_decision_check_enum(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        action_class_check = await _constraint_definition(
            session,
            table_name="policy_decisions",
            constraint_name="policy_decisions_ck_action_class",
        )
        decision_check = await _constraint_definition(
            session,
            table_name="policy_decisions",
            constraint_name="policy_decisions_ck_decision",
        )

    assert _check_constraint_values(action_class_check) == POLICY_ACTION_CLASSES
    assert _check_constraint_values(decision_check) == POLICY_EFFECTS


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
    assert project_columns["policy_profile"]["is_nullable"] == "NO"
    assert "default" in str(project_columns["policy_profile"]["column_default"])
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


RESEARCH_EVIDENCE_TABLES = frozenset({"research_tasks", "evidence_sources", "claims", "evidence_items"})




@pytest.mark.asyncio
async def test_research_evidence_tables_have_tenant_id_not_null_bigint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        result = await session.execute(
            text(
                """
                select table_name, is_nullable, data_type
                from information_schema.columns
                where table_schema = 'public'
                  and table_name = any(:table_names)
                  and column_name = 'tenant_id'
                """
            ),
            {"table_names": sorted(RESEARCH_EVIDENCE_TABLES)},
        )

    columns = {str(row["table_name"]): dict(row) for row in result.mappings()}
    assert set(columns) == RESEARCH_EVIDENCE_TABLES
    for table_name in sorted(RESEARCH_EVIDENCE_TABLES):
        assert columns[table_name]["is_nullable"] == "NO"
        assert columns[table_name]["data_type"] == "bigint"


@pytest.mark.asyncio
async def test_claims_schema_constraints_and_composite_foreign_keys(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    column_names = (
        "id",
        "tenant_id",
        "project_id",
        "research_task_id",
        "claim_text",
        "provenance_json",
        "freshness_score",
        "metadata",
        "created_at",
        "updated_at",
    )

    async with session_factory() as session:
        columns = await _table_columns(session, "claims", column_names)
        tenant_unique = await _constraint_columns(
            session,
            table_name="claims",
            constraint_name="claims_uq_tenant_id",
            constraint_type="u",
        )
        tenant_project_unique = await _constraint_columns(
            session,
            table_name="claims",
            constraint_name="claims_uq_tenant_project_id",
            constraint_type="u",
        )
        claim_text_check = await _constraint_definition(
            session,
            table_name="claims",
            constraint_name="claims_ck_claim_text_length",
        )
        freshness_check = await _constraint_definition(
            session,
            table_name="claims",
            constraint_name="claims_ck_freshness_score_range",
        )
        foreign_keys = await _foreign_key_signatures(session, frozenset({"claims"}))

    assert set(columns) == set(column_names)
    assert columns["tenant_id"]["data_type"] == "bigint"
    assert columns["tenant_id"]["is_nullable"] == "NO"
    assert columns["project_id"]["data_type"] == "uuid"
    assert columns["project_id"]["is_nullable"] == "NO"
    assert columns["research_task_id"]["data_type"] == "uuid"
    assert columns["research_task_id"]["is_nullable"] == "NO"
    assert columns["claim_text"]["data_type"] == "text"
    assert columns["claim_text"]["is_nullable"] == "NO"
    assert columns["provenance_json"]["data_type"] == "jsonb"
    assert columns["provenance_json"]["is_nullable"] == "NO"
    assert columns["freshness_score"]["data_type"] == "double precision"
    assert columns["freshness_score"]["is_nullable"] == "YES"
    assert columns["metadata"]["data_type"] == "jsonb"
    assert columns["metadata"]["is_nullable"] == "NO"

    assert tenant_unique == ("tenant_id", "id")
    assert tenant_project_unique == ("tenant_id", "project_id", "id")
    assert "length(claim_text)" in claim_text_check
    assert "2000" in claim_text_check
    assert "freshness_score" in freshness_check
    assert "0" in freshness_check
    assert "1" in freshness_check
    assert {
        ("claims", ("tenant_id",), "tenants", ("id",)),
        (
            "claims",
            ("tenant_id", "project_id", "research_task_id"),
            "research_tasks",
            ("tenant_id", "project_id", "id"),
        ),
    } <= foreign_keys


@pytest.mark.asyncio
async def test_evidence_items_schema_constraints_and_composite_foreign_keys(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    column_names = (
        "id",
        "tenant_id",
        "project_id",
        "claim_id",
        "source_id",
        "locator",
        "relation",
        "relevance_score",
        "metadata",
        "created_at",
        "updated_at",
    )

    async with session_factory() as session:
        columns = await _table_columns(session, "evidence_items", column_names)
        tenant_unique = await _constraint_columns(
            session,
            table_name="evidence_items",
            constraint_name="evidence_items_uq_tenant_id",
            constraint_type="u",
        )
        item_unique = await _constraint_columns(
            session,
            table_name="evidence_items",
            constraint_name="evidence_items_uq_claim_source_locator",
            constraint_type="u",
        )
        locator_check = await _constraint_definition(
            session,
            table_name="evidence_items",
            constraint_name="evidence_items_ck_locator_length",
        )
        relevance_check = await _constraint_definition(
            session,
            table_name="evidence_items",
            constraint_name="evidence_items_ck_relevance_score_range",
        )
        foreign_keys = await _foreign_key_signatures(session, frozenset({"evidence_items"}))

    assert set(columns) == set(column_names)
    assert columns["tenant_id"]["data_type"] == "bigint"
    assert columns["tenant_id"]["is_nullable"] == "NO"
    assert columns["project_id"]["data_type"] == "uuid"
    assert columns["project_id"]["is_nullable"] == "NO"
    assert columns["claim_id"]["data_type"] == "uuid"
    assert columns["claim_id"]["is_nullable"] == "NO"
    assert columns["source_id"]["data_type"] == "uuid"
    assert columns["source_id"]["is_nullable"] == "NO"
    assert columns["locator"]["data_type"] == "text"
    assert columns["locator"]["is_nullable"] == "NO"
    assert columns["relevance_score"]["data_type"] == "double precision"
    assert columns["relevance_score"]["is_nullable"] == "YES"
    assert columns["metadata"]["data_type"] == "jsonb"
    assert columns["metadata"]["is_nullable"] == "NO"

    assert tenant_unique == ("tenant_id", "id")
    assert item_unique == ("tenant_id", "claim_id", "source_id", "locator")
    assert "length(locator)" in locator_check
    assert "500" in locator_check
    assert "relevance_score" in relevance_check
    assert "0" in relevance_check
    assert "1" in relevance_check
    assert {
        ("evidence_items", ("tenant_id",), "tenants", ("id",)),
        (
            "evidence_items",
            ("tenant_id", "project_id", "claim_id"),
            "claims",
            ("tenant_id", "project_id", "id"),
        ),
        (
            "evidence_items",
            ("tenant_id", "source_id"),
            "evidence_sources",
            ("tenant_id", "id"),
        ),
    } <= foreign_keys


@pytest.mark.asyncio
async def test_research_evidence_has_no_id_only_foreign_keys(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        foreign_keys = await _foreign_key_signatures(session, RESEARCH_EVIDENCE_TABLES)

    bad_constraints: list[ForeignKeySignature] = []
    for table_name, constrained_columns, referenced_table, referred_columns in foreign_keys:
        if referenced_table != "tenants" and (
            constrained_columns == ("id",)
            or "tenant_id" not in constrained_columns
            or referred_columns == ("id",)
        ):
            bad_constraints.append(
                (table_name, constrained_columns, referenced_table, referred_columns)
            )

    assert bad_constraints == []
