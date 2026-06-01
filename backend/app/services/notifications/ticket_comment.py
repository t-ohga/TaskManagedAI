"""Ticket コメント作成の共通 helper (ADR-00041 N-1).

REST `POST .../comments` と MCP `bridge_ticket_comment` の両方が呼ぶ。コメントは
専用 table ではなく `notification_events` の `event_type="ticket_comment"` event として保存する
(migration なし)。

不変条件 (ADR-00041 plan-review):
- 永続化前に payload 全体を `assert_no_raw_secret` に通し、raw secret / canary hit 時は
  ``ValueError`` を raise (REST=422、MCP=error)。両経路で適用し MCP の secret bypass を塞ぐ (R2-1)。
- author を payload `actor_id` に server-owned 保存する (R1-3 / R2-2)。caller payload では上書き不可。
- `recipient_actor_id` は FK 制約のため author を設定するが、ticket_comment は全 notification read
  surface から除外されるため inbox / triage を汚染しない (R1-3 / R2-3、repository 側で除外)。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.notification_event import NotificationEvent
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.repositories.notification_event import (
    TICKET_COMMENT_EVENT_TYPE,
    NotificationEventRepository,
)

# 一覧 response の message 長さ上限 (空 / 超過は API schema 側で 422)。
TICKET_COMMENT_MESSAGE_MAX_LENGTH = 4000


async def create_ticket_comment_event(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    ticket_id: UUID,
    message: str,
    actor_id: UUID,
) -> NotificationEvent:
    """ticket コメントを notification_events event として保存する。

    呼び出し側は事前に actionable guard (POST=assert_ticket_actionable) を済ませること。
    本 helper は **永続化前 secret scan** と **author server-owned 保存** を担保する。

    Raises:
        ValueError: payload (message 含む) に raw secret / canary / prohibited key を検出した場合。
    """
    payload: dict[str, Any] = {
        "project_id": str(project_id),
        "ticket_id": str(ticket_id),
        "message": message,
        "actor_id": str(actor_id),
    }
    # raw secret / provider token / private key marker を DB / UI に流さない (fail-closed、R2-1)。
    assert_no_raw_secret(payload)

    repo = NotificationEventRepository(session)
    return await repo.append(
        tenant_id=tenant_id,
        event_type=TICKET_COMMENT_EVENT_TYPE,
        payload=payload,
        recipient_actor_id=actor_id,
    )
