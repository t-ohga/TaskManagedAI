from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.evidence_source import EvidenceSource
from backend.app.db.session import create_engine

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

SOURCE_ID = UUID("00000000-0000-4000-8000-000000020001")
SOURCE_DEFAULT_TENANT_ID = UUID("00000000-0000-4000-8000-000000020002")
SOURCE_BOUNDARY_ID = UUID("00000000-0000-4000-8000-000000020003")
SOURCE_TOO_LONG_ID = UUID("00000000-0000-4000-8000-000000020004")
SOURCE_BAD_HASH_ID = UUID("00000000-0000-4000-8000-000000020005")
SOURCE_CROSS_TENANT_ID = UUID("00000000-0000-4000-8000-000000020006")
# F-S10B0-R1-003 + R1-004 fix: additional negative IDs
SOURCE_EMPTY_URL_ID = UUID("00000000-0000-4000-8000-000000020007")
SOURCE_HASH_TOO_SHORT_ID = UUID("00000000-0000-4000-8000-000000020008")
SOURCE_HASH_TOO_LONG_ID = UUID("00000000-0000-4000-8000-000000020009")
SOURCE_HASH_NON_HEX_ID = UUID("00000000-0000-4000-8000-00000002000a")
VALID_HASH_A = "a" * 64
VALID_HASH_B = "b" * 64
VALID_HASH_C = "c" * 64

ForeignKeySignature = tuple[str, tuple[str, ...], str, tuple[str, ...]]


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-evidence-source-tests",
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
            raise AssertionError("Evidence source model tests require a reachable test database.") from exc
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
        getattr(error.orig, "constraint_name", None)
        or getattr(getattr(error.orig, "__cause__", None), "constraint_name", None)
    )
    assert actual_constraint_name == constraint_name


async def _reset_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate evidence_sources, tenants
            restart identity cascade
            """
        )
    )


async def _insert_tenant_one(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (1, 'tenant-one', '{"rls_ready": true}'::jsonb)
            """
        )
    )


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


async def _foreign_key_signatures(
    session: AsyncSession,
    table_names: frozenset[str],
) -> set[ForeignKeySignature]:
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
        {"table_names": sorted(table_names)},
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


def _url_of_length(prefix: str, length: int, fill: str) -> str:
    assert len(prefix) <= length
    return prefix + (fill * (length - len(prefix)))


def test_evidence_source_model_declares_expected_table_columns_and_types() -> None:
    table = EvidenceSource.__table__

    assert table.name == "evidence_sources"
    assert set(table.c.keys()) == {
        "id",
        "tenant_id",
        "canonical_url",
        "content_hash",
        "retrieved_at",
        "published_at",
        "metadata",
        "created_at",
        "updated_at",
    }

    assert isinstance(table.c.id.type, PG_UUID)
    assert isinstance(table.c.tenant_id.type, sa.BigInteger)
    assert isinstance(table.c.canonical_url.type, sa.Text)
    assert isinstance(table.c.content_hash.type, sa.Text)
    assert isinstance(table.c.retrieved_at.type, sa.DateTime)
    assert table.c.retrieved_at.type.timezone is True
    assert isinstance(table.c.published_at.type, sa.DateTime)
    assert table.c.published_at.type.timezone is True
    assert isinstance(table.c["metadata"].type, JSONB)
    assert isinstance(table.c.created_at.type, sa.DateTime)
    assert table.c.created_at.type.timezone is True
    assert isinstance(table.c.updated_at.type, sa.DateTime)
    assert table.c.updated_at.type.timezone is True

    constraint_names = {constraint.name for constraint in table.constraints}
    assert "evidence_sources_ck_canonical_url_length" in constraint_names
    assert "evidence_sources_ck_content_hash_sha256_hex" in constraint_names
    assert "evidence_sources_tenant_id_fkey" in constraint_names
    assert "evidence_sources_uq_tenant_id" in constraint_names
    assert "evidence_sources_uq_tenant_canonical_url" in constraint_names


