from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

EVAL_TABLES = frozenset({"dataset_versions", "eval_runs", "eval_cases", "eval_scores"})
TENANT_1_DATASET_ID = UUID("00000000-0000-4000-8000-000000180001")
TENANT_2_DATASET_ID = UUID("00000000-0000-4000-8000-000000180002")
EVAL_RUN_ID = UUID("00000000-0000-4000-8000-000000180003")
EVAL_CASE_ID = UUID("00000000-0000-4000-8000-000000180004")
EVAL_SCORE_ID = UUID("00000000-0000-4000-8000-000000180005")


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-eval-schema-tests",
        ),
    )


def _run_alembic(database_url: str, direction: Literal["upgrade", "downgrade"], target: str) -> None:
    previous_database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()

    try:
        config = Config(str(_REPO_ROOT / "alembic.ini"))
        if direction == "upgrade":
            command.upgrade(config, target)
        else:
            command.downgrade(config, target)
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
            raise AssertionError("Eval schema migration tests require a reachable test database.") from exc
        pytest.skip("Set TASKMANAGEDAI_RUN_DB_TESTS=1 with test PostgreSQL running.")
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    settings = _integration_settings()
    await _assert_database_available(settings)
    await asyncio.to_thread(_run_alembic, settings.database_url, "upgrade", "head")

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


def _assert_integrity_error(error: IntegrityError, *, constraint_name: str) -> None:
    assert _sqlstate(error) == "23503"
    actual_constraint_name = (
        getattr(error.orig, "constraint_name", None)
        or getattr(getattr(error.orig, "__cause__", None), "constraint_name", None)
    )
    assert actual_constraint_name == constraint_name


def _inspect_eval_schema(sync_connection: Connection) -> dict[str, Any]:
    inspector = sa.inspect(sync_connection)
    return {
        "tables": set(inspector.get_table_names()),
        "indexes": {
            table_name: {
                str(index["name"]): tuple(str(column) for column in index["column_names"])
                for index in inspector.get_indexes(table_name)
            }
            for table_name in EVAL_TABLES
            if table_name in inspector.get_table_names()
        },
        "unique_constraints": {
            table_name: {
                str(constraint["name"]): tuple(str(column) for column in constraint["column_names"])
                for constraint in inspector.get_unique_constraints(table_name)
            }
            for table_name in EVAL_TABLES
            if table_name in inspector.get_table_names()
        },
        "foreign_keys": {
            table_name: {
                str(fk["name"]): (
                    tuple(str(column) for column in fk["constrained_columns"]),
                    str(fk["referred_table"]),
                    tuple(str(column) for column in fk["referred_columns"]),
                )
                for fk in inspector.get_foreign_keys(table_name)
            }
            for table_name in EVAL_TABLES
            if table_name in inspector.get_table_names()
        },
    }


async def _schema_snapshot(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    async with session_factory() as session:
        connection = await session.connection()
        return await connection.run_sync(_inspect_eval_schema)


async def _reset_eval_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate eval_scores, eval_cases, eval_runs, dataset_versions
            restart identity cascade
            """
        )
    )


async def _ensure_two_tenants(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values
              (1, 'tenant-one', '{"rls_ready": true}'::jsonb),
              (2, 'tenant-two', '{"rls_ready": true}'::jsonb)
            on conflict (id) do update set name = excluded.name
            """
        )
    )


