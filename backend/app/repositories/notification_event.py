from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.notification_event import NotificationEvent

# ADR-00041: ticket コメントは notification_events に保存されるが、通知 (inbox / triage) では
# ない。全 notification read surface から除外し、投稿者の未読 / badge / triage を汚染しない (R1-3 / R2-3)。
TICKET_COMMENT_EVENT_TYPE = "ticket_comment"


class NotificationEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(
        self,
        tenant_id: int,
        event_type: str,
        payload: dict[str, Any],
        recipient_actor_id: UUID,
        *,
        severity: str | None = None,
        required_action: str | None = None,
    ) -> NotificationEvent:
        await self._ensure_tenant_context(tenant_id)
        enriched_payload = {**payload}
        if severity is not None:
            enriched_payload["severity"] = severity
        if required_action is not None:
            enriched_payload["required_action"] = required_action
        event = NotificationEvent(
            tenant_id=tenant_id,
            event_type=event_type,
            payload=enriched_payload,
            recipient_actor_id=recipient_actor_id,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def get(self, tenant_id: int, id: UUID) -> NotificationEvent | None:
        await self._ensure_tenant_context(tenant_id)
        return cast(
            NotificationEvent | None,
            await self.session.scalar(
                select(NotificationEvent).where(
                    NotificationEvent.tenant_id == tenant_id,
                    NotificationEvent.id == id,
                )
            ),
        )

    async def mark_read(self, tenant_id: int, event_id: UUID) -> NotificationEvent | None:
        # ADR-00041 R1 F-MEDIUM (Codex adversarial): snooze / resolve は本 method に委譲するため、
        # ここを ticket_comment の単一防御点にする。WHERE に event_type 除外を入れることで、
        # REST (mark_read/snooze/resolve) と MCP (notification_resolve→repo.resolve) の双方で
        # ticket_comment id は claim されず None を返す (REST=404、MCP=not_found に倒れる)。
        # コメントは notification ではないため direct-id 操作対象から外す (read_at 改変 / 状態汚染を塞ぐ)。
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            update(NotificationEvent)
            .where(
                NotificationEvent.tenant_id == tenant_id,
                NotificationEvent.id == event_id,
                NotificationEvent.event_type != TICKET_COMMENT_EVENT_TYPE,
            )
            .values(
                read_at=func.coalesce(
                    NotificationEvent.read_at,
                    datetime.now(tz=UTC),
                )
            )
            .returning(NotificationEvent)
        )
        return result.scalar_one_or_none()

    async def list_unread(
        self,
        tenant_id: int,
        recipient_actor_id: UUID,
    ) -> list[NotificationEvent]:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            select(NotificationEvent)
            .where(
                NotificationEvent.tenant_id == tenant_id,
                NotificationEvent.recipient_actor_id == recipient_actor_id,
                NotificationEvent.read_at.is_(None),
                NotificationEvent.event_type != TICKET_COMMENT_EVENT_TYPE,
            )
            .order_by(NotificationEvent.created_at, NotificationEvent.id)
        )
        return list(result.scalars().all())

    async def list_for_recipient(
        self,
        tenant_id: int,
        recipient_actor_id: UUID,
        *,
        limit: int = 50,
    ) -> list[NotificationEvent]:
        await self._ensure_tenant_context(tenant_id)
        bounded_limit = min(max(limit, 1), 200)
        result = await self.session.execute(
            select(NotificationEvent)
            .where(
                NotificationEvent.tenant_id == tenant_id,
                NotificationEvent.recipient_actor_id == recipient_actor_id,
                NotificationEvent.event_type != TICKET_COMMENT_EVENT_TYPE,
            )
            .order_by(NotificationEvent.created_at.desc(), NotificationEvent.id.desc())
            .limit(bounded_limit)
        )
        return list(result.scalars().all())

    async def count_unread(self, tenant_id: int, recipient_actor_id: UUID) -> int:
        await self._ensure_tenant_context(tenant_id)
        count = await self.session.scalar(
            select(func.count(NotificationEvent.id)).where(
                NotificationEvent.tenant_id == tenant_id,
                NotificationEvent.recipient_actor_id == recipient_actor_id,
                NotificationEvent.read_at.is_(None),
                NotificationEvent.event_type != TICKET_COMMENT_EVENT_TYPE,
            )
        )
        return int(count or 0)

    async def list_triage(
        self,
        tenant_id: int,
        recipient_actor_id: UUID,
        *,
        limit: int = 50,
        state: str | None = None,
    ) -> list[NotificationEvent]:
        await self._ensure_tenant_context(tenant_id)
        bounded_limit = min(max(limit, 1), 200)
        result = await self.session.execute(
            select(NotificationEvent)
            .where(
                NotificationEvent.tenant_id == tenant_id,
                NotificationEvent.recipient_actor_id == recipient_actor_id,
                NotificationEvent.read_at.is_(None),
                NotificationEvent.event_type != TICKET_COMMENT_EVENT_TYPE,
            )
            .order_by(NotificationEvent.created_at.desc(), NotificationEvent.id.desc())
            .limit(bounded_limit)
        )
        return list(result.scalars().all())

    async def list_ticket_comments(
        self,
        tenant_id: int,
        ticket_id: UUID,
    ) -> list[NotificationEvent]:
        """ADR-00041 N-1: ticket のコメント (event_type=ticket_comment) を created_at 昇順で返す。

        tenant 境界 + payload.ticket_id filter。recipient_actor_id では絞らない (コメントは
        通知ではなく ticket 紐付き)。GET 側は archived 許可 = active-scope (deleted_at) は呼出側で確認。
        """
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            select(NotificationEvent)
            .where(
                NotificationEvent.tenant_id == tenant_id,
                NotificationEvent.event_type == TICKET_COMMENT_EVENT_TYPE,
                NotificationEvent.payload["ticket_id"].astext == str(ticket_id),
            )
            .order_by(NotificationEvent.created_at, NotificationEvent.id)
        )
        return list(result.scalars().all())

    async def snooze(
        self,
        tenant_id: int,
        event_id: UUID,
        *,
        snoozed_until: datetime | str | None = None,
    ) -> NotificationEvent | None:
        return await self.mark_read(tenant_id, event_id)

    async def resolve(
        self,
        tenant_id: int,
        event_id: UUID,
        *,
        resolved_by_actor_id: UUID | None = None,
    ) -> NotificationEvent | None:
        return await self.mark_read(tenant_id, event_id)

    async def _ensure_tenant_context(self, tenant_id: int) -> None:
        self._require_tenant_id(tenant_id)
        current_tenant_id = await get_tenant_context(self.session)
        if current_tenant_id is None:
            await set_tenant_context(self.session, tenant_id)
        await assert_tenant_context(self.session, tenant_id)

    @staticmethod
    def _require_tenant_id(tenant_id: int) -> None:
        if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
            raise ValueError("tenant_id must be a positive integer.")


__all__ = ["NotificationEventRepository"]

