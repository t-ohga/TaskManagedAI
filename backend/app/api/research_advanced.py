"""SP-032 (ADR-00052): research advanced read-only API。

conflict candidates (deterministic 検出) と research-advanced summary (conflict groups + candidates +
per-claim computed_freshness + evidence domain trust) を返す。read は認証 actor、mutation なし。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.repositories.research_task import get_research_task_by_id
from backend.app.schemas.research_advanced import (
    ConflictCandidateListResponse,
    ResearchAdvancedSummary,
)
from backend.app.services.research.conflict_detection import list_conflict_candidates
from backend.app.services.research.research_advanced import build_research_advanced_summary

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/research-tasks/{research_task_id}",
    tags=["research-advanced"],
)


async def _require_research_task(
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    research_task_id: UUID,
) -> None:
    task = await get_research_task_by_id(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        research_task_id=research_task_id,
    )
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "research_task_not_found", "error_summary": "research task not found"},
        )


@router.get("/conflict-candidates", response_model=ConflictCandidateListResponse)
async def list_conflict_candidates_endpoint(
    project_id: UUID,
    research_task_id: UUID,
    _actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ConflictCandidateListResponse:
    await _require_research_task(session, tenant_id, project_id, research_task_id)
    candidates, relation_coverage = await list_conflict_candidates(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        research_task_id=research_task_id,
    )
    return ConflictCandidateListResponse(items=candidates, relation_coverage=relation_coverage)


@router.get("/research-advanced", response_model=ResearchAdvancedSummary)
async def get_research_advanced_endpoint(
    project_id: UUID,
    research_task_id: UUID,
    _actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ResearchAdvancedSummary:
    await _require_research_task(session, tenant_id, project_id, research_task_id)
    return await build_research_advanced_summary(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        research_task_id=research_task_id,
    )


__all__ = ["router"]
