from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.tag import TagRead

TicketStatus = Literal["open", "in_progress", "blocked", "review", "closed", "cancelled"]
TicketPriority = Literal["low", "medium", "high", "critical"]

_SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"

# Q-2 (ADR-00037 DoD): import の untrusted boundary。件数上限 (100) に加えて per-field の payload
# size 上限を backend-owned で定義し、巨大 text による memory 圧迫 / storage 肥大 / 後段 UI 崩れを防ぐ
# (Codex adversarial R8)。frontend Zod (session.ts) も同値をミラーする。
IMPORT_SLUG_MAX_LENGTH = 100
IMPORT_TITLE_MAX_LENGTH = 200
IMPORT_DESCRIPTION_MAX_LENGTH = 10_000


def _rls_ready_metadata() -> dict[str, Any]:
    return {"rls_ready": True}


class TicketCreate(BaseModel):
    id: UUID | None = None
    repository_id: UUID | None = None
    slug: str = Field(min_length=1, pattern=_SLUG_PATTERN)
    title: str = Field(min_length=1)
    description: str | None = None
    status: TicketStatus = "open"
    priority: TicketPriority | None = None
    due_date: date | None = None
    assignee_actor_id: UUID | None = None
    created_by_actor_id: UUID
    metadata: dict[str, Any] = Field(default_factory=_rls_ready_metadata)


class TicketUpdate(BaseModel):
    repository_id: UUID | None = None
    slug: str | None = Field(default=None, min_length=1, pattern=_SLUG_PATTERN)
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    status: TicketStatus | None = None
    priority: TicketPriority | None = None
    due_date: date | None = None
    assignee_actor_id: UUID | None = None
    metadata: dict[str, Any] | None = None


class TicketImportItem(BaseModel):
    """Q-2 (ADR-00037): 一括インポート 1 件分の caller 入力 ticket payload。

    caller (owner が貼付/アップロードする JSON) が指定できるのは下記 field のみ。
    ``created_by_actor_id`` / ``metadata`` / ``tenant_id`` / ``project_id`` は endpoint / repository が
    server-owned で注入する (caller-supplied 禁止、server-owned-boundary)。slug 一意性は endpoint が
    in-payload / 既存 (active+deleted) 衝突を検証し、DB unique (``tickets_uq_tenant_project_slug``) が
    最終防衛する。
    """

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=IMPORT_SLUG_MAX_LENGTH, pattern=_SLUG_PATTERN)
    title: str = Field(min_length=1, max_length=IMPORT_TITLE_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=IMPORT_DESCRIPTION_MAX_LENGTH)
    status: TicketStatus = "open"
    priority: TicketPriority | None = None


class TicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    tenant_id: int
    project_id: UUID
    repository_id: UUID | None
    slug: str
    title: str
    description: str | None
    status: TicketStatus
    priority: TicketPriority | None
    due_date: date | None
    assignee_actor_id: UUID | None
    created_by_actor_id: UUID
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
    # ADR-00044 (A-5): per-ticket tag。endpoint が TagRepository.tags_for_tickets で inject する
    # (Ticket ORM の relationship ではないため default は空、from_attributes では設定されない)。
    tags: list[TagRead] = Field(default_factory=list)


__all__ = [
    "TicketCreate",
    "TicketImportItem",
    "TicketPriority",
    "TicketRead",
    "TicketStatus",
    "TicketUpdate",
]

