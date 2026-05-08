"""In-App Notification API (Sprint 3 Batch 3, BL-0037)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.db.models.notification_event import NotificationEvent
from backend.app.repositories.notification_event import NotificationEventRepository

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


class NotificationItem(BaseModel):
    id: UUID
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
    read_at: datetime | None


class BadgeCount(BaseModel):
    unread_count: int


def _to_item(notification: NotificationEvent) -> NotificationItem:
    return NotificationItem(
        id=notification.id,
        event_type=notification.event_type,
        payload=notification.payload,
        created_at=notification.created_at,
        read_at=notification.read_at,
    )


@router.get("", response_model=list[NotificationItem])
async def list_notifications(
    actor_id: UUID = Depends(get_current_actor_id),
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[NotificationItem]:
    repo = NotificationEventRepository(session)
    items = await repo.list_for_recipient(
        tenant_id=tenant_id,
        recipient_actor_id=actor_id,
        limit=50,
    )
    return [_to_item(item) for item in items]


@router.get("/badge_count", response_model=BadgeCount)
async def get_badge_count(
    actor_id: UUID = Depends(get_current_actor_id),
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> BadgeCount:
    repo = NotificationEventRepository(session)
    count = await repo.count_unread(tenant_id=tenant_id, recipient_actor_id=actor_id)
    return BadgeCount(unread_count=count)


@router.post("/{notification_id}/mark_read", response_model=NotificationItem)
async def mark_read(
    notification_id: UUID,
    actor_id: UUID = Depends(get_current_actor_id),
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationItem:
    repo = NotificationEventRepository(session)
    notification = await repo.get(tenant_id=tenant_id, id=notification_id)
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="notification not found",
        )
    if notification.recipient_actor_id != actor_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not your notification",
        )

    if notification.read_at is None:
        updated = await repo.mark_read(tenant_id=tenant_id, event_id=notification_id)
        if updated is not None:
            notification = updated
        await session.commit()

    return _to_item(notification)


__all__ = ["BadgeCount", "NotificationItem", "router"]

