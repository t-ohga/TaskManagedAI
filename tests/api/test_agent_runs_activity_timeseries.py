"""ADR-00040: AgentRun activity_timeseries endpoint のテスト (D-3/D-4, read-only).

- route 登録 + `/{run_id}` より **前** に定義される route ordering
- bucket は Literal[day,week] で検証、不正値は 422
- response schema が bucket_start / run_count / cost_usd / measured_run_count /
  unmeasured_run_count のみ (raw secret なし)
- **SQL introspection** (Codex ADR R1-1、強化): compile した SQL に tenant 境界 / active-scope の
  NOT EXISTS 極性 + tenant/project/ticket_id 相関 + deleted_at 内側配置 / date_trunc / GROUP BY が
  含まれることを assert (EXISTS / 非相関 / 極性反転 / predicate 削除を no-DB で catch)。

注: seed-based DB negative (soft-deleted ticket bound 除外 / ticket-less 包含 / restore / cost
measurement の null vs 0) は ADR-00040 テスト指針に従い CI Compose postgres で検証する
(host dev は conftest の test-password 不一致で実行不可)。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api import agent_runs as agent_runs_api
from backend.app.config import Settings
from backend.app.main import create_app


class _CapturingResult:
    def __init__(self, rows: list[object] | None = None) -> None:
        self._rows = rows or []

    def all(self) -> list[object]:
        return self._rows


class _CapturingSession:
    def __init__(self, rows: list[object] | None = None) -> None:
        self.statements: list[object] = []
        self._rows = rows or []

    async def execute(self, statement: object, *args: object, **kwargs: object) -> _CapturingResult:
        self.statements.append(statement)
        return _CapturingResult(self._rows)


def _compiled_sql(statement: object) -> str:
    compiled = statement.compile(compile_kwargs={"literal_binds": False})  # type: ignore[attr-defined]
    return " ".join(str(compiled).split())


def _settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        dev_login_cookie_secret="test-cookie-secret-for-activity-timeseries-api",
    )


def test_activity_timeseries_route_is_registered() -> None:
    app = create_app(_settings())
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/v1/agent_runs/activity_timeseries" in paths


def test_activity_timeseries_route_registered_before_run_id_detail() -> None:
    app = create_app(_settings())
    paths = [getattr(route, "path", None) for route in app.routes]
    assert paths.index("/api/v1/agent_runs/activity_timeseries") < paths.index(
        "/api/v1/agent_runs/{run_id}"
    )


def test_activity_timeseries_response_schema_has_no_secret_fields() -> None:
    bucket_fields = set(agent_runs_api.ActivityBucket.model_fields.keys())
    assert bucket_fields == {
        "bucket_start",
        "run_count",
        "cost_usd",
        "measured_run_count",
        "unmeasured_run_count",
    }
    resp_fields = set(agent_runs_api.ActivityTimeseriesResponse.model_fields.keys())
    assert resp_fields == {"buckets", "bucket", "range"}
    for forbidden in ("secret", "token_hash", "api_key", "provider_key", "capability"):
        assert not any(forbidden in f for f in bucket_fields | resp_fields)


def test_activity_timeseries_bucket_param_constrained_to_day_week() -> None:
    # bucket は Literal["day","week"] (FastAPI が enum 検証、非 enum は 422)。
    # OpenAPI schema の enum で制約を確認 (HTTP request は app lifespan が DB 接続するため host で不可)。
    app = create_app(_settings())
    schema = app.openapi()
    params = schema["paths"]["/api/v1/agent_runs/activity_timeseries"]["get"]["parameters"]
    bucket_param = next(p for p in params if p["name"] == "bucket")
    assert set(bucket_param["schema"]["enum"]) == {"day", "week"}


def test_activity_timeseries_query_applies_tenant_active_scope_and_bucketing() -> None:
    # tenant 境界 + active-scope (NOT EXISTS 極性 + 相関 + deleted_at) + date_trunc + GROUP BY
    # が SQL に含まれること (ADR-00040 R1-1)。
    session = _CapturingSession()
    asyncio.run(
        agent_runs_api.activity_timeseries_endpoint(
            bucket="day",
            range_value="month",
            actor_id=uuid4(),
            tenant_id=1,
            session=cast(AsyncSession, session),
        )
    )
    assert len(session.statements) == 1
    sql = _compiled_sql(session.statements[0])
    assert "agent_runs.tenant_id =" in sql
    # active-scope: NOT EXISTS の極性 + 相関 + deleted_at 内側配置
    assert "NOT (EXISTS" in sql
    assert "tickets.tenant_id = agent_runs.tenant_id" in sql
    assert "tickets.project_id = agent_runs.project_id" in sql
    assert "tickets.id = agent_runs.ticket_id" in sql
    assert "tickets.deleted_at IS NOT NULL" in sql
    # bucket 化 + GROUP BY
    assert "date_trunc(" in sql
    assert "GROUP BY date_trunc" in sql
    # UTC 固定 bucket (3 引数 date_trunc(bucket, created_at, 'UTC'))。session TimeZone 非依存 (R2)。
    # literal_binds で 'UTC' を確認 (range='all' で cutoff datetime bind を避ける)。
    session_utc = _CapturingSession()
    asyncio.run(
        agent_runs_api.activity_timeseries_endpoint(
            bucket="day",
            range_value="all",
            actor_id=uuid4(),
            tenant_id=1,
            session=cast(AsyncSession, session_utc),
        )
    )
    sql_literal = str(
        session_utc.statements[0].compile(compile_kwargs={"literal_binds": True})  # type: ignore[attr-defined]
    )
    assert "'UTC'" in sql_literal


def test_activity_timeseries_row_mapping_null_zero_and_measured_math() -> None:
    # response 変換を fake rows で検証 (Codex R1-2、no-DB):
    # cost_usd の null (measured 0) vs 0、measured + unmeasured == run_count、sparse 保持。
    # 各 row = (bucket_start, run_count, cost_sum, measured_count)。
    rows: list[object] = [
        (datetime(2026, 5, 1, tzinfo=UTC), 5, Decimal("3.21"), 5),  # all measured
        (datetime(2026, 5, 3, tzinfo=UTC), 4, Decimal("0"), 0),  # all unmeasured → cost null
        (datetime(2026, 5, 4, tzinfo=UTC), 6, Decimal("2.00"), 2),  # mixed (2 measured / 4 unmeasured)
    ]
    session = _CapturingSession(rows)
    resp = asyncio.run(
        agent_runs_api.activity_timeseries_endpoint(
            bucket="day",
            range_value="month",
            actor_id=uuid4(),
            tenant_id=1,
            session=cast(AsyncSession, session),
        )
    )
    assert len(resp.buckets) == 3
    # all measured
    assert resp.buckets[0].run_count == 5
    assert resp.buckets[0].cost_usd == 3.21
    assert resp.buckets[0].measured_run_count == 5
    assert resp.buckets[0].unmeasured_run_count == 0
    # all unmeasured → cost_usd は null (0 に丸めない)
    assert resp.buckets[1].run_count == 4
    assert resp.buckets[1].cost_usd is None
    assert resp.buckets[1].measured_run_count == 0
    assert resp.buckets[1].unmeasured_run_count == 4
    # mixed
    assert resp.buckets[2].cost_usd == 2.0
    assert resp.buckets[2].measured_run_count == 2
    assert resp.buckets[2].unmeasured_run_count == 4
    # measured + unmeasured == run_count (不変条件)
    for b in resp.buckets:
        assert b.measured_run_count + b.unmeasured_run_count == b.run_count
