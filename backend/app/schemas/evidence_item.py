from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _rls_ready_metadata() -> dict[str, Any]:
    return {"rls_ready": True}


class EvidenceItemBase(BaseModel):
    locator: str = Field(min_length=1, max_length=500)
    relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=_rls_ready_metadata)

    @field_validator("metadata", mode="before")
    @classmethod
    def _validate_metadata_is_dict(cls, value: object) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("metadata must be a JSON object.")
        return value


class EvidenceItemCreate(EvidenceItemBase):
    source_id: UUID


class EvidenceItemRead(EvidenceItemBase):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    tenant_id: int
    project_id: UUID
    claim_id: UUID
    source_id: UUID
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class EvidenceItemAttach(BaseModel):
    source_id: UUID
    locator: str = Field(min_length=1, max_length=500)


__all__ = [
    "EvidenceItemAttach",
    "EvidenceItemBase",
    "EvidenceItemCreate",
    "EvidenceItemRead",
]
