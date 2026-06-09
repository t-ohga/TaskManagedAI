"""SP-027 (ADR-00053): per-source effective trust 派生 (read-only、deterministic)。

effective trust = manual override (evidence_sources.trust_level) > domain 由来 (SP-032
domain_trust_registry、exact hostname match) > 未設定/invalid。AI / 外部呼び出しなし。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.claim import Claim
from backend.app.db.models.evidence_item import EvidenceItem
from backend.app.db.models.evidence_source import EvidenceSource
from backend.app.repositories.domain_trust import DomainTrustRepository
from backend.app.schemas.source_trust import EffectiveSourceTrust
from backend.app.services.research.domain_normalize import domain_from_url


def resolve_effective_source_trust(
    *,
    evidence_source_id: UUID,
    manual_trust_level: str | None,
    manual_trust_score: float | None,
    domain_tier: str | None,
    domain: str | None,
) -> EffectiveSourceTrust:
    """1 source の effective trust を解決する (純関数、registry lookup は呼び出し側で実施)。

    - manual_trust_level が set → origin=manual。
    - else domain 正規化不能 → origin=invalid。
    - else domain_tier が set (registry hit) → origin=domain (score は常に null)。
    - else origin=none。
    """
    if manual_trust_level is not None:
        return EffectiveSourceTrust(
            evidence_source_id=evidence_source_id,
            trust_level=manual_trust_level,
            trust_score=manual_trust_score,
            origin="manual",
            domain=None,
            match_type="none",
        )
    if domain is None:
        return EffectiveSourceTrust(
            evidence_source_id=evidence_source_id,
            trust_level=None,
            trust_score=None,
            origin="invalid",
            domain=None,
            match_type="invalid",
        )
    if domain_tier is not None:
        return EffectiveSourceTrust(
            evidence_source_id=evidence_source_id,
            trust_level=domain_tier,
            trust_score=None,
            origin="domain",
            domain=domain,
            match_type="exact",
        )
    return EffectiveSourceTrust(
        evidence_source_id=evidence_source_id,
        trust_level=None,
        trust_score=None,
        origin="none",
        domain=domain,
        match_type="none",
    )


async def build_source_trust_list(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    research_task_id: UUID,
) -> list[EffectiveSourceTrust]:
    """research_task の各 evidence source の effective trust を返す。

    導出経路: research_task → claims → evidence_items → evidence_sources の distinct (source id asc)。
    """
    rows = (
        await session.execute(
            select(
                EvidenceSource.id,
                EvidenceSource.canonical_url,
                EvidenceSource.trust_level,
                EvidenceSource.trust_score,
            )
            .select_from(Claim)
            .join(
                EvidenceItem,
                (EvidenceItem.tenant_id == Claim.tenant_id)
                & (EvidenceItem.project_id == Claim.project_id)
                & (EvidenceItem.claim_id == Claim.id),
            )
            .join(
                EvidenceSource,
                (EvidenceSource.tenant_id == EvidenceItem.tenant_id)
                & (EvidenceSource.id == EvidenceItem.source_id),
            )
            .where(
                Claim.tenant_id == tenant_id,
                Claim.project_id == project_id,
                Claim.research_task_id == research_task_id,
            )
            .distinct()
            .order_by(EvidenceSource.id)
        )
    ).all()

    normalized_by_source: dict[UUID, str | None] = {}
    for source_id, canonical_url, _level, _score in rows:
        normalized_by_source[source_id] = domain_from_url(canonical_url)

    registry = await DomainTrustRepository(session).get_by_domains(
        tenant_id=tenant_id,
        domains=sorted({d for d in normalized_by_source.values() if d is not None}),
    )

    results: list[EffectiveSourceTrust] = []
    for source_id, _canonical_url, level, score in rows:
        domain = normalized_by_source[source_id]
        entry = registry.get(domain) if domain is not None else None
        results.append(
            resolve_effective_source_trust(
                evidence_source_id=source_id,
                manual_trust_level=level,
                manual_trust_score=score,
                domain_tier=entry.trust_tier if entry is not None else None,
                domain=domain,
            )
        )
    return results


__all__ = ["build_source_trust_list", "resolve_effective_source_trust"]
