from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NotificationEventCreate(BaseModel):
    id: UUID | None = None
    event_type: str = Field(min_length=1)
    payload: dict[str, Any]
    recipient_actor_id: UUID


class NotificationEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: int
    event_type: str
    payload: dict[str, Any]
    recipient_actor_id: UUID
    read_at: datetime | None
    created_at: datetime


__all__ = ["NotificationEventCreate", "NotificationEventRead"]

