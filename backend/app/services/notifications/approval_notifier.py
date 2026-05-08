"""In-App Notification service (Sprint 3 Batch 3, BL-0037)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.notification_event import NotificationEvent
from backend.app.repositories.notification_event import NotificationEventRepository


class ApprovalNotifierService:
    """Create approval pending notifications for in-app recipients."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def notify_approval_pending(
        self,
        *,
        tenant_id: int,
        approval_id: UUID,
        recipient_actor_id: UUID,
        action_class: str,
        resource_ref: str,
        risk_level: str,
    ) -> NotificationEvent:
        """Append an approval_pending notification for a reviewer candidate."""

        repo = NotificationEventRepository(self.session)
        return await repo.append(
            tenant_id=tenant_id,
            event_type="approval_pending",
            payload={
                "approval_id": str(approval_id),
                "action_class": action_class,
                "resource_ref": resource_ref,
                "risk_level": risk_level,
            },
            recipient_actor_id=recipient_actor_id,
        )


__all__ = ["ApprovalNotifierService"]

