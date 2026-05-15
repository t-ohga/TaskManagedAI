from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.repositories.claim import ClaimRepository
from backend.app.schemas.claim import ClaimCreate, ClaimRead
from backend.app.services.research.prov_validator import (
    ProvValidationError,
    validate_provenance_json,
)

router = APIRouter(
    prefix="/api/projects/{project_id}/research-tasks/{research_task_id}/claims",
    tags=["claims"],
)


def _provenance_json_hash(provenance_json: dict[str, Any]) -> str:
    canonical = json.dumps(
        provenance_json,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _correlation_id(request: Request) -> str:
    value = request.headers.get("x-correlation-id")
    if value:
        return value
    return str(getattr(request.state, "request_id", ""))


def _trace_id(request: Request) -> str | None:
    return request.headers.get("x-trace-id")


@router.post("", response_model=ClaimRead, status_code=status.HTTP_201_CREATED)
async def create_claim_endpoint(
    project_id: UUID,
    research_task_id: UUID,
    body: ClaimCreate,
    request: Request,
    actor_id: UUID = Depends(get_current_actor_id),
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ClaimRead:
    try:
        validate_provenance_json(body.provenance_json)
    except ProvValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "prov_validation_failed",
                "error_summary": exc.detail,
            },
        ) from exc

    repo = ClaimRepository(session)
    try:
        claim = await repo.create_claim(
            tenant_id=tenant_id,
            project_id=project_id,
            research_task_id=research_task_id,
            claim_create=body,
        )
        correlation_id = _correlation_id(request)
        await AuditEventRepository(session).append(
            tenant_id=tenant_id,
            event_type="claim_created",
            actor_id=actor_id,
            correlation_id=correlation_id,
            trace_id=_trace_id(request),
            payload={
                "tenant_id": tenant_id,
                "actor_id": str(actor_id),
                "claim_id": str(claim.id),
                "research_task_id": str(research_task_id),
                "provenance_json_hash": _provenance_json_hash(body.provenance_json),
                "correlation_id": correlation_id,
                "timestamp": datetime.now(tz=UTC).isoformat(),
            },
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "claim_create_failed",
                "error_summary": "claim project/research_task binding failed",
            },
        ) from exc

    return ClaimRead.model_validate(claim)


@router.get("", response_model=list[ClaimRead])
async def list_claims_endpoint(
    project_id: UUID,
    research_task_id: UUID,
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[ClaimRead]:
    repo = ClaimRepository(session)
    claims = await repo.list_claims_by_research_task(
        tenant_id=tenant_id,
        project_id=project_id,
        research_task_id=research_task_id,
    )
    return [ClaimRead.model_validate(claim) for claim in claims]


__all__ = ["router"]
