from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TicketRelationType = Literal["blocks", "blocked_by", "duplicates", "relates_to", "depends_on"]


def _rls_ready_metadata() -> dict[str, Any]:
    return {"rls_ready": True}


class TicketRelationCreate(BaseModel):
    id: UUID | None = None
    source_ticket_id: UUID
    target_ticket_id: UUID
    relation_type: TicketRelationType
    metadata: dict[str, Any] = Field(default_factory=_rls_ready_metadata)


class TicketRelationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    tenant_id: int
    project_id: UUID
    source_ticket_id: UUID
    target_ticket_id: UUID
    relation_type: TicketRelationType
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime


__all__ = ["TicketRelationCreate", "TicketRelationRead", "TicketRelationType"]

