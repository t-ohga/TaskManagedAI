"""ADR-00051 (SP-026) KPI analytics drilldown read-only API。

(A) `GET /api/v1/eval/kpi_timeseries`: operational KPI time series (project/period、既存 metric service の
    公式を bucketing 再利用)。
(B) `GET /api/v1/eval/provider_breakdown`: eval_runs.provider × eval_scores の bake-off (tenant-wide)。

fixture P0-Exit KPI (`/api/v1/eval/kpi-rollup`) は不変。本 endpoint は別軸の live operational trend。
secret / raw payload を返さない (集計値のみ)。
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.services.eval.kpi_timeseries import (
    Bucket,
    BucketState,
    KpiDirection,
    KpiId,
    KpiTimeseries,
    KpiTimeseriesService,
    MeasurementKind,
    TimeseriesRange,
    range_cutoff,
)

router = APIRouter(prefix="/api/v1/eval", tags=["eval_analytics"])


class KpiBucketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    bucket_start: str
    value: float | None
    state: BucketState
    numerator_count: int | None
    denominator_count: int | None
    measured_count: int | None
    unmeasured_count: int | None


class KpiSeriesRead(BaseModel):
    kpi_id: KpiId
    unit: str
    threshold: float
    direction: KpiDirection
    measurement_kind: MeasurementKind
    buckets: list[KpiBucketRead]


class KpiTimeseriesResponse(BaseModel):
    bucket: Bucket
    range: TimeseriesRange
    project_id: UUID | None
    unattributed_approval_count: int
    series: list[KpiSeriesRead]


class ProviderBreakdownMetric(BaseModel):
    metric_key: str
    run_count: int
    pass_rate: float | None
    median_score: float | None


class ProviderBreakdownRow(BaseModel):
    provider: str
    model: str
    metrics: list[ProviderBreakdownMetric]


class ProviderBreakdownResponse(BaseModel):
    range: TimeseriesRange
    scope: Literal["tenant"]
    project_filter_applied: Literal[False]
    rows: list[ProviderBreakdownRow]


def _serialize(timeseries: KpiTimeseries) -> KpiTimeseriesResponse:
    return KpiTimeseriesResponse(
        bucket=timeseries.bucket,
        range=timeseries.range,
        project_id=timeseries.project_id,
        unattributed_approval_count=timeseries.unattributed_approval_count,
        series=[
            KpiSeriesRead(
                kpi_id=s.kpi_id,
                unit=s.unit,
                threshold=s.threshold,
                direction=s.direction,
                measurement_kind=s.measurement_kind,
                buckets=[
                    KpiBucketRead(
                        bucket_start=b.bucket_start.isoformat(),
                        value=b.value,
                        state=b.state,
                        numerator_count=b.numerator_count,
                        denominator_count=b.denominator_count,
                        measured_count=b.measured_count,
                        unmeasured_count=b.unmeasured_count,
                    )
                    for b in s.buckets
                ],
            )
            for s in timeseries.series
        ],
    )


@router.get("/kpi_timeseries", response_model=KpiTimeseriesResponse)
async def kpi_timeseries_endpoint(
    bucket: Annotated[Bucket, Query()] = "day",
    range_value: Annotated[TimeseriesRange, Query(alias="range")] = "month",
    project_id: UUID | None = Query(default=None),
    _actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008  # authenticated 必須
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> KpiTimeseriesResponse:
    """operational KPI time series。fixture P0-Exit KPI とは別軸の live trend (project/period 集計)。"""
    timeseries = await KpiTimeseriesService(session).compute(
        tenant_id=tenant_id,
        bucket=bucket,
        range_value=range_value,
        project_id=project_id,
    )
    return _serialize(timeseries)


# provider bake-off: eval_runs.provider × eval_scores (tenant-wide、project_id 非保持)。
_PROVIDER_BREAKDOWN_SQL = sa.text(
    """
    select er.provider as provider,
           er.model as model,
           es.metric_key as metric_key,
           count(distinct er.id) as run_count,
           avg(case when es.passed then 1.0 else 0.0 end) as pass_rate,
           percentile_cont(0.5) within group (order by es.score) as median_score
      from eval_runs er
      join eval_scores es
        on es.tenant_id = er.tenant_id
       and es.eval_run_id = er.id
       and es.dataset_version_id = er.dataset_version_id
     where er.tenant_id = :tenant_id
       and er.started_at >= :cutoff
     group by er.provider, er.model, es.metric_key
     order by er.provider, er.model, es.metric_key
    """
)


@router.get("/provider_breakdown", response_model=ProviderBreakdownResponse)
async def provider_breakdown_endpoint(
    range_value: Annotated[TimeseriesRange, Query(alias="range")] = "month",
    _actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ProviderBreakdownResponse:
    """eval provider bake-off (tenant-wide)。eval_runs は project_id 非保持のため project filter 非適用 (F-005)。"""
    await _ensure_tenant_context(session, tenant_id)
    cutoff = range_cutoff(range_value)
    rows = (
        await session.execute(
            _PROVIDER_BREAKDOWN_SQL, {"tenant_id": tenant_id, "cutoff": cutoff}
        )
    ).mappings().all()

    grouped: dict[tuple[str, str], list[ProviderBreakdownMetric]] = {}
    order: list[tuple[str, str]] = []
    for r in rows:
        key = (str(r["provider"]), str(r["model"]))
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(
            ProviderBreakdownMetric(
                metric_key=str(r["metric_key"]),
                run_count=int(r["run_count"] or 0),
                pass_rate=float(r["pass_rate"]) if r["pass_rate"] is not None else None,
                median_score=float(r["median_score"]) if r["median_score"] is not None else None,
            )
        )
    return ProviderBreakdownResponse(
        range=range_value,
        scope="tenant",
        project_filter_applied=False,
        rows=[
            ProviderBreakdownRow(provider=p, model=m, metrics=grouped[(p, m)])
            for (p, m) in order
        ],
    )


async def _ensure_tenant_context(session: AsyncSession, tenant_id: int) -> None:
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
        raise ValueError("tenant_id must be a positive integer.")
    current = await get_tenant_context(session)
    if current is None:
        await set_tenant_context(session, tenant_id)
    await assert_tenant_context(session, tenant_id)


__all__ = [
    "KpiBucketRead",
    "KpiSeriesRead",
    "KpiTimeseriesResponse",
    "ProviderBreakdownResponse",
    "kpi_timeseries_endpoint",
    "provider_breakdown_endpoint",
    "router",
]
