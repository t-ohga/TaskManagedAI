"""Pydantic schemas for GroundingSupport (Sprint 10 BL-0119 / SP-010 QL-C).

server-owned-boundary §1: ``id`` / ``tenant_id`` / ``project_id`` /
``created_at`` / ``updated_at`` are **NOT** caller-supplied. The repository
strips any value the caller smuggles through.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

SupportType = Literal["cite", "paraphrase", "quote"]


def _rls_ready_metadata() -> dict[str, Any]:
    return {"rls_ready": True}


class GroundingSupportBase(BaseModel):
    """Common write-side fields. ``support_type`` is enum-constrained;
    ``confidence_score`` is optional ``[0, 1]``."""

    support_type: SupportType
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=_rls_ready_metadata)

    @field_validator("metadata", mode="before")
    @classmethod
    def _validate_metadata_is_dict(cls, value: object) -> dict[str, Any]:
        # Mirror Claim / EvidenceItem: force ``rls_ready: true`` so
        # caller-supplied false / missing / non-dict cannot bypass the
        # RLS-ready invariant (cross-source-enum-integrity §3 / DD-02
        # rls_ready metadata).
        if not isinstance(value, dict):
            raise ValueError("metadata must be a JSON object.")
        result = dict(value)
        result["rls_ready"] = True
        return result


class GroundingSupportCreate(GroundingSupportBase):
    """Create payload. The caller supplies the **server-owned IDs** that
    bind the GroundingSupport to its AgentRun, generated artifact, claim,
    evidence_source, and evidence_item. All references must exist in the
    same project (verified by the FK chain) and same AgentRun (verified
    by the ``run_id = agent_run_id`` CHECK + 2-stage FK).

    ``run_id`` is **not** in the create payload — the repository copies
    it from ``agent_run_id`` to satisfy the equality CHECK without ever
    accepting a caller-supplied value (server-owned-boundary §1).
    """

    agent_run_id: UUID
    generated_artifact_id: UUID
    claim_id: UUID
    evidence_source_id: UUID
    evidence_item_id: UUID


class GroundingSupportRead(GroundingSupportBase):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    tenant_id: int
    project_id: UUID
    agent_run_id: UUID
    run_id: UUID
    generated_artifact_id: UUID
    claim_id: UUID
    evidence_source_id: UUID
    evidence_item_id: UUID
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class CitationCoverageRead(BaseModel):
    """Response shape for the citation_coverage source endpoint
    (BL-0119 / AC-KPI-04 source).

    QL-C spec line 162-165:
    - claim-level: ``count(distinct claim_id with >= 1 GroundingSupport)
      / count(distinct claim_id within evaluated AgentRun)``
    - null evidence_set_hash AgentRun is included in the denominator
      with numerator=0 (uncovered).
    - ``denominator_nonzero`` is reported separately so consumers can
      apply AC-KPI-04 P0 acceptance gate that requires a non-zero
      denominator (avoid divide-by-zero masking of failures).
    """

    model_config = ConfigDict(from_attributes=True)

    agent_run_id: UUID
    tenant_id: int
    project_id: UUID
    evidence_set_hash: str | None
    distinct_claims: int
    grounded_claims: int
    coverage: float
    denominator_nonzero: bool


__all__ = [
    "CitationCoverageRead",
    "GroundingSupportBase",
    "GroundingSupportCreate",
    "GroundingSupportRead",
    "SupportType",
]
