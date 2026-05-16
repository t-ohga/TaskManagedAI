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

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.repositories.audit_event import AuditEventRepository
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
    actor_id: UUID = Depends(get_current_actor_id),
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
    # F-PR25-R8-002 fix (Codex R8 P2): record an audit event linking
    # the registering actor to the GroundingSupport row. Pre-R8 the
    # endpoint had no actor binding, so any tenant-scoped request
    # could inflate AC-KPI-04 numerators without attribution.
    audit = AuditEventRepository(session)
    await audit.append(
        tenant_id=tenant_id,
        actor_id=actor_id,
        event_type="grounding_support_registered",
        payload={
            "tenant_id": tenant_id,
            "actor_id": str(actor_id),
            "project_id": str(project_id),
            "agent_run_id": str(agent_run_id),
            "grounding_support_id": str(support.id),
            "claim_id": str(support.claim_id),
            "evidence_source_id": str(support.evidence_source_id),
            "evidence_item_id": str(support.evidence_item_id),
            "support_type": support.support_type,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )

    # F-PR25-R2-002 fix (Codex R2 P1): the repository only flushes; the
    # ``get_db_session`` dependency does not auto-commit on teardown,
    # so the inserted row would be rolled back on response. Commit
    # explicitly so the GroundingSupport row is durable before the
    # 201 reaches the caller.
    await session.commit()
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
    actor_id: UUID = Depends(get_current_actor_id),
) -> None:
    repo = GroundingSupportRepository(session)
    # F-PR25-R9-003 fix (Codex R9 P2): load the row **before** the
    # delete so the audit event can preserve which citation edge was
    # erased (claim / source / item / artifact / support_type).
    # Pre-R9 the audit payload only had the grounding_support_id,
    # which is not enough for an export consumer to reconstruct the
    # AC-KPI-04 input that was deflated.
    existing = await repo.get_grounding_support_by_id(
        tenant_id=tenant_id,
        project_id=project_id,
        grounding_support_id=grounding_support_id,
    )
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"grounding_support {grounding_support_id} not found.",
        )

    deleted = await repo.delete_grounding_support(
        tenant_id=tenant_id,
        project_id=project_id,
        grounding_support_id=grounding_support_id,
    )
    if not deleted:
        # Race between the get and the delete (concurrent DELETE).
        # Surface as 404 so the caller does not see the audit event
        # for a row we did not actually erase.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"grounding_support {grounding_support_id} deleted "
                "concurrently."
            ),
        )

    # F-PR25-R8-002 + F-PR25-R9-003 fix: record an audit event with
    # the full deleted-row fingerprint so an export consumer can
    # reconstruct which AC-KPI-04 input was deflated.
    audit = AuditEventRepository(session)
    await audit.append(
        tenant_id=tenant_id,
        actor_id=actor_id,
        event_type="grounding_support_deleted",
        payload={
            "tenant_id": tenant_id,
            "actor_id": str(actor_id),
            "project_id": str(project_id),
            "grounding_support_id": str(grounding_support_id),
            "agent_run_id": str(existing.agent_run_id),
            "generated_artifact_id": str(existing.generated_artifact_id),
            "claim_id": str(existing.claim_id),
            "evidence_source_id": str(existing.evidence_source_id),
            "evidence_item_id": str(existing.evidence_item_id),
            "support_type": existing.support_type,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    # F-PR25-R2-002 fix (Codex R2 P1): commit so the DELETE is durable;
    # otherwise the row reappears after request teardown.
    await session.commit()


__all__ = ["project_router", "run_router"]
