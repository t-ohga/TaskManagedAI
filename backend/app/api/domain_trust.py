"""SP-032 (ADR-00052): domain_trust_registry API (tenant-scoped)。

write は ``require_project_owner`` (P0 owner = tenant owner、project route なし)。domain は server で
``normalize_domain`` (raise → 400)、unique(tenant, domain) violation は 409 (R1 F-013)。PATCH は
trust_tier / rationale のみ (domain immutable)。audit payload は ID + 正規化済み domain + trust_tier
(raw rationale 本文は含めない、R1 F-007)。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api._request_trace import correlation_id, trace_id
from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.api.me import require_project_owner
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.repositories.domain_trust import DomainTrustRepository
from backend.app.schemas.domain_trust import (
    DomainTrustCreate,
    DomainTrustListResponse,
    DomainTrustRead,
    DomainTrustUpdate,
)
from backend.app.services.research.domain_normalize import (
    DomainNormalizationError,
    normalize_domain,
)
from backend.app.services.research.read_redaction import redact_domain
from backend.app.services.research.read_redaction import (
    to_domain_trust_read as _to_read,
)

router = APIRouter(prefix="/api/v1/domain-trust", tags=["domain-trust"])


async def _audit(
    session: AsyncSession,
    request: Request,
    *,
    tenant_id: int,
    actor_id: UUID,
    event_type: str,
    payload: dict[str, object],
) -> None:
    corr = correlation_id(request)
    await AuditEventRepository(session).append(
        tenant_id=tenant_id,
        event_type=event_type,
        actor_id=actor_id,
        correlation_id=corr,
        trace_id=trace_id(request),
        payload={
            **payload,
            "tenant_id": tenant_id,
            "actor_id": str(actor_id),
            "correlation_id": corr,
            "timestamp": datetime.now(tz=UTC).isoformat(),
        },
    )


@router.post("", response_model=DomainTrustRead, status_code=status.HTTP_201_CREATED)
async def create_domain_trust_endpoint(
    body: DomainTrustCreate,
    request: Request,
    owner_actor_id: UUID = Depends(require_project_owner),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> DomainTrustRead:
    try:
        domain = normalize_domain(body.domain)
    except DomainNormalizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "invalid_domain", "error_summary": str(exc)},
        ) from exc

    repo = DomainTrustRepository(session)
    try:
        entry = await repo.create_domain_trust(
            tenant_id=tenant_id,
            domain=domain,
            trust_tier=body.trust_tier,
            rationale=body.rationale,
            created_by_actor_id=owner_actor_id,
        )
        await _audit(
            session,
            request,
            tenant_id=tenant_id,
            actor_id=owner_actor_id,
            event_type="domain_trust_registered",
            payload={
                "domain_trust_id": str(entry.id),
                "domain": redact_domain(domain),
                "trust_tier": body.trust_tier,
            },
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "domain_trust_duplicate",
                "error_summary": "a trust entry for this domain already exists",
            },
        ) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "domain_trust_payload_validation_failed", "error_summary": str(exc)},
        ) from exc
    return _to_read(entry)


@router.get("", response_model=DomainTrustListResponse)
async def list_domain_trust_endpoint(
    _actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> DomainTrustListResponse:
    entries = await DomainTrustRepository(session).list_domain_trust(tenant_id=tenant_id)
    return DomainTrustListResponse(items=[_to_read(e) for e in entries])


@router.patch("/{entry_id}", response_model=DomainTrustRead)
async def update_domain_trust_endpoint(
    entry_id: UUID,
    body: DomainTrustUpdate,
    request: Request,
    owner_actor_id: UUID = Depends(require_project_owner),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> DomainTrustRead:
    values = body.model_dump(exclude_unset=True)
    repo = DomainTrustRepository(session)
    existing = await repo.get_domain_trust(tenant_id=tenant_id, entry_id=entry_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "domain_trust_not_found", "error_summary": "domain trust entry not found"},
        )
    if not values:
        return _to_read(existing)
    try:
        entry = await repo.update_domain_trust(
            tenant_id=tenant_id,
            entry_id=entry_id,
            values=values,
        )
        if entry is None:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_code": "domain_trust_not_found", "error_summary": "domain trust entry not found"},
            )
        await _audit(
            session,
            request,
            tenant_id=tenant_id,
            actor_id=owner_actor_id,
            event_type="domain_trust_updated",
            payload={
                "domain_trust_id": str(entry_id),
                "domain": redact_domain(entry.domain),
                "changed_fields": sorted(values.keys()),
                "trust_tier": entry.trust_tier,
            },
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "domain_trust_update_failed", "error_summary": str(exc)},
        ) from exc
    return _to_read(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_domain_trust_endpoint(
    entry_id: UUID,
    request: Request,
    owner_actor_id: UUID = Depends(require_project_owner),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> None:
    repo = DomainTrustRepository(session)
    existing = await repo.get_domain_trust(tenant_id=tenant_id, entry_id=entry_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "domain_trust_not_found", "error_summary": "domain trust entry not found"},
        )
    deleted = await repo.delete_domain_trust(tenant_id=tenant_id, entry_id=entry_id)
    if not deleted:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "domain_trust_not_found", "error_summary": "domain trust entry not found"},
        )
    await _audit(
        session,
        request,
        tenant_id=tenant_id,
        actor_id=owner_actor_id,
        event_type="domain_trust_removed",
        payload={"domain_trust_id": str(entry_id), "domain": redact_domain(existing.domain)},
    )
    await session.commit()


__all__ = ["router"]
