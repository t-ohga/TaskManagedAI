"""Read-only GitHub webhook event feed API (ADR-00050 SP-028)。

project-scoped (`/api/v1/projects/{project_id}/webhook_events`) で、対象 project に属する repository の
accepted webhook event (PR / CI) を received_at 降順で返す。tenant + project boundary は repository join +
既存の project-scoped path 規約で enforce する (cross-project leak 防止、F-002)。secret は保存も表示もしない。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_db_session,
    get_tenant_id,
)
from backend.app.api.me import require_project_owner
from backend.app.db.models.github_webhook_event import (
    GitHubWebhookEvent,
    WebhookEventKind,
)
from backend.app.repositories.github_webhook_event import (
    WEBHOOK_EVENT_FEED_MAX_LIMIT,
    GitHubWebhookEventRepository,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/webhook_events",
    tags=["webhook_events"],
)


class WebhookEventRead(BaseModel):
    """非機密 field のみの read response (raw secret / payload なし)。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    repository_id: UUID | None
    event_kind: WebhookEventKind
    action: str | None
    external_ref: str | None
    state: str | None
    title: str | None
    sender_login: str | None
    received_at: datetime


class WebhookEventListResponse(BaseModel):
    items: list[WebhookEventRead]
    limit: int


def _to_read(event: GitHubWebhookEvent) -> WebhookEventRead:
    return WebhookEventRead(
        id=event.id,
        repository_id=event.repository_id,
        event_kind=event.event_kind,  # DB CHECK enum で値域保証済 (Mapped[str] → Literal)
        action=event.action,
        external_ref=event.external_ref,
        state=event.state,
        title=event.title,
        sender_login=event.sender_login,
        received_at=event.received_at,
    )


@router.get("", response_model=WebhookEventListResponse)
async def list_webhook_events_endpoint(
    project_id: UUID,
    repository_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=WEBHOOK_EVENT_FEED_MAX_LIMIT),
    # Codex adversarial F-1: project join だけでは「actor がこの project を読んでよいか」を保証しない。
    # P0 owner gate (R-3 secret-refs read と同じ owner-only read 先例) で fail-closed に enforce する
    # (service / agent / provider / github_app / 別 human / 未認証は 401/403)。multi-project membership は
    # forward の actor_membership table 追加後に per-project gate へ拡張 (me.py の single-project note と整合)。
    _owner_actor_id: UUID = Depends(require_project_owner),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> WebhookEventListResponse:
    """project 配下の accepted webhook event (PR / CI) を received_at 降順で返す。

    owner gate (require_project_owner) で P0 owner のみに限定し、tenant + project boundary は repository
    join で enforce、quarantine (repository_id NULL) は除外。任意 ``repository_id`` filter は当該 project
    内に属する repository に限定 (cross-project / cross-actor leak 防止)。
    """

    events = await GitHubWebhookEventRepository(session).list_accepted_for_project(
        tenant_id=tenant_id,
        project_id=project_id,
        repository_id=repository_id,
        limit=limit,
    )
    return WebhookEventListResponse(
        items=[_to_read(event) for event in events],
        limit=limit,
    )


__all__ = [
    "WebhookEventListResponse",
    "WebhookEventRead",
    "list_webhook_events_endpoint",
    "router",
]
