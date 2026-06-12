"""ADR-00051 (SP-026) KPI analytics の DB-backed smoke + 集計 contract test。

本 test は **bucketed SQL が実 PostgreSQL で実行可能**であること (column / jsonb operator /
percentile_cont / date_trunc 'UTC' bucket の構文) を固定する。host の compile-only introspection
(test_eval_analytics_unit.py) では catch できない実行時エラーを検出する。各 KPI 公式の値正しさは
既存 metric service の DB test + 本 module の drift guard で担保する。

DB 接続必要: TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container (host では skip)。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.seeds.initial import (
    DEFAULT_ACTOR_ID,
    DEFAULT_PROJECT_ID,
    DEFAULT_TENANT_ID,
    seed_initial,
)
from backend.app.services.eval.kpi_timeseries import KPI_DEFINITIONS, KpiTimeseriesService

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)


def _integration_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-eval-analytics",
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
        if os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") == "1":
            raise AssertionError("eval analytics test requires PostgreSQL.") from exc
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
    # seed_initial は呼び出し側 commit が前提 (内部 commit しない)。begin() で確実に commit し、
    # 他 test file の seed に依存せず本 file 単独でも project/actor が存在する状態にする。
    # さらに data table を reset し、test 間で acceptance_criteria/tickets が蓄積して KPI 集計が
    # 混ざるのを防ぐ (本 file は per-test の独立 data を前提)。
    async with factory.begin() as session:
        await session.execute(
            text("truncate acceptance_criteria, tickets restart identity cascade")
        )
        await seed_initial(session)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_kpi_timeseries_sql_executes_on_postgres(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """全 5 KPI の bucketed SQL が実 PostgreSQL で実行でき、5 series を返す (構文/column/jsonb smoke)。"""
    async with session_factory() as session:
        result = await KpiTimeseriesService(session).compute(
            tenant_id=DEFAULT_TENANT_ID,
            bucket="day",
            range_value="quarter",
            project_id=None,
        )
    assert {s.kpi_id for s in result.series} == {d.kpi_id for d in KPI_DEFINITIONS}
    assert len(result.series) == 5
    assert result.unattributed_approval_count == 0


@pytest.mark.asyncio
async def test_kpi_timeseries_with_project_filter_executes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """project filter 付き (run_id join 経由 approval 含む) でも SQL が実行でき unattributed を返す。"""
    async with session_factory() as session:
        result = await KpiTimeseriesService(session).compute(
            tenant_id=DEFAULT_TENANT_ID,
            bucket="week",
            range_value="month",
            project_id=DEFAULT_PROJECT_ID,
        )
    assert len(result.series) == 5
    assert result.project_id == DEFAULT_PROJECT_ID
    assert result.unattributed_approval_count >= 0


@pytest.mark.asyncio
async def test_acceptance_pass_rate_ratio_and_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """acceptance_criteria の satisfied/rejected から ratio + measured state を集計する。"""
    now = datetime.now(UTC)
    async with session_factory() as session:
        # 同一 bucket に satisfied x2 + rejected x1 を投入 (ticket-less は不可なので ticket を作る)。
        ticket_id = uuid4()
        await session.execute(
            text(
                "insert into tickets (id, tenant_id, project_id, slug, title, status, priority, "
                "created_by_actor_id) "
                "values (:id, :t, :p, :slug, 'KPI acceptance', 'open', 'medium', :actor)"
            ),
            {
                "id": ticket_id,
                "t": DEFAULT_TENANT_ID,
                "p": DEFAULT_PROJECT_ID,
                "slug": f"acc-{ticket_id}",
                "actor": str(DEFAULT_ACTOR_ID),
            },
        )
        for status_value, n in (("satisfied", 2), ("rejected", 1)):
            for _ in range(n):
                await session.execute(
                    text(
                        "insert into acceptance_criteria "
                        "(id, tenant_id, project_id, ticket_id, description, status, created_at) "
                        "values (:id, :t, :p, :tk, 'c', :st, :ts)"
                    ),
                    {
                        "id": uuid4(),
                        "t": DEFAULT_TENANT_ID,
                        "p": DEFAULT_PROJECT_ID,
                        "tk": ticket_id,
                        "st": status_value,
                        "ts": now,
                    },
                )
        await session.commit()

    async with session_factory() as session:
        result = await KpiTimeseriesService(session).compute(
            tenant_id=DEFAULT_TENANT_ID,
            bucket="day",
            range_value="quarter",
            project_id=DEFAULT_PROJECT_ID,
        )
    acceptance = next(s for s in result.series if s.kpi_id == "acceptance_pass_rate")
    measured = [b for b in acceptance.buckets if b.state == "measured"]
    assert measured, "acceptance に measured bucket が無い"
    # satisfied 2 / (satisfied 2 + rejected 1) = 2/3
    assert any(abs((b.value or 0) - (2 / 3)) < 1e-9 for b in measured)


@pytest.mark.asyncio
async def test_acceptance_no_denominator_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """deferred/pending のみ (decided 0) の bucket は no_denominator (value=null) で 0 と区別する。"""
    now = datetime.now(UTC)
    async with session_factory() as session:
        ticket_id = uuid4()
        await session.execute(
            text(
                "insert into tickets (id, tenant_id, project_id, slug, title, status, priority, "
                "created_by_actor_id) "
                "values (:id, :t, :p, :slug, 'KPI pending', 'open', 'medium', :actor)"
            ),
            {
                "id": ticket_id,
                "t": DEFAULT_TENANT_ID,
                "p": DEFAULT_PROJECT_ID,
                "slug": f"pend-{ticket_id}",
                "actor": str(DEFAULT_ACTOR_ID),
            },
        )
        await session.execute(
            text(
                "insert into acceptance_criteria "
                "(id, tenant_id, project_id, ticket_id, description, status, created_at) "
                "values (:id, :t, :p, :tk, 'c', 'pending', :ts)"
            ),
            {"id": uuid4(), "t": DEFAULT_TENANT_ID, "p": DEFAULT_PROJECT_ID, "tk": ticket_id, "ts": now},
        )
        await session.commit()
    async with session_factory() as session:
        result = await KpiTimeseriesService(session).compute(
            tenant_id=DEFAULT_TENANT_ID,
            bucket="day",
            range_value="quarter",
            project_id=DEFAULT_PROJECT_ID,
        )
    acceptance = next(s for s in result.series if s.kpi_id == "acceptance_pass_rate")
    no_denom = [b for b in acceptance.buckets if b.state == "no_denominator"]
    assert any(b.value is None and b.denominator_count == 0 for b in no_denom)


@pytest.mark.asyncio
async def test_provider_breakdown_sql_executes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """provider_breakdown SQL が実 PostgreSQL で実行できる (eval_runs ⋈ eval_scores、percentile_cont)。"""
    from backend.app.api.eval_analytics import _PROVIDER_BREAKDOWN_SQL
    from backend.app.services.eval.kpi_timeseries import range_cutoff

    async with session_factory() as session:
        rows = (
            await session.execute(
                _PROVIDER_BREAKDOWN_SQL,
                {"tenant_id": DEFAULT_TENANT_ID, "cutoff": range_cutoff("quarter")},
            )
        ).mappings().all()
    # seed には eval_runs が無いので空。SQL が実行できることが本 test の核 (構文 smoke)。
    assert isinstance(rows, list)
