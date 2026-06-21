from __future__ import annotations

import ast
import asyncio
import json
import os
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, get_args
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.agent_run import AgentRun
from backend.app.db.session import create_engine
from backend.app.domain.agent_runtime.event_type import (
    ALL_AGENT_RUN_EVENT_TYPES,
    AgentRunEventType,
)
from backend.app.repositories.agent_run_event import AgentRunEventRepository, append_event
from backend.app.services.agent_runtime.event_log import transition_with_event

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_AGENT_RUNS_MIGRATION = _REPO_ROOT / "migrations" / "versions" / "0008_agent_runs_lifecycle.py"
_EVENT_TYPE_25_MIGRATION = (
    _REPO_ROOT / "migrations" / "versions" / "0011_trust_level_event_25.py"
)
_EVENT_TYPE_28_MIGRATION = (
    _REPO_ROOT / "migrations" / "versions" / "0013_cli_event_type_28.py"
)
_EVENT_TYPE_37_MIGRATION = (
    _REPO_ROOT / "migrations" / "versions" / "0025_sp014_event_type_37.py"
)
_EVENT_TYPE_39_MIGRATION = (
    _REPO_ROOT / "migrations" / "versions" / "0051_phase1_event_type_39.py"
)

ACTOR_ID = UUID("00000000-0000-4000-8000-000000005001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000005002")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000005003")
RUN_ID = UUID("00000000-0000-4000-8000-000000005004")

EXPECTED_AGENT_RUN_EVENT_TYPES = (
    "run_queued",
    "context_gathered",
    "provider_requested",
    "provider_responded",
    "artifact_generated",
    "schema_validated",
    "validation_failed",
    "repair_retry_scheduled",
    "policy_linted",
    "policy_blocked",
    "budget_blocked",
    "runtime_blocked",
    "diff_ready",
    "approval_requested",
    "approval_decided",
    "runner_started",
    "runner_completed",
    "runner_blocked",
    "repo_pr_opened",
    "run_completed",
    "run_failed",
    "run_cancelled",
    "repair_exhausted",
    "trust_level_promoted",
    "trust_level_promotion_denied",
    "cli_invocation_started",
    "cli_process_completed",
    "cli_decision_recorded",
    "orchestrator_dispatched",
    "orchestrator_lease_renewed",
    "orchestrator_lease_expired",
    "orchestrator_failover_triggered",
    "orchestrator_kill_engaged",
    "inter_agent_message_sent_ref",
    "inter_agent_message_consumed_ref",
    "tool_web_fetch_executed",
    "tool_docs_search_executed",
    # SP-PHASE1 B1 (ADR-00048 A-5): emergency-stop witnessing events (37 -> 39).
    "emergency_stop_engaged",
    "emergency_stop_resumed",
)


class _DummySession:
    pass


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-agent-run-event-tests",
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
            raise AssertionError("AgentRun event tests require a reachable test database.") from exc
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


def _module_string_constants(module: ast.Module) -> dict[str, str]:
    """Collect top-level ``_NAME = "..."`` string-typed assignments.

    Implicit string concatenation like ``("a" "b")`` collapses to a single
    ``ast.Constant`` during parse, so this helper handles both inline
    literals and module-level constants composed by adjacent strings.
    """

    result: dict[str, str] = {}
    for stmt in module.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            result[target.id] = stmt.value.value
    return result


def _coerce_string_argument(
    node: ast.expr,
    constants: dict[str, str],
) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id]
    return None


