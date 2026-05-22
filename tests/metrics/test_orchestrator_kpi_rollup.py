from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.services.metrics.orchestrator_kpi_rollup import (
    OrchestratorKpiRollupService,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-00000000a001")
DECIDER_ID = UUID("00000000-0000-4000-8000-00000000a002")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-00000000a010")
PROJECT_ID = UUID("00000000-0000-4000-8000-00000000a011")
ROOT_RUN_ID = UUID("00000000-0000-4000-8000-00000000a101")
CHILD_RUN_ID = UUID("00000000-0000-4000-8000-00000000a102")
FAILED_CHILD_RUN_ID = UUID("00000000-0000-4000-8000-00000000a103")
DATASET_VERSION_ID = UUID("00000000-0000-4000-8000-00000000a201")
EVAL_RUN_ID = UUID("00000000-0000-4000-8000-00000000a202")


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-orchestrator-kpi-rollup",
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
            raise AssertionError("orchestrator KPI rollup tests require PostgreSQL.") from exc
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


async def _reset_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate
              audit_events,
              eval_scores,
              eval_cases,
              eval_runs,
              dataset_versions,
              agent_run_events,
              approval_requests,
              agent_runs,
              projects,
              workspaces,
              actors,
              tenants
            restart identity cascade
            """
        )
    )


async def _seed_project_boundary(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (:tenant_id, 'tenant-one', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"tenant_id": TENANT_ID},
    )
    await session.execute(
        text(
            """
            insert into policy_profiles (tenant_id, profile_id, description)
            values (:tenant_id, 'default', 'default profile')
            on conflict (tenant_id, profile_id) do nothing
            """
        ),
        {"tenant_id": TENANT_ID},
    )
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values
              (:actor_id, :tenant_id, 'agent', 'agent:kpi', 'KPI Agent',
               '{"rls_ready": true}'::jsonb),
              (:decider_id, :tenant_id, 'human', 'human:kpi-decider', 'KPI Decider',
               '{"rls_ready": true}'::jsonb)
            """
        ),
        {"tenant_id": TENANT_ID, "actor_id": ACTOR_ID, "decider_id": DECIDER_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, :tenant_id, 'kpi', 'KPI', :actor_id,
                    '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "workspace_id": WORKSPACE_ID,
            "tenant_id": TENANT_ID,
            "actor_id": ACTOR_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into projects (
              id, tenant_id, workspace_id, slug, name, status, policy_profile, metadata
            )
            values (:project_id, :tenant_id, :workspace_id, 'kpi', 'KPI',
                    'active', 'default', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "project_id": PROJECT_ID,
            "tenant_id": TENANT_ID,
            "workspace_id": WORKSPACE_ID,
        },
    )


async def _seed_run_tree(session: AsyncSession) -> None:
    base = datetime(2026, 5, 22, 10, 0, tzinfo=UTC)
    await session.execute(
        text(
            """
            insert into agent_runs (
              id, tenant_id, project_id, parent_run_id, status, completed_at,
              role_id, role_scope, cost_usd, tokens_input, tokens_output,
              created_at, updated_at
            )
            values
              (:root_run_id, :tenant_id, :project_id, null, 'completed',
               :root_completed_at, 'orchestrator', 'project', 0, 0, 0,
               :base, :base),
              (:child_run_id, :tenant_id, :project_id, :root_run_id, 'completed',
               :child_completed_at, 'implementer', 'project', 0, 0, 0,
               :base, :base),
              (:failed_child_run_id, :tenant_id, :project_id, :root_run_id, 'failed',
               null, 'reviewer', 'project', 0, 0, 0,
               :base, :base)
            """
        ),
        {
            "tenant_id": TENANT_ID,
            "project_id": PROJECT_ID,
            "root_run_id": ROOT_RUN_ID,
            "child_run_id": CHILD_RUN_ID,
            "failed_child_run_id": FAILED_CHILD_RUN_ID,
            "base": base,
            "root_completed_at": base + timedelta(hours=2),
            "child_completed_at": base + timedelta(hours=1),
        },
    )


