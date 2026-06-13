"""SP-004-5 (ADR-00057) AgentRun worker driver の DB-backed contract test。

実 PostgreSQL で worker driver の不変条件を固定する:
- end-to-end 駆動 (queued -> completed、Mock) + event timeline + ContextSnapshot(input)
  + Artifact + provenance fingerprint 一致 (F4)。
- atomic claim: 非 queued / production run は no-op (claim-miss、failed にしない、F3)。
- non-terminal closure: provider_incomplete -> 即 failed (running/repair_exhausted へ行かない、R3-F2)。
- cancel entrypoint 統一: bridge_run_cancel が run_cancelled event を append + status cancelled
  を実 DB に永続 (R2-F2 + R3-F1)。cancelled run の drive は no-op。
- enqueue fail-closed: bridge_run_create の enqueue 失敗で run を failed に終端化 (silent orphan
  禁止、R2-F1)。

DB 接続必要: TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container 起動時のみ実行。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.agent_run_event import AgentRunEvent
from backend.app.db.models.artifact import Artifact
from backend.app.db.models.context_snapshot import ContextSnapshot
from backend.app.db.session import create_engine
from backend.app.mcp import api_bridge
from backend.app.mcp.api_bridge import bridge_run_cancel, bridge_run_create, bridge_ticket_create
from backend.app.seeds.initial import (
    DEFAULT_PROJECT_ID,
    DEFAULT_TENANT_ID,
    seed_initial,
)
from backend.app.workers import agent_run_driver
from backend.app.workers.agent_run_driver import execute_agent_run

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)


def _integration_settings(*, shadow_mode_enabled: bool = True) -> Settings:
    return Settings(
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-sp0045",
        shadow_mode_enabled=shadow_mode_enabled,
    )


def _run_alembic(database_url: str, target: str) -> None:
    previous = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    config = Config(str(_REPO_ROOT / "alembic.ini"))
    try:
        command.upgrade(config, target)
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
        if os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") == "1":
            raise AssertionError("agent_run_driver DB test requires PostgreSQL.") from exc
        pytest.skip("Set TASKMANAGEDAI_RUN_DB_TESTS=1 with test PostgreSQL running.")
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    settings = _integration_settings()
    await _assert_database_available(settings)
    await asyncio.to_thread(_run_alembic, settings.database_url, "head")

    engine = create_engine(settings.database_url)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory.begin() as session:
        await session.execute(
            text("truncate tickets, agent_runs, mcp_idempotency_keys restart identity cascade")
        )
        await seed_initial(session)
        # projects は truncate されない共有行。prior test の archive 汚染を防ぐため active へ戻す。
        await session.execute(text("update projects set status = 'active'"))
    # driver は global AsyncSessionFactory で session を開くため test factory へ向ける。
    monkeypatch.setattr(agent_run_driver, "AsyncSessionFactory", factory)
    # shadow flag を on にする (bridge_run_create が shadow run を作れるように)。
    monkeypatch.setattr(api_bridge, "get_settings", lambda: _integration_settings())
    try:
        yield factory
    finally:
        await engine.dispose()


async def _create_ticket(factory: async_sessionmaker[AsyncSession]) -> str:
    async with factory() as session:
        result = await bridge_ticket_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            title=f"driver-target-{uuid4()}",
        )
    return str(result["ticket_id"])


async def _create_shadow_run(
    factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    *,
    run_mode: str = "shadow",
) -> str:
    """shadow/production run を作成する。enqueue は no-op にして redis 依存を避ける。"""

    async def _noop_enqueue(*, run_id: UUID, tenant_id: int) -> None:
        return None

    monkeypatch.setattr(api_bridge, "_enqueue_shadow_run", _noop_enqueue)
    ticket_id = await _create_ticket(factory)
    async with factory() as session:
        result = await bridge_run_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            ticket_id=ticket_id,
            purpose="driver test",
            run_mode=run_mode,
        )
    return str(result["run_id"])


# ---------------------------------------------------------------------------
# end-to-end 駆動 + provenance (F4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_driver_drives_shadow_run_to_completed(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = await _create_shadow_run(session_factory, monkeypatch)

    result = await execute_agent_run({}, run_id=run_id, tenant_id=DEFAULT_TENANT_ID)
    assert result["status"] == "completed"

    async with session_factory() as session:
        run = await session.scalar(select(AgentRun).where(AgentRun.id == UUID(run_id)))
        assert run is not None
        assert run.status == "completed"
        assert run.run_mode == "shadow"

        events = (
            await session.scalars(
                select(AgentRunEvent)
                .where(AgentRunEvent.run_id == UUID(run_id))
                .order_by(AgentRunEvent.seq_no)
            )
        ).all()
        timeline = [e.event_type for e in events]
        # run_queued (create) -> context_gathered -> provider_requested ->
        # provider_responded/artifact_generated -> schema_validated -> run_completed
        assert timeline[0] == "run_queued"
        assert "context_gathered" in timeline
        assert "provider_requested" in timeline
        assert "schema_validated" in timeline
        assert timeline[-1] == "run_completed"

        snapshot = await session.scalar(
            select(ContextSnapshot).where(
                ContextSnapshot.run_id == UUID(run_id),
                ContextSnapshot.snapshot_kind == "input",
            )
        )
        assert snapshot is not None
        # F4 (R1-A4): provenance — snapshot に格納した fingerprint hash が、driver が build した
        # ProviderRequest の canonical hash と **完全一致**する (driver は provider step 後に
        # ProviderResult.provider_request_fingerprint との等価も enforce 済 = run completed が証拠)。
        from backend.app.domain.provider.fingerprint import (
            compute_provider_request_fingerprint,
        )
        from backend.app.services.providers.matrix_loader import load_compliance_matrix
        from backend.app.workers.agent_run_driver import (
            _COMPLIANCE_MATRIX_PATH,
            _build_shadow_provider_request,
        )

        matrix = load_compliance_matrix(_COMPLIANCE_MATRIX_PATH)
        rebuilt = _build_shadow_provider_request(run, matrix.matrix_version)
        expected_fp = compute_provider_request_fingerprint(
            rebuilt, matrix_version=matrix.matrix_version
        )
        assert snapshot.provider_request_fingerprint["model_resolved"] == "mock-model"
        assert snapshot.provider_request_fingerprint["fingerprint_sha256"] == expected_fp

        artifact = await session.scalar(
            select(Artifact).where(Artifact.run_id == UUID(run_id))
        )
        assert artifact is not None
        assert artifact.payload_data_class == "internal"


# ---------------------------------------------------------------------------
# atomic claim: non-queued / production は no-op (F3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_driver_no_op_on_already_completed_run(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = await _create_shadow_run(session_factory, monkeypatch)
    first = await execute_agent_run({}, run_id=run_id, tenant_id=DEFAULT_TENANT_ID)
    assert first["status"] == "completed"

    # 二重 enqueue / crash 後 arq 再実行を模した再駆動 → claim-miss no-op (failed にしない)。
    second = await execute_agent_run({}, run_id=run_id, tenant_id=DEFAULT_TENANT_ID)
    assert second["status"] == "claim_miss"

    async with session_factory() as session:
        run = await session.scalar(select(AgentRun).where(AgentRun.id == UUID(run_id)))
        assert run is not None
        assert run.status == "completed"  # 再駆動で壊れていない


@pytest.mark.asyncio
async def test_driver_no_op_on_production_run(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = await _create_shadow_run(session_factory, monkeypatch, run_mode="production")
    result = await execute_agent_run({}, run_id=run_id, tenant_id=DEFAULT_TENANT_ID)
    assert result["status"] == "claim_miss"  # run_mode != shadow gate

    async with session_factory() as session:
        run = await session.scalar(select(AgentRun).where(AgentRun.id == UUID(run_id)))
        assert run is not None
        assert run.status == "queued"  # production は駆動されず queued 据置


# ---------------------------------------------------------------------------
# non-terminal closure: provider_incomplete -> 即 failed (R3-F2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_driver_provider_incomplete_closes_to_failed(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.domain.provider.fingerprint import compute_provider_request_fingerprint
    from backend.app.domain.provider.request import ProviderRequest
    from backend.app.domain.provider.result import ProviderResult, ProviderUsage

    class _IncompleteProvider:
        def provider_name(self) -> str:
            return "mock"

        def api_or_feature(self) -> str:
            return "mock"

        def execute(self, request: ProviderRequest) -> ProviderResult:
            # fingerprint は報告する api/sdk version と一致させる (driver の provenance 検証
            # は result 報告の api/sdk で再計算するため、実 adapter と同様 consistent にする)。
            return ProviderResult(
                status="incomplete",
                usage=ProviderUsage(tokens_input=12, tokens_output=4, cost_usd=0.0),
                model_resolved=request.model_resolved,
                api_version="mock-v1",
                sdk_version="mock-1.0",
                provider_request_fingerprint=compute_provider_request_fingerprint(
                    request,
                    matrix_version=request.provider_compliance_matrix_version,
                    api_version="mock-v1",
                    sdk_version="mock-1.0",
                ),
                redacted_response_summary={"mock_status": "incomplete"},
            )

    monkeypatch.setattr(agent_run_driver, "MockProviderAdapter", _IncompleteProvider)

    run_id = await _create_shadow_run(session_factory, monkeypatch)
    result = await execute_agent_run({}, run_id=run_id, tenant_id=DEFAULT_TENANT_ID)
    assert result["status"] == "failed"

    async with session_factory() as session:
        run = await session.scalar(select(AgentRun).where(AgentRun.id == UUID(run_id)))
        assert run is not None
        # R3-F2: provider_incomplete は failed へ閉じる (running / repair_exhausted へ行かない)。
        assert run.status == "failed"
        run_failed = await session.scalar(
            select(AgentRunEvent).where(
                AgentRunEvent.run_id == UUID(run_id),
                AgentRunEvent.event_type == "run_failed",
            )
        )
        assert run_failed is not None
        assert run_failed.event_payload["reason_code"] == "provider_incomplete_no_retry"


# ---------------------------------------------------------------------------
# cancel entrypoint 統一 (R2-F2 + R3-F1) + cancelled run の drive は no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bridge_run_cancel_appends_event_and_persists(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = await _create_shadow_run(session_factory, monkeypatch)

    # publish_cancel_signal の redis 依存を避ける (best-effort なので no-op publisher)。
    async with session_factory() as session:
        cancel_result = await bridge_run_cancel(
            session, tenant_id=DEFAULT_TENANT_ID, run_id=UUID(run_id)
        )
    assert cancel_result["status"] == "cancelled"

    async with session_factory() as session:
        run = await session.scalar(select(AgentRun).where(AgentRun.id == UUID(run_id)))
        assert run is not None
        assert run.status == "cancelled"
        # R2-F2: 従来 status 直接 set で append されなかった run_cancelled event が永続する。
        cancel_event = await session.scalar(
            select(AgentRunEvent).where(
                AgentRunEvent.run_id == UUID(run_id),
                AgentRunEvent.event_type == "run_cancelled",
            )
        )
        assert cancel_event is not None

    # cancelled run の drive は claim-miss no-op (status != queued)。
    drive = await execute_agent_run({}, run_id=run_id, tenant_id=DEFAULT_TENANT_ID)
    assert drive["status"] == "claim_miss"


@pytest.mark.asyncio
async def test_bridge_run_cancel_terminal_is_already_terminal(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = await _create_shadow_run(session_factory, monkeypatch)
    completed = await execute_agent_run({}, run_id=run_id, tenant_id=DEFAULT_TENANT_ID)
    assert completed["status"] == "completed"

    async with session_factory() as session:
        result = await bridge_run_cancel(
            session, tenant_id=DEFAULT_TENANT_ID, run_id=UUID(run_id)
        )
    assert result["error"] == "already_terminal"


# ---------------------------------------------------------------------------
# enqueue fail-closed (R2-F1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_dispatch_failure_fails_run_closed(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(*, run_id: UUID, tenant_id: int) -> None:
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(api_bridge, "_enqueue_shadow_run", _boom)
    ticket_id = await _create_ticket(session_factory)

    async with session_factory() as session:
        result = await bridge_run_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            ticket_id=ticket_id,
            purpose="enqueue failure",
            run_mode="shadow",
        )
    # R2-F1: enqueue 失敗で run は queued 残置 (silent orphan) でなく failed に終端化。
    assert result["status"] == "failed"
    run_id = result["run_id"]

    async with session_factory() as session:
        run = await session.scalar(select(AgentRun).where(AgentRun.id == UUID(run_id)))
        assert run is not None
        assert run.status == "failed"
        run_failed = await session.scalar(
            select(AgentRunEvent).where(
                AgentRunEvent.run_id == UUID(run_id),
                AgentRunEvent.event_type == "run_failed",
            )
        )
        assert run_failed is not None
        assert run_failed.event_payload["reason_code"] == "enqueue_dispatch_failed"

        # queued run が残っていない (orphan なし)。
        queued_count = await session.scalar(
            select(func.count())
            .select_from(AgentRun)
            .where(AgentRun.status == "queued")
        )
        assert queued_count == 0


# ---------------------------------------------------------------------------
# R2-A1: claim 確認後の setup/snapshot 失敗も fail-closed (queued orphan なし)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_driver_setup_failure_after_claim_fails_closed(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = await _create_shadow_run(session_factory, monkeypatch)

    # claim 確認後の ContextSnapshot 作成で例外を注入 (snapshot 制約違反 / matrix 不備の代理)。
    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("snapshot setup failure")

    monkeypatch.setattr(agent_run_driver, "_create_input_snapshot", _boom)

    result = await execute_agent_run({}, run_id=run_id, tenant_id=DEFAULT_TENANT_ID)
    # R2-A1: claim 後の通常例外でも queued 残置 (orphan) でなく failed に終端化。
    assert result["status"] == "failed"

    async with session_factory() as session:
        run = await session.scalar(select(AgentRun).where(AgentRun.id == UUID(run_id)))
        assert run is not None
        assert run.status == "failed"
        queued_count = await session.scalar(
            select(func.count())
            .select_from(AgentRun)
            .where(AgentRun.status == "queued")
        )
        assert queued_count == 0


# ---------------------------------------------------------------------------
# R2-A2: provenance mismatch (result fp != driver request) は fail-closed
# ---------------------------------------------------------------------------


# R3-A1: terminal outcome (refusal/safety_refusal) でも tamper fingerprint は provider 遷移ごと
# rollback されて failed に終端化する (invalid な provider_refused terminal を残さない)。
@pytest.mark.parametrize("provider_status", ["success", "refusal", "safety_refusal"])
@pytest.mark.asyncio
async def test_driver_provenance_mismatch_fails_closed(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    provider_status: str,
) -> None:
    from backend.app.domain.provider.request import ProviderRequest
    from backend.app.domain.provider.result import ProviderResult, ProviderUsage

    class _TamperProvider:
        def provider_name(self) -> str:
            return "mock"

        def api_or_feature(self) -> str:
            return "mock"

        def execute(self, request: ProviderRequest) -> ProviderResult:
            # 報告 api/sdk から再計算した hash と一致しない fingerprint を返す (tamper / drift)。
            return ProviderResult(
                status=provider_status,  # type: ignore[arg-type]
                usage=ProviderUsage(tokens_input=12, tokens_output=4, cost_usd=0.0),
                model_resolved=request.model_resolved,
                api_version="mock-v1",
                sdk_version="mock-1.0",
                provider_request_fingerprint="0" * 64,  # 不正 fingerprint
                redacted_response_summary={"result": "x"},
            )

    monkeypatch.setattr(agent_run_driver, "MockProviderAdapter", _TamperProvider)

    run_id = await _create_shadow_run(session_factory, monkeypatch)
    result = await execute_agent_run({}, run_id=run_id, tenant_id=DEFAULT_TENANT_ID)
    assert result["status"] == "failed"

    async with session_factory() as session:
        run = await session.scalar(select(AgentRun).where(AgentRun.id == UUID(run_id)))
        assert run is not None
        # R3-A1: tamper は provider 遷移ごと rollback され failed。terminal provider_refused や
        # provider_responded event は永続しない。
        assert run.status == "failed"
        run_failed = await session.scalar(
            select(AgentRunEvent).where(
                AgentRunEvent.run_id == UUID(run_id),
                AgentRunEvent.event_type == "run_failed",
            )
        )
        assert run_failed is not None
        assert run_failed.event_payload["reason_code"] == "driver_exception"
        provider_responded = await session.scalar(
            select(func.count())
            .select_from(AgentRunEvent)
            .where(
                AgentRunEvent.run_id == UUID(run_id),
                AgentRunEvent.event_type == "provider_responded",
            )
        )
        assert provider_responded == 0  # tampered provider outcome は rollback され非永続


# ---------------------------------------------------------------------------
# R4-A1: freeze invariant — 作成後に ticket soft-delete / project archive された run は
# driver が駆動せず queued 据置で skip する (provider work / output を作らない)。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_driver_skips_run_when_project_archived_after_create(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = await _create_shadow_run(session_factory, monkeypatch)

    # 作成後・dequeue 前に project を archive する (bulk-soft-delete / archive 相当の freeze)。
    # projects は fixture で truncate されない共有行のため、finally で必ず active へ戻し
    # 後続 test (pytest-randomly 順) を汚染しない。
    async with session_factory.begin() as session:
        await session.execute(
            text("update projects set status = 'archived' where id = :pid"),
            {"pid": DEFAULT_PROJECT_ID},
        )
    try:
        result = await execute_agent_run({}, run_id=run_id, tenant_id=DEFAULT_TENANT_ID)
        # R4-A1: frozen run は駆動せず skip (fail でなく queued 据置 = freeze は可逆)。
        assert result["status"] == "skipped_not_actionable"

        async with session_factory() as session:
            run = await session.scalar(select(AgentRun).where(AgentRun.id == UUID(run_id)))
            assert run is not None
            assert run.status == "queued"  # 駆動されず queued 据置 (restore で再駆動可能)
            # provider work / output は一切発生しない (run_queued のみ)。
            non_queued_events = await session.scalar(
                select(func.count())
                .select_from(AgentRunEvent)
                .where(
                    AgentRunEvent.run_id == UUID(run_id),
                    AgentRunEvent.event_type != "run_queued",
                )
            )
            assert non_queued_events == 0
            artifact_count = await session.scalar(
                select(func.count())
                .select_from(Artifact)
                .where(Artifact.run_id == UUID(run_id))
            )
            assert artifact_count == 0
    finally:
        async with session_factory.begin() as session:
            await session.execute(
                text("update projects set status = 'active' where id = :pid"),
                {"pid": DEFAULT_PROJECT_ID},
            )
