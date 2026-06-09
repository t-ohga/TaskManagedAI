"""SP-032 (ADR-00052): research advanced の read-only response schema。

conflict candidates (deterministic 検出) + per-claim computed_freshness (advisory) +
evidence source ごとの domain trust 適用結果 (match_type 付き) を集約する read model。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from backend.app.db.models.domain_trust import TrustTier
from backend.app.schemas.conflict_group import ConflictGroupRead

# R1 F-018: registry lookup 結果。exact=hit / none=未登録 / invalid=domain 正規化不能。
DomainTrustMatchType = Literal["exact", "none", "invalid"]


class ConflictCandidate(BaseModel):
    """R1 F-008: contradicting evidence を持つ claim (= 争点)。"""

    model_config = ConfigDict(from_attributes=True)

    claim_id: UUID
    contradicting_count: int
    supporting_count: int
    context_count: int
    conflict_group_id: UUID | None


class ClaimFreshness(BaseModel):
    """R1 F-006/F-009: claim の computed_freshness (read-only advisory)。"""

    claim_id: UUID
    computed_freshness: float | None
    newest_evidence_at: datetime | None


class EvidenceDomainTrust(BaseModel):
    """R1 F-018: evidence source の domain に対する trust registry 適用結果。"""

    evidence_source_id: UUID
    domain: str | None
    trust_tier: TrustTier | None
    match_type: DomainTrustMatchType


class ResearchAdvancedSummary(BaseModel):
    """research_task の advanced 集約 read model。"""

    research_task_id: UUID
    conflict_groups: list[ConflictGroupRead]
    conflict_candidates: list[ConflictCandidate]
    # relation_coverage = relation 付き evidence を持つ claim 比率 (0.0-1.0)。
    # 「争点なし」と「relation 未整備」を UI が区別するための signal。
    relation_coverage: float
    claim_freshness: list[ClaimFreshness]
    evidence_domain_trust: list[EvidenceDomainTrust]


class ConflictCandidateListResponse(BaseModel):
    items: list[ConflictCandidate]
    relation_coverage: float


__all__ = [
    "ClaimFreshness",
    "ConflictCandidate",
    "ConflictCandidateListResponse",
    "DomainTrustMatchType",
    "EvidenceDomainTrust",
    "ResearchAdvancedSummary",
]
