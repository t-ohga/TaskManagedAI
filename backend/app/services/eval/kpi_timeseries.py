"""ADR-00051 (SP-026) operational KPI time series aggregation。

既存 metric service (`OrchestratorKpiRollupService` / `ApprovalWaitMsMetricService` /
`AdoptedArtifactCitationCoverageService` / `AgentRunKpiService`) の **公式を再利用**し、tenant/project-wide +
`date_trunc(bucket, <time_col>, 'UTC')` の time-series へ拡張する (公式を独自再実装しない、Pack 残リスク回避)。

各 KPI の formula 定数 (status set / denominator / cost extraction / proxy) は本 module の module-level 定数で
明示し、`tests/.../test_kpi_timeseries_drift.py` で既存 service の定数と一致を固定する (F-009)。fixture P0-Exit
KPI (`compute_kpi_rollup`) は別物 (point-in-time)、本 module は live operational trend。
"""

# ruff: noqa: S608 - 本 module の SQL は全て trusted module 定数 (status set / cost expr) のみ補間し、
# caller 入力 (bucket / tenant_id / cutoff / project_id) は全て bound param。injection 面は無い。

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)

KpiId = Literal[
    "acceptance_pass_rate",
    "approval_wait_ms",
    "citation_coverage",
    "cost_per_completed_task",
    "time_to_merge",
]
Bucket = Literal["day", "week"]
TimeseriesRange = Literal["week", "month", "quarter"]
BucketState = Literal["measured", "no_denominator", "partial_unmeasured", "proxy"]
MeasurementKind = Literal["measured", "proxy"]
KpiDirection = Literal["higher_better", "lower_better"]

BUCKETS: tuple[Bucket, ...] = ("day", "week")
RANGES: tuple[TimeseriesRange, ...] = ("week", "month", "quarter")
# 既存 CostSummaryRange と同じ cutoff (week=7d / month=30d / quarter=90d、ADR-00040、F-006)。
_RANGE_DAYS: dict[TimeseriesRange, int] = {"week": 7, "month": 30, "quarter": 90}

# --- drift guard: 既存 metric service の公式定数を本 module で明示 (F-009) ---
# ApprovalWaitMsMetricService.aggregate と一致 (status set + decided_at>=requested_at)。
APPROVAL_DECIDED_STATUSES: tuple[str, ...] = ("approved", "rejected")
# acceptance operational: acceptance_criteria.status (fixture AC-KPI-01 と semantics 同一)。
ACCEPTANCE_PASS_STATUS = "satisfied"  # noqa: S105 - acceptance_criteria status 値 (secret ではない)
ACCEPTANCE_DECIDED_STATUSES: tuple[str, ...] = ("satisfied", "rejected")
# AgentRunKpiService.time_to_merge_proxy_source と一致。
TIME_TO_MERGE_PROXY_SOURCE = "repo_pr_opened_to_agent_run_completed"


@dataclass(frozen=True)
class KpiDefinition:
    kpi_id: KpiId
    unit: str
    threshold: float
    direction: KpiDirection
    measurement_kind: MeasurementKind


# backend authority (F-009): unit / threshold / direction / measurement_kind は backend が正本。
# threshold は fixture KPI (eval/quality manifest) と同値。
KPI_DEFINITIONS: tuple[KpiDefinition, ...] = (
    KpiDefinition("acceptance_pass_rate", "ratio", 0.60, "higher_better", "measured"),
    KpiDefinition("time_to_merge", "ms", 7_200_000.0, "lower_better", "proxy"),
    KpiDefinition("approval_wait_ms", "ms", 14_400_000.0, "lower_better", "measured"),
    KpiDefinition("citation_coverage", "ratio", 0.90, "higher_better", "measured"),
    KpiDefinition("cost_per_completed_task", "usd", 0.50, "lower_better", "measured"),
)
_DEFINITION_BY_ID: dict[KpiId, KpiDefinition] = {d.kpi_id: d for d in KPI_DEFINITIONS}


@dataclass(frozen=True)
class KpiBucket:
    bucket_start: datetime
    value: float | None
    state: BucketState
    numerator_count: int | None
    denominator_count: int | None
    measured_count: int | None
    unmeasured_count: int | None


@dataclass(frozen=True)
class KpiSeries:
    kpi_id: KpiId
    unit: str
    threshold: float
    direction: KpiDirection
    measurement_kind: MeasurementKind
    buckets: tuple[KpiBucket, ...]


