from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _rls_ready_metadata() -> dict[str, Any]:
    return {"rls_ready": True}


class ClaimBase(BaseModel):
    claim_text: str = Field(min_length=1, max_length=2000)
    provenance_json: dict[str, Any]
    freshness_score: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=_rls_ready_metadata)

    @field_validator("provenance_json", mode="before")
    @classmethod
    def _validate_provenance_json_is_dict(cls, value: object) -> dict[str, Any]:
        # F-PR19-R8-001 P2 adopt: raw value を error message に含めない (sanitized message のみ)
        if not isinstance(value, dict):
            raise ValueError("provenance_json must be a JSON object.")
        return value

    @field_validator("metadata", mode="before")
    @classmethod
    def _validate_metadata_is_dict(cls, value: object) -> dict[str, Any]:
        # F-PR19-R8-003 P2 adopt: caller が metadata={} を passing する場合も rls_ready: true を server-side で merge
        # (rls_ready は RLS-ready metadata invariant、caller-supplied metadata で消失しないよう preserve)
        if not isinstance(value, dict):
            raise ValueError("metadata must be a JSON object.")
        result = dict(value)
        result.setdefault("rls_ready", True)
        return result


class ClaimCreate(ClaimBase):
    pass


class ClaimRead(ClaimBase):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    tenant_id: int
    project_id: UUID
    research_task_id: UUID
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class ClaimUpdate(BaseModel):
    claim_text: str | None = Field(default=None, min_length=1, max_length=2000)
    provenance_json: dict[str, Any] | None = None
    freshness_score: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] | None = None

    @field_validator("provenance_json", mode="before")
    @classmethod
    def _validate_optional_provenance_json_is_dict(cls, value: object) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("provenance_json must be a JSON object.")
        return value

    @field_validator("metadata", mode="before")
    @classmethod
    def _validate_optional_metadata_is_dict(cls, value: object) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("metadata must be a JSON object.")
        return value


__all__ = [
    "ClaimBase",
    "ClaimCreate",
    "ClaimRead",
    "ClaimUpdate",
]
