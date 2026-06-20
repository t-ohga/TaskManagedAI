"""SP-029 (ADR-00055) shadow mode の DB-backed contract test。

実 PostgreSQL で次を固定する:
- bridge_run_create の shadow feature toggle gate (§6) + run_mode persistence + event payload。
- approval shadow guard (§3): shadow run の ApprovalRequest 作成は fail-closed で reject、row 非永続。
- production KPI 除外 (§8): shadow completed run の cost を cost KPI / rollup から除外。
- migration 0048 可逆性 (§9): downgrade で run_mode 列消失、upgrade で復活 + 既存 row は production。

DB 接続必要: TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container 起動時のみ実行 (host では skip)。
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
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
from backend.app.db.models.budget import Budget
from backend.app.db.session import create_engine
from backend.app.domain.provider.result import ProviderUsage
from backend.app.mcp import api_bridge
from backend.app.mcp.api_bridge import bridge_run_create, bridge_ticket_create
from backend.app.repositories.approval_request import ApprovalRequestRepository
from backend.app.seeds.initial import (
    DEFAULT_ACTOR_ID,
    DEFAULT_PROJECT_ID,
    DEFAULT_TENANT_ID,
    seed_initial,
)
from backend.app.services.agent_runtime.shadow_guard import ShadowSideEffectError
from backend.app.services.eval.kpi_timeseries import KpiTimeseriesService
from backend.app.services.metrics.orchestrator_kpi_rollup import (
    OrchestratorKpiRollupService,
)
from backend.app.services.providers.usage_logger import record_provider_usage
from backend.app.services.secrets.broker import BrokerIssueDenied, SecretBroker

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)


def _integration_settings(*, shadow_mode_enabled: bool = False) -> Settings:
    return Settings(
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-sp029",
        shadow_mode_enabled=shadow_mode_enabled,
    )


def _run_alembic(database_url: str, target: str, *, downgrade: bool = False) -> None:
    previous = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    config = Config(str(_REPO_ROOT / "alembic.ini"))
    try:
        if downgrade:
            command.downgrade(config, target)
        else:
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
            raise AssertionError("shadow mode DB test requires PostgreSQL.") from exc
        pytest.skip("Set TASKMANAGEDAI_RUN_DB_TESTS=1 with test PostgreSQL running.")
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
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
            title=f"shadow-target-{uuid4()}",
        )
    return str(result["ticket_id"])


# ---------------------------------------------------------------------------
# §6 bridge_run_create flag gate + persistence.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_run_create_denied_when_flag_off(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket_id = await _create_ticket(session_factory)
    monkeypatch.setattr(
        api_bridge, "get_settings", lambda: _integration_settings(shadow_mode_enabled=False)
    )
    async with session_factory() as session:
        with pytest.raises(ValueError, match="shadow run_mode is disabled"):
            await bridge_run_create(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                project_id=DEFAULT_PROJECT_ID,
                ticket_id=ticket_id,
                purpose="shadow试走",
                run_mode="shadow",
            )
    # 拒否時は run 行を一切作らない。
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(AgentRun))
    assert count == 0


@pytest.mark.asyncio
async def test_shadow_run_create_persists_run_mode_when_flag_on(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket_id = await _create_ticket(session_factory)
    monkeypatch.setattr(
        api_bridge, "get_settings", lambda: _integration_settings(shadow_mode_enabled=True)
    )
    async with session_factory() as session:
        result = await bridge_run_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            ticket_id=ticket_id,
            purpose="shadow试走",
            run_mode="shadow",
        )
    assert result["run_mode"] == "shadow"
    run_id = result["run_id"]

    async with session_factory() as session:
        run = await session.scalar(
            select(AgentRun).where(AgentRun.id == UUID(run_id))
        )
        assert run is not None
        assert run.run_mode == "shadow"
        event = await session.scalar(
            select(AgentRunEvent).where(
                AgentRunEvent.run_id == run.id,
                AgentRunEvent.event_type == "run_queued",
            )
        )
        assert event is not None
        assert event.event_payload["run_mode"] == "shadow"


@pytest.mark.asyncio
async def test_production_run_create_defaults_to_production(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ticket_id = await _create_ticket(session_factory)
    async with session_factory() as session:
        result = await bridge_run_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            ticket_id=ticket_id,
            purpose="production",
        )
    assert result["run_mode"] == "production"


@pytest.mark.asyncio
async def test_production_idempotency_fingerprint_is_backward_compatible(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Codex R2 F-1: production は run_mode を fingerprint に含めない (legacy shape 維持)。
    # 同 key + 同 params の production 再送は replay として既存 run を返す (deploy 跨ぎ
    # exactly-once create recovery が壊れない)。
    ticket_id = await _create_ticket(session_factory)
    key = f"prod-idem-{uuid4()}"
    async with session_factory() as session:
        first = await bridge_run_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            ticket_id=ticket_id,
            purpose="production",
            idempotency_key=key,
        )
    async with session_factory() as session:
        second = await bridge_run_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            ticket_id=ticket_id,
            purpose="production",
            idempotency_key=key,
        )
    assert first["run_id"] == second["run_id"]
    assert second.get("idempotent_replay") is True
    assert second["run_mode"] == "production"


@pytest.mark.asyncio
async def test_shadow_idempotency_replay_returns_same_run(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket_id = await _create_ticket(session_factory)
    monkeypatch.setattr(
        api_bridge, "get_settings", lambda: _integration_settings(shadow_mode_enabled=True)
    )
    key = f"shadow-idem-{uuid4()}"
    async with session_factory() as session:
        first = await bridge_run_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            ticket_id=ticket_id,
            purpose="shadow",
            idempotency_key=key,
            run_mode="shadow",
        )
    async with session_factory() as session:
        second = await bridge_run_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            ticket_id=ticket_id,
            purpose="shadow",
            idempotency_key=key,
            run_mode="shadow",
        )
    assert first["run_id"] == second["run_id"]
    assert second.get("idempotent_replay") is True
    assert second["run_mode"] == "shadow"


# ---------------------------------------------------------------------------
# §3 approval shadow guard.
# ---------------------------------------------------------------------------


async def _insert_run(
    factory: async_sessionmaker[AsyncSession],
    *,
    run_mode: str,
    ticket_id: str,
    status: str = "queued",
    cost_usd: Decimal | None = None,
    completed_at: datetime | None = None,
) -> AgentRun:
    async with factory.begin() as session:
        run = AgentRun(
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            ticket_id=UUID(ticket_id),
            status=status,
            run_mode=run_mode,
            cost_usd=cost_usd,
            completed_at=completed_at,
        )
        session.add(run)
        await session.flush()
        await session.refresh(run)
    return run


@pytest.mark.asyncio
async def test_approval_create_rejected_for_shadow_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ticket_id = await _create_ticket(session_factory)
    run = await _insert_run(session_factory, run_mode="shadow", ticket_id=ticket_id)

    async with session_factory() as session:
        repo = ApprovalRequestRepository(session)
        with pytest.raises(ShadowSideEffectError):
            await repo.create_pending_approval(
                tenant_id=DEFAULT_TENANT_ID,
                action_class="repo_write",
                resource_ref=f"run:{run.id}",
                risk_level="medium",
                requested_by_actor_id=DEFAULT_ACTOR_ID,
                recipient_actor_id=DEFAULT_ACTOR_ID,
                policy_version="v1",
                run_id=run.id,
            )
        await session.rollback()

    # approval 行は一切永続化されない (fail-closed)。
    async with session_factory() as session:
        count = await session.scalar(
            text("select count(*) from approval_requests where run_id = :rid"),
            {"rid": run.id},
        )
    assert count == 0


@pytest.mark.asyncio
async def test_approval_create_allowed_for_production_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ticket_id = await _create_ticket(session_factory)
    run = await _insert_run(session_factory, run_mode="production", ticket_id=ticket_id)

    async with session_factory() as session:
        repo = ApprovalRequestRepository(session)
        approval = await repo.create_pending_approval(
            tenant_id=DEFAULT_TENANT_ID,
            action_class="repo_write",
            resource_ref=f"run:{run.id}",
            risk_level="medium",
            requested_by_actor_id=DEFAULT_ACTOR_ID,
            recipient_actor_id=DEFAULT_ACTOR_ID,
            policy_version="v1",
            run_id=run.id,
        )
        await session.commit()
        assert approval.status == "pending"


# ---------------------------------------------------------------------------
# §8 production KPI 除外.
# ---------------------------------------------------------------------------


async def _insert_provider_responded(
    factory: async_sessionmaker[AsyncSession],
    *,
    run_id: object,
    cost_usd: str,
) -> None:
    async with factory.begin() as session:
        session.add(
            AgentRunEvent(
                tenant_id=DEFAULT_TENANT_ID,
                run_id=run_id,
                seq_no=1,
                event_type="provider_responded",
                event_payload={
                    "usage": {
                        "cost_usd": cost_usd,
                        "tokens_input": 1,
                        "tokens_output": 1,
                    }
                },
                actor_id=DEFAULT_ACTOR_ID,
            )
        )


@pytest.mark.asyncio
async def test_shadow_run_excluded_from_cost_kpi(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    completed_at = now - timedelta(hours=1)
    ticket_id = await _create_ticket(session_factory)

    prod = await _insert_run(
        session_factory,
        run_mode="production",
        ticket_id=ticket_id,
        status="completed",
        cost_usd=Decimal("0.30"),
        completed_at=completed_at,
    )
    shadow = await _insert_run(
        session_factory,
        run_mode="shadow",
        ticket_id=ticket_id,
        status="completed",
        cost_usd=Decimal("5.00"),
        completed_at=completed_at,
    )
    await _insert_provider_responded(session_factory, run_id=prod.id, cost_usd="0.30")
    await _insert_provider_responded(session_factory, run_id=shadow.id, cost_usd="5.00")

    async with session_factory() as session:
        timeseries = await KpiTimeseriesService(session).compute(
            tenant_id=DEFAULT_TENANT_ID,
            bucket="day",
            range_value="week",
            project_id=DEFAULT_PROJECT_ID,
            now=now,
        )
    cost_series = next(s for s in timeseries.series if s.kpi_id == "cost_per_completed_task")
    measured = [b for b in cost_series.buckets if b.denominator_count]
    assert measured, "expected one completed-run cost bucket"
    bucket = measured[0]
    # production 1 件のみ計上、shadow (5.00) は除外。denominator も production のみ。
    assert bucket.denominator_count == 1
    assert bucket.value is not None
    assert abs(bucket.value - 0.30) < 1e-9


@pytest.mark.asyncio
async def test_shadow_root_excluded_from_orchestrator_rollup(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ticket_id = await _create_ticket(session_factory)
    shadow = await _insert_run(
        session_factory,
        run_mode="shadow",
        ticket_id=ticket_id,
        status="completed",
        cost_usd=Decimal("5.00"),
        completed_at=datetime.now(UTC),
    )
    prod = await _insert_run(
        session_factory,
        run_mode="production",
        ticket_id=ticket_id,
        status="completed",
        cost_usd=Decimal("0.30"),
        completed_at=datetime.now(UTC),
    )

    async with session_factory() as session:
        service = OrchestratorKpiRollupService(session)
        # shadow root は run_tree base で除外 → lineage 0 → None。
        shadow_rollup = await service.fetch(
            tenant_id=DEFAULT_TENANT_ID, root_run_id=shadow.id
        )
        assert shadow_rollup is None
        # production root は通常通り集計される。
        prod_rollup = await service.fetch(
            tenant_id=DEFAULT_TENANT_ID, root_run_id=prod.id
        )
        assert prod_rollup is not None
        assert prod_rollup.completed_run_count == 1


# ---------------------------------------------------------------------------
# §3 / Codex R1 F-1: shadow/production lineage は混ざらない (parent/child run_mode).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_parent_cannot_spawn_production_child(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ticket_id = await _create_ticket(session_factory)
    parent = await _insert_run(session_factory, run_mode="shadow", ticket_id=ticket_id)

    async with session_factory() as session:
        # run_mode 未指定 = default production (delegation/dispatch と同じ経路)。
        with pytest.raises(ValueError, match="must match parent run_mode"):
            await bridge_run_create(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                project_id=DEFAULT_PROJECT_ID,
                ticket_id=ticket_id,
                purpose="child",
                parent_run_id=parent.id,
            )


@pytest.mark.asyncio
async def test_production_parent_cannot_spawn_shadow_child(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket_id = await _create_ticket(session_factory)
    parent = await _insert_run(session_factory, run_mode="production", ticket_id=ticket_id)
    monkeypatch.setattr(
        api_bridge, "get_settings", lambda: _integration_settings(shadow_mode_enabled=True)
    )
    async with session_factory() as session:
        with pytest.raises(ValueError, match="must match parent run_mode"):
            await bridge_run_create(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                project_id=DEFAULT_PROJECT_ID,
                ticket_id=ticket_id,
                purpose="child",
                parent_run_id=parent.id,
                run_mode="shadow",
            )


@pytest.mark.asyncio
async def test_shadow_parent_can_spawn_shadow_child(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket_id = await _create_ticket(session_factory)
    parent = await _insert_run(session_factory, run_mode="shadow", ticket_id=ticket_id)
    monkeypatch.setattr(
        api_bridge, "get_settings", lambda: _integration_settings(shadow_mode_enabled=True)
    )
    async with session_factory() as session:
        child = await bridge_run_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            ticket_id=ticket_id,
            purpose="child",
            parent_run_id=parent.id,
            run_mode="shadow",
        )
    assert child["run_mode"] == "shadow"


# ---------------------------------------------------------------------------
# §3 / Codex R1 F-2: SecretBroker は shadow run へ repo mutation capability を発行しない.
# ---------------------------------------------------------------------------


async def _insert_secret_ref(
    factory: async_sessionmaker[AsyncSession],
    *,
    secret_ref_id: UUID,
    name: str,
    operations: list[str],
) -> None:
    async with factory.begin() as session:
        await session.execute(
            text(
                """
                insert into secret_refs (
                  id, tenant_id, secret_uri, scope, name, version, status,
                  runner_injectable, allowed_consumers, allowed_operations,
                  owner_actor_id, metadata, material_state
                ) values (
                  :id, :tenant, :uri, 'project', :name, 'v1', 'active', false,
                  cast(:consumers as jsonb), cast(:operations as jsonb),
                  :owner, '{"rls_ready": true}'::jsonb, 'present'
                )
                """
            ),
            {
                "id": secret_ref_id,
                "tenant": DEFAULT_TENANT_ID,
                "uri": f"secret://sops/project/{name}#v1",
                "name": name,
                "consumers": json.dumps([str(DEFAULT_ACTOR_ID)]),
                "operations": json.dumps(operations),
                "owner": DEFAULT_ACTOR_ID,
            },
        )


@pytest.mark.asyncio
async def test_secret_broker_denies_repo_push_for_shadow_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ticket_id = await _create_ticket(session_factory)
    run = await _insert_run(
        session_factory, run_mode="shadow", ticket_id=ticket_id, status="running"
    )
    secret_ref_id = uuid4()
    await _insert_secret_ref(
        session_factory,
        secret_ref_id=secret_ref_id,
        name=f"gh-app-{uuid4().hex[:8]}",
        operations=["repo.push"],
    )

    async with session_factory() as session:
        broker = SecretBroker(session=session)
        # guard は approval 検証より前 (fail-fast) のため approval 未設定でも shadow で deny。
        with pytest.raises(BrokerIssueDenied, match="shadow_run_mutation_forbidden"):
            await broker.issue_capability_token(
                tenant_id=DEFAULT_TENANT_ID,
                actor_id=DEFAULT_ACTOR_ID,
                run_id=run.id,
                secret_ref_id=secret_ref_id,
                requested_operation="repo.push",
                target={
                    "repo_full_name": "owner/repo",
                    "branch": "main",
                    "commit_sha": "a" * 40,
                },
                payload_hash="0" * 64,
                policy_version="policy-v1",
            )


@pytest.mark.asyncio
async def test_secret_broker_denies_repo_push_without_run_binding(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Codex R3 F-1: run_id を落として shadow guard を迂回できないよう、repo mutation は
    # run binding 必須。run_id=None は deny。
    secret_ref_id = uuid4()
    await _insert_secret_ref(
        session_factory,
        secret_ref_id=secret_ref_id,
        name=f"gh-app-{uuid4().hex[:8]}",
        operations=["repo.push"],
    )
    async with session_factory() as session:
        broker = SecretBroker(session=session)
        with pytest.raises(BrokerIssueDenied, match="run_required_for_repo_mutation"):
            await broker.issue_capability_token(
                tenant_id=DEFAULT_TENANT_ID,
                actor_id=DEFAULT_ACTOR_ID,
                run_id=None,
                secret_ref_id=secret_ref_id,
                requested_operation="repo.push",
                target={
                    "repo_full_name": "owner/repo",
                    "branch": "main",
                    "commit_sha": "a" * 40,
                },
                payload_hash="0" * 64,
                policy_version="policy-v1",
            )


@pytest.mark.asyncio
async def test_secret_broker_denies_repo_push_for_nonexistent_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # 不在 run_id を詐称しても run_mode を確認できないため deny (fail-closed)。
    secret_ref_id = uuid4()
    await _insert_secret_ref(
        session_factory,
        secret_ref_id=secret_ref_id,
        name=f"gh-app-{uuid4().hex[:8]}",
        operations=["repo.push"],
    )
    async with session_factory() as session:
        broker = SecretBroker(session=session)
        with pytest.raises(BrokerIssueDenied, match="run_required_for_repo_mutation"):
            await broker.issue_capability_token(
                tenant_id=DEFAULT_TENANT_ID,
                actor_id=DEFAULT_ACTOR_ID,
                run_id=uuid4(),
                secret_ref_id=secret_ref_id,
                requested_operation="repo.push",
                target={
                    "repo_full_name": "owner/repo",
                    "branch": "main",
                    "commit_sha": "a" * 40,
                },
                payload_hash="0" * 64,
                policy_version="policy-v1",
            )


@pytest.mark.asyncio
async def test_secret_broker_allows_provider_call_for_shadow_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # constraint §7: shadow も provider.call は通常経路で許可される (provider key は broker 内部)。
    ticket_id = await _create_ticket(session_factory)
    run = await _insert_run(
        session_factory, run_mode="shadow", ticket_id=ticket_id, status="running"
    )
    secret_ref_id = uuid4()
    await _insert_secret_ref(
        session_factory,
        secret_ref_id=secret_ref_id,
        name=f"provider-openai-{uuid4().hex[:8]}",
        operations=["provider.call"],
    )

    async with session_factory() as session:
        broker = SecretBroker(session=session)
        issue_result = await broker.issue_capability_token(
            tenant_id=DEFAULT_TENANT_ID,
            actor_id=DEFAULT_ACTOR_ID,
            run_id=run.id,
            secret_ref_id=secret_ref_id,
            requested_operation="provider.call",
            target={
                "provider": "openai",
                "api_or_feature": "chat",
                "model_resolved": "gpt-5.5",
            },
            payload_hash="0" * 64,
            policy_version="policy-v1",
            provider_compliance_matrix_version="2026-05-08",
        )
        await session.commit()
    assert issue_result.raw_token


# ---------------------------------------------------------------------------
# §4 / Codex R1 F-3: shadow path も global kill switch を尊重する.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_run_blocked_by_global_kill_switch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ticket_id = await _create_ticket(session_factory)
    run = await _insert_run(
        session_factory, run_mode="shadow", ticket_id=ticket_id, status="running"
    )
    # budgets は session_factory の truncate 対象外のため、本 test 専用の global kill switch
    # row が他 test (production budget) に leak しないよう finally で必ず削除する。
    try:
        async with session_factory.begin() as session:
            session.add(
                Budget(
                    tenant_id=DEFAULT_TENANT_ID,
                    level="global",
                    level_id=None,
                    active=True,
                    global_kill_switch=True,
                )
            )

        async with session_factory() as session:
            fresh = await session.scalar(select(AgentRun).where(AgentRun.id == run.id))
            assert fresh is not None
            result = await record_provider_usage(
                session,
                run=fresh,
                usage=ProviderUsage(tokens_input=1, tokens_output=1, cost_usd=0.01),
                actor_id=DEFAULT_ACTOR_ID,
                matrix_version="pcm-v1",
            )
            await session.commit()

        assert result.exceeded is True
        assert result.reason == "global_kill_switch"
        async with session_factory() as session:
            blocked = await session.scalar(select(AgentRun).where(AgentRun.id == run.id))
            assert blocked is not None
            assert blocked.status == "blocked"
            assert blocked.blocked_reason == "budget_blocked"
    finally:
        async with session_factory.begin() as session:
            await session.execute(text("delete from budgets"))


# ---------------------------------------------------------------------------
# Codex R10 F-1: shadow run の cost/tokens は run_cost 手動補正で reset 不可 (cap 権威性).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_cost_rejected_for_shadow_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from backend.app.mcp.api_bridge import bridge_run_cost

    ticket_id = await _create_ticket(session_factory)
    run = await _insert_run(
        session_factory,
        run_mode="shadow",
        ticket_id=ticket_id,
        status="running",
        cost_usd=Decimal("0.90"),
    )
    async with session_factory() as session:
        result = await bridge_run_cost(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            run_id=run.id,
            cost_usd=0.0,
            tokens_input=0,
            tokens_output=0,
        )
    assert result["error"] == "shadow_run_cost_immutable"
    # cost は reset されない (cap の権威性維持)。
    async with session_factory() as session:
        fresh = await session.scalar(select(AgentRun).where(AgentRun.id == run.id))
        assert fresh is not None
        assert fresh.cost_usd == Decimal("0.90")


@pytest.mark.asyncio
async def test_run_cost_allowed_for_production_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from backend.app.mcp.api_bridge import bridge_run_cost

    ticket_id = await _create_ticket(session_factory)
    run = await _insert_run(
        session_factory, run_mode="production", ticket_id=ticket_id, status="running"
    )
    async with session_factory() as session:
        result = await bridge_run_cost(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            run_id=run.id,
            cost_usd=0.5,
            tokens_input=10,
            tokens_output=20,
        )
    assert result.get("error") is None
    assert result["cost_usd"] == 0.5


# ---------------------------------------------------------------------------
# Codex R12 F-1: shadow run は run_update で resume / 強制 complete できない.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_update_rejected_for_shadow_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from backend.app.mcp.api_bridge import bridge_run_update

    ticket_id = await _create_ticket(session_factory)
    # budget/kill/usage で blocked になった shadow run を模す。
    run = await _insert_run(
        session_factory, run_mode="shadow", ticket_id=ticket_id, status="running"
    )
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "update agent_runs set status='blocked', blocked_reason='runtime_blocked' "
                "where id = :id"
            ),
            {"id": run.id},
        )
    async with session_factory() as session:
        result = await bridge_run_update(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            run_id=run.id,
            status="running",
        )
    assert result["error"] == "shadow_run_update_forbidden"
    # blocked のまま resume されない。
    async with session_factory() as session:
        fresh = await session.scalar(select(AgentRun).where(AgentRun.id == run.id))
        assert fresh is not None
        assert fresh.status == "blocked"


@pytest.mark.asyncio
async def test_run_update_allowed_for_production_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from backend.app.mcp.api_bridge import bridge_run_update

    ticket_id = await _create_ticket(session_factory)
    run = await _insert_run(
        session_factory, run_mode="production", ticket_id=ticket_id, status="running"
    )
    async with session_factory() as session:
        result = await bridge_run_update(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            run_id=run.id,
            status="completed",
        )
    assert result.get("error") is None
    assert result["new_status"] == "completed"


# ---------------------------------------------------------------------------
# Codex R12 F-3: shadow flag は新規 create のみ gate し、既存 run の冪等 replay は壊さない.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_idempotent_replay_works_after_flag_disabled(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket_id = await _create_ticket(session_factory)
    key = f"shadow-flagflip-{uuid4()}"
    # flag ON で shadow run を作成。
    monkeypatch.setattr(
        api_bridge, "get_settings", lambda: _integration_settings(shadow_mode_enabled=True)
    )
    async with session_factory() as session:
        first = await bridge_run_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            ticket_id=ticket_id,
            purpose="shadow",
            idempotency_key=key,
            run_mode="shadow",
        )
    # flag OFF にしても同 key の replay は既存 run を返す (新規 create のみ gate)。
    monkeypatch.setattr(
        api_bridge, "get_settings", lambda: _integration_settings(shadow_mode_enabled=False)
    )
    async with session_factory() as session:
        replay = await bridge_run_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            ticket_id=ticket_id,
            purpose="shadow",
            idempotency_key=key,
            run_mode="shadow",
        )
    assert replay["run_id"] == first["run_id"]
    assert replay.get("idempotent_replay") is True
    # 一方、flag OFF での **新規** shadow create (別 key) は依然 deny。
    async with session_factory() as session:
        with pytest.raises(ValueError, match="shadow run_mode is disabled"):
            await bridge_run_create(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                project_id=DEFAULT_PROJECT_ID,
                ticket_id=ticket_id,
                purpose="shadow",
                idempotency_key=f"new-{uuid4()}",
                run_mode="shadow",
            )


# ---------------------------------------------------------------------------
# Codex R10 F-2: MCP workflow_status / kpi_show は shadow run を production 集計から除外.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workflow_status_excludes_shadow_runs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from backend.app.mcp.api_bridge import bridge_workflow_status

    ticket_id = await _create_ticket(session_factory)
    await _insert_run(
        session_factory, run_mode="production", ticket_id=ticket_id, status="completed"
    )
    await _insert_run(
        session_factory, run_mode="shadow", ticket_id=ticket_id, status="completed"
    )
    async with session_factory() as session:
        summary = await bridge_workflow_status(session, tenant_id=DEFAULT_TENANT_ID)
    # production 1 件のみ集計、shadow completed は除外。
    assert summary["total_runs"] == 1
    assert summary["completed"] == 1


@pytest.mark.asyncio
async def test_kpi_show_predicate_excludes_shadow_runs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # kpi_show (server.py) の MCP tool は global get_db_session に依存し test 順序に脆弱なため、
    # tool 呼び出しでなく **kpi_show と同一の count predicate** (tenant + active-scope +
    # run_mode='production' + status) を自前 session で deterministic に検証する
    # (tool レベルは bridge_workflow_status test が担保)。
    from backend.app.domain.agent_runtime.active_scope import (
        soft_deleted_ticket_run_exclusion,
    )

    ticket_id = await _create_ticket(session_factory)
    await _insert_run(
        session_factory, run_mode="production", ticket_id=ticket_id, status="completed"
    )
    await _insert_run(
        session_factory, run_mode="shadow", ticket_id=ticket_id, status="completed"
    )
    await _insert_run(
        session_factory, run_mode="shadow", ticket_id=ticket_id, status="failed"
    )

    active_run = soft_deleted_ticket_run_exclusion()
    production_only = AgentRun.run_mode == "production"
    async with session_factory() as session:
        total = await session.scalar(
            select(func.count())
            .select_from(AgentRun)
            .where(AgentRun.tenant_id == DEFAULT_TENANT_ID, active_run, production_only)
        )
        completed = await session.scalar(
            select(func.count())
            .select_from(AgentRun)
            .where(
                AgentRun.tenant_id == DEFAULT_TENANT_ID,
                AgentRun.status == "completed",
                active_run,
                production_only,
            )
        )
        failed = await session.scalar(
            select(func.count())
            .select_from(AgentRun)
            .where(
                AgentRun.tenant_id == DEFAULT_TENANT_ID,
                AgentRun.status == "failed",
                active_run,
                production_only,
            )
        )
    # production 1 (completed) のみ。shadow completed/failed は除外。
    assert total == 1
    assert completed == 1
    assert failed == 0


# ---------------------------------------------------------------------------
# §9 migration 0048 可逆性.
# ---------------------------------------------------------------------------


_COLUMN_EXISTS_SQL = text(
    "select count(*) from information_schema.columns "
    "where table_name = 'agent_runs' and column_name = 'run_mode'"
)


@pytest.mark.asyncio
async def test_migration_0048_is_reversible(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = _integration_settings()
    # 既存 row (shadow) を 1 件作り、downgrade→列消失 (row 自体は非破壊で残る)→
    # upgrade→列復活 + server_default 'production' で backfill されることを検証する。
    ticket_id = await _create_ticket(session_factory)
    await _insert_run(session_factory, run_mode="shadow", ticket_id=ticket_id)

    await asyncio.to_thread(_run_alembic, settings.database_url, "-1", downgrade=True)
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            after_down = await conn.scalar(_COLUMN_EXISTS_SQL)
            # 列は消えるが agent_runs の row は残る (additive 列 drop は非破壊)。
            run_rows = await conn.scalar(text("select count(*) from agent_runs"))
        assert after_down == 0
        assert run_rows == 1
    finally:
        await engine.dispose()

    await asyncio.to_thread(_run_alembic, settings.database_url, "head")
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            after_up = await conn.scalar(_COLUMN_EXISTS_SQL)
            # 既存 row は再 upgrade の server_default で全て production に backfill される。
            total = await conn.scalar(text("select count(*) from agent_runs"))
            non_production = await conn.scalar(
                text("select count(*) from agent_runs where run_mode <> 'production'")
            )
        assert after_up == 1
        assert total == 1
        assert non_production == 0
    finally:
        await engine.dispose()