async def _seed_events(session: AsyncSession) -> None:
    base = datetime(2026, 5, 22, 10, 0, tzinfo=UTC)
    await session.execute(
        text(
            """
            insert into agent_run_events (
              id, tenant_id, run_id, seq_no, event_type, event_payload,
              actor_id, idempotency_key, created_at
            )
            values
              ('00000000-0000-4000-8000-00000000b001', :tenant_id, :root_run_id,
               1, 'repo_pr_opened',
               '{"repo_full_name": "t/example", "pr_number": 1}'::jsonb,
               :actor_id, 'root-pr-opened', :root_pr_opened_at),
              ('00000000-0000-4000-8000-00000000b002', :tenant_id, :root_run_id,
               2, 'provider_responded',
               '{"usage": {"cost_usd": 0.20, "tokens_input": 100, "tokens_output": 20}}'::jsonb,
               :actor_id, 'root-provider-responded', :provider_at),
              ('00000000-0000-4000-8000-00000000b003', :tenant_id, :child_run_id,
               1, 'provider_responded',
               '{"usage": {"cost_usd": 0.30, "tokens_input": 200, "tokens_output": 30}}'::jsonb,
               :actor_id, 'child-provider-responded', :provider_at),
              ('00000000-0000-4000-8000-00000000b004', :tenant_id, :failed_child_run_id,
               1, 'provider_responded',
               '{"usage": {"cost_usd": 9.99, "tokens_input": 999, "tokens_output": 999}}'::jsonb,
               :actor_id, 'failed-provider-responded', :provider_at)
            """
        ),
        {
            "tenant_id": TENANT_ID,
            "root_run_id": ROOT_RUN_ID,
            "child_run_id": CHILD_RUN_ID,
            "failed_child_run_id": FAILED_CHILD_RUN_ID,
            "actor_id": ACTOR_ID,
            "root_pr_opened_at": base + timedelta(minutes=15),
            "provider_at": base + timedelta(minutes=20),
        },
    )


