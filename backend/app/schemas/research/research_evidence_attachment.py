from __future__ import annotations

from datetime import UTC, datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator


class ResearchEvidenceAttachmentMetric(BaseModel):
    """Per-research_task evidence attachment rate (F-PR24-R1-001 P1 adopt).

    NOT the AC-KPI-04 ``citation_coverage`` metric. The AC-KPI-04
    citation_coverage requires GroundingSupport (citations linked from
    final-adopted generated artifacts to evidence sources), which
    Sprint 11 BL-0126 implements. This service provides the **upstream
    data source** for that aggregation: of the claims attached to this
    research_task, how many have at least one ``evidence_items`` row
    attached (i.e., research has gathered supporting evidence).

    A research_task can have evidence_items attached but the final
    adopted answer might omit citations entirely; that case would still
    show ``attachment_rate == 1.0`` here while AC-KPI-04 would correctly
    record ``citation_coverage == 0.0``. Sprint 11 BL-0126 reconciles
    this with GroundingSupport-derived per-AgentRun coverage.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    research_task_id: UUID
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    computed_at: datetime

    @field_validator("computed_at")
    @classmethod
    def _computed_at_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("computed_at must be timezone-aware.")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _numerator_must_not_exceed_denominator(self) -> Self:
        if self.numerator > self.denominator:
            raise ValueError("numerator must be less than or equal to denominator.")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def attachment_rate(self) -> float | None:
        """Numerator / denominator, or ``None`` for empty research_task.

        ``None`` semantics (SP-010 §QL-C F-QLC-007 + SP-011 citation_coverage
        acceptance spec): a research_task with zero claims is reported with
        ``denominator == 0`` and ``attachment_rate is None``. Sprint 11
        BL-0126 decides how to treat the null case at the AgentRun
        aggregation layer (typically uncovered = 0 by default policy).
        """

        if self.denominator == 0:
            return None
        return self.numerator / self.denominator


__all__ = ["ResearchEvidenceAttachmentMetric"]
