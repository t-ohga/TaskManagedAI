from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.agent_run_event import AgentRunEvent
from backend.app.db.models.context_snapshot import ContextSnapshot
from backend.app.domain.agent_runtime.status import AgentRunStatus, BlockedReason
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.services.agent_runtime.cancel import cancel_agent_run
from backend.app.services.metrics.agent_run_kpi import (
    AgentRunKpi,
    AgentRunKpiService,
    TimeToMergeProxySource,
)

router = APIRouter(prefix="/api/v1/agent_runs", tags=["agent_runs"])

PayloadRedactionStatus = Literal["keys_only", "blocked_by_secret_scan"]


class CancelAgentRunRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class AgentRunResponse(BaseModel):
    id: UUID
    tenant_id: int
    project_id: UUID
    parent_run_id: UUID | None
    status: AgentRunStatus
    blocked_reason: BlockedReason | None
    error_code: str | None
    error_summary: str | None
    completed_at: datetime | None


class AgentRunRead(AgentRunResponse):
    role_id: str | None
    role_scope: str | None
    orchestrator_lease_expires_at: datetime | None
    last_progress_at: datetime | None
    progress_seq: int
    created_at: datetime
    updated_at: datetime


class AgentRunListResponse(BaseModel):
    items: list[AgentRunRead]
    total: int
    limit: int
    offset: int


CostSummaryRange = Literal["today", "week", "month", "quarter", "all"]


class CostSummaryByStatus(BaseModel):
    status: str
    cost_usd: float
    run_count: int


class CostSummaryResponse(BaseModel):
    total_cost_usd: float | None
    total_tokens_input: int
    total_tokens_output: int
    run_count: int
    by_status: list[CostSummaryByStatus]
    range: CostSummaryRange


class AgentRunEventRead(BaseModel):
    id: UUID
    run_id: UUID
    seq_no: int
    event_type: str
    actor_id: UUID
    payload_keys: list[str]
    payload_redaction_status: PayloadRedactionStatus
    created_at: datetime


class ContextSnapshotRead(BaseModel):
    id: UUID
    run_id: UUID
    prompt_pack_version: str
    prompt_pack_lock: str
    policy_version: str
    policy_pack_lock: str
    repo_state_keys: list[str]
    tool_manifest_keys: list[str]
    evidence_set_hash: str
    has_provider_continuation_ref: bool
    provider_request_fingerprint_keys: list[str]
    snapshot_kind: str
    created_at: datetime


class AgentRunDetailResponse(AgentRunRead):
    events: list[AgentRunEventRead]
    context_snapshot: ContextSnapshotRead | None


class AgentRunKpiResponse(BaseModel):
    run_id: UUID
    tenant_id: int
    project_id: UUID
    status: AgentRunStatus
    completed_at: datetime | None
    repo_pr_opened_event_count: int
    first_repo_pr_opened_at: datetime | None
    time_to_merge_proxy_sample_count: int
    time_to_merge_proxy_ms: float | None
    time_to_merge_proxy_source: TimeToMergeProxySource


def _to_response(run: AgentRun) -> AgentRunResponse:
    return AgentRunResponse(
        id=run.id,
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        parent_run_id=run.parent_run_id,
        status=run.status,
        blocked_reason=run.blocked_reason,
        error_code=run.error_code,
        error_summary=run.error_summary,
        completed_at=run.completed_at,
    )