def _check_constraint_values_from_migration(
    constraint_name: str,
    migration_path: Path | None = None,
) -> set[str]:
    """Parse a migration file for a CHECK constraint's quoted enum literals.

    Supports two patterns in the same parser:
    - ``sa.CheckConstraint("event_type in (...)", name="...")`` (Sprint 1-4
      migration style, e.g. ``0008_agent_runs_lifecycle.py``).
    - ``op.create_check_constraint("name", "table", "event_type in (...)")``
      (Sprint 5.5 migration style, e.g. ``0011_trust_level_event_25.py``).
      The ``condition`` argument MAY be either an inline string literal or
      a reference to a module-level string constant.
    """

    target = migration_path if migration_path is not None else _AGENT_RUNS_MIGRATION
    module = ast.parse(target.read_text(encoding="utf-8"))
    constants = _module_string_constants(module)

    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue

        # Pattern A: sa.CheckConstraint(condition, name=name) [Sprint 1-4 style].
        if node.func.attr == "CheckConstraint":
            if _call_keyword_string(node, "name") != constraint_name:
                continue
            if not node.args:
                raise AssertionError(f"{constraint_name} has no SQL expression.")
            expression = _coerce_string_argument(node.args[0], constants)
            if expression is None:
                raise AssertionError(
                    f"{constraint_name} SQL expression must be a string literal "
                    "or module-level string constant."
                )
            return set(re.findall(r"'([^']+)'", expression))

        # Pattern B: op.create_check_constraint(name, table, condition) [Sprint 5.5+].
        if node.func.attr == "create_check_constraint":
            if len(node.args) < 3:
                continue
            name_arg = node.args[0]
            if not isinstance(name_arg, ast.Constant) or name_arg.value != constraint_name:
                continue
            condition = _coerce_string_argument(node.args[2], constants)
            if condition is None:
                raise AssertionError(
                    f"{constraint_name} create_check_constraint condition "
                    "must be a string literal or module-level string constant."
                )
            return set(re.findall(r"'([^']+)'", condition))

    raise AssertionError(
        f"{constraint_name} was not found in {target.name}."
    )


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


async def _setup_runtime_fixture(session: AsyncSession, *, run_status: str = "queued") -> None:
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
              :actor_id, 1, 'human', 'human:agentrun-event',
              'AgentRun Event Actor', '{"rls_ready": true}'::jsonb
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
              :workspace_id, 1, 'event-workspace', 'event-workspace', :actor_id,
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
              :project_id, 1, :workspace_id, 'event-project', 'event-project',
              'active', '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {"project_id": PROJECT_ID, "workspace_id": WORKSPACE_ID},
    )
    await session.execute(
        text(
            """
            insert into agent_runs (id, tenant_id, project_id, status)
            values (:run_id, 1, :project_id, :run_status)
            """
        ),
        {"run_id": RUN_ID, "project_id": PROJECT_ID, "run_status": run_status},
    )


async def _insert_raw_event(
    session: AsyncSession,
    *,
    run_id: UUID = RUN_ID,
    seq_no: int,
    event_type: str = "run_queued",
    idempotency_key: str | None = None,
    event_payload: dict[str, object] | None = None,
) -> None:
    await session.execute(
        text(
            """
            insert into agent_run_events (
              id,
              tenant_id,
              run_id,
              seq_no,
              event_type,
              event_payload,
              actor_id,
              idempotency_key
            )
            values (
              :event_id,
              1,
              :run_id,
              :seq_no,
              :event_type,
              cast(:event_payload as jsonb),
              :actor_id,
              :idempotency_key
            )
            """
        ),
        {
            "event_id": uuid4(),
            "run_id": run_id,
            "seq_no": seq_no,
            "event_type": event_type,
            "event_payload": json.dumps(event_payload or {"summary": "redacted"}),
            "actor_id": ACTOR_ID,
            "idempotency_key": idempotency_key,
        },
    )


async def _event_count(session: AsyncSession) -> int:
    result = await session.scalar(
        select(func.count()).select_from(text("agent_run_events")).where(text("tenant_id = 1"))
    )
    return int(result or 0)


async def _event_count_for_run(session: AsyncSession, run_id: UUID) -> int:
    result = await session.scalar(
        select(func.count())
        .select_from(text("agent_run_events"))
        .where(text("tenant_id = 1 and run_id = :run_id"))
        .params(run_id=run_id)
    )
    return int(result or 0)


