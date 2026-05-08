from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AuditEventCreate(BaseModel):
    id: UUID | None = None
    event_type: str = Field(min_length=1)
    event_payload: dict[str, Any]
    actor_id: UUID | None = None
    principal_id: UUID | None = None
    correlation_id: str | None = None
    trace_id: str | None = None


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: int
    event_type: str
    event_payload: dict[str, Any]
    actor_id: UUID | None
    principal_id: UUID | None
    correlation_id: str | None
    trace_id: str | None
    created_at: datetime


__all__ = ["AuditEventCreate", "AuditEventRead"]

