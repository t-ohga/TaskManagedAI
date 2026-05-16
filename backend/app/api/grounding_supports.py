"""GroundingSupport REST API (Sprint 10 BL-0119).

Endpoints:
- POST   /api/v1/projects/{project_id}/agent-runs/{agent_run_id}/grounding-supports
  Register a generated_artifact ↔ Evidence binding.
- GET    /api/v1/projects/{project_id}/agent-runs/{agent_run_id}/grounding-supports
  List all GroundingSupport rows attributed to the AgentRun.
- GET    /api/v1/projects/{project_id}/agent-runs/{agent_run_id}/citation-coverage
  Compute and return the AC-KPI-04 claim-level coverage metric.
- DELETE /api/v1/projects/{project_id}/grounding-supports/{grounding_support_id}
  Remove a single GroundingSupport (recreate semantics — P0 immutable
  rows are removed-and-recreated rather than updated).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_db_session,
    get_tenant_id,
)
from backend.app.repositories.grounding_support import (
    GroundingSupportRepository,
)
from backend.app.schemas.grounding_support import (
    CitationCoverageRead,
    GroundingSupportCreate,
    GroundingSupportRead,
)
from backend.app.services.research.citation_coverage_source import (
    CitationCoverageError,
    compute_citation_coverage,
)

run_router = APIRouter(
    prefix="/api/v1/projects/{project_id}/agent-runs/{agent_run_id}",
    tags=["grounding-supports"],
)

project_router = APIRouter(
    prefix="/api/v1/projects/{project_id}/grounding-supports",
    tags=["grounding-supports"],
)


@run_router.post(
    "/grounding-supports",
    response_model=GroundingSupportRead,
    status_code=status.HTTP_201_CREATED,
)
async def register_grounding_support(
    project_id: UUID,
    agent_run_id: UUID,
    payload: GroundingSupportCreate,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: int = Depends(get_tenant_id),
) -> GroundingSupportRead:
    if payload.agent_run_id != agent_run_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="payload agent_run_id must match path agent_run_id.",
        )
    repo = GroundingSupportRepository(session)
    try:
        support = await repo.create_grounding_support(
            tenant_id=tenant_id,
            project_id=project_id,
            grounding_support_create=payload,
        )
    except IntegrityError as exc:
        # FK chain rejection (e.g. cross-project claim_id) or unique
        # violation. Surface as 422 so the boundary intent is explicit.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"grounding_support integrity violation: {exc.orig}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return GroundingSupportRead.model_validate(support)


@run_router.get(
    "/grounding-supports",
    response_model=list[GroundingSupportRead],
)
async def list_grounding_supports(
    project_id: UUID,
    agent_run_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: int = Depends(get_tenant_id),
) -> list[GroundingSupportRead]:
    repo = GroundingSupportRepository(session)
    rows = await repo.list_grounding_supports_by_agent_run(
        tenant_id=tenant_id,
        project_id=project_id,
        agent_run_id=agent_run_id,
    )
    return [GroundingSupportRead.model_validate(row) for row in rows]


@run_router.get(
    "/citation-coverage",
    response_model=CitationCoverageRead,
)
async def get_citation_coverage(
    project_id: UUID,
    agent_run_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: int = Depends(get_tenant_id),
) -> CitationCoverageRead:
    try:
        metric = await compute_citation_coverage(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            agent_run_id=agent_run_id,
        )
    except CitationCoverageError as exc:
        if exc.reason_code == "agent_run_not_in_project":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return CitationCoverageRead.model_validate(metric)


@project_router.delete(
    "/{grounding_support_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_grounding_support(
    project_id: UUID,
    grounding_support_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: int = Depends(get_tenant_id),
) -> None:
    repo = GroundingSupportRepository(session)
    deleted = await repo.delete_grounding_support(
        tenant_id=tenant_id,
        project_id=project_id,
        grounding_support_id=grounding_support_id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"grounding_support {grounding_support_id} not found.",
        )


__all__ = ["project_router", "run_router"]
