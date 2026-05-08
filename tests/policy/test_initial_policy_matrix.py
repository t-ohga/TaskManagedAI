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
from backend.app.domain.policy.action_class import (
    ALL_ACTION_CLASSES,
    P0_ALWAYS_DENIED,
    P0_CONDITIONAL,
    P0_FAIL_CLOSED,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_INITIAL_POLICY_VERSION = "2026-05-08-initial"


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-initial-policy-matrix-tests",
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
            raise AssertionError("Initial policy matrix tests require a reachable test database.") from exc
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


async def _initial_policy_matrix_rows(session: AsyncSession) -> list[dict[str, Any]]:
    result = await session.execute(
        text(
            """
            select
              tenant_id,
              action_class,
              effect,
              rule_json,
              policy_version,
              metadata
            from policy_rules
            where policy_version = :policy_version
            order by action_class
            """
        ),
        {"policy_version": _INITIAL_POLICY_VERSION},
    )
    return [dict(row) for row in result.mappings()]


def _rows_by_action_class(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows_by_action_class = {str(row["action_class"]): row for row in rows}
    assert len(rows_by_action_class) == len(rows)
    return rows_by_action_class


def _json_object(row: dict[str, Any], column_name: str) -> dict[str, Any]:
    value = row[column_name]
    assert isinstance(value, dict)
    return value


@pytest.mark.asyncio
async def test_initial_matrix_has_seven_action_classes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        rows = await _initial_policy_matrix_rows(session)

    assert len(rows) == 7
    assert {str(row["action_class"]) for row in rows} == set(ALL_ACTION_CLASSES)
    assert {str(row["policy_version"]) for row in rows} == {_INITIAL_POLICY_VERSION}


@pytest.mark.asyncio
async def test_merge_deploy_p0_always_deny(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        rows = await _initial_policy_matrix_rows(session)

    rows_by_action_class = _rows_by_action_class(rows)

    for action_class in P0_ALWAYS_DENIED:
        row = rows_by_action_class[action_class]
        rule_json = _json_object(row, "rule_json")

        assert row["effect"] == "deny"
        assert rule_json["reason_code"] == "p0_merge_deploy_disabled"
        assert rule_json["scope"] == "all"


@pytest.mark.asyncio
async def test_secret_access_provider_call_fail_closed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    expected_notes = {
        "secret_access": "Sprint 4 SecretBroker で fail-closed override",
        "provider_call": "Sprint 5 Provider Compliance で fail-closed override",
    }

    async with session_factory() as session:
        rows = await _initial_policy_matrix_rows(session)

    rows_by_action_class = _rows_by_action_class(rows)

    for action_class in P0_FAIL_CLOSED:
        row = rows_by_action_class[action_class]
        rule_json = _json_object(row, "rule_json")

        assert row["effect"] == "deny"
        assert rule_json["reason_code"] == "policy_matrix_default_deny"
        assert rule_json["scope"] == "default"
        assert rule_json["note"] == expected_notes[action_class]


@pytest.mark.asyncio
async def test_task_repo_pr_require_approval(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    expected_reason_codes = {
        "task_write": "task_write_requires_approval",
        "repo_write": "repo_write_requires_approval",
        "pr_open": "pr_open_requires_approval",
    }

    async with session_factory() as session:
        rows = await _initial_policy_matrix_rows(session)

    rows_by_action_class = _rows_by_action_class(rows)

    for action_class in P0_CONDITIONAL:
        row = rows_by_action_class[action_class]
        rule_json = _json_object(row, "rule_json")

        assert row["effect"] == "require_approval"
        assert rule_json["reason_code"] == expected_reason_codes[action_class]
        assert rule_json["scope"] == "default"


@pytest.mark.asyncio
async def test_initial_matrix_tenant_id_default(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        rows = await _initial_policy_matrix_rows(session)

    assert len(rows) == 7
    assert {int(row["tenant_id"]) for row in rows} == {1}


@pytest.mark.asyncio
async def test_initial_matrix_metadata_rls_ready(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        rows = await _initial_policy_matrix_rows(session)

    assert len(rows) == 7
    for row in rows:
        metadata = _json_object(row, "metadata")
        assert metadata["rls_ready"] is True

