"""SP-032 (ADR-00052): conflict_groups の API schema。

body の `project_id` / `research_task_id` / `tenant_id` / `metadata` / `created_by_actor_id` は
extra="forbid" + 非掲載で reject (server-owned boundary)。title / resolution_note は NFC + trim +
whitespace-only reject (R1 F-014)。
"""

from __future__ import annotations

import unicodedata
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.db.models.conflict_group import ConflictGroupStatus


def _normalize_text(value: str) -> str:
    """NFC 正規化 + 前後 trim。whitespace-only は reject。"""
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        raise ValueError("値は空白のみにできません。")
    return normalized


class ConflictGroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    tenant_id: int
    project_id: UUID
    research_task_id: UUID
    title: str
    status: ConflictGroupStatus
    resolution_note: str | None
    created_by_actor_id: UUID
    created_at: datetime
    updated_at: datetime


class ConflictGroupListResponse(BaseModel):
    items: list[ConflictGroupRead]


class ConflictGroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def _normalize_title(cls, value: str) -> str:
        normalized = _normalize_text(value)
        if len(normalized) > 200:
            raise ValueError("title は 200 文字以内です。")
        return normalized


class ConflictGroupUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: ConflictGroupStatus | None = None
    resolution_note: str | None = Field(default=None, max_length=2000)

    @field_validator("title")
    @classmethod
    def _normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _normalize_text(value)
        if len(normalized) > 200:
            raise ValueError("title は 200 文字以内です。")
        return normalized

    @field_validator("resolution_note")
    @classmethod
    def _normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _normalize_text(value)
        if len(normalized) > 2000:
            raise ValueError("resolution_note は 2000 文字以内です。")
        return normalized


__all__ = [
    "ConflictGroupCreate",
    "ConflictGroupListResponse",
    "ConflictGroupRead",
    "ConflictGroupUpdate",
]
