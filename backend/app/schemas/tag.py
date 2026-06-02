"""ADR-00044 (A-5): ticket tag の API schema (canonical)。

api/tags.py の endpoint と schemas/ticket.py の TicketRead 埋め込みが共有する。
body の `project_id` / `tenant_id` は extra="forbid" で reject (server-owned boundary、R2)。
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.app.db.models.tag import TagColor


class TagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    color: TagColor


class TagListResponse(BaseModel):
    items: list[TagRead]


class TagCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=50)
    color: TagColor


class TagUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=50)
    color: TagColor | None = None


class TicketTagAttach(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag_id: UUID


__all__ = [
    "TagRead",
    "TagListResponse",
    "TagCreate",
    "TagUpdate",
    "TicketTagAttach",
]
