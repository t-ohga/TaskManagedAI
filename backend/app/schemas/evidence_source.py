from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _safe_metadata(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("metadata must be a JSON object.")
    return {"rls_ready": value.get("rls_ready") is True}


class EvidenceSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True, frozen=True)

    id: UUID
    tenant_id: int
    canonical_url: str
    content_hash: str
    retrieved_at: datetime
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(validation_alias="metadata_")

    @field_validator("metadata", mode="before")
    @classmethod
    def _metadata_must_be_safe_subset(cls, value: object) -> dict[str, Any]:
        return _safe_metadata(value)


class EvidenceSourceListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[EvidenceSourceRead]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


__all__ = [
    "EvidenceSourceListResponse",
    "EvidenceSourceRead",
]
