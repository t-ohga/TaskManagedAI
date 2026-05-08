from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _rls_ready_metadata() -> dict[str, Any]:
    return {"rls_ready": True}


class TenantCreate(BaseModel):
    id: int | None = Field(default=None, ge=1)
    name: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=_rls_ready_metadata)


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    metadata: dict[str, Any] | None = None


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    name: str
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


__all__ = ["TenantCreate", "TenantRead", "TenantUpdate"]