async def _load_run(session: AsyncSession) -> AgentRun:
    run = await session.scalar(
        select(AgentRun).where(
            AgentRun.tenant_id == 1,
            AgentRun.id == RUN_ID,
        )
    )
    assert run is not None
    return run


def test_all_agent_run_event_types_match_literal_and_order() -> None:
    assert tuple(get_args(AgentRunEventType)) == ALL_AGENT_RUN_EVENT_TYPES
    assert ALL_AGENT_RUN_EVENT_TYPES == EXPECTED_AGENT_RUN_EVENT_TYPES


def test_db_event_type_check_constraint_matches_event_types() -> None:
    # SP-PHASE1 B1 (migration 0051) extends the CHECK from 37 -> 39
    # (emergency_stop_engaged / emergency_stop_resumed). The latest migration's
    # upgrade CHECK MUST exact-set match the Literal source of truth.
    assert (
        _check_constraint_values_from_migration(
            "agent_run_events_ck_event_type",
            _EVENT_TYPE_39_MIGRATION,
        )
        == set(ALL_AGENT_RUN_EVENT_TYPES)
    )


def test_migration_0013_supersedes_0011_for_cli_events() -> None:
    """Sprint 6 batch 2 では 25 → 28 を additive 拡張するため、cli_* events は
    0013 にのみ登場し、0011 には登場しないことを fail-fast で確認する。"""

    cli_events = {
        "cli_invocation_started",
        "cli_process_completed",
        "cli_decision_recorded",
    }
    migration_0011 = _EVENT_TYPE_25_MIGRATION.read_text(encoding="utf-8")
    migration_0013 = _EVENT_TYPE_28_MIGRATION.read_text(encoding="utf-8")
    for ev in cli_events:
        assert f"'{ev}'" not in migration_0011
        assert f"'{ev}'" in migration_0013


def test_migration_and_repository_prohibited_keys_match() -> None:
    """R3-F-003 (R4): migration 0008 と repository の denylist が完全一致。"""

    from backend.app.repositories.agent_run_event import _PROHIBITED_PAYLOAD_KEYS

    migration = _AGENT_RUNS_MIGRATION.read_text(encoding="utf-8")
    match = re.search(
        r"_PROHIBITED_EVENT_PAYLOAD_KEYS:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\((.+?)\)",
        migration,
        re.DOTALL,
    )
    assert match, "migration の _PROHIBITED_EVENT_PAYLOAD_KEYS 不在"
    migration_keys = set(re.findall(r'"([a-z_]+)"', match.group(1)))
    assert migration_keys == _PROHIBITED_PAYLOAD_KEYS, (
        f"drift: migration={sorted(migration_keys)}, "
        f"repository={sorted(_PROHIBITED_PAYLOAD_KEYS)}"
    )


@pytest.mark.asyncio
async def test_agent_run_event_repository_is_append_only() -> None:
    repo = AgentRunEventRepository(_DummySession())  # type: ignore[arg-type]

    with pytest.raises(NotImplementedError, match="append-only"):
        await repo.update(tenant_id=1, id=uuid4(), payload={})

    with pytest.raises(NotImplementedError, match="append-only"):
        await repo.delete(tenant_id=1, id=uuid4())

    with pytest.raises(NotImplementedError, match="statement_for_update"):
        repo.statement_for_update(tenant_id=1, id=uuid4(), payload={})

    with pytest.raises(NotImplementedError, match="statement_for_delete"):
        repo.statement_for_delete(tenant_id=1, id=uuid4())


