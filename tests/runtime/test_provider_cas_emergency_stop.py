"""SP-PHASE1 B5c: provider CAS = monotonic generation history + preflight-active-fail (ADR-00048 §G/A-4)。

``execute_provider_step`` は emergency-stop latch を次の 2 段で CAS する (B5 adversarial P1-2/3/5 で
active-only 等価比較の 3 つの穴を解消した再設計):
- **preflight**: (a) latch が **currently active** なら provider.execute の前に ``EmergencyStopEngagedError``
  を raise (P1-2: latch 既 active での新規 provider call を構造的に防ぐ)。(b) ``max_generation_ever`` (G0)
  を snapshot。
- **postflight** (provider response 後、usage/artifact/status の前、同一 tenant advisory lock 下): latch が
  **currently active** なら、または ``max_generation_ever`` (G1) ``> G0`` なら → **discard** (usage/artifact/
  status を進めず ``running -> blocked`` (runtime_blocked) へ confine)。else 通常進行。

DB-gated: real DB の ``running`` production run + real latch + real ``transition_with_event`` で CAS branch を
検証する。compliance gate / provider は stub (CAS branch の単離検証、provider pipeline 全体の再 test は不要)。

カバーする race:
- P1-2: latch が step 開始時点で既に active → provider.execute 前に deny (新規 call させない)。
- P1-3: preflight (active なし、G0) 後・provider.execute 前に engage → postflight active あり / G1>G0 で discard。
- P1-5: call 中に engage→clear → active は preflight/postflight 共 None だが G1>G0 (cleared 行が MAX に残る)
  で discard (active-only 等価比較が見逃す穴を monotonic history で捕捉)。
- generation 不変 (engage 無し) は通常進行 (generated_artifact、usage 記録)。
- discard 時 usage row が記録されない (課金/artifact/status を進めない)。
- LOW-4: concurrent engage が既に run を block 済なら benign graceful discard (ungraceful ValueError 抑止)。

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
from backend.app.services.superintendent.emergency_stop import (
    EmergencyStopEngagedError,
    EmergencyStopService,
)

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
async def test_cas_p1_2_denies_when_latch_already_active_at_step_start(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """P1-2: latch が step 開始時点で既に active なら provider.execute の **前** に deny する。

    active-only 等価比較 (preflight==postflight==active gen) では discard されず provider call + usage/
    status が進行してしまう穴。preflight-active-fail で新規 provider call をさせない (新規課金を防ぐ)。
    """
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        # latch を engage (active のまま)。その **後** に running run を作る (block 対象にしない)。
        await EmergencyStopService(session).engage(
            tenant_id=1, operator_actor_id=ACTOR_OWNER_1
        )
        await session.commit()
        await _make_running_run(session)

    async with session_factory() as session:
        run = await _load_run(session)
        # latch 既 active → provider.execute 前に EmergencyStopEngagedError (新規 call させない)。
        with pytest.raises(EmergencyStopEngagedError):
            await _orchestrator(session).execute_provider_step(
                run=run, request=_request(), actor_id=ACTOR_OWNER_1
            )
        await session.rollback()

    async with session_factory() as session:
        # run は CAS が触らず running のまま (block は engage block-source が別途行う。本 test は
        # engage 後に run を作っているため engage の block 対象外 = running を維持)。usage は記録なし。
        run = await _load_run(session)
        assert run.status == "running"
        assert await _accumulated_tokens(session) == 0


@pytest.mark.asyncio
async def test_cas_p1_3_discards_when_engage_during_call(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-3: preflight (active なし、G0) 後・provider.execute 前に engage → postflight で discard。

    preflight active-check は None (engage 前) を返すので provider.execute へ進み、call window 中の engage
    で postflight active あり / G1>G0 → discard (usage/artifact/status を進めない)。
    """
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        await _make_running_run(session)

    # preflight 時点では engage 前 (active None / G0=0)。provider.execute の途中で engage が起きる状況を
    # 模すため、preflight active-check と G0 read は real (None / 0)、その後 real latch を engage する。
    real_active = orchestrator_mod._read_emergency_stop_generation
    real_max = orchestrator_mod._read_max_emergency_stop_generation
    active_calls = {"n": 0}

    async def _fake_active(session: AsyncSession, tenant_id: int) -> int | None:
        active_calls["n"] += 1
        if active_calls["n"] == 1:
            return None  # preflight active-check: engage 前。
        return await real_active(session, tenant_id)  # postflight: real engaged active gen。

    max_calls = {"n": 0}

    async def _fake_max(session: AsyncSession, tenant_id: int) -> int:
        max_calls["n"] += 1
        if max_calls["n"] == 1:
            # preflight G0 を読んだ「直後」に engage が割り込む状況を模す (G0=0 を返してから engage)。
            async with session_factory() as other:
                await EmergencyStopService(other).engage(
                    tenant_id=1, operator_actor_id=ACTOR_OWNER_1
                )
                await other.commit()
            return 0  # preflight G0 (engage 前の値)。
        return await real_max(session, tenant_id)  # postflight G1 (engage 済 = 1)。

    monkeypatch.setattr(orchestrator_mod, "_read_emergency_stop_generation", _fake_active)
    monkeypatch.setattr(orchestrator_mod, "_read_max_emergency_stop_generation", _fake_max)

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
        assert await _accumulated_tokens(session) == 0
        # discard の witness event: call window 中の engage が先に本 run を block 済なら engage 側の
        # ``emergency_stop_engaged`` event が残り、orchestrator の discard は already-blocked graceful path で
        # event=None (二重 event を積まない)。orchestrator が先に block した場合は ``runtime_blocked``
        # (reason_code=emergency_stop_engaged)。どちらの経路でも emergency-stop 由来の witness が 1 件残る。
        ev = (
            await session.execute(
                text(
                    "select event_type, event_payload::text from agent_run_events "
                    "where run_id = :r and event_type in ('runtime_blocked', 'emergency_stop_engaged') "
                    "order by seq_no desc limit 1"
                ),
                {"r": RUN_ID},
            )
        ).one()
        assert ev[0] == "emergency_stop_engaged" or "emergency_stop_engaged" in ev[1]


