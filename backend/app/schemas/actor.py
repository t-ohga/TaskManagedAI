from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ActorType = Literal["human", "service", "agent", "provider", "github_app"]


def _rls_ready_metadata() -> dict[str, Any]:
    return {"rls_ready": True}


class ActorCreate(BaseModel):
    id: UUID | None = None
    actor_type: ActorType
    actor_id: str = Field(min_length=1)
    display_name: str | None = None
    auth_context_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=_rls_ready_metadata)
    impersonated_by: UUID | None = None


class ActorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    tenant_id: int
    actor_type: ActorType
    actor_id: str
    display_name: str | None
    auth_context_hash: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    impersonated_by: UUID | None
    created_at: datetime
    updated_at: datetime


__all__ = ["ActorCreate", "ActorRead", "ActorType"]

