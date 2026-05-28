from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TicketStatus = Literal["open", "in_progress", "blocked", "review", "closed", "cancelled"]
TicketPriority = Literal["low", "medium", "high", "critical"]

_SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


def _rls_ready_metadata() -> dict[str, Any]:
    return {"rls_ready": True}


class TicketCreate(BaseModel):
    id: UUID | None = None
    repository_id: UUID | None = None
    slug: str = Field(min_length=1, pattern=_SLUG_PATTERN)
    title: str = Field(min_length=1)
    description: str | None = None
    status: TicketStatus = "open"
    priority: TicketPriority | None = None
    due_date: date | None = None
    assignee_actor_id: UUID | None = None
    created_by_actor_id: UUID
    metadata: dict[str, Any] = Field(default_factory=_rls_ready_metadata)


class TicketUpdate(BaseModel):
    repository_id: UUID | None = None
    slug: str | None = Field(default=None, min_length=1, pattern=_SLUG_PATTERN)
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    status: TicketStatus | None = None
    priority: TicketPriority | None = None
    due_date: date | None = None
    assignee_actor_id: UUID | None = None
    metadata: dict[str, Any] | None = None


class TicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    tenant_id: int
    project_id: UUID
    repository_id: UUID | None
    slug: str
    title: str
    description: str | None
    status: TicketStatus
    priority: TicketPriority | None
    due_date: date | None
    assignee_actor_id: UUID | None
    created_by_actor_id: UUID
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


__all__ = [
    "TicketCreate",
    "TicketPriority",
    "TicketRead",
    "TicketStatus",
    "TicketUpdate",
]