@pytest.mark.asyncio
async def test_cas_p1_5_discards_on_engage_clear_cycle_during_call(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-5: call 中に engage→clear が起きると active は両端 None だが G1>G0 で discard する。

    active-only 等価比較 (None==None) は通してしまう穴。monotonic ``max_generation_ever`` は cleared 行を
    MAX に残すため、engage→clear で G が +1 され G1>G0 → discard できる (cleared 行が history を保持)。
    """
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        await _make_running_run(session)

    real_active = orchestrator_mod._read_emergency_stop_generation
    real_max = orchestrator_mod._read_max_emergency_stop_generation
    max_calls = {"n": 0}

    async def _fake_max(session: AsyncSession, tenant_id: int) -> int:
        max_calls["n"] += 1
        if max_calls["n"] == 1:
            # preflight G0 を読んだ「直後」に engage→clear cycle が割り込む状況を模す。
            async with session_factory() as other:
                svc = EmergencyStopService(other)
                g = await svc.engage(tenant_id=1, operator_actor_id=ACTOR_OWNER_1)
                await other.commit()
            async with session_factory() as other:
                await EmergencyStopService(other).clear(
                    tenant_id=1,
                    operator_actor_id=ACTOR_OWNER_1,
                    expected_generation=g.generation,
                )
                await other.commit()
            return 0  # preflight G0 (cycle 前)。
        return await real_max(session, tenant_id)  # postflight G1 (cleared 行に gen=1 が残る = 1)。

    monkeypatch.setattr(orchestrator_mod, "_read_emergency_stop_generation", real_active)
    monkeypatch.setattr(orchestrator_mod, "_read_max_emergency_stop_generation", _fake_max)

    async with session_factory() as session:
        run = await _load_run(session)
        result = await _orchestrator(session).execute_provider_step(
            run=run, request=_request(), actor_id=ACTOR_OWNER_1
        )
        await session.commit()

    # postflight active は None (clear 済) だが G1>G0 で discard する (active-only 比較が見逃す穴)。
    assert result.outcome == "discarded_emergency_stop"
    assert result.to_state == "blocked"
    assert result.blocked_reason == "runtime_blocked"

    async with session_factory() as session:
        run = await _load_run(session)
        assert run.status == "blocked"
        # postflight latch は cleared (active None) だが G1>G0 で確実に discard 済。
        assert await _accumulated_tokens(session) == 0


@pytest.mark.asyncio
async def test_cas_allows_when_no_engage_during_call(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """engage 無し (preflight active None / G0==G1) は通常進行 (generated_artifact、usage 記録)。"""
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
        await _make_running_run(session)

    real_active = orchestrator_mod._read_emergency_stop_generation
    real_max = orchestrator_mod._read_max_emergency_stop_generation
    max_calls = {"n": 0}

    async def _fake_max(session: AsyncSession, tenant_id: int) -> int:
        max_calls["n"] += 1
        if max_calls["n"] == 1:
            return 0  # preflight G0 (engage 前)。
        # postflight: concurrent engage が既に本 run を blocked へ遷移済の状態を模す (別 session で flip +
        # latch engage で G を bump)。
        async with session_factory() as other:
            await EmergencyStopService(other).engage(
                tenant_id=1, operator_actor_id=ACTOR_OWNER_1
            )
            await other.execute(
                text(
                    "update agent_runs set status = 'blocked', blocked_reason = 'runtime_blocked' "
                    "where id = :r and status = 'running'"
                ),
                {"r": RUN_ID},
            )
            await other.commit()
        return await real_max(session, tenant_id)  # postflight G1 (= 1 > G0)。

    # preflight active-check は engage 前なので None を返させる (real は flip 後に呼ばれ None でない可能性
    # があるため、active-check は preflight 1 回目のみ None 固定)。
    active_calls = {"n": 0}

    async def _fake_active(session: AsyncSession, tenant_id: int) -> int | None:
        active_calls["n"] += 1
        if active_calls["n"] == 1:
            return None  # preflight active-check: engage 前。
        return await real_active(session, tenant_id)

    monkeypatch.setattr(orchestrator_mod, "_read_emergency_stop_generation", _fake_active)
    monkeypatch.setattr(orchestrator_mod, "_read_max_emergency_stop_generation", _fake_max)

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