@pytest.mark.asyncio
async def test_0018_upgrade_and_downgrade_create_and_drop_eval_tables(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = _integration_settings()

    try:
        await asyncio.to_thread(_run_alembic, settings.database_url, "downgrade", "0017_claims_evidence_items")
        downgraded = await _schema_snapshot(session_factory)
        assert EVAL_TABLES.isdisjoint(downgraded["tables"])

        await asyncio.to_thread(_run_alembic, settings.database_url, "upgrade", "head")
        upgraded = await _schema_snapshot(session_factory)
        assert EVAL_TABLES <= upgraded["tables"]

        assert upgraded["unique_constraints"]["dataset_versions"]["dataset_versions_uq_tenant_id"] == (
            "tenant_id",
            "id",
        )
        assert upgraded["unique_constraints"]["dataset_versions"]["dataset_versions_uq_tenant_dataset_key_version"] == (
            "tenant_id",
            "dataset_key",
            "version",
        )
        assert upgraded["unique_constraints"]["eval_runs"]["eval_runs_uq_tenant_id_dataset_version"] == (
            "tenant_id",
            "id",
            "dataset_version_id",
        )
        assert upgraded["unique_constraints"]["eval_cases"]["eval_cases_uq_tenant_id_dataset_version"] == (
            "tenant_id",
            "id",
            "dataset_version_id",
        )
        assert upgraded["unique_constraints"]["eval_scores"]["eval_scores_uq_tenant_run_case_metric"] == (
            "tenant_id",
            "eval_run_id",
            "eval_case_id",
            "metric_key",
        )

        assert upgraded["indexes"]["dataset_versions"]["dataset_versions_ix_tenant_kind_created"] == (
            "tenant_id",
            "fixture_kind",
            "created_at",
        )
        assert upgraded["indexes"]["eval_runs"]["eval_runs_ix_tenant_dataset_started"] == (
            "tenant_id",
            "dataset_version_id",
            "started_at",
        )
        assert upgraded["indexes"]["eval_cases"]["eval_cases_ix_tenant_dataset"] == (
            "tenant_id",
            "dataset_version_id",
        )
        assert upgraded["indexes"]["eval_scores"]["eval_scores_ix_tenant_run_metric"] == (
            "tenant_id",
            "eval_run_id",
            "metric_key",
        )

        assert upgraded["foreign_keys"]["eval_scores"]["eval_scores_eval_run_dataset_version_fkey"] == (
            ("tenant_id", "eval_run_id", "dataset_version_id"),
            "eval_runs",
            ("tenant_id", "id", "dataset_version_id"),
        )
        assert upgraded["foreign_keys"]["eval_scores"]["eval_scores_eval_case_dataset_version_fkey"] == (
            ("tenant_id", "eval_case_id", "dataset_version_id"),
            "eval_cases",
            ("tenant_id", "id", "dataset_version_id"),
        )

        await asyncio.to_thread(_run_alembic, settings.database_url, "downgrade", "0017_claims_evidence_items")
        downgraded_again = await _schema_snapshot(session_factory)
        assert EVAL_TABLES.isdisjoint(downgraded_again["tables"])
    finally:
        await asyncio.to_thread(_run_alembic, settings.database_url, "upgrade", "head")


@pytest.mark.asyncio
async def test_eval_runs_reject_cross_tenant_dataset_version_reference(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_eval_tables(session)
        await _ensure_two_tenants(session)
        await session.execute(
            text(
                """
                insert into dataset_versions (
                  id, tenant_id, dataset_key, version, fixture_kind, content_hash, metadata
                )
                values (
                  :dataset_id, 1, 'tenant_isolation', 'v2026.05.16',
                  'public_regression', :content_hash, '{"rls_ready": true}'::jsonb
                )
                """
            ),
            {"dataset_id": TENANT_1_DATASET_ID, "content_hash": "a" * 64},
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into eval_runs (
                      id, tenant_id, run_id, dataset_version_id, suite_name, provider, model, summary
                    )
                    values (
                      :eval_run_id, 2, null, :dataset_id, 'tenant_isolation',
                      'mock', 'mock-eval', '{}'::jsonb
                    )
                    """
                ),
                {"eval_run_id": EVAL_RUN_ID, "dataset_id": TENANT_1_DATASET_ID},
            )
            await session.commit()

        _assert_integrity_error(exc_info.value, constraint_name="eval_runs_dataset_version_fkey")
        await session.rollback()


@pytest.mark.asyncio
async def test_eval_scores_reject_run_case_dataset_version_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_eval_tables(session)
        await _ensure_two_tenants(session)
        await session.execute(
            text(
                """
                insert into dataset_versions (
                  id, tenant_id, dataset_key, version, fixture_kind, content_hash, metadata
                )
                values
                  (
                    :dataset_1_id, 1, 'tenant_isolation', 'v2026.05.16-run',
                    'public_regression', :content_hash_1, '{"rls_ready": true}'::jsonb
                  ),
                  (
                    :dataset_2_id, 1, 'tenant_isolation', 'v2026.05.16-case',
                    'public_regression', :content_hash_2, '{"rls_ready": true}'::jsonb
                  )
                """
            ),
            {
                "dataset_1_id": TENANT_1_DATASET_ID,
                "dataset_2_id": TENANT_2_DATASET_ID,
                "content_hash_1": "b" * 64,
                "content_hash_2": "c" * 64,
            },
        )
        await session.execute(
            text(
                """
                insert into eval_runs (
                  id, tenant_id, run_id, dataset_version_id, suite_name, provider, model, summary
                )
                values (
                  :eval_run_id, 1, null, :dataset_1_id, 'tenant_isolation',
                  'mock', 'mock-eval', '{}'::jsonb
                )
                """
            ),
            {"eval_run_id": EVAL_RUN_ID, "dataset_1_id": TENANT_1_DATASET_ID},
        )
        await session.execute(
            text(
                """
                insert into eval_cases (
                  id, tenant_id, dataset_version_id, case_key, case_json, expected_json, metadata
                )
                values (
                  :eval_case_id, 1, :dataset_2_id, 'cross_dataset_case',
                  '{"input": true}'::jsonb, '{"expected": true}'::jsonb,
                  '{"rls_ready": true}'::jsonb
                )
                """
            ),
            {"eval_case_id": EVAL_CASE_ID, "dataset_2_id": TENANT_2_DATASET_ID},
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into eval_scores (
                      id, tenant_id, eval_run_id, eval_case_id, dataset_version_id,
                      metric_key, score, passed, details
                    )
                    values (
                      :eval_score_id, 1, :eval_run_id, :eval_case_id, :dataset_1_id,
                      'tenant_isolation_negative_pass', 1.0, true, '{}'::jsonb
                    )
                    """
                ),
                {
                    "eval_score_id": EVAL_SCORE_ID,
                    "eval_run_id": EVAL_RUN_ID,
                    "eval_case_id": EVAL_CASE_ID,
                    "dataset_1_id": TENANT_1_DATASET_ID,
                },
            )
            await session.commit()

        _assert_integrity_error(exc_info.value, constraint_name="eval_scores_eval_case_dataset_version_fkey")
        await session.rollback()
