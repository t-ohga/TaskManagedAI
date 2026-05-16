from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.repositories.research_task import ResearchTaskRepository
from backend.app.schemas.research.evidence_set import ResearchSetReference
from backend.app.schemas.research_task import (
    ResearchTaskDetailRead,
    ResearchTaskListResponse,
    ResearchTaskRead,
)
from backend.app.services.research.evidence_set_hash import compute_evidence_set_hash
from backend.app.services.research.research_evidence_attachment import (
    compute_research_evidence_attachment_rate,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/research-tasks",
    tags=["research_tasks"],
)

_TRACE_ID_RE = re.compile(
    r"^[0-9a-fA-F]{16,32}$"
    r"|^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _correlation_id(request: Request) -> str:
    value = request.headers.get("x-correlation-id")
    if value and _TRACE_ID_RE.fullmatch(value):
        return value
    fallback = str(getattr(request.state, "request_id", ""))
    if fallback and _TRACE_ID_RE.fullmatch(fallback):
        return fallback
    return ""


@router.get("", response_model=ResearchTaskListResponse)
async def list_research_tasks_endpoint(
    project_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    actor_id: UUID = Depends(get_current_actor_id),
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ResearchTaskListResponse:
    repo = ResearchTaskRepository(session)
    tasks, total = await repo.list_research_tasks_by_project(
        tenant_id=tenant_id,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )
    return ResearchTaskListResponse(
        items=[ResearchTaskRead.model_validate(task) for task in tasks],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{research_task_id}", response_model=ResearchTaskDetailRead)
async def get_research_task_endpoint(
    project_id: UUID,
    research_task_id: UUID,
    actor_id: UUID = Depends(get_current_actor_id),
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ResearchTaskDetailRead:
    repo = ResearchTaskRepository(session)
    task = await repo.get_research_task_by_id(
        tenant_id=tenant_id,
        project_id=project_id,
        research_task_id=research_task_id,
    )
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="research task not found")

    reference = ResearchSetReference(
        project_id=project_id,
        research_task_id=research_task_id,
    )
    try:
        evidence_set_hash = await compute_evidence_set_hash(
            session=session,
            tenant_id=tenant_id,
            reference=reference,
        )
        attachment_metric = await compute_research_evidence_attachment_rate(
            session=session,
            tenant_id=tenant_id,
            project_id=project_id,
            research_task_id=research_task_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "research_task_evidence_boundary_failed",
                "error_summary": "research task evidence boundary validation failed",
            },
        ) from exc

    base = ResearchTaskRead.model_validate(task).model_dump()
    return ResearchTaskDetailRead.model_validate(
        {
            **base,
            "evidence_set_hash": evidence_set_hash,
            "research_evidence_attachment": attachment_metric,
        }
    )


__all__ = ["router"]
