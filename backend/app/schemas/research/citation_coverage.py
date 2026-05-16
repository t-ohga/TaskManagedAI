from __future__ import annotations

from datetime import UTC, datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator


class CitationCoverageMetric(BaseModel):
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
    def coverage(self) -> float | None:
        if self.denominator == 0:
            return None
        return self.numerator / self.denominator


__all__ = ["CitationCoverageMetric"]
