"""Read-only audit event API for SP-012-9 UI wiring."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.db.models.audit_event import AuditEvent
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret

router = APIRouter(prefix="/api/v1/audit_events", tags=["audit_events"])

PayloadRedactionStatus = Literal["keys_only", "blocked_by_secret_scan"]


class AuditEventRead(BaseModel):
    id: UUID
    tenant_id: int
    event_type: str
    actor_id: UUID | None
    principal_id: UUID | None
    correlation_id: str | None
    trace_id: str | None
    reason_code: str | None
    payload_keys: list[str]
    payload_redaction_status: PayloadRedactionStatus
    created_at: datetime


class AuditEventListResponse(BaseModel):
    events: list[AuditEventRead]
    total: int
    limit: int
    offset: int


def _payload_keys(payload: dict[str, Any]) -> tuple[list[str], PayloadRedactionStatus]:
    try:
        assert_no_raw_secret(payload, path="$audit_event_payload")
    except ValueError:
        return [], "blocked_by_secret_scan"
    return sorted(payload.keys()), "keys_only"


def _reason_code(payload: dict[str, Any]) -> str | None:
    value = payload.get("reason_code")
    return value if isinstance(value, str) and value.strip() else None


def _to_read(event: AuditEvent) -> AuditEventRead:
    payload_keys, payload_redaction_status = _payload_keys(event.event_payload)
    return AuditEventRead(
        id=event.id,
        tenant_id=event.tenant_id,
        event_type=event.event_type,
        actor_id=event.actor_id,
        principal_id=event.principal_id,
        correlation_id=event.correlation_id,
        trace_id=event.trace_id,
        reason_code=_reason_code(event.event_payload),
        payload_keys=payload_keys,
        payload_redaction_status=payload_redaction_status,
        created_at=event.created_at,
    )


@router.get("", response_model=AuditEventListResponse)
async def list_audit_events_endpoint(
    event_type: str | None = Query(default=None, min_length=1, max_length=100),
    actor_id_filter: UUID | None = Query(default=None, alias="actor_id"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> AuditEventListResponse:
    """List redacted audit event metadata for the current tenant."""
    conditions = [AuditEvent.tenant_id == tenant_id]
    if event_type is not None:
        conditions.append(AuditEvent.event_type == event_type)
    if actor_id_filter is not None:
        conditions.append(AuditEvent.actor_id == actor_id_filter)

    total = await session.scalar(select(func.count()).select_from(AuditEvent).where(*conditions))
    result = await session.execute(
        select(AuditEvent)
        .where(*conditions)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
        .limit(limit)
        .offset(offset)
    )
    return AuditEventListResponse(
        events=[_to_read(event) for event in result.scalars()],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


__all__ = [
    "AuditEventListResponse",
    "AuditEventRead",
    "router",
]
