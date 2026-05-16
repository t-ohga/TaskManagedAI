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
from backend.app.repositories.evidence_source import EvidenceSourceRepository
from backend.app.schemas.evidence_source import EvidenceSourceListResponse, EvidenceSourceRead

router = APIRouter(
    prefix="/api/v1/evidence-sources",
    tags=["evidence_sources"],
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


@router.get("", response_model=EvidenceSourceListResponse)
async def list_evidence_sources_endpoint(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    actor_id: UUID = Depends(get_current_actor_id),
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> EvidenceSourceListResponse:
    repo = EvidenceSourceRepository(session)
    sources, total = await repo.list_evidence_sources_by_tenant(
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
    )
    return EvidenceSourceListResponse(
        items=[EvidenceSourceRead.model_validate(source) for source in sources],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{evidence_source_id}", response_model=EvidenceSourceRead)
async def get_evidence_source_endpoint(
    evidence_source_id: UUID,
    actor_id: UUID = Depends(get_current_actor_id),
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> EvidenceSourceRead:
    repo = EvidenceSourceRepository(session)
    source = await repo.get_evidence_source_by_id(
        tenant_id=tenant_id,
        evidence_source_id=evidence_source_id,
    )
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="evidence source not found")
    return EvidenceSourceRead.model_validate(source)


__all__ = ["router"]
