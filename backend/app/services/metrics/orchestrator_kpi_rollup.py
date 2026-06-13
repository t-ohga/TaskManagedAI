"""SP-014 orchestrator KPI rollup service.

The rollup is intentionally read-only and DB-backed. It uses an AgentRun
recursive CTE only to discover the root orchestrator run and descendant child
runs, then computes KPI samples from the existing source-of-truth tables
documented by ADR-00014 §10.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)


@dataclass(frozen=True)
class OrchestratorKpiRollup:
    tenant_id: int
    root_run_id: UUID
    project_id: UUID
    lineage_run_count: int
    completed_run_count: int
    acceptance_eval_score_count: int
    acceptance_passed_count: int
    acceptance_pass_rate: float | None
    provider_responded_event_count: int
    provider_usage_event_count: int
    provider_total_cost_usd: float
    provider_tokens_input: int
    provider_tokens_output: int
    cost_per_completed_task_usd: float | None
    repo_pr_opened_event_count: int
    time_to_merge_proxy_sample_count: int
    time_to_merge_proxy_median_ms: float | None
    approval_wait_sample_count: int
    approval_wait_median_ms: float | None
    approval_wait_p95_ms: float | None


class OrchestratorKpiRollupService:
    """Aggregate multi-agent KPI samples for one root orchestrator run."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def fetch(
        self,
        *,
        tenant_id: int,
        root_run_id: UUID,
    ) -> OrchestratorKpiRollup | None:
        """Return KPI rollup for ``root_run_id`` and all descendant runs.

        Event-derived metrics dedupe AgentRunEvent rows by ``(run_id, seq_no)``
        inside the query even though the DB also enforces that uniqueness. This
        keeps the metric contract explicit and protects future query rewrites
        from accidentally double-counting idempotent timeline events.
        """

        await self._ensure_tenant_context(tenant_id)
        row = (
            await self.session.execute(
                _ROLLUP_SQL,
                {"tenant_id": tenant_id, "root_run_id": str(root_run_id)},
            )
        ).mappings().one()

        lineage_run_count = _int(row["lineage_run_count"])
        if lineage_run_count == 0:
            return None

        project_id = row["project_id"]
        if not isinstance(project_id, UUID):
            project_id = UUID(str(project_id))

        return OrchestratorKpiRollup(
            tenant_id=tenant_id,
            root_run_id=root_run_id,
            project_id=project_id,
            lineage_run_count=lineage_run_count,
            completed_run_count=_int(row["completed_run_count"]),
            acceptance_eval_score_count=_int(row["acceptance_eval_score_count"]),
            acceptance_passed_count=_int(row["acceptance_passed_count"]),
            acceptance_pass_rate=_optional_float(row["acceptance_pass_rate"]),
            provider_responded_event_count=_int(row["provider_responded_event_count"]),
            provider_usage_event_count=_int(row["provider_usage_event_count"]),
            provider_total_cost_usd=_float(row["provider_total_cost_usd"]),
            provider_tokens_input=_int(row["provider_tokens_input"]),
            provider_tokens_output=_int(row["provider_tokens_output"]),
            cost_per_completed_task_usd=_optional_float(
                row["cost_per_completed_task_usd"]
            ),
            repo_pr_opened_event_count=_int(row["repo_pr_opened_event_count"]),
            time_to_merge_proxy_sample_count=_int(
                row["time_to_merge_proxy_sample_count"]
            ),
            time_to_merge_proxy_median_ms=_optional_float(
                row["time_to_merge_proxy_median_ms"]
            ),
            approval_wait_sample_count=_int(row["approval_wait_sample_count"]),
            approval_wait_median_ms=_optional_float(row["approval_wait_median_ms"]),
            approval_wait_p95_ms=_optional_float(row["approval_wait_p95_ms"]),
        )

    async def _ensure_tenant_context(self, tenant_id: int) -> None:
        if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
            raise ValueError("tenant_id must be a positive integer.")
        current = await get_tenant_context(self.session)
        if current is None:
            await set_tenant_context(self.session, tenant_id)
        await assert_tenant_context(self.session, tenant_id)


