"""SP-027 (ADR-00053): source trust + provenance の read-only API。

GET source-trust (research task の各 evidence source の effective trust) と GET claims/{id}/provenance
(構造化 PROV view、raw 非露出)。read は認証 actor (tenant)、research_task / claim が
(tenant, project, research_task) に属することを 404 で確認 (R1 F-009)。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.db.models.claim import Claim
from backend.app.repositories.research_task import get_research_task_by_id
from backend.app.schemas.provenance_view import ProvenanceView
from backend.app.schemas.source_trust import SourceTrustListResponse
from backend.app.services.research.provenance_view import build_provenance_view
from backend.app.services.research.source_trust import build_source_trust_list

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/research-tasks/{research_task_id}",
    tags=["source-trust"],
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


@router.get("/source-trust", response_model=SourceTrustListResponse)
async def list_source_trust_endpoint(
    project_id: UUID,
    research_task_id: UUID,
    _actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> SourceTrustListResponse:
    await _require_research_task(session, tenant_id, project_id, research_task_id)
    items = await build_source_trust_list(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        research_task_id=research_task_id,
    )
    return SourceTrustListResponse(items=items)


@router.get("/claims/{claim_id}/provenance", response_model=ProvenanceView)
async def get_claim_provenance_endpoint(
    project_id: UUID,
    research_task_id: UUID,
    claim_id: UUID,
    _actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ProvenanceView:
    await _require_research_task(session, tenant_id, project_id, research_task_id)
    # claim が (tenant, project, research_task) に属することを確認 (R1 F-009、cross-tenant/task は 404)。
    provenance_json = await session.scalar(
        select(Claim.provenance_json).where(
            Claim.tenant_id == tenant_id,
            Claim.project_id == project_id,
            Claim.research_task_id == research_task_id,
            Claim.id == claim_id,
        )
    )
    if provenance_json is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "claim_not_found", "error_summary": "claim not found in research task"},
        )
    payload: dict[str, Any] = provenance_json if isinstance(provenance_json, dict) else {}
    return build_provenance_view(payload)


__all__ = ["router"]
