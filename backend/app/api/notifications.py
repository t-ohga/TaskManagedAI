"""In-App Notification API (Sprint 3 Batch 3, BL-0037)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.db.models.notification_event import NotificationEvent
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.repositories.notification_event import NotificationEventRepository

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

NotificationSeverityLiteral = Literal["info", "low", "medium", "high", "critical"]
NotificationRequiredActionLiteral = Literal[
    "acknowledge",
    "review_approval",
    "inspect_run",
    "resolve_blocker",
    "external_followup",
]
NotificationTriageStateLiteral = Literal["open", "snoozed", "resolved", "all"]
PayloadRedactionStatusLiteral = Literal["keys_only"]
_MAX_SNOOZE_WINDOW = timedelta(days=30)


class NotificationItem(BaseModel):
    id: UUID
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
    read_at: datetime | None


class NotificationTriageItem(BaseModel):
    id: UUID
    event_type: str
    payload_keys: list[str]
    payload_redaction_status: PayloadRedactionStatusLiteral
    severity: NotificationSeverityLiteral
    required_action: NotificationRequiredActionLiteral
    due_at: datetime | None
    snoozed_until: datetime | None
    resolved_at: datetime | None
    resolved_by_actor_id: UUID | None
    created_at: datetime
    read_at: datetime | None


class BadgeCount(BaseModel):
    unread_count: int


class NotificationSnoozeRequest(BaseModel):
    snoozed_until: datetime


class NotificationResolveRequest(BaseModel):
    resolution_note: str | None = Field(default=None, max_length=2000)


def _to_item(notification: NotificationEvent) -> NotificationItem:
    return NotificationItem(
        id=notification.id,
        event_type=notification.event_type,
        payload=notification.payload,
        created_at=notification.created_at,
        read_at=notification.read_at,
    )


def _to_triage_item(notification: NotificationEvent) -> NotificationTriageItem:
    return NotificationTriageItem(
        id=notification.id,
        event_type=notification.event_type,
        payload_keys=sorted(str(key) for key in notification.payload.keys()),
        payload_redaction_status="keys_only",
        severity=notification.severity,
        required_action=notification.required_action,
        due_at=notification.due_at,
        snoozed_until=notification.snoozed_until,
        resolved_at=notification.resolved_at,
        resolved_by_actor_id=notification.resolved_by_actor_id,
        created_at=notification.created_at,
        read_at=notification.read_at,
    )


def _assert_owned(notification: NotificationEvent, actor_id: UUID) -> None:
    if notification.recipient_actor_id != actor_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not your notification",
        )


def _validate_snooze_until(snoozed_until: datetime) -> datetime:
    now = datetime.now(tz=UTC)
    resolved = (
        snoozed_until
        if snoozed_until.tzinfo is not None
        else snoozed_until.replace(tzinfo=UTC)
    )
    if resolved <= now:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="snoozed_until must be in the future",
        )
    if resolved > now + _MAX_SNOOZE_WINDOW:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="snoozed_until must be within 30 days",
        )
    return resolved


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


@router.get("/triage", response_model=list[NotificationTriageItem])
async def list_notification_triage(
    state_filter: Annotated[NotificationTriageStateLiteral, Query(alias="state")] = "open",
    actor_id: UUID = Depends(get_current_actor_id),
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[NotificationTriageItem]:
    repo = NotificationEventRepository(session)
    items = await repo.list_triage(
        tenant_id=tenant_id,
        recipient_actor_id=actor_id,
        state=state_filter,
        limit=50,
    )
    return [_to_triage_item(item) for item in items]


@router.get("/badge_count", response_model=BadgeCount)
async def get_badge_count(
    actor_id: UUID = Depends(get_current_actor_id),
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> BadgeCount:
    repo = NotificationEventRepository(session)
    count = await repo.count_unread(tenant_id=tenant_id, recipient_actor_id=actor_id)
    return BadgeCount(unread_count=count)


@router.post("/{notification_id}/snooze", response_model=NotificationTriageItem)
async def snooze_notification(
    notification_id: UUID,
    body: NotificationSnoozeRequest,
    actor_id: UUID = Depends(get_current_actor_id),
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationTriageItem:
    repo = NotificationEventRepository(session)
    notification = await repo.get(tenant_id=tenant_id, id=notification_id)
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="notification not found",
        )
    _assert_owned(notification, actor_id)
    if notification.resolved_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="notification already resolved",
        )

    snoozed_until = _validate_snooze_until(body.snoozed_until)
    updated = await repo.snooze(
        tenant_id=tenant_id,
        event_id=notification_id,
        snoozed_until=snoozed_until,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="notification already resolved",
        )
    await AuditEventRepository(session).append(
        tenant_id=tenant_id,
        event_type="notification_snoozed",
        payload={
            "notification_id": str(updated.id),
            "event_type": updated.event_type,
            "severity": updated.severity,
            "required_action": updated.required_action,
            "snoozed_until": updated.snoozed_until.isoformat()
            if updated.snoozed_until is not None
            else None,
        },
        actor_id=actor_id,
    )
    await session.commit()
    return _to_triage_item(updated)


@router.post("/{notification_id}/resolve", response_model=NotificationTriageItem)
async def resolve_notification(
    notification_id: UUID,
    body: NotificationResolveRequest,
    actor_id: UUID = Depends(get_current_actor_id),
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationTriageItem:
    repo = NotificationEventRepository(session)
    notification = await repo.get(tenant_id=tenant_id, id=notification_id)
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="notification not found",
        )
    _assert_owned(notification, actor_id)
    if notification.resolved_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="notification already resolved",
        )

    updated = await repo.resolve(
        tenant_id=tenant_id,
        event_id=notification_id,
        resolved_by_actor_id=actor_id,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="notification already resolved",
        )
    await AuditEventRepository(session).append(
        tenant_id=tenant_id,
        event_type="notification_resolved",
        payload={
            "notification_id": str(updated.id),
            "event_type": updated.event_type,
            "severity": updated.severity,
            "required_action": updated.required_action,
            "resolved_at": updated.resolved_at.isoformat()
            if updated.resolved_at is not None
            else None,
            "resolution_note_present": body.resolution_note is not None,
        },
        actor_id=actor_id,
    )
    await session.commit()
    return _to_triage_item(updated)


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
    _assert_owned(notification, actor_id)

    if notification.read_at is None:
        updated = await repo.mark_read(tenant_id=tenant_id, event_id=notification_id)
        if updated is not None:
            notification = updated
        await session.commit()

    return _to_item(notification)


__all__ = [
    "BadgeCount",
    "NotificationItem",
    "NotificationRequiredActionLiteral",
    "NotificationResolveRequest",
    "NotificationSeverityLiteral",
    "NotificationSnoozeRequest",
    "NotificationTriageItem",
    "NotificationTriageStateLiteral",
    "router",
]
