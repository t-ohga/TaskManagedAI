"""ADR-00044 (A-5): ticket tag の API schema (canonical)。

api/tags.py の endpoint と schemas/ticket.py の TicketRead 埋め込みが共有する。
body の `project_id` / `tenant_id` は extra="forbid" で reject (server-owned boundary、R2)。
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    """ticket への tag 付与。既存 tag を `tag_id` で付けるか、新規 tag を `name`+`color` で
    作成して同一 transaction で付ける (ADR-00044、Codex R5 HIGH: create+attach を atomic 化し
    部分成功の孤立 tag を防ぐ)。tag_id と (name, color) は排他。"""

    model_config = ConfigDict(extra="forbid")

    tag_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=50)
    color: TagColor | None = None

    @model_validator(mode="after")
    def _exactly_one_mode(self) -> TicketTagAttach:
        has_existing = self.tag_id is not None
        has_new = self.name is not None or self.color is not None
        if has_existing and has_new:
            raise ValueError("tag_id と name/color は同時に指定できません。")
        if not has_existing and not has_new:
            raise ValueError("tag_id または (name, color) のいずれかを指定してください。")
        if has_new and (self.name is None or self.color is None):
            raise ValueError("新規タグには name と color の両方が必要です。")
        return self


__all__ = [
    "TagRead",
    "TagListResponse",
    "TagCreate",
    "TagUpdate",
    "TicketTagAttach",
]