@pytest.mark.asyncio
async def test_seq_no_unique_constraint_rejects_duplicate_seq_no(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await _insert_raw_event(session, seq_no=1)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_raw_event(session, seq_no=1)
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23505",
            constraint_name="agent_run_events_uq_tenant_run_seq_no",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_concurrent_append_with_same_expected_previous_seq_requires_retry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await session.commit()

    async def append_once(label: str) -> tuple[str, int | str]:
        async with session_factory() as session:
            repo = AgentRunEventRepository(session)
            try:
                event = await repo.append_event(
                    tenant_id=1,
                    run_id=RUN_ID,
                    event_type="run_queued",
                    event_payload={"summary": f"append {label}"},
                    actor_id=ACTOR_ID,
                    expected_previous_seq_no=0,
                )
                await session.commit()
                return ("ok", event.seq_no)
            except (IntegrityError, ValueError) as exc:
                await session.rollback()
                return ("retry", type(exc).__name__)

    results = await asyncio.gather(append_once("a"), append_once("b"))

    assert sorted(result[0] for result in results) == ["ok", "retry"]
    assert [result[1] for result in results if result[0] == "ok"] == [1]

    async with session_factory() as session:
        assert await _event_count(session) == 1


@pytest.mark.asyncio
async def test_idempotency_key_unique_constraint_rejects_duplicate_key(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await _insert_raw_event(session, seq_no=1, idempotency_key="same-operation")
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_raw_event(
                session,
                seq_no=2,
                event_type="context_gathered",
                idempotency_key="same-operation",
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23505",
            constraint_name="agent_run_events_uq_tenant_run_idempotency_key",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_null_idempotency_key_can_repeat(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await _insert_raw_event(session, seq_no=1, idempotency_key=None)
        await _insert_raw_event(
            session,
            seq_no=2,
            event_type="context_gathered",
            idempotency_key=None,
        )
        await session.commit()

        assert await _event_count(session) == 2


@pytest.mark.asyncio
async def test_transition_with_event_updates_status_and_appends_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await session.commit()
        run = await _load_run(session)

        event = await transition_with_event(
            session,
            tenant_id=1,
            run=run,
            to_state="gathering_context",
            event_type="context_gathered",
            payload={"summary": "context snapshot created"},
            actor_id=ACTOR_ID,
        )
        await session.commit()

        assert run.status == "gathering_context"
        assert event.seq_no == 1
        assert event.event_type == "context_gathered"
        assert await _event_count(session) == 1


@pytest.mark.asyncio
async def test_transition_with_event_rolls_back_status_update_when_event_append_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await _insert_raw_event(session, seq_no=1, idempotency_key="same-operation")
        await session.commit()
        run = await _load_run(session)

        with pytest.raises(IntegrityError):
            await transition_with_event(
                session,
                tenant_id=1,
                run=run,
                to_state="gathering_context",
                event_type="context_gathered",
                payload={"summary": "duplicate idempotency key"},
                actor_id=ACTOR_ID,
                idempotency_key="same-operation",
                expected_previous_seq_no=1,
            )
            await session.commit()

        await session.rollback()
        reloaded = await _load_run(session)

        assert reloaded.status == "queued"
        assert await _event_count(session) == 1


@pytest.mark.asyncio
async def test_transition_with_event_rolls_back_event_when_status_update_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session, run_status="running")
        await session.commit()
        run = await _load_run(session)
        initial_status = run.status
        initial_event_count = await _event_count_for_run(session, RUN_ID)
        await session.commit()

        with pytest.raises((IntegrityError, ValueError)):
            async with session.begin():
                await transition_with_event(
                    session,
                    tenant_id=1,
                    run=run,
                    to_state="blocked",
                    event_type="policy_blocked",
                    actor_id=ACTOR_ID,
                    payload={"summary": "test"},
                    blocked_reason=None,
                )

        await session.refresh(run)
        assert run.status == initial_status
        final_event_count = await _event_count_for_run(session, RUN_ID)
        assert final_event_count == initial_event_count


@pytest.mark.asyncio
async def test_transition_with_event_rejects_event_type_transition_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await session.commit()
        run = await _load_run(session)
        initial_status = run.status
        initial_event_count = await _event_count_for_run(session, RUN_ID)
        await session.commit()

        with pytest.raises(ValueError, match="event_type.*not allowed"):
            async with session.begin():
                await transition_with_event(
                    session,
                    tenant_id=1,
                    run=run,
                    to_state="gathering_context",
                    event_type="run_failed",
                    actor_id=ACTOR_ID,
                    payload={},
                )

        await session.refresh(run)
        assert run.status == initial_status
        final_event_count = await _event_count_for_run(session, RUN_ID)
        assert final_event_count == initial_event_count


@pytest.mark.asyncio
async def test_transition_with_event_rejects_blocked_without_reason(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session, run_status="running")
        await session.commit()
        run = await _load_run(session)
        await session.commit()

        with pytest.raises(ValueError, match="blocked_reason required"):
            async with session.begin():
                await transition_with_event(
                    session,
                    tenant_id=1,
                    run=run,
                    to_state="blocked",
                    event_type="policy_blocked",
                    actor_id=ACTOR_ID,
                    payload={},
                    blocked_reason=None,
                )


@pytest.mark.asyncio
async def test_transition_with_event_rejects_blocked_event_reason_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """R3-F-002 (R4): event_type='policy_blocked' で blocked_reason='budget_blocked' は reject。"""

    async with session_factory() as session:
        await _setup_runtime_fixture(session, run_status="running")
        await session.commit()
        run = await _load_run(session)
        initial_event_count = await _event_count_for_run(session, RUN_ID)
        await session.commit()

        with pytest.raises(ValueError, match="event_type.*requires blocked_reason"):
            async with session.begin():
                await transition_with_event(
                    session,
                    tenant_id=1,
                    run=run,
                    to_state="blocked",
                    event_type="policy_blocked",
                    blocked_reason="budget_blocked",
                    actor_id=ACTOR_ID,
                    payload={},
                )

        await session.refresh(run)
        assert run.status == "running"
        assert await _event_count_for_run(session, RUN_ID) == initial_event_count


@pytest.mark.asyncio
async def test_transition_with_event_accepts_blocked_event_reason_match(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """R3-F-002 (R4): event_type と blocked_reason が一致した場合 transition 成功。"""

    async with session_factory() as session:
        await _setup_runtime_fixture(session, run_status="running")
        await session.commit()
        run = await _load_run(session)
        await session.commit()

        async with session.begin():
            await transition_with_event(
                session,
                tenant_id=1,
                run=run,
                to_state="blocked",
                event_type="policy_blocked",
                blocked_reason="policy_blocked",
                actor_id=ACTOR_ID,
                payload={},
            )

        await session.refresh(run)
        assert run.status == "blocked"
        assert run.blocked_reason == "policy_blocked"


@pytest.mark.asyncio
async def test_transition_with_event_rejects_non_blocked_with_reason(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session, run_status="running")
        await session.commit()
        run = await _load_run(session)
        initial_event_count = await _event_count_for_run(session, RUN_ID)
        await session.commit()

        with pytest.raises(ValueError, match="blocked_reason must be None"):
            async with session.begin():
                await transition_with_event(
                    session,
                    tenant_id=1,
                    run=run,
                    to_state="completed",
                    event_type="run_completed",
                    actor_id=ACTOR_ID,
                    payload={},
                    blocked_reason="policy_blocked",
                )

        final_event_count = await _event_count_for_run(session, RUN_ID)
        assert final_event_count == initial_event_count


@pytest.mark.asyncio
async def test_event_payload_contract_rejects_raw_secret_keys(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        repo = AgentRunEventRepository(session)

        safe_event = await repo.append_event(
            tenant_id=1,
            run_id=RUN_ID,
            event_type="run_queued",
            event_payload={"summary": "redacted", "secret_ref": "secret://opaque/reference"},
            actor_id=ACTOR_ID,
        )
        assert safe_event.seq_no == 1

        with pytest.raises(ValueError, match="prohibited payload key"):
            await repo.append_event(
                tenant_id=1,
                run_id=RUN_ID,
                event_type="context_gathered",
                event_payload={"secret_value": "redacted"},
                actor_id=ACTOR_ID,
            )


@pytest.mark.asyncio
async def test_append_event_rejects_raw_secret_pattern_in_payload_value(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)

        with pytest.raises(ValueError, match="raw secret"):
            await append_event(
                session,
                tenant_id=1,
                run_id=RUN_ID,
                event_type="run_queued",
                actor_id=ACTOR_ID,
                payload={"summary": "API key sk-abcdefghijklmnopqrstuvwxyz123"},
            )


@pytest.mark.asyncio
async def test_append_event_rejects_raw_secret_in_nested_value(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)

        with pytest.raises(ValueError, match="raw secret"):
            await append_event(
                session,
                tenant_id=1,
                run_id=RUN_ID,
                event_type="run_queued",
                actor_id=ACTOR_ID,
                payload={
                    "context": {
                        "items": [
                            {"label": "ok"},
                            {"label": "ghs_abcdefghijklmnopqrstuvwx"},
                        ]
                    }
                },
            )


@pytest.mark.asyncio
async def test_append_event_rejects_raw_secret_pattern_in_dict_key(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """R3-F-001 (R4): dict key に raw token pattern (sk-...) が入ると reject。"""

    async with session_factory() as session:
        await _setup_runtime_fixture(session)

        with pytest.raises(ValueError, match="raw secret pattern"):
            await append_event(
                session,
                tenant_id=1,
                run_id=RUN_ID,
                event_type="run_queued",
                actor_id=ACTOR_ID,
                payload={"sk-abcdefghijklmnopqrstuvwx": "value"},
            )


@pytest.mark.asyncio
async def test_append_event_rejects_prohibited_payload_key_recursive(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)

        with pytest.raises(ValueError, match="prohibited payload key"):
            await append_event(
                session,
                tenant_id=1,
                run_id=RUN_ID,
                event_type="run_queued",
                actor_id=ACTOR_ID,
                payload={"providers": {"openai": {"provider_key": "value"}}},
            )


@pytest.mark.asyncio
async def test_append_event_rejects_prohibited_key_in_nested_dict_key(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """R3-F-001 (R4): nested dict key に prohibited key (api_key) が入ると reject。"""

    async with session_factory() as session:
        await _setup_runtime_fixture(session)

        with pytest.raises(ValueError, match="prohibited key"):
            await append_event(
                session,
                tenant_id=1,
                run_id=RUN_ID,
                event_type="run_queued",
                actor_id=ACTOR_ID,
                payload={"providers": {"api_key": {"value": "x"}}},
            )


@pytest.mark.asyncio
async def test_append_event_rejects_cyclic_payload(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """R3-F-004 (R4): payload に循環参照があると ValueError ('cyclic')。"""

    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        cycle: dict[str, Any] = {"a": 1}
        cycle["self"] = cycle

        with pytest.raises(ValueError, match="cyclic"):
            await append_event(
                session,
                tenant_id=1,
                run_id=RUN_ID,
                event_type="run_queued",
                actor_id=ACTOR_ID,
                payload=cycle,
            )


@pytest.mark.asyncio
async def test_append_event_rejects_excessive_depth(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """R3-F-004 (R4): payload の depth が max_depth=32 超で ValueError。"""

    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        payload: dict[str, Any] = {"value": 0}
        for _ in range(40):
            payload = {"nested": payload}

        with pytest.raises(ValueError, match="max_depth"):
            await append_event(
                session,
                tenant_id=1,
                run_id=RUN_ID,
                event_type="run_queued",
                actor_id=ACTOR_ID,
                payload=payload,
            )
