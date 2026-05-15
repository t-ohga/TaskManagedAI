from __future__ import annotations

import re
from datetime import UTC, datetime
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
from backend.app.repositories.evidence_item import EvidenceItemRepository
from backend.app.schemas.evidence_item import EvidenceItemCreate, EvidenceItemRead

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/claims/{claim_id}/evidence-items",
    tags=["evidence_items"],
)


def _constraint_name(error: IntegrityError) -> str | None:
    candidates = [error.orig, getattr(error.orig, "__cause__", None)]
    for candidate in candidates:
        value = getattr(candidate, "constraint_name", None)
        if isinstance(value, str):
            return value
    return None


# F-PR19-R5-001 P1 adopt: trace_id format を narrow に (claims.py と同 invariant)
_TRACE_ID_RE = re.compile(
    r"^[0-9a-fA-F]{16,32}$"
    r"|^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    r"|^[A-Za-z0-9-]{16,64}$"
)


def _correlation_id(request: Request) -> str:
    value = request.headers.get("x-correlation-id")
    if value and _TRACE_ID_RE.fullmatch(value):
        return value
    # F-PR19-R6-006 P1 adopt: fallback request_id も sanitize、framework が caller-controlled
    # request_id を state に set する経路でも secret-shaped string を audit に保存させない。
    fallback = str(getattr(request.state, "request_id", ""))
    if fallback and _TRACE_ID_RE.fullmatch(fallback):
        return fallback
    return ""


def _trace_id(request: Request) -> str | None:
    # F-PR19-R4-001 P1 adopt: caller-controlled x-trace-id header に raw secret / canary が混入する経路を遮断
    value = request.headers.get("x-trace-id")
    if value is None or not _TRACE_ID_RE.fullmatch(value):
        return None
    return value


@router.post("", response_model=EvidenceItemRead, status_code=status.HTTP_201_CREATED)
async def create_evidence_item_endpoint(
    project_id: UUID,
    claim_id: UUID,
    body: EvidenceItemCreate,
    request: Request,
    actor_id: UUID = Depends(get_current_actor_id),
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> EvidenceItemRead:
    repo = EvidenceItemRepository(session)
    try:
        try:
            item = await repo.create_evidence_item(
                tenant_id=tenant_id,
                project_id=project_id,
                claim_id=claim_id,
                evidence_item_create=body,
            )
        except ValueError as exc:
            # F-PR19-R3-002 P2 adopt: assert_no_raw_secret 失敗を 400 で返す
            # (uncontrolled 500 ではなく structured 4xx error code、caller が原因を区別可能)
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error_code": "evidence_item_payload_validation_failed",
                    "error_summary": str(exc),
                },
            ) from exc
        correlation_id = _correlation_id(request)
        await AuditEventRepository(session).append(
            tenant_id=tenant_id,
            event_type="evidence_item_attached",
            actor_id=actor_id,
            correlation_id=correlation_id,
            trace_id=_trace_id(request),
            payload={
                "tenant_id": tenant_id,
                "actor_id": str(actor_id),
                "evidence_item_id": str(item.id),
                "claim_id": str(claim_id),
                "source_id": str(body.source_id),
                "locator": body.locator,
                "correlation_id": correlation_id,
                "timestamp": datetime.now(tz=UTC).isoformat(),
            },
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if _constraint_name(exc) == "evidence_items_uq_claim_source_locator":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "evidence_item_duplicate",
                    "error_summary": "evidence item already exists for claim/source/locator",
                },
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "evidence_item_attach_failed",
                "error_summary": "evidence item claim/source binding failed",
            },
        ) from exc

    return EvidenceItemRead.model_validate(item)


@router.get("", response_model=list[EvidenceItemRead])
async def list_evidence_items_endpoint(
    project_id: UUID,
    claim_id: UUID,
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[EvidenceItemRead]:
    repo = EvidenceItemRepository(session)
    items = await repo.list_evidence_items_by_claim(
        tenant_id=tenant_id,
        project_id=project_id,
        claim_id=claim_id,
    )
    return [EvidenceItemRead.model_validate(item) for item in items]


__all__ = ["router"]
