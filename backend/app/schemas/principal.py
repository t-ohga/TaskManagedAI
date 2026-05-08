from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PrincipalType = Literal["session", "api_token", "capability_token", "installation", "worker"]


def _rls_ready_metadata() -> dict[str, Any]:
    return {"rls_ready": True}


class PrincipalCreate(BaseModel):
    id: UUID | None = None
    actor_id: UUID
    principal_type: PrincipalType
    auth_context_hash: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=_rls_ready_metadata)
    expires_at: datetime | None = None


class PrincipalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    tenant_id: int
    actor_id: UUID
    principal_type: PrincipalType
    auth_context_hash: str
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime
    expires_at: datetime | None


__all__ = ["PrincipalCreate", "PrincipalRead", "PrincipalType"]

