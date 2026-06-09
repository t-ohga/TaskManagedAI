"""SP-027 (ADR-00053): per-source effective trust の read / write schema。

trust_level は SP-032 ``TrustTier`` reuse。effective 派生 origin = manual > domain > none/invalid。
PATCH body の trust_level / trust_score 以外は extra="forbid" で reject (server-owned boundary)。
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.db.models.domain_trust import TrustTier
from backend.app.schemas.research_advanced import DomainTrustMatchType

# R1 F-005: trust_score は manual-only。domain 由来は常に score=null。
SourceTrustOrigin = Literal["manual", "domain", "none", "invalid"]


class EffectiveSourceTrust(BaseModel):
    """evidence source の effective trust (manual override > domain 由来 > 未設定/invalid)。"""

    evidence_source_id: UUID
    trust_level: TrustTier | None
    trust_score: float | None
    origin: SourceTrustOrigin
    domain: str | None
    match_type: DomainTrustMatchType


class SourceTrustListResponse(BaseModel):
    items: list[EffectiveSourceTrust]


class EvidenceSourceTrustUpdate(BaseModel):
    """PATCH evidence-sources/{id}/trust。set = {trust_level, trust_score?}、clear = {両 null}。"""

    model_config = ConfigDict(extra="forbid")

    trust_level: TrustTier | None
    trust_score: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _score_requires_level(self) -> EvidenceSourceTrustUpdate:
        # R1 F-004: trust_score 単独 (level null + score 非 null) を 400 で reject。
        if self.trust_level is None and self.trust_score is not None:
            raise ValueError("trust_score requires trust_level (level null = clear).")
        return self


__all__ = [
    "EffectiveSourceTrust",
    "EvidenceSourceTrustUpdate",
    "SourceTrustListResponse",
    "SourceTrustOrigin",
]