@dataclass(frozen=True)
class KpiTimeseries:
    bucket: Bucket
    range: TimeseriesRange
    project_id: UUID | None
    unattributed_approval_count: int
    series: tuple[KpiSeries, ...]


def range_cutoff(range_value: TimeseriesRange, *, now: datetime | None = None) -> datetime:
    """range から created_at/requested_at cutoff を server 側で算出 (caller-supplied date 禁止)。"""
    base = now if now is not None else datetime.now(UTC)
    return base - timedelta(days=_RANGE_DAYS[range_value])


# --- provider cost 抽出 (OrchestratorKpiRollupService と一致、drift guard 対象) ---
# provider_responded event の usage.cost_usd / cost_usd (numeric-shaped) を抽出。
_PROVIDER_COST_EXPR = (
    "case "
    "when jsonb_typeof(e.event_payload->'usage') = 'object' "
    " and (e.event_payload #>> '{usage,cost_usd}') ~ '^[0-9]+(\\.[0-9]+)?$' "
    "then (e.event_payload #>> '{usage,cost_usd}')::numeric "
    "when (e.event_payload->>'cost_usd') ~ '^[0-9]+(\\.[0-9]+)?$' "
    "then (e.event_payload->>'cost_usd')::numeric else null end"
)


def _bucketed_acceptance_sql() -> sa.TextClause:
    return sa.text(
        f"""
        select date_trunc(:bucket, ac.created_at, 'UTC') as bucket_start,
               count(*) filter (where ac.status = '{ACCEPTANCE_PASS_STATUS}') as numerator,
               count(*) filter (
                   where ac.status in ('satisfied','rejected')
               ) as denominator
          from acceptance_criteria ac
         where ac.tenant_id = :tenant_id
           and ac.created_at >= :cutoff
           and (cast(:project_id as uuid) is null or ac.project_id = cast(:project_id as uuid))
           and not exists (
               select 1 from tickets t
                where t.tenant_id = ac.tenant_id
                  and t.project_id = ac.project_id
                  and t.id = ac.ticket_id
                  and t.deleted_at is not null
           )
         group by 1
         order by 1
        """
    )


def _bucketed_approval_sql() -> sa.TextClause:
    statuses = ", ".join(f"'{s}'" for s in APPROVAL_DECIDED_STATUSES)
    return sa.text(
        f"""
        select date_trunc(:bucket, arq.requested_at, 'UTC') as bucket_start,
               percentile_cont(0.5) within group (
                   order by extract(epoch from (arq.decided_at - arq.requested_at)) * 1000.0
               ) as median_ms,
               count(*) as sample_count
          from approval_requests arq
          left join agent_runs ar
            on ar.tenant_id = arq.tenant_id and ar.id = arq.run_id
         where arq.tenant_id = :tenant_id
           and arq.status in ({statuses})
           and arq.decided_at is not null
           and arq.decided_at >= arq.requested_at
           and arq.requested_at >= :cutoff
           and (cast(:project_id as uuid) is null or ar.project_id = cast(:project_id as uuid))
         group by 1
         order by 1
        """
    )


def _unattributed_approval_sql() -> sa.TextClause:
    """run 未紐付 (run_id null) / stale (run 不存在) で **どの project にも attribute 不能**な approval 数。

    adversarial F-2 fix: 旧版は `ar.project_id is distinct from :project_id` で **別 project の正当な
    approval まで unattributed に数えていた** (project B の approval が project A view で「run 未紐付」と
    誤表示)。本来 unattributed = run_id null か join 不成立 (stale run_id) のみ。別 project の approval は
    その project に正しく attribute 済なので unattributed ではない。
    """
    statuses = ", ".join(f"'{s}'" for s in APPROVAL_DECIDED_STATUSES)
    return sa.text(
        f"""
        select count(*) as unattributed
          from approval_requests arq
          left join agent_runs ar
            on ar.tenant_id = arq.tenant_id and ar.id = arq.run_id
         where arq.tenant_id = :tenant_id
           and arq.status in ({statuses})
           and arq.decided_at is not null
           and arq.decided_at >= arq.requested_at
           and arq.requested_at >= :cutoff
           and (arq.run_id is null or ar.id is null)
        """
    )