async def _seed_approvals(session: AsyncSession) -> None:
    base = datetime(2026, 5, 22, 10, 0, tzinfo=UTC)
    await session.execute(
        text(
            """
            insert into approval_requests (
              id, tenant_id, run_id, action_class, resource_ref, risk_level, status,
              requested_by_actor_id, decided_by_actor_id, requested_at, decided_at,
              policy_version, metadata
            )
            values
              ('00000000-0000-4000-8000-00000000c001', :tenant_id, :root_run_id,
               'task_write', 'ticket:kpi-root', 'low', 'approved',
               :actor_id, :decider_id, :base, :approval_one_decided_at,
               'policy-v1', '{"rls_ready": true}'::jsonb),
              ('00000000-0000-4000-8000-00000000c002', :tenant_id, :child_run_id,
               'task_write', 'ticket:kpi-child', 'low', 'rejected',
               :actor_id, :decider_id, :base, :approval_two_decided_at,
               'policy-v1', '{"rls_ready": true}'::jsonb),
              ('00000000-0000-4000-8000-00000000c003', :tenant_id, :child_run_id,
               'task_write', 'ticket:kpi-pending', 'low', 'pending',
               :actor_id, null, :base, null,
               'policy-v1', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "tenant_id": TENANT_ID,
            "root_run_id": ROOT_RUN_ID,
            "child_run_id": CHILD_RUN_ID,
            "actor_id": ACTOR_ID,
            "decider_id": DECIDER_ID,
            "base": base,
            "approval_one_decided_at": base + timedelta(minutes=30),
            "approval_two_decided_at": base + timedelta(hours=2),
        },
    )


async def _seed_eval_scores(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            insert into dataset_versions (
              id, tenant_id, dataset_key, version, fixture_kind, content_hash, metadata
            )
            values (:dataset_version_id, :tenant_id, 'acceptance_pass_rate',
                    'v-test', 'public_regression', :content_hash,
                    '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "tenant_id": TENANT_ID,
            "dataset_version_id": DATASET_VERSION_ID,
            "content_hash": "a" * 64,
        },
    )
    await session.execute(
        text(
            """
            insert into eval_runs (
              id, tenant_id, run_id, dataset_version_id, suite_name, provider, model, summary
            )
            values (:eval_run_id, :tenant_id, :child_run_id, :dataset_version_id,
                    'acceptance', 'local', 'test', '{}'::jsonb)
            """
        ),
        {
            "tenant_id": TENANT_ID,
            "eval_run_id": EVAL_RUN_ID,
            "child_run_id": CHILD_RUN_ID,
            "dataset_version_id": DATASET_VERSION_ID,
        },
    )
    for index, passed in enumerate((True, True, False), start=1):
        case_id = UUID(f"00000000-0000-4000-8000-00000000d00{index}")
        await session.execute(
            text(
                """
                insert into eval_cases (
                  id, tenant_id, dataset_version_id, case_key, case_json,
                  expected_json, metadata
                )
                values (:case_id, :tenant_id, :dataset_version_id, :case_key,
                        '{}'::jsonb, '{}'::jsonb, '{"rls_ready": true}'::jsonb)
                """
            ),
            {
                "case_id": case_id,
                "tenant_id": TENANT_ID,
                "dataset_version_id": DATASET_VERSION_ID,
                "case_key": f"case-{index}",
            },
        )
        await session.execute(
            text(
                """
                insert into eval_scores (
                  id, tenant_id, eval_run_id, eval_case_id, dataset_version_id,
                  metric_key, score, passed, details
                )
                values (:score_id, :tenant_id, :eval_run_id, :case_id,
                        :dataset_version_id, 'acceptance', :score, :passed,
                        '{}'::jsonb)
                """
            ),
            {
                "score_id": UUID(f"00000000-0000-4000-8000-00000000e00{index}"),
                "tenant_id": TENANT_ID,
                "eval_run_id": EVAL_RUN_ID,
                "case_id": case_id,
                "dataset_version_id": DATASET_VERSION_ID,
                "score": 1 if passed else 0,
                "passed": passed,
            },
        )


async def _seed_rollup_fixture(session: AsyncSession) -> None:
    await _reset_tables(session)
    await _seed_project_boundary(session)
    await _seed_run_tree(session)
    await _seed_events(session)
    await _seed_approvals(session)
    await _seed_eval_scores(session)
    await session.commit()


@pytest.mark.asyncio
async def test_orchestrator_kpi_rollup_aggregates_descendant_runs_with_dedupe_sources(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _seed_rollup_fixture(session)

        result = await OrchestratorKpiRollupService(session).fetch(
            tenant_id=TENANT_ID,
            root_run_id=ROOT_RUN_ID,
        )

    assert result is not None
    assert result.project_id == PROJECT_ID
    assert result.lineage_run_count == 3
    assert result.completed_run_count == 2
    assert result.acceptance_eval_score_count == 3
    assert result.acceptance_passed_count == 2
    assert result.acceptance_pass_rate == pytest.approx(2 / 3)
    assert result.provider_responded_event_count == 3
    assert result.provider_usage_event_count == 2
    assert result.provider_total_cost_usd == pytest.approx(0.50)
    assert result.provider_tokens_input == 300
    assert result.provider_tokens_output == 50
    assert result.cost_per_completed_task_usd == pytest.approx(0.25)
    assert result.repo_pr_opened_event_count == 1
    assert result.time_to_merge_proxy_sample_count == 1
    assert result.time_to_merge_proxy_median_ms == pytest.approx(6_300_000.0)
    assert result.approval_wait_sample_count == 2
    assert result.approval_wait_median_ms == pytest.approx(4_500_000.0)


@pytest.mark.asyncio
async def test_orchestrator_kpi_rollup_returns_none_for_missing_root_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _seed_rollup_fixture(session)

        result = await OrchestratorKpiRollupService(session).fetch(
            tenant_id=TENANT_ID,
            root_run_id=UUID("00000000-0000-4000-8000-00000000ffff"),
        )

    assert result is None
