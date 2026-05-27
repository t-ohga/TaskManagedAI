"""MCP → FastAPI API bridge.

Resolves session context (tenant_id, actor_id, project_id) from
MCP server state and calls backend services directly.
Server-owned fields are never accepted from MCP tool input.
"""

from __future__ import annotations

import re
import time
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.audit_event import AuditEvent
from backend.app.repositories.ticket import TicketRepository


def _title_to_slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not slug:
        slug = "ticket"
    return f"{slug}-{int(time.time()) % 100000}"


async def bridge_ticket_list(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    repo = TicketRepository(session)
    all_tickets = await repo.list_in_project(tenant_id=tenant_id, project_id=project_id)
    tickets = all_tickets[offset : offset + limit]
    return {
        "tickets": [
            {
                "id": str(t.id),
                "title": t.title,
                "status": t.status,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tickets
        ],
        "total": len(tickets),
        "limit": limit,
        "offset": offset,
    }


async def bridge_ticket_create(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    title: str,
    description: str = "",
) -> dict[str, Any]:
    from backend.app.mcp.context import DEFAULT_SUPERINTENDENT_ACTOR_ID

    repo = TicketRepository(session)
    ticket = await repo.create(
        tenant_id=tenant_id,
        payload={
            "project_id": project_id,
            "title": title,
            "slug": _title_to_slug(title),
            "description": description,
            "status": "open",
            "created_by_actor_id": DEFAULT_SUPERINTENDENT_ACTOR_ID,
        },
    )
    await session.commit()
    return {
        "ticket_id": str(ticket.id),
        "title": ticket.title,
        "status": ticket.status,
    }


async def bridge_ticket_show(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    ticket_id: UUID,
) -> dict[str, Any]:
    repo = TicketRepository(session)
    ticket = await repo.get_in_project(
        tenant_id=tenant_id, project_id=project_id, ticket_id=ticket_id
    )
    if ticket is None:
        return {"error": "not_found", "ticket_id": str(ticket_id)}
    return {
        "id": str(ticket.id),
        "title": ticket.title,
        "slug": ticket.slug,
        "status": ticket.status,
        "description": ticket.description,
        "priority": ticket.priority,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
    }


async def bridge_ticket_update(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    ticket_id: UUID,
    payload: dict[str, Any],
) -> dict[str, Any]:
    repo = TicketRepository(session)
    ticket = await repo.update_in_project(
        tenant_id=tenant_id,
        project_id=project_id,
        ticket_id=ticket_id,
        payload=payload,
    )
    if ticket is None:
        return {"error": "not_found", "ticket_id": str(ticket_id)}
    await session.commit()
    return {
        "ticket_id": str(ticket.id),
        "title": ticket.title,
        "status": ticket.status,
        "updated": True,
    }


async def bridge_run_show(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID,
) -> dict[str, Any]:
    result = await session.execute(
        select(AgentRun).where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.id == run_id,
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        return {"error": "not_found", "run_id": str(run_id)}
    return {
        "run_id": str(run.id),
        "project_id": str(run.project_id),
        "status": run.status,
        "blocked_reason": run.blocked_reason,
        "error_code": run.error_code,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


async def bridge_audit_list(
    session: AsyncSession,
    *,
    tenant_id: int,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    count_result = await session.execute(
        select(sa.func.count()).select_from(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id
        )
    )
    total = count_result.scalar() or 0

    result = await session.execute(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    events = result.scalars().all()
    return {
        "events": [
            {
                "id": str(e.id),
                "event_type": e.event_type,
                "actor_id": str(e.actor_id) if e.actor_id else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def bridge_approval_list(
    session: AsyncSession,
    *,
    tenant_id: int,
    status: str = "pending",
) -> dict[str, Any]:
    from backend.app.repositories.approval_request import ApprovalRequestRepository

    repo = ApprovalRequestRepository(session)
    approvals = await repo.list_by_status(tenant_id=tenant_id, status=status)
    return {
        "approvals": [
            {
                "id": str(a.id),
                "action_class": a.action_class,
                "status": a.status,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in approvals
        ],
        "status_filter": status,
    }


async def bridge_run_create(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    ticket_id: str,
    purpose: str,
) -> dict[str, Any]:
    run = AgentRun(
        tenant_id=tenant_id,
        project_id=project_id,
        status="queued",
    )
    session.add(run)
    await session.flush()
    await session.commit()
    return {
        "run_id": str(run.id),
        "status": run.status,
        "project_id": str(project_id),
        "ticket_id": ticket_id,
        "purpose": purpose,
    }


async def bridge_run_cancel(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID,
) -> dict[str, Any]:
    result = await session.execute(
        select(AgentRun).where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.id == run_id,
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        return {"error": "not_found", "run_id": str(run_id)}

    terminal = {"completed", "failed", "cancelled", "provider_refused", "repair_exhausted"}
    if run.status in terminal:
        return {"error": "already_terminal", "run_id": str(run_id), "status": run.status}

    run.status = "cancelled"
    run.blocked_reason = None
    await session.commit()
    return {"run_id": str(run.id), "status": "cancelled"}


async def bridge_approval_show(
    session: AsyncSession,
    *,
    tenant_id: int,
    approval_id: UUID,
) -> dict[str, Any]:
    from backend.app.repositories.approval_request import ApprovalRequestRepository

    repo = ApprovalRequestRepository(session)
    approval = await repo.get_by_id(tenant_id=tenant_id, id=approval_id)
    if approval is None:
        return {"error": "not_found", "approval_id": str(approval_id)}
    return {
        "id": str(approval.id),
        "action_class": approval.action_class,
        "status": approval.status,
        "requester_actor_id": str(approval.requester_actor_id) if approval.requester_actor_id else None,
        "decider_actor_id": str(approval.decider_actor_id) if approval.decider_actor_id else None,
        "created_at": approval.created_at.isoformat() if approval.created_at else None,
    }


async def bridge_notification_list(
    session: AsyncSession,
    *,
    tenant_id: int,
    actor_id: UUID,
    limit: int = 20,
) -> dict[str, Any]:
    from backend.app.repositories.notification_event import NotificationEventRepository

    repo = NotificationEventRepository(session)
    events = await repo.list_for_recipient(
        tenant_id=tenant_id, recipient_actor_id=actor_id
    )
    limited = events[:limit]
    return {
        "notifications": [
            {
                "id": str(e.id),
                "event_type": e.event_type,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in limited
        ],
        "total": len(limited),
    }


async def bridge_notification_resolve(
    session: AsyncSession,
    *,
    tenant_id: int,
    notification_id: UUID,
) -> dict[str, Any]:
    from backend.app.repositories.notification_event import NotificationEventRepository

    repo = NotificationEventRepository(session)
    event = await repo.resolve(tenant_id=tenant_id, event_id=notification_id)
    if event is None:
        return {"error": "not_found", "notification_id": str(notification_id)}
    await session.commit()
    return {"notification_id": str(event.id), "resolved": True}