def _bucketed_citation_sql() -> sa.TextClause:
    # AdoptedArtifactCitationCoverageService の final-adopted + sample_claims/citation_ids 公式を、
    # tenant/project-wide + finalized_at bucket へ拡張 (run_tree なし)。
    return sa.text(
        r"""
        with final_adoptions as (
            select aa.project_id, aa.run_id, aa.artifact_id, aa.finalized_at, a.content_jsonb
              from adopted_artifacts aa
              join artifacts a
                on a.tenant_id = aa.tenant_id and a.project_id = aa.project_id
               and a.run_id = aa.run_id and a.id = aa.artifact_id
             where aa.tenant_id = :tenant_id
               and aa.adoption_state = 'final'
               and aa.finalized_at >= :cutoff
               and (cast(:project_id as uuid) is null or aa.project_id = cast(:project_id as uuid))
               -- adversarial F-1 fix: artifact の run が soft-deleted ticket に紐づく場合は除外
               -- (cost / time_to_merge / acceptance と同じ soft_deleted_ticket_run_exclusion 整合)。
               and not exists (
                   select 1 from agent_runs ar
                   join tickets t
                     on t.tenant_id = ar.tenant_id and t.project_id = ar.project_id
                    and t.id = ar.ticket_id
                  where ar.tenant_id = aa.tenant_id
                    and ar.project_id = aa.project_id
                    and ar.id = aa.run_id
                    and t.deleted_at is not null
               )
        ),
        claim_rows as (
            select fa.artifact_id, fa.finalized_at, claim.value as claim_json
              from final_adoptions fa
              cross join lateral jsonb_array_elements(
                case
                    when jsonb_typeof(fa.content_jsonb->'sample_claims') = 'array'
                    then fa.content_jsonb->'sample_claims'
                    when jsonb_typeof(fa.content_jsonb#>'{input,sample_claims}') = 'array'
                    then fa.content_jsonb#>'{input,sample_claims}'
                    else '[]'::jsonb
                end
              ) as claim(value)
        ),
        normalized_claims as (
            select artifact_id,
                   date_trunc(:bucket, finalized_at, 'UTC') as bucket_start,
                   claim_json->>'claim_id' as claim_id,
                   bool_or(
                       case
                           when jsonb_typeof(claim_json->'citation_ids') = 'array'
                           then jsonb_array_length(claim_json->'citation_ids') > 0
                           else false
                       end
                   ) as has_citation
              from claim_rows
             where jsonb_typeof(claim_json) = 'object'
               and nullif(claim_json->>'claim_id', '') is not null
             group by artifact_id, bucket_start, claim_json->>'claim_id'
        )
        select bucket_start,
               count(*) filter (where has_citation is true) as numerator,
               count(*) as denominator
          from normalized_claims
         group by bucket_start
         order by bucket_start
        """
    )


def _bucketed_cost_sql() -> sa.TextClause:
    # OrchestratorKpiRollupService の cost_per_completed_task 公式 (provider_responded cost / completed run)
    # を tenant/project-wide + completed_at bucket + active-scope へ拡張。
    return sa.text(
        f"""
        with completed_runs as (
            select ar.id, ar.completed_at,
                   date_trunc(:bucket, ar.completed_at, 'UTC') as bucket_start
              from agent_runs ar
             where ar.tenant_id = :tenant_id
               and ar.status = 'completed'
               -- SP-029 (ADR-00055 §設計制約 8): shadow run の cost を production KPI から除外。
               and ar.run_mode = 'production'
               and ar.completed_at is not null
               and ar.completed_at >= :cutoff
               and (cast(:project_id as uuid) is null or ar.project_id = cast(:project_id as uuid))
               and not exists (
                   select 1 from tickets t
                    where t.tenant_id = ar.tenant_id
                      and t.project_id = ar.project_id
                      and t.id = ar.ticket_id
                      and t.deleted_at is not null
               )
        ),
        run_cost as (
            select cr.id, cr.bucket_start,
                   (
                     select coalesce(sum({_PROVIDER_COST_EXPR}), 0)
                       from agent_run_events e
                      where e.tenant_id = :tenant_id
                        and e.run_id = cr.id
                        and e.event_type = 'provider_responded'
                   ) as cost_usd,
                   (
                     select count(*) filter (where {_PROVIDER_COST_EXPR} is not null)
                       from agent_run_events e
                      where e.tenant_id = :tenant_id
                        and e.run_id = cr.id
                        and e.event_type = 'provider_responded'
                   ) as measured_cost_event_count
              from completed_runs cr
        )
        select bucket_start,
               count(*) as completed_run_count,
               count(*) filter (where measured_cost_event_count > 0) as measured_count,
               count(*) filter (where measured_cost_event_count = 0) as unmeasured_count,
               coalesce(sum(cost_usd), 0) as total_cost
          from run_cost
         group by bucket_start
         order by bucket_start
        """
    )


