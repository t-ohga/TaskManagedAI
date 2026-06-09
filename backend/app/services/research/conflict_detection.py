"""SP-032 (ADR-00052 R1 F-008): 矛盾検出 (deterministic SQL、read-only)。

claim ごとに evidence_items.relation を集計し、contradicting evidence を持つ claim を candidate と
する。AI / 外部呼び出しなし。group の自動生成はしない (reviewer が判断)。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.claim import Claim
from backend.app.db.models.evidence_item import EvidenceItem
from backend.app.schemas.research_advanced import ConflictCandidate


async def list_conflict_candidates(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    research_task_id: UUID,
) -> tuple[list[ConflictCandidate], float]:
    """research_task の conflict candidates + relation_coverage を返す。

    - candidate = `contradicting_count > 0` の claim。
    - relation_coverage = (1 件以上の evidence_item を持つ claim 数) / (total claim 数)。
      total が 0 なら 0.0。「争点なし」と「relation 未整備 (evidence 未付与)」を UI が区別する signal。
    """
    contradicting = func.count(EvidenceItem.id).filter(EvidenceItem.relation == "contradicts")
    supporting = func.count(EvidenceItem.id).filter(EvidenceItem.relation == "supports")
    context = func.count(EvidenceItem.id).filter(EvidenceItem.relation == "context")
    evidence_count = func.count(EvidenceItem.id)

    stmt = (
        select(
            Claim.id.label("claim_id"),
            Claim.conflict_group_id.label("conflict_group_id"),
            contradicting.label("contradicting_count"),
            supporting.label("supporting_count"),
            context.label("context_count"),
            evidence_count.label("evidence_count"),
        )
        .select_from(Claim)
        .outerjoin(
            EvidenceItem,
            (EvidenceItem.tenant_id == Claim.tenant_id)
            & (EvidenceItem.project_id == Claim.project_id)
            & (EvidenceItem.claim_id == Claim.id),
        )
        .where(
            Claim.tenant_id == tenant_id,
            Claim.project_id == project_id,
            Claim.research_task_id == research_task_id,
        )
        .group_by(Claim.id, Claim.conflict_group_id, Claim.created_at)
        .order_by(Claim.created_at, Claim.id)
    )

    result = await session.execute(stmt)
    rows = result.all()

    total_claims = len(rows)
    claims_with_evidence = sum(1 for row in rows if row.evidence_count > 0)
    relation_coverage = (claims_with_evidence / total_claims) if total_claims > 0 else 0.0

    candidates = [
        ConflictCandidate(
            claim_id=row.claim_id,
            contradicting_count=row.contradicting_count,
            supporting_count=row.supporting_count,
            context_count=row.context_count,
            conflict_group_id=row.conflict_group_id,
        )
        for row in rows
        if row.contradicting_count > 0
    ]
    return candidates, relation_coverage


__all__ = ["list_conflict_candidates"]
