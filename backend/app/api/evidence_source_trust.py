"""SP-027 (ADR-00053): evidence source の per-source manual trust set/clear API。

PATCH `/api/v1/evidence-sources/{id}/trust` (tenant-scoped、owner-gated)。actor tenant 内の source
のみ更新 (cross-tenant は 404)。response は effective trust。audit payload は固定 allowlist
(evidence_source_id / action / trust_level / trust_score / origin、url/domain/locator/raw なし、R1 F-003)。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api._request_trace import correlation_id, trace_id
from backend.app.api.approval_inbox import get_db_session, get_tenant_id
from backend.app.api.me import require_project_owner
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.repositories.domain_trust import DomainTrustRepository
from backend.app.repositories.evidence_source import EvidenceSourceRepository
from backend.app.schemas.source_trust import EffectiveSourceTrust, EvidenceSourceTrustUpdate
from backend.app.services.research.domain_normalize import domain_from_url
from backend.app.services.research.source_trust import resolve_effective_source_trust

router = APIRouter(prefix="/api/v1/evidence-sources", tags=["source-trust"])

# R1 F-003 + adversarial R1 F-002: 固定 5-field allowlist (tenant/actor/correlation/trace/timestamp は
# AuditEventRepository.append() の専用 column に保存され payload に重複させない)。
TRUST_AUDIT_PAYLOAD_KEYS = frozenset(
    {"evidence_source_id", "action", "trust_level", "trust_score", "origin"}
)


def resolve_trust_write(
    *,
    requested_level: str | None,
    requested_score: float | None,
    score_provided: bool,
    existing_score: float | None,
) -> tuple[str | None, float | None]:
    """書き込む (trust_level, trust_score) を解決する (adversarial R2 F-002、pure)。

    - level null (clear) → 両方 null。
    - level set + score 明示 (`score_provided`) → その値 (null で score だけ clear)。
    - level set + score 省略 → 既存 score を保持 (script/旧 client の silent loss 防止)。
    """
    if requested_level is None:
        return None, None
    if score_provided:
        return requested_level, requested_score
    return requested_level, existing_score


def build_trust_audit_payload(
    *,
    evidence_source_id: UUID,
    action: str,
    trust_level: str | None,
    trust_score: float | None,
    origin: str,
) -> dict[str, object]:
    """trust set/clear の audit payload (固定 allowlist のみ)。"""
    return {
        "evidence_source_id": str(evidence_source_id),
        "action": action,
        "trust_level": trust_level,
        "trust_score": trust_score,
        "origin": origin,
    }


@router.patch("/{evidence_source_id}/trust", response_model=EffectiveSourceTrust)
async def set_evidence_source_trust_endpoint(
    evidence_source_id: UUID,
    body: EvidenceSourceTrustUpdate,
    request: Request,
    owner_actor_id: UUID = Depends(require_project_owner),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> EffectiveSourceTrust:
    repo = EvidenceSourceRepository(session)
    existing = await repo.get_evidence_source_by_id(
        tenant_id=tenant_id, evidence_source_id=evidence_source_id
    )
    if existing is None:
        # cross-tenant / 存在しない id は 404 (存在秘匿、R1 F-002)。
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "evidence_source_not_found", "error_summary": "evidence source not found"},
        )

    # adversarial R2 F-002: omitted `trust_score` を explicit null と区別する (model_fields_set)。
    new_level, new_score = resolve_trust_write(
        requested_level=body.trust_level,
        requested_score=body.trust_score,
        score_provided="trust_score" in body.model_fields_set,
        existing_score=existing.trust_score,
    )

    try:
        updated = await repo.set_trust(
            tenant_id=tenant_id,
            evidence_source_id=evidence_source_id,
            trust_level=new_level,
            trust_score=new_score,
        )
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "evidence_source_trust_invalid", "error_summary": "trust constraint violation"},
        ) from exc
    if updated is None:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "evidence_source_not_found", "error_summary": "evidence source not found"},
        )

    # effective trust を解決 (clear 時は domain 由来 fallback)。
    domain = domain_from_url(updated.canonical_url)
    registry = await DomainTrustRepository(session).get_by_domains(
        tenant_id=tenant_id, domains=[domain] if domain is not None else []
    )
    entry = registry.get(domain) if domain is not None else None
    effective = resolve_effective_source_trust(
        evidence_source_id=evidence_source_id,
        manual_trust_level=updated.trust_level,
        manual_trust_score=updated.trust_score,
        domain_tier=entry.trust_tier if entry is not None else None,
        domain=domain,
    )

    action = "set" if body.trust_level is not None else "clear"
    # R1 F-003 (adversarial R1 F-002): 固定 allowlist は **5 field のみ**
    # (evidence_source_id / action / trust_level / trust_score / origin)。tenant / actor / correlation /
    # trace / timestamp は append() 引数で専用 column に保存され payload には重複させない。url / domain /
    # locator / raw は含めない。
    await AuditEventRepository(session).append(
        tenant_id=tenant_id,
        event_type="evidence_source_trust_set" if action == "set" else "evidence_source_trust_cleared",
        actor_id=owner_actor_id,
        correlation_id=correlation_id(request),
        trace_id=trace_id(request),
        payload=build_trust_audit_payload(
            evidence_source_id=evidence_source_id,
            action=action,
            trust_level=body.trust_level,
            trust_score=body.trust_score,
            origin=effective.origin,
        ),
    )
    await session.commit()
    return effective


__all__ = ["router"]
