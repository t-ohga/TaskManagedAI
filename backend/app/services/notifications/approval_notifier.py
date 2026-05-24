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

    async def notify_approval_revision_requested(
        self,
        *,
        tenant_id: int,
        approval_id: UUID,
        revision_request_id: UUID,
        recipient_actor_id: UUID,
    ) -> NotificationEvent:
        """Append a metadata-only notification for the original approval requester."""

        repo = NotificationEventRepository(self.session)
        return await repo.append(
            tenant_id=tenant_id,
            event_type="approval_revision_requested",
            payload={
                "approval_id": str(approval_id),
                "revision_request_id": str(revision_request_id),
            },
            recipient_actor_id=recipient_actor_id,
            severity="medium",
            required_action="inspect_run",
        )


__all__ = ["ApprovalNotifierService"]
