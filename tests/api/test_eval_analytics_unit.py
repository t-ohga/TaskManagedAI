"""ADR-00051 (SP-026) KPI analytics の no-DB unit test。

SQL introspection (tenant/active-scope/date_trunc/group by) + 既存 metric service との公式 drift guard
(F-009) + KPI definition authority + range vocab を host で固定する。集計値の正しさは
test_eval_analytics_db.py で DB-gated 検証。
"""

from __future__ import annotations

import inspect

from backend.app.services.eval.kpi_timeseries import (
    ACCEPTANCE_DECIDED_STATUSES,
    APPROVAL_DECIDED_STATUSES,
    BUCKETS,
    KPI_DEFINITIONS,
    RANGES,
    TIME_TO_MERGE_PROXY_SOURCE,
    _bucketed_acceptance_sql,
    _bucketed_approval_sql,
    _bucketed_citation_sql,
    _bucketed_cost_sql,
    _bucketed_time_to_merge_sql,
    range_cutoff,
)

EXPECTED_KPI_IDS = {
    "acceptance_pass_rate",
    "approval_wait_ms",
    "citation_coverage",
    "cost_per_completed_task",
    "time_to_merge",
}


def _sql(stmt: object) -> str:
    # raw TextClause SQL (:bucket 等の bound param 名を保持、introspection 用)。
    return str(stmt.text)  # type: ignore[attr-defined]


# --- KPI definitions (backend authority、F-009) ---


def test_kpi_definitions_cover_5_kpis() -> None:
    assert {d.kpi_id for d in KPI_DEFINITIONS} == EXPECTED_KPI_IDS
    assert len(KPI_DEFINITIONS) == 5


def test_kpi_thresholds_match_fixture_kpi_values() -> None:
    by_id = {d.kpi_id: d for d in KPI_DEFINITIONS}
    assert by_id["acceptance_pass_rate"].threshold == 0.60
    assert by_id["citation_coverage"].threshold == 0.90
    assert by_id["cost_per_completed_task"].threshold == 0.50
    assert by_id["approval_wait_ms"].threshold == 14_400_000.0  # 4h ms
    assert by_id["time_to_merge"].measurement_kind == "proxy"  # F-004


# --- range vocab (F-006) ---


def test_range_vocab_is_week_month_quarter() -> None:
    assert set(RANGES) == {"week", "month", "quarter"}
    assert "year" not in RANGES
    assert set(BUCKETS) == {"day", "week"}


def test_range_cutoff_days() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 6, 5, tzinfo=UTC)
    assert (now - range_cutoff("week", now=now)).days == 7
    assert (now - range_cutoff("month", now=now)).days == 30
    assert (now - range_cutoff("quarter", now=now)).days == 90


# --- SQL introspection: tenant + active-scope + UTC bucket + group by ---


def test_all_bucketed_sql_use_utc_date_trunc_and_group_by() -> None:
    for fn in (
        _bucketed_acceptance_sql,
        _bucketed_approval_sql,
        _bucketed_citation_sql,
        _bucketed_cost_sql,
        _bucketed_time_to_merge_sql,
    ):
        sql = _sql(fn())
        assert "date_trunc(:bucket" in sql, fn.__name__
        assert "'UTC'" in sql, fn.__name__
        assert "group by" in sql.lower(), fn.__name__
        assert ":tenant_id" in sql, fn.__name__
        assert ":cutoff" in sql, fn.__name__


def test_run_based_sql_enforce_soft_delete_active_scope() -> None:
    # cost / time_to_merge / acceptance / citation は soft-deleted ticket を除外する (adversarial F-1)。
    for fn in (
        _bucketed_cost_sql,
        _bucketed_time_to_merge_sql,
        _bucketed_acceptance_sql,
        _bucketed_citation_sql,
    ):
        sql = _sql(fn()).lower()
        assert "not exists" in sql, fn.__name__
        assert "deleted_at is not null" in sql, fn.__name__


def test_unattributed_approval_only_counts_null_or_stale_run() -> None:
    # adversarial F-2: 別 project の approval を unattributed に数えない。run_id null / join 不成立のみ。
    from backend.app.services.eval.kpi_timeseries import _unattributed_approval_sql

    sql = _sql(_unattributed_approval_sql()).lower()
    assert "arq.run_id is null or ar.id is null" in sql
    assert "project_id is distinct" not in sql  # 旧 over-count predicate を残さない


def test_approval_sql_supports_project_filter_join() -> None:
    sql = _sql(_bucketed_approval_sql()).lower()
    # project filter は run_id -> agent_runs join 経由 (F-003)。
    assert "left join agent_runs" in sql
    assert "ar.id = arq.run_id" in sql
    assert "project_id" in sql


# --- 公式 drift guard (F-009): 既存 metric service と一致 ---


def test_approval_statuses_match_existing_service() -> None:
    # ApprovalWaitMsMetricService の status set (approved/rejected) と一致。
    from backend.app.services.metrics import approval_wait_ms as svc

    src = inspect.getsource(svc)
    assert '"approved"' in src and '"rejected"' in src
    assert set(APPROVAL_DECIDED_STATUSES) == {"approved", "rejected"}
    # decided_at >= requested_at の gaming 防止条件も既存 service に存在。
    assert "decided_at >= ApprovalRequest.requested_at" in src


def test_approval_sql_carries_decided_at_contract() -> None:
    sql = _sql(_bucketed_approval_sql()).lower()
    assert "decided_at is not null" in sql
    assert "decided_at >= arq.requested_at" in sql
    assert "'approved'" in sql and "'rejected'" in sql


def test_cost_expr_matches_orchestrator_service() -> None:
    # provider cost 抽出が OrchestratorKpiRollupService の公式と一致 (drift 防止)。
    from backend.app.services.metrics import orchestrator_kpi_rollup as svc

    orch_sql = inspect.getsource(svc)
    cost_sql = _sql(_bucketed_cost_sql())
    # 既存 service の cost 抽出フラグメントが本 module の cost SQL にも現れる。
    assert "{usage,cost_usd}" in orch_sql
    assert "usage,cost_usd" in cost_sql
    assert "provider_responded" in cost_sql
    # 分母 = 全 completed run (status='completed')。
    assert "status = 'completed'" in cost_sql


def test_time_to_merge_proxy_source_matches_service() -> None:
    from backend.app.services.metrics import agent_run_kpi as svc

    src = inspect.getsource(svc)
    assert TIME_TO_MERGE_PROXY_SOURCE in src
    assert TIME_TO_MERGE_PROXY_SOURCE == "repo_pr_opened_to_agent_run_completed"
    # proxy SQL が repo_pr_opened first -> completed の wait を測る。
    ttm_sql = _sql(_bucketed_time_to_merge_sql()).lower()
    assert "repo_pr_opened" in ttm_sql
    assert "completed_at" in ttm_sql


def test_citation_uses_final_adopted_not_raw_claims() -> None:
    # F-001: citation 分母は final-adopted artifact (raw claims ではない)。
    sql = _sql(_bucketed_citation_sql()).lower()
    assert "adopted_artifacts" in sql
    assert "adoption_state = 'final'" in sql
    assert "sample_claims" in sql
    assert "citation_ids" in sql


def test_acceptance_statuses() -> None:
    assert set(ACCEPTANCE_DECIDED_STATUSES) == {"satisfied", "rejected"}
    sql = _sql(_bucketed_acceptance_sql()).lower()
    assert "'satisfied'" in sql
    assert "acceptance_criteria" in sql
