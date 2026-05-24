from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.notification_event import (
    NotificationEvent,
    NotificationRequiredAction,
    NotificationSeverity,
)

NotificationTriageState = str

_SEVERITY_RANK = case(
    (NotificationEvent.severity == "critical", 5),
    (NotificationEvent.severity == "high", 4),
    (NotificationEvent.severity == "medium", 3),
    (NotificationEvent.severity == "low", 2),
    else_=1,
)


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
        severity: NotificationSeverity = "info",
        required_action: NotificationRequiredAction = "acknowledge",
        due_at: datetime | None = None,
        dedupe_key: str | None = None,
    ) -> NotificationEvent:
        await self._ensure_tenant_context(tenant_id)
        event = NotificationEvent(
            tenant_id=tenant_id,
            event_type=event_type,
            payload=payload,
            recipient_actor_id=recipient_actor_id,
            severity=severity,
            required_action=required_action,
            due_at=due_at,
            dedupe_key=dedupe_key,
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

    async def list_triage(
        self,
        tenant_id: int,
        recipient_actor_id: UUID,
        *,
        state: NotificationTriageState = "open",
        limit: int = 50,
        now: datetime | None = None,
    ) -> list[NotificationEvent]:
        await self._ensure_tenant_context(tenant_id)
        bounded_limit = min(max(limit, 1), 200)
        resolved_now = now or datetime.now(tz=UTC)
        query = select(NotificationEvent).where(
            NotificationEvent.tenant_id == tenant_id,
            NotificationEvent.recipient_actor_id == recipient_actor_id,
        )

        if state == "open":
            query = query.where(
                NotificationEvent.resolved_at.is_(None),
                or_(
                    NotificationEvent.snoozed_until.is_(None),
                    NotificationEvent.snoozed_until <= resolved_now,
                ),
            )
        elif state == "snoozed":
            query = query.where(
                NotificationEvent.resolved_at.is_(None),
                NotificationEvent.snoozed_until > resolved_now,
            )
        elif state == "resolved":
            query = query.where(NotificationEvent.resolved_at.is_not(None))
        elif state != "all":
            raise ValueError(f"unsupported notification triage state: {state!r}")

        result = await self.session.execute(
            query.order_by(
                _SEVERITY_RANK.desc(),
                NotificationEvent.due_at.asc().nulls_last(),
                NotificationEvent.created_at.desc(),
                NotificationEvent.id.desc(),
            ).limit(bounded_limit)
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

    async def snooze(
        self,
        tenant_id: int,
        event_id: UUID,
        snoozed_until: datetime,
    ) -> NotificationEvent | None:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            update(NotificationEvent)
            .where(
                NotificationEvent.tenant_id == tenant_id,
                NotificationEvent.id == event_id,
                NotificationEvent.resolved_at.is_(None),
            )
            .values(snoozed_until=snoozed_until)
            .returning(NotificationEvent)
        )
        return result.scalar_one_or_none()

    async def resolve(
        self,
        tenant_id: int,
        event_id: UUID,
        resolved_by_actor_id: UUID,
    ) -> NotificationEvent | None:
        await self._ensure_tenant_context(tenant_id)
        resolved_now = datetime.now(tz=UTC)
        result = await self.session.execute(
            update(NotificationEvent)
            .where(
                NotificationEvent.tenant_id == tenant_id,
                NotificationEvent.id == event_id,
                NotificationEvent.resolved_at.is_(None),
            )
            .values(
                resolved_at=resolved_now,
                resolved_by_actor_id=resolved_by_actor_id,
                snoozed_until=None,
                read_at=func.coalesce(NotificationEvent.read_at, resolved_now),
            )
            .returning(NotificationEvent)
        )
        return result.scalar_one_or_none()

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
