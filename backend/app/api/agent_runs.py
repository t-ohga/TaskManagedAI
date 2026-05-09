from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.db.models.agent_run import AgentRun
from backend.app.domain.agent_runtime.status import AgentRunStatus, BlockedReason
from backend.app.services.agent_runtime.cancel import cancel_agent_run

router = APIRouter(prefix="/api/v1/agent_runs", tags=["agent_runs"])


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
    "AgentRunResponse",
    "CancelAgentRunRequest",
    "router",
]

