from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.app.domain.policy.autonomy_level import AutonomyLevel

ProjectStatus = Literal["active", "archived"]


def _rls_ready_metadata() -> dict[str, Any]:
    return {"rls_ready": True}


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID | None = None
    workspace_id: UUID
    slug: str = Field(min_length=1)
    name: str = Field(min_length=1)
    status: ProjectStatus = "active"
    metadata: dict[str, Any] = Field(default_factory=_rls_ready_metadata)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    tenant_id: int
    workspace_id: UUID
    slug: str
    name: str
    status: ProjectStatus
    policy_profile: str
    autonomy_level: AutonomyLevel
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


__all__ = ["ProjectCreate", "ProjectRead", "ProjectStatus"]