def _bucketed_time_to_merge_sql() -> sa.TextClause:
    # AgentRunKpiService time_to_merge_proxy (repo_pr_opened first -> completed_at) を tenant/project-wide
    # + completed_at bucket + active-scope へ拡張。
    return sa.text(
        """
        with completed_runs as (
            select ar.id, ar.completed_at,
                   date_trunc(:bucket, ar.completed_at, 'UTC') as bucket_start
              from agent_runs ar
             where ar.tenant_id = :tenant_id
               and ar.status = 'completed'
               -- SP-029 (ADR-00055 §設計制約 8): shadow run を production time_to_merge KPI から除外。
               and ar.run_mode = 'production'
               and ar.completed_at is not null
               and ar.completed_at >= :cutoff
               and (cast(:project_id as uuid) is null or ar.project_id = cast(:project_id as uuid))
               and not exists (
                   select 1 from tickets t
                    where t.tenant_id = ar.tenant_id
                      and t.project_id = ar.project_id
                      and t.id = ar.ticket_id
                      and t.deleted_at is not null
               )
        ),
        pr_opened as (
            select e.run_id, min(e.created_at) as first_pr_opened_at
              from agent_run_events e
              join completed_runs cr on cr.id = e.run_id
             where e.tenant_id = :tenant_id
               and e.event_type = 'repo_pr_opened'
             group by e.run_id
        ),
        proxy_samples as (
            select cr.bucket_start,
                   extract(epoch from (cr.completed_at - p.first_pr_opened_at)) * 1000.0 as wait_ms
              from completed_runs cr
              join pr_opened p on p.run_id = cr.id
             where cr.completed_at >= p.first_pr_opened_at
        )
        select bucket_start,
               count(*) as sample_count,
               percentile_cont(0.5) within group (order by wait_ms) as median_ms
          from proxy_samples
         group by bucket_start
         order by bucket_start
        """
    )


def _ratio_bucket(bucket_start: datetime, numerator: int, denominator: int) -> KpiBucket:
    if denominator == 0:
        return KpiBucket(bucket_start, None, "no_denominator", numerator, 0, None, None)
    return KpiBucket(
        bucket_start,
        numerator / denominator,
        "measured",
        numerator,
        denominator,
        None,
        None,
    )


def _median_bucket(bucket_start: datetime, sample_count: int, median: float | None) -> KpiBucket:
    if sample_count == 0 or median is None:
        return KpiBucket(bucket_start, None, "no_denominator", None, sample_count, None, None)
    return KpiBucket(bucket_start, float(median), "measured", None, sample_count, None, None)


def _proxy_bucket(bucket_start: datetime, sample_count: int, median: float | None) -> KpiBucket:
    if sample_count == 0 or median is None:
        return KpiBucket(bucket_start, None, "no_denominator", None, sample_count, None, None)
    return KpiBucket(bucket_start, float(median), "proxy", None, sample_count, None, None)


def _opt_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float | Decimal | str):
        return float(value)
    raise TypeError(f"expected float-compatible value, got {type(value).__name__}")


def _to_int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, int | float | Decimal | str):
        return int(value)
    raise TypeError(f"expected int-compatible value, got {type(value).__name__}")


