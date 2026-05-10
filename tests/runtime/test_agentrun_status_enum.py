from __future__ import annotations

import ast
import asyncio
import os
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import get_args
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.domain.agent_runtime.status import (
    ALL_AGENT_RUN_STATUSES,
    ALL_BLOCKED_REASONS,
    TERMINAL_STATES,
    AgentRunStatus,
    BlockedReason,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_AGENT_RUNS_MIGRATION = _REPO_ROOT / "migrations" / "versions" / "0008_agent_runs_lifecycle.py"

ACTOR_ID = UUID("00000000-0000-4000-8000-000000004001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000004002")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000004003")
RUN_ID = UUID("00000000-0000-4000-8000-000000004004")


EXPECTED_AGENT_RUN_STATUSES = (
    "queued",
    "gathering_context",
    "running",
    "generated_artifact",
    "schema_validated",
    "policy_linted",
    "diff_ready",
    "waiting_approval",
    "blocked",
    "provider_refused",
    "provider_incomplete",
    "validation_failed",
    "repair_exhausted",
    "completed",
    "failed",
    "cancelled",
)

EXPECTED_TERMINAL_STATES = {
    "completed",
    "failed",
    "cancelled",
    "provider_refused",
    "repair_exhausted",
}

EXPECTED_BLOCKED_REASONS = (
    "policy_blocked",
    "budget_blocked",
    "runtime_blocked",
)


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-agentrun-status-tests",
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
            raise AssertionError("AgentRun status tests require a reachable test database.") from exc
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


def _call_keyword_string(node: ast.Call, keyword_name: str) -> str | None:
    for keyword in node.keywords:
        if (
            keyword.arg == keyword_name
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
        ):
            return keyword.value.value
    return None


def _check_constraint_values_from_migration(constraint_name: str) -> set[str]:
    module = ast.parse(_AGENT_RUNS_MIGRATION.read_text(encoding="utf-8"))

    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "CheckConstraint":
            continue
        if _call_keyword_string(node, "name") != constraint_name:
            continue
        if not node.args:
            raise AssertionError(f"{constraint_name} has no SQL expression.")

        expression_node = node.args[0]
        if not isinstance(expression_node, ast.Constant) or not isinstance(
            expression_node.value,
            str,
        ):
            raise AssertionError(f"{constraint_name} SQL expression must be a string literal.")

        return set(re.findall(r"'([^']+)'", expression_node.value))

    raise AssertionError(f"{constraint_name} was not found in 0008_agent_runs_lifecycle.py.")


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
        getattr(error.orig, 'constraint_name', None)
        or getattr(getattr(error.orig, '__cause__', None), 'constraint_name', None)
    )
    assert actual_constraint_name == constraint_name


async def _reset_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate
              agent_run_events,
              agent_runs,
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


async def _setup_project(session: AsyncSession) -> None:
    await _reset_tables(session)
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (1, 'tenant-one', '{"rls_ready": true}'::jsonb)
            """
        )
    )
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values (
              :actor_id, 1, 'human', 'human:agentrun-status',
              'AgentRun Status Actor', '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (
              :workspace_id, 1, 'runtime-workspace', 'runtime-workspace', :actor_id,
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (
              :project_id, 1, :workspace_id, 'runtime-project', 'runtime-project',
              'active', '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {"project_id": PROJECT_ID, "workspace_id": WORKSPACE_ID},
    )


async def _insert_agent_run(
    session: AsyncSession,
    *,
    run_id: UUID = RUN_ID,
    status: str,
    blocked_reason: str | None = None,
) -> None:
    await session.execute(
        text(
            """
            insert into agent_runs (
              id,
              tenant_id,
              project_id,
              status,
              blocked_reason
            )
            values (
              :run_id,
              1,
              :project_id,
              :status,
              :blocked_reason
            )
            """
        ),
        {
            "run_id": run_id,
            "project_id": PROJECT_ID,
            "status": status,
            "blocked_reason": blocked_reason,
        },
    )


def test_all_agent_run_statuses_match_literal_and_order() -> None:
    assert tuple(get_args(AgentRunStatus)) == ALL_AGENT_RUN_STATUSES
    assert ALL_AGENT_RUN_STATUSES == EXPECTED_AGENT_RUN_STATUSES


def test_terminal_states_match_five_terminal_states() -> None:
    assert TERMINAL_STATES == EXPECTED_TERMINAL_STATES


def test_db_status_check_constraint_matches_statuses() -> None:
    assert (
        _check_constraint_values_from_migration("agent_runs_ck_status")
        == set(ALL_AGENT_RUN_STATUSES)
    )


def test_blocked_reason_literal_matches_expected_values() -> None:
    assert tuple(get_args(BlockedReason)) == ALL_BLOCKED_REASONS
    assert ALL_BLOCKED_REASONS == EXPECTED_BLOCKED_REASONS


def test_db_blocked_reason_check_constraint_matches_reasons() -> None:
    assert (
        _check_constraint_values_from_migration("agent_runs_ck_blocked_reason")
        == set(ALL_BLOCKED_REASONS)
    )


@pytest.mark.asyncio
async def test_db_rejects_unknown_agent_run_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_project(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_agent_run(session, status="unknown")
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="agent_runs_ck_status",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_db_rejects_blocked_without_blocked_reason(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_project(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_agent_run(session, status="blocked", blocked_reason=None)
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="agent_runs_ck_blocked_reason_consistency",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_db_rejects_non_blocked_status_with_blocked_reason(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_project(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_agent_run(
                session,
                status="running",
                blocked_reason="policy_blocked",
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="agent_runs_ck_blocked_reason_consistency",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_agent_runs_accepts_running_with_null_blocked_reason(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_project(session)

        await _insert_agent_run(session, status="running", blocked_reason=None)
        await session.commit()

        row = (
            await session.execute(
                text(
                    """
                    select status, blocked_reason
                    from agent_runs
                    where tenant_id = 1 and id = :run_id
                    """
                ),
                {"run_id": RUN_ID},
            )
        ).one()
        values = row._mapping

        assert values["status"] == "running"
        assert values["blocked_reason"] is None


@pytest.mark.asyncio
async def test_agent_runs_rejects_unknown_blocked_reason(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_project(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_agent_run(
                session,
                status="blocked",
                blocked_reason="unknown_reason",
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="agent_runs_ck_blocked_reason",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_agent_runs_accepts_terminal_states_with_null_blocked_reason(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_project(session)

        run_ids: dict[str, UUID] = {}
        for terminal in sorted(TERMINAL_STATES):
            run_id = uuid4()
            run_ids[terminal] = run_id
            await _insert_agent_run(
                session,
                run_id=run_id,
                status=terminal,
                blocked_reason=None,
            )
        await session.commit()

        for terminal, run_id in run_ids.items():
            row = (
                await session.execute(
                    text(
                        """
                        select status, blocked_reason
                        from agent_runs
                        where tenant_id = 1 and id = :run_id
                        """
                    ),
                    {"run_id": run_id},
                )
            ).one()
            values = row._mapping

            assert values["status"] == terminal
            assert values["blocked_reason"] is None

