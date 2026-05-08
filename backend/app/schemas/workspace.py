from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


def _rls_ready_metadata() -> dict[str, Any]:
    return {"rls_ready": True}


class WorkspaceCreate(BaseModel):
    id: UUID | None = None
    slug: str = Field(min_length=1)
    name: str = Field(min_length=1)
    owner_actor_id: UUID
    metadata: dict[str, Any] = Field(default_factory=_rls_ready_metadata)


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    tenant_id: int
    slug: str
    name: str
    owner_actor_id: UUID
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


__all__ = ["WorkspaceCreate", "WorkspaceRead"]

