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


class NotificationEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(
        self,
        tenant_id: int,
        event_type: str,
        payload: dict[str, Any],
        recipient_actor_id: UUID,
    ) -> NotificationEvent:
        await self._ensure_tenant_context(tenant_id)
        event = NotificationEvent(
            tenant_id=tenant_id,
            event_type=event_type,
            payload=payload,
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
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            update(NotificationEvent)
            .where(
                NotificationEvent.tenant_id == tenant_id,
                NotificationEvent.id == event_id,
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
            )
        )
        return int(count or 0)

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

