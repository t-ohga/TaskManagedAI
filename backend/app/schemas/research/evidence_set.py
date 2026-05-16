from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResearchSetReference(BaseModel):
    """Server-owned reference to a project-scoped research/evidence set."""

    model_config = ConfigDict(frozen=True)

    project_id: UUID
    research_task_id: UUID
    claim_ids: tuple[UUID, ...] = Field(default_factory=tuple)
    evidence_item_ids: tuple[UUID, ...] = Field(default_factory=tuple)

    @field_validator("claim_ids", "evidence_item_ids", mode="before")
    @classmethod
    def _coerce_uuid_tuple(cls, value: object) -> tuple[UUID, ...]:
        if value is None:
            return ()
        if isinstance(value, UUID):
            raise ValueError("id list must be a sequence of UUIDs, not a single UUID.")
        if isinstance(value, str | bytes):
            raise ValueError("id list must be a sequence of UUIDs, not a string.")
        if not isinstance(value, Iterable):
            raise ValueError("id list must be a sequence of UUIDs.")
        return tuple(value)

    @field_validator("claim_ids", "evidence_item_ids")
    @classmethod
    def _reject_duplicate_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(set(value)) != len(value):
            raise ValueError("id list must not contain duplicate UUIDs.")
        return value


__all__ = ["ResearchSetReference"]
