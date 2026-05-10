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

SECRET_TABLES = frozenset({"secret_refs", "secret_capability_tokens"})
PROHIBITED_SECRET_COLUMNS = frozenset(
    {
        "age_key",
        "api_key",
        "auth_token",
        "canary",
        "plaintext",
        "private_key",
        "raw_secret",
        "raw_token",
        "raw_value",
        "request_fingerprint",
        "secret_value",
        "sops_key",
        "token",
        "value",
    }
)

ForeignKeySignature = tuple[str, tuple[str, ...], str, tuple[str, ...]]


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-secret-schema-tests",
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
            raise AssertionError("Secret schema tests require a reachable test database.") from exc
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
    # pg_constraint.contype は PostgreSQL "char" 型 (1-byte 内部単一バイト型)。
    # asyncpg prepared statement type inference が $1 を "char" と推論し str -> bytes encode
    # で fail するため、column 側を `::text` cast して $1 を text 推論させる。
    # (test_schema_introspection.py で検出した同 pattern を適用)
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
        {"table_names": sorted(SECRET_TABLES)},
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


@pytest.mark.asyncio
async def test_secret_tables_have_required_columns_and_tenant_defaults(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    secret_ref_column_names = (
        "id",
        "tenant_id",
        "secret_uri",
        "scope",
        "name",
        "version",
        "status",
        "runner_injectable",
        "allowed_consumers",
        "allowed_operations",
        "owner_actor_id",
        "rotated_from_id",
        "metadata",
        "created_at",
        "updated_at",
        "deprecated_at",
        "revoked_at",
    )
    token_column_names = (
        "id",
        "tenant_id",
        "secret_ref_id",
        "token_hash",
        "allowed_operations",
        "scope_constraint",
        "issued_to_actor_id",
        "issued_run_id",
        "expected_request_fingerprint",
        "expires_at",
        "used_at",
        "status",
        "metadata",
        "created_at",
    )

    async with session_factory() as session:
        secret_ref_columns = await _table_columns(session, "secret_refs", secret_ref_column_names)
        token_columns = await _table_columns(
            session,
            "secret_capability_tokens",
            token_column_names,
        )

    assert set(secret_ref_columns) == set(secret_ref_column_names)
    assert secret_ref_columns["id"]["data_type"] == "uuid"
    assert "uuid_generate_v4" in str(secret_ref_columns["id"]["column_default"])
    assert secret_ref_columns["tenant_id"]["data_type"] == "bigint"
    assert secret_ref_columns["tenant_id"]["is_nullable"] == "NO"
    assert secret_ref_columns["tenant_id"]["column_default"] == "1"
    assert secret_ref_columns["secret_uri"]["data_type"] == "text"
    assert secret_ref_columns["secret_uri"]["is_nullable"] == "NO"
    assert secret_ref_columns["runner_injectable"]["data_type"] == "boolean"
    assert secret_ref_columns["runner_injectable"]["is_nullable"] == "NO"
    assert "false" in str(secret_ref_columns["runner_injectable"]["column_default"])
    assert secret_ref_columns["allowed_consumers"]["data_type"] == "jsonb"
    assert secret_ref_columns["allowed_consumers"]["is_nullable"] == "NO"
    assert "[]" in str(secret_ref_columns["allowed_consumers"]["column_default"])
    assert secret_ref_columns["allowed_operations"]["data_type"] == "jsonb"
    assert secret_ref_columns["allowed_operations"]["is_nullable"] == "NO"
    assert "[]" in str(secret_ref_columns["allowed_operations"]["column_default"])
    assert secret_ref_columns["owner_actor_id"]["data_type"] == "uuid"
    assert secret_ref_columns["owner_actor_id"]["is_nullable"] == "NO"
    assert secret_ref_columns["rotated_from_id"]["data_type"] == "uuid"
    assert secret_ref_columns["rotated_from_id"]["is_nullable"] == "YES"
    assert secret_ref_columns["metadata"]["data_type"] == "jsonb"
    assert "rls_ready" in str(secret_ref_columns["metadata"]["column_default"])

    assert set(token_columns) == set(token_column_names)
    assert token_columns["id"]["data_type"] == "uuid"
    assert "uuid_generate_v4" in str(token_columns["id"]["column_default"])
    assert token_columns["tenant_id"]["data_type"] == "bigint"
    assert token_columns["tenant_id"]["is_nullable"] == "NO"
    assert token_columns["tenant_id"]["column_default"] == "1"
    assert token_columns["secret_ref_id"]["data_type"] == "uuid"
    assert token_columns["secret_ref_id"]["is_nullable"] == "NO"
    assert token_columns["token_hash"]["data_type"] == "text"
    assert token_columns["token_hash"]["is_nullable"] == "NO"
    assert token_columns["allowed_operations"]["data_type"] == "jsonb"
    assert token_columns["allowed_operations"]["is_nullable"] == "NO"
    assert "[]" in str(token_columns["allowed_operations"]["column_default"])
    assert token_columns["scope_constraint"]["data_type"] == "jsonb"
    assert token_columns["scope_constraint"]["is_nullable"] == "NO"
    assert "{}" in str(token_columns["scope_constraint"]["column_default"])
    assert token_columns["issued_to_actor_id"]["data_type"] == "uuid"
    assert token_columns["issued_to_actor_id"]["is_nullable"] == "NO"
    assert token_columns["issued_run_id"]["data_type"] == "uuid"
    assert token_columns["issued_run_id"]["is_nullable"] == "YES"
    assert token_columns["expected_request_fingerprint"]["data_type"] == "text"
    assert token_columns["expected_request_fingerprint"]["is_nullable"] == "NO"
    assert token_columns["expires_at"]["is_nullable"] == "NO"
    assert token_columns["used_at"]["is_nullable"] == "YES"
    assert token_columns["status"]["data_type"] == "text"
    assert token_columns["status"]["is_nullable"] == "NO"
    assert token_columns["metadata"]["data_type"] == "jsonb"
    assert "rls_ready" in str(token_columns["metadata"]["column_default"])


@pytest.mark.asyncio
async def test_secret_constraints_match_secretbroker_boundary(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        secret_uri_check = await _constraint_definition(
            session,
            table_name="secret_refs",
            constraint_name="secret_refs_ck_secret_uri_format",
        )
        secret_uri_components_check = await _constraint_definition(
            session,
            table_name="secret_refs",
            constraint_name="secret_refs_ck_secret_uri_components_match",
        )
        secret_scope_check = await _constraint_definition(
            session,
            table_name="secret_refs",
            constraint_name="secret_refs_ck_scope",
        )
        secret_status_check = await _constraint_definition(
            session,
            table_name="secret_refs",
            constraint_name="secret_refs_ck_status",
        )
        runner_check = await _constraint_definition(
            session,
            table_name="secret_refs",
            constraint_name="secret_refs_ck_runner_injectable_false",
        )
        secret_allowlist_arrays_check = await _constraint_definition(
            session,
            table_name="secret_refs",
            constraint_name="secret_refs_ck_allowlist_jsonb_arrays",
        )
        secret_allowed_consumers_string_elements_check = await _constraint_definition(
            session,
            table_name="secret_refs",
            constraint_name="secret_refs_ck_allowed_consumers_string_elements",
        )
        secret_allowed_operations_string_elements_check = await _constraint_definition(
            session,
            table_name="secret_refs",
            constraint_name="secret_refs_ck_allowed_operations_string_elements",
        )
        secret_active_allowlist_check = await _constraint_definition(
            session,
            table_name="secret_refs",
            constraint_name="secret_refs_ck_active_allowlist_nonempty",
        )
        secret_metadata_check = await _constraint_definition(
            session,
            table_name="secret_refs",
            constraint_name="secret_refs_ck_metadata_no_raw_secret",
        )
        token_status_check = await _constraint_definition(
            session,
            table_name="secret_capability_tokens",
            constraint_name="secret_capability_tokens_ck_status",
        )
        token_expires_check = await _constraint_definition(
            session,
            table_name="secret_capability_tokens",
            constraint_name="secret_capability_tokens_ck_expires_within_ttl_bounds",
        )
        token_hash_format_check = await _constraint_definition(
            session,
            table_name="secret_capability_tokens",
            constraint_name="secret_capability_tokens_ck_token_hash_format",
        )
        token_fingerprint_format_check = await _constraint_definition(
            session,
            table_name="secret_capability_tokens",
            constraint_name="secret_capability_tokens_ck_expected_request_fingerprint_format",
        )
        token_allowed_operations_check = await _constraint_definition(
            session,
            table_name="secret_capability_tokens",
            constraint_name="secret_capability_tokens_ck_allowed_operations_nonempty_array",
        )
        token_allowed_operations_string_elements_check = await _constraint_definition(
            session,
            table_name="secret_capability_tokens",
            constraint_name="secret_capability_tokens_ck_allowed_operations_string_elements",
        )
        token_scope_constraint_check = await _constraint_definition(
            session,
            table_name="secret_capability_tokens",
            constraint_name="secret_capability_tokens_ck_scope_constraint_jsonb_object",
        )
        token_metadata_check = await _constraint_definition(
            session,
            table_name="secret_capability_tokens",
            constraint_name="secret_capability_tokens_ck_metadata_no_raw_secret",
        )
        token_used_at_check = await _constraint_definition(
            session,
            table_name="secret_capability_tokens",
            constraint_name="secret_capability_tokens_ck_used_at_status",
        )

    assert "secret://sops" in secret_uri_check
    for scope in ("p0", "workspace", "project", "repo", "agent_run", "provider"):
        assert scope in secret_uri_check
    assert "[a-z0-9_-]+#v[0-9]+" in secret_uri_check
    for component in ("secret_uri", "scope", "name", "version"):
        assert component in secret_uri_components_check
    for scope in ("p0", "workspace", "project", "repo", "agent_run", "provider"):
        assert scope in secret_scope_check
    for status in ("pending", "active", "deprecated", "revoked"):
        assert status in secret_status_check
    assert "runner_injectable" in runner_check
    assert "false" in runner_check
    assert "jsonb_typeof" in secret_allowlist_arrays_check
    assert "allowed_consumers" in secret_allowlist_arrays_check
    assert "allowed_operations" in secret_allowlist_arrays_check
    assert "array" in secret_allowlist_arrays_check
    assert "jsonb_typeof" in secret_allowed_consumers_string_elements_check
    assert "jsonb_path_exists" in secret_allowed_consumers_string_elements_check
    assert "allowed_consumers" in secret_allowed_consumers_string_elements_check
    assert "string" in secret_allowed_consumers_string_elements_check
    assert "jsonb_typeof" in secret_allowed_operations_string_elements_check
    assert "jsonb_path_exists" in secret_allowed_operations_string_elements_check
    assert "allowed_operations" in secret_allowed_operations_string_elements_check
    assert "string" in secret_allowed_operations_string_elements_check
    assert "active" in secret_active_allowlist_check
    assert "jsonb_array_length" in secret_active_allowlist_check
    assert "allowed_consumers" in secret_active_allowlist_check
    assert "allowed_operations" in secret_active_allowlist_check
    assert "jsonb_typeof" in secret_metadata_check
    assert "jsonb_path_exists" in secret_metadata_check
    assert "keyvalue" in secret_metadata_check
    assert "metadata" in secret_metadata_check
    for prohibited_key in (
        "raw_secret",
        "raw_token",
        "api_key",
        "auth_token",
        "secret_value",
        "plaintext",
        "private_key",
        "sops_key",
        "age_key",
        "canary",
        "token",
        "raw_value",
        "value",
    ):
        assert prohibited_key in secret_metadata_check

    for status in ("issued", "redeeming", "used", "expired", "revoked"):
        assert status in token_status_check
    assert "expires_at" in token_expires_check
    assert "created_at" in token_expires_check
    assert "5 minutes" in token_expires_check or "00:05:00" in token_expires_check
    assert "30 minutes" in token_expires_check or "00:30:00" in token_expires_check
    assert "token_hash" in token_hash_format_check
    assert "[a-f0-9]{64}" in token_hash_format_check
    assert "expected_request_fingerprint" in token_fingerprint_format_check
    assert "[a-f0-9]{64}" in token_fingerprint_format_check
    assert "jsonb_typeof" in token_allowed_operations_check
    assert "allowed_operations" in token_allowed_operations_check
    assert "array" in token_allowed_operations_check
    assert "jsonb_array_length" in token_allowed_operations_check
    assert "jsonb_typeof" in token_allowed_operations_string_elements_check
    assert "jsonb_path_exists" in token_allowed_operations_string_elements_check
    assert "allowed_operations" in token_allowed_operations_string_elements_check
    assert "string" in token_allowed_operations_string_elements_check
    assert "jsonb_typeof" in token_scope_constraint_check
    assert "scope_constraint" in token_scope_constraint_check
    assert "object" in token_scope_constraint_check
    assert "jsonb_typeof" in token_metadata_check
    assert "jsonb_path_exists" in token_metadata_check
    assert "keyvalue" in token_metadata_check
    assert "metadata" in token_metadata_check
    for prohibited_key in (
        "raw_secret",
        "raw_token",
        "api_key",
        "auth_token",
        "secret_value",
        "plaintext",
        "private_key",
        "sops_key",
        "age_key",
        "canary",
        "token",
        "raw_value",
        "value",
    ):
        assert prohibited_key in token_metadata_check
    assert "used_at" in token_used_at_check
    assert "issued" in token_used_at_check
    assert "used_at IS NULL" in token_used_at_check
    assert "redeeming" in token_used_at_check
    assert "used" in token_used_at_check
    assert "used_at IS NOT NULL" in token_used_at_check
    assert "expired" in token_used_at_check
    assert "revoked" in token_used_at_check


@pytest.mark.asyncio
async def test_secret_unique_constraints_and_indexes_exist(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        secret_ref_unique = await _constraint_columns(
            session,
            table_name="secret_refs",
            constraint_name="secret_refs_uq_tenant_id",
            constraint_type="u",
        )
        secret_ref_secret_uri_unique = await _constraint_columns(
            session,
            table_name="secret_refs",
            constraint_name="secret_refs_uq_tenant_secret_uri",
            constraint_type="u",
        )
        secret_ref_components_unique = await _constraint_columns(
            session,
            table_name="secret_refs",
            constraint_name="secret_refs_uq_tenant_scope_name_version",
            constraint_type="u",
        )
        token_id_unique = await _constraint_columns(
            session,
            table_name="secret_capability_tokens",
            constraint_name="secret_capability_tokens_uq_tenant_id",
            constraint_type="u",
        )
        token_hash_unique = await _constraint_columns(
            session,
            table_name="secret_capability_tokens",
            constraint_name="secret_capability_tokens_uq_tenant_token_hash",
            constraint_type="u",
        )
        indexes = await _index_definitions(session, SECRET_TABLES)

    assert secret_ref_unique == ("tenant_id", "id")
    assert secret_ref_secret_uri_unique == ("tenant_id", "secret_uri")
    assert secret_ref_components_unique == ("tenant_id", "scope", "name", "version")
    assert token_id_unique == ("tenant_id", "id")
    assert token_hash_unique == ("tenant_id", "token_hash")

    assert "secret_refs_one_active_per_name" in indexes
    active_index = indexes["secret_refs_one_active_per_name"]
    assert active_index.startswith("CREATE UNIQUE INDEX")
    assert "(tenant_id, scope, name)" in active_index
    assert "status = 'active'::text" in active_index

    assert "secret_refs_one_pending_per_name" in indexes
    pending_index = indexes["secret_refs_one_pending_per_name"]
    assert pending_index.startswith("CREATE UNIQUE INDEX")
    assert "(tenant_id, scope, name)" in pending_index
    assert "status = 'pending'::text" in pending_index

    assert "(tenant_id, status)" in indexes["secret_refs_idx_status"]
    assert "(tenant_id, scope, name)" in indexes["secret_refs_idx_scope_name"]
    assert "(tenant_id, expires_at)" in indexes["secret_capability_tokens_idx_expires_at"]
    assert "status = 'issued'::text" in indexes["secret_capability_tokens_idx_expires_at"]
    assert "(tenant_id, secret_ref_id, status)" in indexes[
        "secret_capability_tokens_idx_issued_status"
    ]
    assert "status = 'issued'::text" in indexes["secret_capability_tokens_idx_issued_status"]
    assert "(tenant_id, issued_to_actor_id)" in indexes[
        "secret_capability_tokens_idx_issued_actor"
    ]
    assert "(tenant_id, issued_run_id)" in indexes["secret_capability_tokens_idx_issued_run"]
    assert "issued_run_id IS NOT NULL" in indexes[
        "secret_capability_tokens_idx_issued_run"
    ]


@pytest.mark.asyncio
async def test_secret_foreign_keys_are_composite_and_run_fk_is_deferred(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    expected: set[ForeignKeySignature] = {
        ("secret_refs", ("tenant_id",), "tenants", ("id",)),
        ("secret_refs", ("tenant_id", "owner_actor_id"), "actors", ("tenant_id", "id")),
        (
            "secret_refs",
            ("tenant_id", "rotated_from_id"),
            "secret_refs",
            ("tenant_id", "id"),
        ),
        ("secret_capability_tokens", ("tenant_id",), "tenants", ("id",)),
        (
            "secret_capability_tokens",
            ("tenant_id", "secret_ref_id"),
            "secret_refs",
            ("tenant_id", "id"),
        ),
        (
            "secret_capability_tokens",
            ("tenant_id", "issued_to_actor_id"),
            "actors",
            ("tenant_id", "id"),
        ),
    }

    async with session_factory() as session:
        actual = await _foreign_key_signatures(session)

    assert expected <= actual
    assert all(signature[2] != "agent_runs" for signature in actual)
    assert all("issued_run_id" not in signature[1] for signature in actual)

    bad_constraints: list[ForeignKeySignature] = []
    for signature in actual:
        table_name, constrained_columns, referenced_table, referred_columns = signature
        if referenced_table in {"actors", "secret_refs"} and (
            "tenant_id" not in constrained_columns or referred_columns == ("id",)
        ):
            bad_constraints.append((table_name, constrained_columns, referenced_table, referred_columns))

    assert bad_constraints == []


@pytest.mark.asyncio
async def test_secret_schema_has_no_raw_secret_or_raw_token_columns(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        result = await session.execute(
            text(
                """
                select table_name, column_name
                from information_schema.columns
                where table_schema = 'public'
                  and table_name = any(:table_names)
                """
            ),
            {"table_names": sorted(SECRET_TABLES)},
        )

    columns_by_table: dict[str, set[str]] = {table_name: set() for table_name in SECRET_TABLES}
    for row in result.mappings():
        columns_by_table[str(row["table_name"])].add(str(row["column_name"]))

    assert columns_by_table["secret_refs"].isdisjoint(PROHIBITED_SECRET_COLUMNS)
    assert columns_by_table["secret_capability_tokens"].isdisjoint(PROHIBITED_SECRET_COLUMNS)
    assert "expected_request_fingerprint" in columns_by_table["secret_capability_tokens"]