def _to_read(run: AgentRun) -> AgentRunRead:
    return AgentRunRead(
        id=run.id,
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        parent_run_id=run.parent_run_id,
        status=run.status,
        blocked_reason=run.blocked_reason,
        error_code=run.error_code,
        error_summary=run.error_summary,
        completed_at=run.completed_at,
        role_id=run.role_id,
        role_scope=run.role_scope,
        orchestrator_lease_expires_at=run.orchestrator_lease_expires_at,
        last_progress_at=run.last_progress_at,
        progress_seq=run.progress_seq,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _payload_keys(payload: dict[str, Any]) -> tuple[list[str], PayloadRedactionStatus]:
    try:
        assert_no_raw_secret(payload, path="$agent_run_event_payload")
    except ValueError:
        return [], "blocked_by_secret_scan"
    return sorted(payload.keys()), "keys_only"


def _to_event_read(event: AgentRunEvent) -> AgentRunEventRead:
    payload_keys, payload_redaction_status = _payload_keys(event.event_payload)
    return AgentRunEventRead(
        id=event.id,
        run_id=event.run_id,
        seq_no=event.seq_no,
        event_type=event.event_type,
        actor_id=event.actor_id,
        payload_keys=payload_keys,
        payload_redaction_status=payload_redaction_status,
        created_at=event.created_at,
    )


def _safe_json_keys(payload: dict[str, Any]) -> list[str]:
    try:
        assert_no_raw_secret(payload, path="$context_snapshot_payload")
    except ValueError:
        return []
    return sorted(payload.keys())


def _to_context_snapshot_read(snapshot: ContextSnapshot) -> ContextSnapshotRead:
    return ContextSnapshotRead(
        id=snapshot.id,
        run_id=snapshot.run_id,
        prompt_pack_version=snapshot.prompt_pack_version,
        prompt_pack_lock=snapshot.prompt_pack_lock,
        policy_version=snapshot.policy_version,
        policy_pack_lock=snapshot.policy_pack_lock,
        repo_state_keys=_safe_json_keys(snapshot.repo_state),
        tool_manifest_keys=_safe_json_keys(snapshot.tool_manifest),
        evidence_set_hash=snapshot.evidence_set_hash,
        has_provider_continuation_ref=snapshot.provider_continuation_ref is not None,
        provider_request_fingerprint_keys=_safe_json_keys(
            snapshot.provider_request_fingerprint
        ),
        snapshot_kind=snapshot.snapshot_kind,
        created_at=snapshot.created_at,
    )


def _to_kpi_response(kpi: AgentRunKpi) -> AgentRunKpiResponse:
    return AgentRunKpiResponse(
        run_id=kpi.run_id,
        tenant_id=kpi.tenant_id,
        project_id=kpi.project_id,
        status=kpi.status,
        completed_at=kpi.completed_at,
        repo_pr_opened_event_count=kpi.repo_pr_opened_event_count,
        first_repo_pr_opened_at=kpi.first_repo_pr_opened_at,
        time_to_merge_proxy_sample_count=kpi.time_to_merge_proxy_sample_count,
        time_to_merge_proxy_ms=kpi.time_to_merge_proxy_ms,
        time_to_merge_proxy_source=kpi.time_to_merge_proxy_source,
    )


@router.get("", response_model=AgentRunListResponse)
async def list_agent_runs_endpoint(
    status_filter: AgentRunStatus | None = Query(default=None, alias="status"),
    role: str | None = Query(default=None, min_length=1, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> AgentRunListResponse:
    """List AgentRuns for the current tenant.

    `actor_id` is intentionally resolved via Depends to enforce authenticated
    session context even though list visibility is tenant-scoped in P0.1.
    """
    conditions = [AgentRun.tenant_id == tenant_id]
    if status_filter is not None:
        conditions.append(AgentRun.status == status_filter)
    if role is not None:
        conditions.append(AgentRun.role_id == role)

    total = await session.scalar(select(func.count()).select_from(AgentRun).where(*conditions))
    result = await session.execute(
        select(AgentRun)
        .where(*conditions)
        .order_by(AgentRun.created_at.desc(), AgentRun.id)
        .limit(limit)
        .offset(offset)
    )
    runs = list(result.scalars())
    return AgentRunListResponse(
        items=[_to_read(run) for run in runs],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


def _cost_summary_cutoff(range_value: CostSummaryRange) -> datetime | None:
    """range から created_at の cutoff を server 側で算出 (caller-supplied date 禁止)."""
    now = datetime.now(UTC)
    if range_value == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if range_value == "week":
        return now - timedelta(days=7)
    if range_value == "month":
        return now - timedelta(days=30)
    if range_value == "quarter":
        return now - timedelta(days=90)
    return None


@router.get("/cost_summary", response_model=CostSummaryResponse)
async def cost_summary_endpoint(
    range_value: CostSummaryRange = Query(default="all", alias="range"),
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> CostSummaryResponse:
    """AgentRun のコスト/トークンを集計 (read-only、ADR-00033).

    tenant 境界を強制し、cost_usd / tokens のみ返す (raw secret なし)。
    `actor_id` は authenticated session 強制のため Depends で resolve。
    """
    conditions = [AgentRun.tenant_id == tenant_id]
    cutoff = _cost_summary_cutoff(range_value)
    if cutoff is not None:
        conditions.append(AgentRun.created_at >= cutoff)

    totals = (
        await session.execute(
            select(
                func.coalesce(func.sum(AgentRun.cost_usd), Decimal(0)),
                func.coalesce(func.sum(AgentRun.tokens_input), 0),
                func.coalesce(func.sum(AgentRun.tokens_output), 0),
                func.count(),
            ).where(*conditions)
        )
    ).one()
    total_cost, total_in, total_out, run_count = totals

    by_status_rows = (
        await session.execute(
            select(
                AgentRun.status,
                func.coalesce(func.sum(AgentRun.cost_usd), Decimal(0)),
                func.count(),
            )
            .where(*conditions)
            .group_by(AgentRun.status)
            .order_by(AgentRun.status)
        )
    ).all()

    return CostSummaryResponse(
        total_cost_usd=float(total_cost) if run_count else None,
        total_tokens_input=int(total_in or 0),
        total_tokens_output=int(total_out or 0),
        run_count=int(run_count or 0),
        by_status=[
            CostSummaryByStatus(
                status=str(row[0]),
                cost_usd=float(row[1]),
                run_count=int(row[2]),
            )
            for row in by_status_rows
        ],
        range=range_value,
    )


@router.get("/{run_id}", response_model=AgentRunDetailResponse)
async def get_agent_run_endpoint(
    run_id: UUID,
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> AgentRunDetailResponse:
    """Read one AgentRun plus redacted event/context metadata."""
    run = await session.scalar(
        select(AgentRun).where(AgentRun.tenant_id == tenant_id, AgentRun.id == run_id)
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="agent run not found",
        )

    events_result = await session.execute(
        select(AgentRunEvent)
        .where(AgentRunEvent.tenant_id == tenant_id, AgentRunEvent.run_id == run_id)
        .order_by(AgentRunEvent.seq_no, AgentRunEvent.created_at, AgentRunEvent.id)
        .limit(200)
    )
    snapshot = await session.scalar(
        select(ContextSnapshot)
        .where(ContextSnapshot.tenant_id == tenant_id, ContextSnapshot.run_id == run_id)
        .order_by(ContextSnapshot.created_at.desc(), ContextSnapshot.id)
        .limit(1)
    )
    base = _to_read(run).model_dump()
    return AgentRunDetailResponse(
        **base,
        events=[_to_event_read(event) for event in events_result.scalars()],
        context_snapshot=_to_context_snapshot_read(snapshot) if snapshot is not None else None,
    )


@router.get("/{run_id}/kpi", response_model=AgentRunKpiResponse)
async def get_agent_run_kpi_endpoint(
    run_id: UUID,
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> AgentRunKpiResponse:
    """Read AC-KPI-02 source metrics for one tenant-scoped AgentRun.

    `actor_id` is resolved only for authentication. The response intentionally
    exposes timestamps and counts, not raw AgentRunEvent payloads.
    """
    kpi = await AgentRunKpiService(session).fetch(tenant_id=tenant_id, run_id=run_id)
    if kpi is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="agent run not found",
        )
    return _to_kpi_response(kpi)


@router.post("/{run_id}/cancel", response_model=AgentRunResponse, status_code=200)
async def cancel_agent_run_endpoint(
    run_id: UUID,
    body: CancelAgentRunRequest,
    actor_id: UUID = Depends(get_current_actor_id),
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AgentRunResponse:
    try:
        run = await cancel_agent_run(
            session=session,
            run_id=run_id,
            reason=body.reason,
            actor_id=actor_id,
            tenant_id=tenant_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="agent run not found",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    await session.commit()
    return _to_response(run)


__all__ = [
    "AgentRunDetailResponse",
    "AgentRunEventRead",
    "AgentRunKpiResponse",
    "AgentRunListResponse",
    "AgentRunRead",
    "AgentRunResponse",
    "CancelAgentRunRequest",
    "ContextSnapshotRead",
    "router",
]
