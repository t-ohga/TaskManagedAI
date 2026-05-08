from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

AcceptanceCriteriaStatus = Literal["pending", "satisfied", "rejected", "deferred"]


def _rls_ready_metadata() -> dict[str, Any]:
    return {"rls_ready": True}


class AcceptanceCriteriaCreate(BaseModel):
    id: UUID | None = None
    description: str = Field(min_length=1)
    status: AcceptanceCriteriaStatus = "pending"
    evidence_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=_rls_ready_metadata)


class AcceptanceCriteriaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    tenant_id: int
    ticket_id: UUID
    project_id: UUID
    description: str
    status: AcceptanceCriteriaStatus
    evidence_ref: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


__all__ = [
    "AcceptanceCriteriaCreate",
    "AcceptanceCriteriaRead",
    "AcceptanceCriteriaStatus",
]

