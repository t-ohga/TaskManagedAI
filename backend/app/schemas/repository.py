from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

RepositoryProvider = Literal["github", "gitlab", "bitbucket"]


def _rls_ready_metadata() -> dict[str, Any]:
    return {"rls_ready": True}


class RepositoryCreate(BaseModel):
    id: UUID | None = None
    project_id: UUID
    provider: RepositoryProvider
    external_id: str = Field(min_length=1)
    owner_name: str = Field(min_length=1)
    repo_name: str = Field(min_length=1)
    default_branch: str = Field(default="main", min_length=1)
    installation_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=_rls_ready_metadata)


class RepositoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    tenant_id: int
    project_id: UUID
    provider: RepositoryProvider
    external_id: str
    owner_name: str
    repo_name: str
    default_branch: str
    installation_ref: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


__all__ = ["RepositoryCreate", "RepositoryProvider", "RepositoryRead"]

