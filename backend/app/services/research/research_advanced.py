"""SP-032 (ADR-00052): research advanced summary 組み立て (read-only)。

conflict groups + conflict candidates + per-claim computed_freshness + evidence source ごとの
domain trust 適用結果を 1 つの read model に集約する。すべて deterministic な DB read のみ。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.claim import Claim
from backend.app.db.models.evidence_item import EvidenceItem
from backend.app.db.models.evidence_source import EvidenceSource
from backend.app.repositories.conflict_group import ConflictGroupRepository
from backend.app.repositories.domain_trust import DomainTrustRepository
from backend.app.schemas.research_advanced import (
    ClaimFreshness,
    EvidenceDomainTrust,
    ResearchAdvancedSummary,
)
from backend.app.services.research.conflict_detection import list_conflict_candidates
from backend.app.services.research.domain_normalize import domain_from_url
from backend.app.services.research.freshness import compute_claim_freshness, effective_at
from backend.app.services.research.read_redaction import to_conflict_group_read


async def build_research_advanced_summary(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    research_task_id: UUID,
    as_of: datetime | None = None,
) -> ResearchAdvancedSummary:
    now = as_of if as_of is not None else datetime.now(tz=UTC)

    # conflict groups
    groups = await ConflictGroupRepository(session).list_conflict_groups_by_research_task(
        tenant_id=tenant_id,
        project_id=project_id,
        research_task_id=research_task_id,
    )

    # conflict candidates + relation coverage
    candidates, relation_coverage = await list_conflict_candidates(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        research_task_id=research_task_id,
    )

    # all claim ids (freshness entry を全 claim 分作るため)
    claim_ids = list(
        (
            await session.execute(
                select(Claim.id)
                .where(
                    Claim.tenant_id == tenant_id,
                    Claim.project_id == project_id,
                    Claim.research_task_id == research_task_id,
                )
                .order_by(Claim.created_at, Claim.id)
            )
        )
        .scalars()
        .all()
    )

    # supporting evidence の timestamps を claim 単位で収集
    supporting_rows = (
        await session.execute(
            select(
                EvidenceItem.claim_id,
                EvidenceSource.published_at,
                EvidenceSource.retrieved_at,
            )
            .select_from(Claim)
            .join(
                EvidenceItem,
                (EvidenceItem.tenant_id == Claim.tenant_id)
                & (EvidenceItem.project_id == Claim.project_id)
                & (EvidenceItem.claim_id == Claim.id)
                & (EvidenceItem.relation == "supports"),
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
        )
    ).all()

    timestamps_by_claim: dict[UUID, list[tuple[datetime | None, datetime | None]]] = {}
    for claim_id, published_at, retrieved_at in supporting_rows:
        timestamps_by_claim.setdefault(claim_id, []).append((published_at, retrieved_at))

    claim_freshness: list[ClaimFreshness] = []
    for claim_id in claim_ids:
        timestamps = timestamps_by_claim.get(claim_id, [])
        computed = compute_claim_freshness(timestamps, now)
        effs = [
            eff
            for published_at, retrieved_at in timestamps
            if (eff := effective_at(published_at, retrieved_at)) is not None
        ]
        newest = max(effs) if effs else None
        claim_freshness.append(
            ClaimFreshness(
                claim_id=claim_id,
                computed_freshness=computed,
                newest_evidence_at=newest,
            )
        )

    # evidence source ごとの domain trust 適用結果
    source_rows = (
        await session.execute(
            select(EvidenceSource.id, EvidenceSource.canonical_url)
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
    for source_id, canonical_url in source_rows:
        normalized_by_source[source_id] = domain_from_url(canonical_url)

    registry = await DomainTrustRepository(session).get_by_domains(
        tenant_id=tenant_id,
        domains=sorted({d for d in normalized_by_source.values() if d is not None}),
    )

    evidence_domain_trust: list[EvidenceDomainTrust] = []
    for source_id in normalized_by_source:
        domain = normalized_by_source[source_id]
        if domain is None:
            evidence_domain_trust.append(
                EvidenceDomainTrust(
                    evidence_source_id=source_id,
                    domain=None,
                    trust_tier=None,
                    match_type="invalid",
                )
            )
            continue
        entry = registry.get(domain)
        if entry is None:
            evidence_domain_trust.append(
                EvidenceDomainTrust(
                    evidence_source_id=source_id,
                    domain=domain,
                    trust_tier=None,
                    match_type="none",
                )
            )
        else:
            evidence_domain_trust.append(
                EvidenceDomainTrust(
                    evidence_source_id=source_id,
                    domain=domain,
                    trust_tier=entry.trust_tier,
                    match_type="exact",
                )
            )

    return ResearchAdvancedSummary(
        research_task_id=research_task_id,
        conflict_groups=[to_conflict_group_read(g) for g in groups],
        conflict_candidates=candidates,
        relation_coverage=relation_coverage,
        claim_freshness=claim_freshness,
        evidence_domain_trust=evidence_domain_trust,
    )


__all__ = ["build_research_advanced_summary"]