_ROLLUP_SQL = sa.text(
    r"""
    with recursive run_tree as (
        select
            ar.id,
            ar.tenant_id,
            ar.project_id,
            ar.parent_run_id,
            ar.status,
            ar.completed_at,
            ar.created_at,
            array[ar.id]::uuid[] as path
          from agent_runs ar
         where ar.tenant_id = :tenant_id
           and ar.id = cast(:root_run_id as uuid)
           -- SP-029 (ADR-00055 §設計制約 8): shadow run を production KPI から除外する。
           -- root が shadow なら lineage_run_count=0 で None を返し KPI に出さない。
           and ar.run_mode = 'production'

        union all

        select
            child.id,
            child.tenant_id,
            child.project_id,
            child.parent_run_id,
            child.status,
            child.completed_at,
            child.created_at,
            array_append(parent.path, child.id) as path
          from agent_runs child
          join run_tree parent
            on parent.tenant_id = child.tenant_id
           and parent.project_id = child.project_id
           and parent.id = child.parent_run_id
         where not child.id = any(parent.path)
           -- SP-029: shadow child も production lineage から除外 (混在 KPI 防止)。
           and child.run_mode = 'production'
    ),
    dedup_events as (
        select distinct on (e.run_id, e.seq_no)
            e.id,
            e.run_id,
            e.seq_no,
            e.event_type,
            e.event_payload,
            e.created_at
          from agent_run_events e
          join run_tree rt
            on rt.tenant_id = e.tenant_id
           and rt.id = e.run_id
         order by e.run_id, e.seq_no, e.created_at, e.id
    ),
    provider_usage_events as (
        select
            e.id,
            case
                when jsonb_typeof(e.event_payload->'usage') = 'object'
                 and (e.event_payload #>> '{usage,cost_usd}') ~ '^[0-9]+(\.[0-9]+)?$'
                then (e.event_payload #>> '{usage,cost_usd}')::numeric
                when (e.event_payload->>'cost_usd') ~ '^[0-9]+(\.[0-9]+)?$'
                then (e.event_payload->>'cost_usd')::numeric
                else null
            end as cost_usd,
            case
                when jsonb_typeof(e.event_payload->'usage') = 'object'
                 and (e.event_payload #>> '{usage,tokens_input}') ~ '^[0-9]+$'
                then (e.event_payload #>> '{usage,tokens_input}')::bigint
                when (e.event_payload->>'tokens_input') ~ '^[0-9]+$'
                then (e.event_payload->>'tokens_input')::bigint
                else 0
            end as tokens_input,
            case
                when jsonb_typeof(e.event_payload->'usage') = 'object'
                 and (e.event_payload #>> '{usage,tokens_output}') ~ '^[0-9]+$'
                then (e.event_payload #>> '{usage,tokens_output}')::bigint
                when (e.event_payload->>'tokens_output') ~ '^[0-9]+$'
                then (e.event_payload->>'tokens_output')::bigint
                else 0
            end as tokens_output
          from dedup_events e
          join run_tree rt
            on rt.id = e.run_id
         where e.event_type = 'provider_responded'
           and rt.status = 'completed'
    ),
    pr_opened_samples as (
        select
            rt.id as run_id,
            min(e.created_at) as first_pr_opened_at
          from run_tree rt
          join dedup_events e
            on e.run_id = rt.id
         where e.event_type = 'repo_pr_opened'
         group by rt.id
    ),
    time_to_merge_proxy_samples as (
        select
            extract(epoch from (rt.completed_at - p.first_pr_opened_at)) * 1000.0 as wait_ms
          from run_tree rt
          join pr_opened_samples p
            on p.run_id = rt.id
         where rt.status = 'completed'
           and rt.completed_at is not null
           and rt.completed_at >= p.first_pr_opened_at
    ),
    approval_waits as (
        select
            extract(epoch from (arq.decided_at - arq.requested_at)) * 1000.0 as wait_ms
          from approval_requests arq
          join run_tree rt
            on rt.id = arq.run_id
         where arq.tenant_id = :tenant_id
           and arq.status in ('approved', 'rejected')
           and arq.decided_at is not null
           and arq.decided_at >= arq.requested_at
    ),
    eval_scores_for_tree as (
        select es.passed
          from eval_runs er
          join run_tree rt
            on rt.id = er.run_id
           and rt.tenant_id = er.tenant_id
          join eval_scores es
            on es.tenant_id = er.tenant_id
           and es.eval_run_id = er.id
           and es.dataset_version_id = er.dataset_version_id
         where er.tenant_id = :tenant_id
    )
    select
        (select project_id from run_tree limit 1) as project_id,
        (select count(*) from run_tree) as lineage_run_count,
        (select count(*) from run_tree where status = 'completed') as completed_run_count,
        (select count(*) from eval_scores_for_tree) as acceptance_eval_score_count,
        (select count(*) from eval_scores_for_tree where passed is true) as acceptance_passed_count,
        (
            select
                case
                    when count(*) = 0 then null
                    else count(*) filter (where passed is true)::float / count(*)::float
                end
              from eval_scores_for_tree
        ) as acceptance_pass_rate,
        (
            select count(*)
              from dedup_events
             where event_type = 'provider_responded'
        ) as provider_responded_event_count,
        (
            select count(*)
              from provider_usage_events
             where cost_usd is not null
        ) as provider_usage_event_count,
        (
            select coalesce(sum(cost_usd), 0.0)
              from provider_usage_events
             where cost_usd is not null
        ) as provider_total_cost_usd,
        (
            select coalesce(sum(tokens_input), 0)
              from provider_usage_events
        ) as provider_tokens_input,
        (
            select coalesce(sum(tokens_output), 0)
              from provider_usage_events
        ) as provider_tokens_output,
        (
            select
                case
                    when (select count(*) from run_tree where status = 'completed') = 0
                    then null
                    else (
                        (select coalesce(sum(cost_usd), 0.0)
                           from provider_usage_events
                          where cost_usd is not null)
                        / (select count(*) from run_tree where status = 'completed')::numeric
                    )
                end
        ) as cost_per_completed_task_usd,
        (
            select count(*)
              from dedup_events
             where event_type = 'repo_pr_opened'
        ) as repo_pr_opened_event_count,
        (
            select count(*)
              from time_to_merge_proxy_samples
        ) as time_to_merge_proxy_sample_count,
        (
            select percentile_cont(0.5) within group (order by wait_ms)
              from time_to_merge_proxy_samples
        ) as time_to_merge_proxy_median_ms,
        (
            select count(*)
              from approval_waits
        ) as approval_wait_sample_count,
        (
            select percentile_cont(0.5) within group (order by wait_ms)
              from approval_waits
        ) as approval_wait_median_ms,
        (
            select percentile_cont(0.95) within group (order by wait_ms)
              from approval_waits
        ) as approval_wait_p95_ms
    """
)


def _int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, int | float | Decimal | str):
        return int(value)
    raise TypeError(f"expected int-compatible DB value, got {type(value).__name__}.")


def _float(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, int | float | Decimal | str):
        return float(value)
    raise TypeError(f"expected float-compatible DB value, got {type(value).__name__}.")


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float | Decimal | str):
        return float(value)
    raise TypeError(f"expected float-compatible DB value, got {type(value).__name__}.")


__all__ = [
    "OrchestratorKpiRollup",
    "OrchestratorKpiRollupService",
]