@pytest.mark.asyncio
async def test_evidence_sources_schema_columns_constraints_and_foreign_keys(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    column_names = (
        "id",
        "tenant_id",
        "canonical_url",
        "content_hash",
        "retrieved_at",
        "published_at",
        "metadata",
        "created_at",
        "updated_at",
    )

    async with session_factory() as session:
        columns = await _table_columns(session, "evidence_sources", column_names)
        tenant_unique = await _constraint_columns(
            session,
            table_name="evidence_sources",
            constraint_name="evidence_sources_uq_tenant_id",
            constraint_type="u",
        )
        canonical_url_unique = await _constraint_columns(
            session,
            table_name="evidence_sources",
            constraint_name="evidence_sources_uq_tenant_canonical_url",
            constraint_type="u",
        )
        canonical_url_check = await _constraint_definition(
            session,
            table_name="evidence_sources",
            constraint_name="evidence_sources_ck_canonical_url_length",
        )
        content_hash_check = await _constraint_definition(
            session,
            table_name="evidence_sources",
            constraint_name="evidence_sources_ck_content_hash_sha256_hex",
        )
        foreign_keys = await _foreign_key_signatures(session, frozenset({"evidence_sources"}))

    assert set(columns) == set(column_names)
    assert columns["id"]["data_type"] == "uuid"
    assert columns["id"]["is_nullable"] == "NO"
    assert "uuid_generate_v4" in str(columns["id"]["column_default"])
    assert columns["tenant_id"]["data_type"] == "bigint"
    assert columns["tenant_id"]["is_nullable"] == "NO"
    assert columns["tenant_id"]["column_default"] == "1"
    assert columns["canonical_url"]["data_type"] == "text"
    assert columns["canonical_url"]["is_nullable"] == "NO"
    assert columns["content_hash"]["data_type"] == "text"
    assert columns["content_hash"]["is_nullable"] == "NO"
    assert columns["retrieved_at"]["data_type"] == "timestamp with time zone"
    assert columns["retrieved_at"]["is_nullable"] == "NO"
    assert columns["published_at"]["data_type"] == "timestamp with time zone"
    assert columns["published_at"]["is_nullable"] == "YES"
    assert columns["metadata"]["data_type"] == "jsonb"
    assert columns["metadata"]["is_nullable"] == "NO"
    assert "rls_ready" in str(columns["metadata"]["column_default"])
    assert columns["created_at"]["data_type"] == "timestamp with time zone"
    assert columns["created_at"]["is_nullable"] == "NO"
    assert columns["updated_at"]["data_type"] == "timestamp with time zone"
    assert columns["updated_at"]["is_nullable"] == "NO"

    assert tenant_unique == ("tenant_id", "id")
    assert canonical_url_unique == ("tenant_id", "canonical_url")
    assert "length(canonical_url)" in canonical_url_check
    assert "2000" in canonical_url_check
    assert "content_hash" in content_hash_check
    assert "[a-f0-9]{64}" in content_hash_check
    assert {("evidence_sources", ("tenant_id",), "tenants", ("id",))} <= foreign_keys


@pytest.mark.asyncio
async def test_evidence_sources_tenant_id_defaults_to_one(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_tenant_one(session)

        result = await session.execute(
            text(
                """
                insert into evidence_sources (
                  id, canonical_url, content_hash, retrieved_at
                )
                values (
                  :source_id, 'https://example.com/default-tenant', :content_hash,
                  timestamptz '2026-05-13 00:00:00+00'
                )
                returning tenant_id, metadata
                """
            ),
            {"source_id": SOURCE_DEFAULT_TENANT_ID, "content_hash": VALID_HASH_A},
        )
        row = result.mappings().one()
        await session.commit()

    assert row["tenant_id"] == 1
    metadata = row["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["rls_ready"] is True


@pytest.mark.asyncio
async def test_evidence_sources_canonical_url_length_boundary(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    boundary_url = _url_of_length("https://example.com/", 2000, "a")
    too_long_url = _url_of_length("https://too-long.example/", 2001, "b")

    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_tenant_one(session)

        await session.execute(
            text(
                """
                insert into evidence_sources (
                  id, tenant_id, canonical_url, content_hash, retrieved_at, metadata
                )
                values (
                  :source_id, 1, :canonical_url, :content_hash,
                  timestamptz '2026-05-13 00:00:00+00',
                  '{"rls_ready": true}'::jsonb
                )
                """
            ),
            {
                "source_id": SOURCE_BOUNDARY_ID,
                "canonical_url": boundary_url,
                "content_hash": VALID_HASH_A,
            },
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into evidence_sources (
                      id, tenant_id, canonical_url, content_hash, retrieved_at, metadata
                    )
                    values (
                      :source_id, 1, :canonical_url, :content_hash,
                      timestamptz '2026-05-13 00:00:00+00',
                      '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {
                    "source_id": SOURCE_TOO_LONG_ID,
                    "canonical_url": too_long_url,
                    "content_hash": VALID_HASH_B,
                },
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="evidence_sources_ck_canonical_url_length",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_evidence_sources_canonical_url_empty_string_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """F-S10B0-R1-003 fix: canonical_url length 1-2000 のうち下限 1 を runtime で固定。
    空文字 INSERT が evidence_sources_ck_canonical_url_length で reject されることを verify。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_tenant_one(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into evidence_sources (
                      id, tenant_id, canonical_url, content_hash, retrieved_at, metadata
                    )
                    values (
                      :source_id, 1, '', :content_hash,
                      timestamptz '2026-05-13 00:00:00+00',
                      '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {"source_id": SOURCE_EMPTY_URL_ID, "content_hash": VALID_HASH_A},
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="evidence_sources_ck_canonical_url_length",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_evidence_sources_content_hash_must_be_sha256_hex(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_tenant_one(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into evidence_sources (
                      id, tenant_id, canonical_url, content_hash, retrieved_at, metadata
                    )
                    values (
                      :source_id, 1, 'https://example.com/bad-hash', :content_hash,
                      timestamptz '2026-05-13 00:00:00+00',
                      '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {"source_id": SOURCE_BAD_HASH_ID, "content_hash": "A" * 64},
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="evidence_sources_ck_content_hash_sha256_hex",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_evidence_sources_content_hash_length_and_charset_negatives(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """F-S10B0-R1-004 fix: sha256 hex 64-char invariant の長さ + charset を分けて固定。
    63-char / 65-char / non-hex char ('g') の 3 ケースが全て
    evidence_sources_ck_content_hash_sha256_hex で reject されることを verify。
    """
    cases = [
        (SOURCE_HASH_TOO_SHORT_ID, "a" * 63, "https://example.com/hash-63"),
        (SOURCE_HASH_TOO_LONG_ID, "a" * 65, "https://example.com/hash-65"),
        (SOURCE_HASH_NON_HEX_ID, "g" * 64, "https://example.com/hash-nonhex"),
    ]

    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_tenant_one(session)
        await session.commit()

        for source_id, content_hash, canonical_url in cases:
            with pytest.raises(IntegrityError) as exc_info:
                await session.execute(
                    text(
                        """
                        insert into evidence_sources (
                          id, tenant_id, canonical_url, content_hash, retrieved_at, metadata
                        )
                        values (
                          :source_id, 1, :canonical_url, :content_hash,
                          timestamptz '2026-05-13 00:00:00+00',
                          '{"rls_ready": true}'::jsonb
                        )
                        """
                    ),
                    {
                        "source_id": source_id,
                        "content_hash": content_hash,
                        "canonical_url": canonical_url,
                    },
                )
                await session.commit()

            _assert_integrity_error(
                exc_info.value,
                sqlstate="23514",
                constraint_name="evidence_sources_ck_content_hash_sha256_hex",
            )
            await session.rollback()


@pytest.mark.asyncio
async def test_evidence_sources_cross_tenant_insert_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_tenant_one(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into evidence_sources (
                      id, tenant_id, canonical_url, content_hash, retrieved_at, metadata
                    )
                    values (
                      :source_id, 2, 'https://example.com/cross-tenant', :content_hash,
                      timestamptz '2026-05-13 00:00:00+00',
                      '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {"source_id": SOURCE_CROSS_TENANT_ID, "content_hash": VALID_HASH_C},
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="evidence_sources_tenant_id_fkey",
        )
        await session.rollback()
