from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.db.models.research_task import ResearchTaskStatus
from backend.app.schemas.research.research_evidence_attachment import ResearchEvidenceAttachmentMetric


def _safe_metadata(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("metadata must be a JSON object.")
    return {"rls_ready": value.get("rls_ready") is True}


class ResearchTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True, frozen=True)

    id: UUID
    tenant_id: int
    project_id: UUID
    title: str
    status: ResearchTaskStatus
    created_by_actor_id: UUID
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(validation_alias="metadata_")

    @field_validator("metadata", mode="before")
    @classmethod
    def _metadata_must_be_safe_subset(cls, value: object) -> dict[str, Any]:
        return _safe_metadata(value)


class ResearchTaskDetailRead(ResearchTaskRead):
    evidence_set_hash: str
    research_evidence_attachment: ResearchEvidenceAttachmentMetric


class ResearchTaskListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[ResearchTaskRead]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)


__all__ = [
    "ResearchTaskDetailRead",
    "ResearchTaskListResponse",
    "ResearchTaskRead",
]
