"""Research-to-Ticket promotion REST API (Sprint 10 BL-0118).

Single endpoint that creates a ``research_promotion`` artifact bound
to the supplied AgentRun. The artifact carries the server-computed
``evidence_set_hash`` for the claim/evidence set so a downstream Ticket
creation flow can attach it without recomputing.

POST /api/v1/projects/{project_id}/research-tasks/{research_task_id}/promote
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.services.research.research_to_ticket_adapter import (
    ResearchToTicketError,
    promote_research_to_ticket,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/research-tasks/{research_task_id}",
    tags=["research-to-ticket"],
)


class ResearchToTicketPromoteRequest(BaseModel):
    """Caller payload. Server owns ``content_hash`` /
    ``evidence_set_hash`` / IDs / timestamps."""

    run_id: UUID
    summary: str = Field(min_length=1, max_length=4000)
    claim_ids: tuple[UUID, ...] = Field(default_factory=tuple)
    evidence_item_ids: tuple[UUID, ...] = Field(default_factory=tuple)
    parent_artifact_id: UUID | None = None


class ResearchToTicketPromoteResponse(BaseModel):
    """Returns the server-computed identity of the promotion artifact +
    the evidence_set_hash that downstream Ticket creation should
    attach to its ContextSnapshot."""

    artifact_id: UUID
    run_id: UUID
    content_hash: str
    evidence_set_hash: str
    payload: dict[str, Any]


@router.post(
    "/promote",
    response_model=ResearchToTicketPromoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def promote(
    project_id: UUID,
    research_task_id: UUID,
    payload: ResearchToTicketPromoteRequest,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: int = Depends(get_tenant_id),
    actor_id: UUID = Depends(get_current_actor_id),
) -> ResearchToTicketPromoteResponse:
    try:
        view = await promote_research_to_ticket(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            research_task_id=research_task_id,
            claim_ids=payload.claim_ids,
            evidence_item_ids=payload.evidence_item_ids,
            run_id=payload.run_id,
            summary=payload.summary,
            parent_artifact_id=payload.parent_artifact_id,
        )
    except ResearchToTicketError as exc:
        if exc.reason_code in (
            "research_task_not_in_project",
            "agent_run_not_found",
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except IntegrityError as exc:
        # F-PR25-R2-004 fix (Codex R2 P2): a stale or different-run
        # ``parent_artifact_id`` trips the composite
        # ``artifacts_parent_artifact_fkey`` during flush. The handler
        # used to surface this as a 500; map to a structured 4xx.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"promotion integrity violation: {exc.orig}",
        ) from exc

    # F-PR25-R2-005 fix (Codex R2 P2): append the
    # ``research_to_ticket_promoted`` audit event so the human/API
    # caller is durably linked to the evidence set seeding downstream
    # ticket work (SP-010 audit contract §line 175-183).
    audit = AuditEventRepository(session)
    await audit.append(
        tenant_id=tenant_id,
        actor_id=actor_id,
        event_type="research_to_ticket_promoted",
        payload={
            "project_id": str(project_id),
            "research_task_id": str(research_task_id),
            "run_id": str(view.artifact.run_id),
            "artifact_id": str(view.artifact.id),
            "evidence_set_hash": view.evidence_set_hash,
            "content_hash": view.artifact.content_hash,
            "claim_id_count": len(payload.claim_ids),
            "evidence_item_id_count": len(payload.evidence_item_ids),
        },
    )

    # F-PR25-R2-001 fix (Codex R2 P1): the service only flushes; the
    # ``get_db_session`` dependency does not auto-commit on teardown,
    # so a successful 201 response would otherwise roll back the
    # artifact + audit event. Commit explicitly before returning.
    await session.commit()

    return ResearchToTicketPromoteResponse(
        artifact_id=view.artifact.id,
        run_id=view.artifact.run_id,
        content_hash=view.artifact.content_hash,
        evidence_set_hash=view.evidence_set_hash,
        payload=dict(view.artifact.content_jsonb),
    )


__all__ = ["router"]
