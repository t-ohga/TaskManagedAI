"""SP-PHASE1 B5c: provider postflight generation CAS (ADR-00048 §G/A-4)。

``execute_provider_step`` は provider response 後、``record_provider_usage`` / artifact / status の **前** に
emergency-stop latch generation を再読し、preflight snapshot と不一致 (engage が割り込んだ) なら result を
discard/quarantine する (usage/artifact/status を進めず ``running -> blocked`` (runtime_blocked) へ confine)。

DB-gated: real DB の ``running`` production run + real latch + real ``transition_with_event`` で CAS branch を
検証する。compliance gate / provider は stub (CAS branch の単離検証、provider pipeline 全体の再 test は不要)。

- preflight None → postflight engaged (generation 出現) で discard。
- preflight gen=N → postflight gen=N+1 (engage→clear→engage cycle) で discard。
- generation 不変 (engage 無し) は通常進行 (generated_artifact)。
- discard 時 usage row が記録されない (課金/artifact/status を進めない)。

TASKHUB_DISABLE_KEYRING=1 + TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import backend.app.services.agent_runtime.orchestrator as orchestrator_mod
from backend.app.config import Settings, get_settings
from backend.app.db.models.agent_run import AgentRun
from backend.app.db.session import create_engine
from backend.app.domain.provider.compliance import ComplianceDecision
from backend.app.domain.provider.request import ProviderRequest
from backend.app.services.agent_runtime.orchestrator import AgentRunOrchestrator
from backend.app.services.providers.compliance_gate import ComplianceGate
from backend.app.services.providers.mock import MockProviderAdapter
from backend.app.services.superintendent.emergency_stop import EmergencyStopService

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

ACTOR_OWNER_1 = UUID("00000000-0000-4000-8000-0000000d7001")
WORKSPACE_1 = UUID("00000000-0000-4000-8000-0000000d7010")
PROJECT_1 = UUID("00000000-0000-4000-8000-0000000d7020")
RUN_ID = UUID("00000000-0000-4000-8000-0000000d7030")

_SCHEMA = {
    "type": "object",
    "required": ["answer"],
    "properties": {"answer": {"type": "string", "minLength": 1}},
    "additionalProperties": False,
}

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-provider-cas",
    )


def _run_alembic_upgrade(database_url: str) -> None:
    previous = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        command.upgrade(Config(str(_REPO_ROOT / "alembic.ini")), "head")
    finally:
        if previous is None:
            os.environ.pop("TASKMANAGEDAI_DATABASE_URL", None)
        else:
            os.environ["TASKMANAGEDAI_DATABASE_URL"] = previous
        get_settings.cache_clear()


async def _assert_database_available(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
    except (OSError, SQLAlchemyError, TimeoutError) as exc:
        raise AssertionError("provider CAS tests require PostgreSQL.") from exc
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


async def _reset(session: AsyncSession) -> None:
    await session.execute(
        text(
            "truncate superintendent_emergency_stops, "
            "agent_run_events, agent_runs, audit_events, projects, workspaces, "
            "actors, tenants restart identity cascade"
        )
    )
    await session.commit()


async def _seed(session: AsyncSession) -> None:
    await session.execute(
        text(
            "insert into tenants (id, name, metadata) values "
            "(1, 'tenant-one', '{\"rls_ready\": true}'::jsonb)"
        )
    )
    await session.execute(
        text(
            "insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata) "
            "values (:o1, 1, 'human', 'human:default', 'Owner1', '{\"rls_ready\": true}'::jsonb)"
        ),
        {"o1": ACTOR_OWNER_1},
    )
    await session.execute(
        text(
            "insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata) "
            "values (:w1, 1, 'ws1', 'ws1', :o1, '{\"rls_ready\": true}'::jsonb)"
        ),
        {"w1": WORKSPACE_1, "o1": ACTOR_OWNER_1},
    )
    await session.execute(
        text(
            "insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata) "
            "values (:p1, 1, :w1, 'p1', 'p1', 'active', '{\"rls_ready\": true}'::jsonb)"
        ),
        {"p1": PROJECT_1, "w1": WORKSPACE_1},
    )
    await session.commit()


async def _make_running_run(session: AsyncSession) -> None:
    """``running`` production run を作る (engage と独立、CAS branch は in-flight run を模す)。

    engaged テストでは latch engage **後** に本 run を作ることで、engage の block 対象にせず run を
    ``running`` に保つ (= provider call 中に engage が割り込んだ in-flight run の状態を模す)。
    """
    await session.execute(
        text(
            "insert into agent_runs (id, tenant_id, project_id, status, run_mode) "
            "values (:r, 1, :p, 'running', 'production')"
        ),
        {"r": RUN_ID, "p": PROJECT_1},
    )
    await session.commit()


def _allow_decision() -> ComplianceDecision:
    return ComplianceDecision.model_validate(
        {
            "decision": "allow",
            "reason_code": "allow",
            "allowed_data_class": "internal",
            "effective_allowed_data_class": "internal",
            "payload_data_class": "internal",
            "provider_compliance_matrix_version": "pcm-v1",
        }
    )


def _request() -> ProviderRequest:
    return ProviderRequest.model_validate(
        {
            "tenant_id": 1,
            "run_id": RUN_ID,
            "provider": "mock",
            "api_or_feature": "mock",
            "model_resolved": "mock-model",
            "messages": [{"role": "user", "content": "hello"}],
            "structured_output_schema": _SCHEMA,
            "payload_data_class": "internal",
            "provider_compliance_matrix_version": "pcm-v1",
            "max_tokens": 256,
            "temperature": 0,
            "safety_settings": {"mode": "deterministic"},
        }
    )


def _orchestrator(session: AsyncSession) -> AgentRunOrchestrator:
    # compliance gate は allow を返す stub (preflight 自体は別 test で網羅、ここは CAS branch を単離)。
    gate = cast(ComplianceGate, SimpleNamespace(evaluate=lambda _request: _allow_decision()))
    return AgentRunOrchestrator(
        session=session,
        compliance_gate=gate,
        provider=MockProviderAdapter(),
    )


async def _load_run(session: AsyncSession) -> AgentRun:
    run = await session.get(AgentRun, RUN_ID)
    assert run is not None
    return run


async def _accumulated_tokens(session: AsyncSession) -> int:
    """run に集計された token (discard 時は record_provider_usage を呼ばないため 0/NULL)。"""
    row = (
        await session.execute(
            text(
                "select coalesce(tokens_input, 0) + coalesce(tokens_output, 0) "
                "from agent_runs where id = :r"
            ),
            {"r": RUN_ID},
        )
    ).scalar_one()
    return int(row or 0)


@pytest.mark.asyncio
async def test_cas_discards_when_latch_engaged_during_call(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """preflight None → postflight engaged で result discard (usage/artifact/status を進めない)。"""
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        # latch を engage (run はまだ無い = block 0 件)。postflight 再読で active generation が出る。
        await EmergencyStopService(session).engage(
            tenant_id=1, operator_actor_id=ACTOR_OWNER_1
        )
        await session.commit()
        # engage **後** に running run を作る (engage の block 対象にせず in-flight running を保つ)。
        await _make_running_run(session)

    # preflight snapshot を None に固定し、postflight は real DB (engaged generation) を読ませる。
    real_read = orchestrator_mod._read_emergency_stop_generation
    state = {"first": True}

    async def _fake_read(session: AsyncSession, tenant_id: int) -> int | None:
        if state["first"]:
            state["first"] = False
            return None  # preflight: 「engage 前」を模す
        return await real_read(session, tenant_id)  # postflight: real engaged generation

    monkeypatch.setattr(orchestrator_mod, "_read_emergency_stop_generation", _fake_read)

    async with session_factory() as session:
        run = await _load_run(session)
        result = await _orchestrator(session).execute_provider_step(
            run=run, request=_request(), actor_id=ACTOR_OWNER_1
        )
        await session.commit()

    assert result.outcome == "discarded_emergency_stop"
    assert result.to_state == "blocked"
    assert result.blocked_reason == "runtime_blocked"

    async with session_factory() as session:
        run = await _load_run(session)
        assert run.status == "blocked"
        assert run.blocked_reason == "runtime_blocked"
        # usage が記録されていない (課金/artifact/status を進めない)。
        assert await _accumulated_tokens(session) == 0
        ev = (
            await session.execute(
                text(
                    "select event_payload::text from agent_run_events "
                    "where run_id = :r and event_type = 'runtime_blocked' order by seq_no desc limit 1"
                ),
                {"r": RUN_ID},
            )
        ).scalar_one()
        assert "emergency_stop_engaged" in ev


@pytest.mark.asyncio
async def test_cas_allows_when_generation_unchanged(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """engage 無し (preflight==postflight==None) は通常進行 (generated_artifact、usage 記録)。"""
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        await _make_running_run(session)

    async with session_factory() as session:
        run = await _load_run(session)
        result = await _orchestrator(session).execute_provider_step(
            run=run, request=_request(), actor_id=ACTOR_OWNER_1
        )
        await session.commit()

    assert result.outcome == "generated_artifact"
    assert result.to_state == "generated_artifact"

    async with session_factory() as session:
        run = await _load_run(session)
        assert run.status == "generated_artifact"
        # 通常進行では usage (token) が集計される。
        assert await _accumulated_tokens(session) >= 1


@pytest.mark.asyncio
async def test_cas_discards_on_generation_bump_cycle(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """preflight gen=N → postflight gen=N+1 (engage→clear→engage) でも discard する。"""
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)

    real_read = orchestrator_mod._read_emergency_stop_generation
    state = {"first": True}

    async def _fake_read(session: AsyncSession, tenant_id: int) -> int | None:
        if state["first"]:
            state["first"] = False
            return 1  # preflight: generation=1 を模す
        return await real_read(session, tenant_id)  # postflight: real (gen=2)

    monkeypatch.setattr(orchestrator_mod, "_read_emergency_stop_generation", _fake_read)

    # 実 latch を gen=2 にする (engage→clear→engage)。
    async with session_factory() as session:
        svc = EmergencyStopService(session)
        g1 = await svc.engage(tenant_id=1, operator_actor_id=ACTOR_OWNER_1)
        await session.commit()
    async with session_factory() as session:
        await EmergencyStopService(session).clear(
            tenant_id=1, operator_actor_id=ACTOR_OWNER_1, expected_generation=g1.generation
        )
        await session.commit()
    async with session_factory() as session:
        g2 = await EmergencyStopService(session).engage(
            tenant_id=1, operator_actor_id=ACTOR_OWNER_1
        )
        await session.commit()
        # engage 後に running run を作る (block 対象にしない)。
        await _make_running_run(session)
    assert g2.generation == 2

    async with session_factory() as session:
        run = await _load_run(session)
        result = await _orchestrator(session).execute_provider_step(
            run=run, request=_request(), actor_id=ACTOR_OWNER_1
        )
        await session.commit()

    assert result.outcome == "discarded_emergency_stop"
    async with session_factory() as session:
        assert await _accumulated_tokens(session) == 0


@pytest.mark.asyncio
async def test_cas_discards_gracefully_when_run_already_blocked_by_concurrent_engage(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """adversarial LOW-4: concurrent engage が既に run を blocked にした場合、CAS discard は status-guarded
    0-row transition を ungraceful ValueError にせず benign discard で graceful return する。

    postflight read 時点で別 session が run を ``running -> blocked`` へ遷移済 (concurrent engage の
    block-source 経路を模す)。CAS branch の ``transition_with_event(status == 'running')`` は 0-row →
    ValueError になるが、held lock 下の status 再読で blocked を確認し discard 扱い (二重 block しない)。
    """
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        # latch engage 後に running run を作る (block 対象にせず in-flight を保つ)。
        await EmergencyStopService(session).engage(
            tenant_id=1, operator_actor_id=ACTOR_OWNER_1
        )
        await session.commit()
        await _make_running_run(session)

    real_read = orchestrator_mod._read_emergency_stop_generation
    state = {"first": True}

    async def _fake_read(session: AsyncSession, tenant_id: int) -> int | None:
        if state["first"]:
            state["first"] = False
            return None  # preflight: 「engage 前」を模す
        # postflight: concurrent engage が既に本 run を blocked へ遷移済の状態を模す (別 session で flip)。
        async with session_factory() as other:
            await other.execute(
                text(
                    "update agent_runs set status = 'blocked', blocked_reason = 'runtime_blocked' "
                    "where id = :r and status = 'running'"
                ),
                {"r": RUN_ID},
            )
            await other.commit()
        return await real_read(session, tenant_id)  # real engaged generation (preflight None と不一致)

    monkeypatch.setattr(orchestrator_mod, "_read_emergency_stop_generation", _fake_read)

    async with session_factory() as session:
        run = await _load_run(session)
        # graceful discard: ValueError を surface させない。
        result = await _orchestrator(session).execute_provider_step(
            run=run, request=_request(), actor_id=ACTOR_OWNER_1
        )
        await session.commit()

    assert result.outcome == "discarded_emergency_stop"
    assert result.to_state == "blocked"
    assert result.blocked_reason == "runtime_blocked"
    assert result.event is None  # 新規 event は積まない (engage 側が emergency_stop event を残す)。

    async with session_factory() as session:
        run = await _load_run(session)
        assert run.status == "blocked"
        # usage を進めない (discard)。
        assert await _accumulated_tokens(session) == 0