class KpiTimeseriesService:
    """operational KPI を time-series 集計する read-only service (ADR-00051)。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def compute(
        self,
        *,
        tenant_id: int,
        bucket: Bucket,
        range_value: TimeseriesRange,
        project_id: UUID | None,
        now: datetime | None = None,
    ) -> KpiTimeseries:
        if bucket not in BUCKETS:
            raise ValueError(f"unsupported bucket: {bucket!r}")
        if range_value not in RANGES:
            raise ValueError(f"unsupported range: {range_value!r}")
        await self._ensure_tenant_context(tenant_id)
        cutoff = range_cutoff(range_value, now=now)
        params: dict[str, object] = {
            "bucket": bucket,
            "tenant_id": tenant_id,
            "cutoff": cutoff,
            "project_id": str(project_id) if project_id is not None else None,
        }

        acceptance = await self._ratio_series("acceptance_pass_rate", _bucketed_acceptance_sql(), params)
        citation = await self._ratio_series("citation_coverage", _bucketed_citation_sql(), params)
        approval = await self._median_series("approval_wait_ms", _bucketed_approval_sql(), params)
        cost = await self._cost_series(params)
        time_to_merge = await self._proxy_series("time_to_merge", _bucketed_time_to_merge_sql(), params)

        unattributed = 0
        if project_id is not None:
            row = (
                await self._session.execute(_unattributed_approval_sql(), params)
            ).mappings().one()
            unattributed = _to_int(row["unattributed"])

        ordered = {s.kpi_id: s for s in (acceptance, time_to_merge, approval, citation, cost)}
        series = tuple(ordered[d.kpi_id] for d in KPI_DEFINITIONS)
        return KpiTimeseries(
            bucket=bucket,
            range=range_value,
            project_id=project_id,
            unattributed_approval_count=unattributed,
            series=series,
        )

    async def _ratio_series(
        self, kpi_id: KpiId, stmt: sa.TextClause, params: dict[str, object]
    ) -> KpiSeries:
        rows = (await self._session.execute(stmt, params)).mappings().all()
        buckets = tuple(
            _ratio_bucket(r["bucket_start"], _to_int(r["numerator"]), _to_int(r["denominator"]))
            for r in rows
        )
        return self._series(kpi_id, buckets)

    async def _median_series(
        self, kpi_id: KpiId, stmt: sa.TextClause, params: dict[str, object]
    ) -> KpiSeries:
        rows = (await self._session.execute(stmt, params)).mappings().all()
        buckets = tuple(
            _median_bucket(r["bucket_start"], _to_int(r["sample_count"]), _opt_float(r["median_ms"]))
            for r in rows
        )
        return self._series(kpi_id, buckets)

    async def _proxy_series(
        self, kpi_id: KpiId, stmt: sa.TextClause, params: dict[str, object]
    ) -> KpiSeries:
        rows = (await self._session.execute(stmt, params)).mappings().all()
        buckets = tuple(
            _proxy_bucket(r["bucket_start"], _to_int(r["sample_count"]), _opt_float(r["median_ms"]))
            for r in rows
        )
        return self._series(kpi_id, buckets)

    async def _cost_series(self, params: dict[str, object]) -> KpiSeries:
        rows = (await self._session.execute(_bucketed_cost_sql(), params)).mappings().all()
        buckets: list[KpiBucket] = []
        for r in rows:
            completed = _to_int(r["completed_run_count"])
            measured = _to_int(r["measured_count"])
            unmeasured = _to_int(r["unmeasured_count"])
            total_cost = _opt_float(r["total_cost"]) or 0.0
            if completed == 0:
                buckets.append(
                    KpiBucket(r["bucket_start"], None, "no_denominator", None, 0, measured, unmeasured)
                )
                continue
            value = total_cost / completed
            state: BucketState = "partial_unmeasured" if unmeasured > 0 else "measured"
            buckets.append(
                KpiBucket(r["bucket_start"], value, state, None, completed, measured, unmeasured)
            )
        return self._series("cost_per_completed_task", tuple(buckets))

    def _series(self, kpi_id: KpiId, buckets: tuple[KpiBucket, ...]) -> KpiSeries:
        d = _DEFINITION_BY_ID[kpi_id]
        return KpiSeries(
            kpi_id=kpi_id,
            unit=d.unit,
            threshold=d.threshold,
            direction=d.direction,
            measurement_kind=d.measurement_kind,
            buckets=buckets,
        )

    async def _ensure_tenant_context(self, tenant_id: int) -> None:
        if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
            raise ValueError("tenant_id must be a positive integer.")
        current = await get_tenant_context(self._session)
        if current is None:
            await set_tenant_context(self._session, tenant_id)
        await assert_tenant_context(self._session, tenant_id)


__all__ = [
    "ACCEPTANCE_DECIDED_STATUSES",
    "ACCEPTANCE_PASS_STATUS",
    "APPROVAL_DECIDED_STATUSES",
    "BUCKETS",
    "KPI_DEFINITIONS",
    "RANGES",
    "TIME_TO_MERGE_PROXY_SOURCE",
    "Bucket",
    "BucketState",
    "KpiBucket",
    "KpiDefinition",
    "KpiId",
    "KpiSeries",
    "KpiTimeseries",
    "KpiTimeseriesService",
    "TimeseriesRange",
    "range_cutoff",
]
