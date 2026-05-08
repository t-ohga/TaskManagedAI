"""approval_wait_ms KPI metric service (Sprint 3 Batch 4, BL-0038, AC-KPI-03 source).

`approval_wait_ms = (decided_at - requested_at).total_seconds() * 1000` の
median / p50 / p95 を DB query 経由で集計。UI event は source of truth にしない。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.approval_request import ApprovalRequest


@dataclass(frozen=True)
class ApprovalWaitMsAggregate:
    """approval_wait_ms KPI 集計結果 (AC-KPI-03 source)。"""

    sample_count: int
    median_ms: float | None
    p50_ms: float | None
    p95_ms: float | None
    min_ms: float | None
    max_ms: float | None
    period_start: datetime | None
    period_end: datetime | None


class ApprovalWaitMsMetricService:
    """approval_wait_ms KPI metric を DB から集計する service。

    AC-KPI-03 contract:
    - source = approval_requests.requested_at + approval_requests.decided_at
    - status='approved' or 'rejected' のみ集計対象 (decided_at NOT NULL)
    - decided_at >= requested_at のみ集計対象 (negative wait_ms gaming 防止)
    - tenant_id scope で DB query
    - UI event / frontend telemetry は source of truth にしない
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def aggregate(
        self,
        *,
        tenant_id: int,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> ApprovalWaitMsAggregate:
        """tenant_id scope で approved / rejected approval の wait_ms を集計。

        period_start / period_end が指定された場合、requested_at で絞る。
        """
        await self._ensure_tenant_context(tenant_id)

        wait_ms_expr = (
            func.extract(
                "epoch",
                ApprovalRequest.decided_at - ApprovalRequest.requested_at,
            )
            * 1000.0
        )

        stmt = select(
            func.count().label("sample_count"),
            func.percentile_cont(0.5).within_group(wait_ms_expr).label("median_ms"),
            func.percentile_cont(0.95).within_group(wait_ms_expr).label("p95_ms"),
            func.min(wait_ms_expr).label("min_ms"),
            func.max(wait_ms_expr).label("max_ms"),
        ).where(
            ApprovalRequest.tenant_id == tenant_id,
            ApprovalRequest.status.in_(["approved", "rejected"]),
            ApprovalRequest.decided_at.is_not(None),
            ApprovalRequest.decided_at >= ApprovalRequest.requested_at,
        )
        if period_start is not None:
            stmt = stmt.where(ApprovalRequest.requested_at >= period_start)
        if period_end is not None:
            stmt = stmt.where(ApprovalRequest.requested_at < period_end)

        row = (await self.session.execute(stmt)).one()
        return ApprovalWaitMsAggregate(
            sample_count=int(row.sample_count or 0),
            median_ms=float(row.median_ms) if row.median_ms is not None else None,
            p50_ms=float(row.median_ms) if row.median_ms is not None else None,
            p95_ms=float(row.p95_ms) if row.p95_ms is not None else None,
            min_ms=float(row.min_ms) if row.min_ms is not None else None,
            max_ms=float(row.max_ms) if row.max_ms is not None else None,
            period_start=period_start,
            period_end=period_end,
        )

    async def _ensure_tenant_context(self, tenant_id: int) -> None:
        if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
            raise ValueError("tenant_id must be a positive integer.")
        current = await get_tenant_context(self.session)
        if current is None:
            await set_tenant_context(self.session, tenant_id)
        await assert_tenant_context(self.session, tenant_id)


__all__ = [
    "ApprovalWaitMsMetricService",
    "ApprovalWaitMsAggregate",
]

