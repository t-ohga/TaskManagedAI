"""AgentRun-level KPI source for SP-008 AC-KPI-02."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.domain.agent_runtime.status import AgentRunStatus

TimeToMergeProxySource = Literal["repo_pr_opened_to_agent_run_completed"]


@dataclass(frozen=True)
class AgentRunKpi:
    tenant_id: int
    run_id: UUID
    project_id: UUID
    status: AgentRunStatus
    completed_at: datetime | None
    repo_pr_opened_event_count: int
    first_repo_pr_opened_at: datetime | None
    time_to_merge_proxy_sample_count: int
    time_to_merge_proxy_ms: float | None
    time_to_merge_proxy_source: TimeToMergeProxySource


class AgentRunKpiService:
    """Read one AgentRun's AC-KPI-02 source without exposing event payloads."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def fetch(self, *, tenant_id: int, run_id: UUID) -> AgentRunKpi | None:
        await self._ensure_tenant_context(tenant_id)
        row = (
            await self.session.execute(
                _AGENT_RUN_KPI_SQL,
                {"tenant_id": tenant_id, "run_id": str(run_id)},
            )
        ).mappings().one_or_none()
        if row is None:
            return None

        project_id = row["project_id"]
        if not isinstance(project_id, UUID):
            project_id = UUID(str(project_id))

        status = _agent_run_status(row["status"])
        completed_at = _optional_datetime(row["completed_at"])
        first_repo_pr_opened_at = _optional_datetime(row["first_repo_pr_opened_at"])
        sample_ms = _time_to_merge_proxy_ms(
            status=status,
            completed_at=completed_at,
            first_repo_pr_opened_at=first_repo_pr_opened_at,
        )
        return AgentRunKpi(
            tenant_id=tenant_id,
            run_id=run_id,
            project_id=project_id,
            status=status,
            completed_at=completed_at,
            repo_pr_opened_event_count=_int(row["repo_pr_opened_event_count"]),
            first_repo_pr_opened_at=first_repo_pr_opened_at,
            time_to_merge_proxy_sample_count=1 if sample_ms is not None else 0,
            time_to_merge_proxy_ms=sample_ms,
            time_to_merge_proxy_source="repo_pr_opened_to_agent_run_completed",
        )

    async def _ensure_tenant_context(self, tenant_id: int) -> None:
        if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
            raise ValueError("tenant_id must be a positive integer.")
        current = await get_tenant_context(self.session)
        if current is None:
            await set_tenant_context(self.session, tenant_id)
        await assert_tenant_context(self.session, tenant_id)


_AGENT_RUN_KPI_SQL = sa.text(
    r"""
    with target_run as (
        select
            ar.id,
            ar.tenant_id,
            ar.project_id,
            ar.status,
            ar.completed_at
          from agent_runs ar
         where ar.tenant_id = :tenant_id
           and ar.id = cast(:run_id as uuid)
    ),
    dedup_repo_pr_opened_events as (
        select distinct on (e.run_id, e.seq_no)
            e.run_id,
            e.seq_no,
            e.created_at
          from agent_run_events e
          join target_run tr
            on tr.tenant_id = e.tenant_id
           and tr.id = e.run_id
         where e.event_type = 'repo_pr_opened'
         order by e.run_id, e.seq_no, e.created_at, e.id
    )
    select
        tr.project_id,
        tr.status,
        tr.completed_at,
        coalesce(count(e.seq_no), 0) as repo_pr_opened_event_count,
        min(e.created_at) as first_repo_pr_opened_at
      from target_run tr
      left join dedup_repo_pr_opened_events e
        on e.run_id = tr.id
     group by tr.project_id, tr.status, tr.completed_at
    """
)


def _time_to_merge_proxy_ms(
    *,
    status: str,
    completed_at: datetime | None,
    first_repo_pr_opened_at: datetime | None,
) -> float | None:
    if status != "completed":
        return None
    if completed_at is None or first_repo_pr_opened_at is None:
        return None
    if completed_at < first_repo_pr_opened_at:
        return None
    return (completed_at - first_repo_pr_opened_at).total_seconds() * 1000.0


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    raise TypeError(f"expected datetime-compatible DB value, got {type(value).__name__}.")


def _agent_run_status(value: object) -> AgentRunStatus:
    if not isinstance(value, str):
        raise TypeError(f"expected AgentRunStatus DB value, got {type(value).__name__}.")
    return cast(AgentRunStatus, value)


def _int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, int | float | str):
        return int(value)
    raise TypeError(f"expected int-compatible DB value, got {type(value).__name__}.")


__all__ = [
    "AgentRunKpi",
    "AgentRunKpiService",
    "TimeToMergeProxySource",
]
