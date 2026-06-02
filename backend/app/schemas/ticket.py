from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from backend.app.schemas.tag import TagRead

TicketStatus = Literal["open", "in_progress", "blocked", "review", "closed", "cancelled"]
TicketPriority = Literal["low", "medium", "high", "critical"]

_SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"

_YMD_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def coerce_strict_due_date(value: object) -> object:
    """due_date を **厳密な暦日 (`YYYY-MM-DD`) または None** のみ受理する before-validator (ADR-00045 R13).

    Pydantic v2 の `date | None` は lax coercion で datetime 文字列 (`2026-06-01T00:00:00Z`) や
    epoch 数値 / 数字文字列 (`1772323200`) も `date` に silent coerce してしまう。`task_create` /
    `task_write` capability を持つ API / CLI / MCP / 内部 promotion caller が frontend の strict
    validator を通らず timestamp / epoch を期限日として永続化できる data integrity gap になるため
    (server-owned boundary での fail-closed enforcement)、ここで full-match `YYYY-MM-DD` 文字列か
    `date` (datetime でない) / None のみ許可し、datetime 文字列・epoch・非実在日 (2026-02-31)・
    junk suffix を reject する。frontend の strict-YMD all-surface 不変条件と trust boundary を揃える
    (authoritative な強制点)。全 ticket write schema (REST request + 内部 TicketCreate/Update) で共有。
    """
    if value is None:
        return None
    # datetime は date のサブクラスのため明示除外 (時刻付き入力を date に潰さない)。
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str) and _YMD_PATTERN.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("due_date must be a valid YYYY-MM-DD calendar date") from exc
    raise ValueError("due_date must be null or a YYYY-MM-DD calendar date string")


# ticket write 共通の strict due_date 型。Pydantic の lax date coercion を before-validator で塞ぐ。
StrictDueDate = Annotated[date | None, BeforeValidator(coerce_strict_due_date)]

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
    # ADR-00045 R13: 厳密な暦日 (YYYY-MM-DD) または null のみ。datetime / epoch / 非実在日を reject。
    due_date: StrictDueDate = None
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
    # ADR-00045 R13: 厳密な暦日 (YYYY-MM-DD) または null のみ。datetime / epoch / 非実在日を reject。
    due_date: StrictDueDate = None
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

