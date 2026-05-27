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
    from sqlalchemy import text as sa_text

    from backend.app.db.models.ticket import Ticket

    count_result = await session.execute(
        sa_text("SELECT count(*) FROM tickets WHERE tenant_id = :tid AND project_id = :pid"),
        {"tid": tenant_id, "pid": project_id},
    )
    total = count_result.scalar() or 0

    result = await session.execute(
        select(Ticket)
        .where(Ticket.tenant_id == tenant_id, Ticket.project_id == project_id)
        .order_by(Ticket.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    tickets = result.scalars().all()
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
        "total": total,
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
    from backend.app.db.models.agent_run_event import AgentRunEvent
    from backend.app.mcp.context import DEFAULT_SUPERINTENDENT_ACTOR_ID

    run = AgentRun(
        tenant_id=tenant_id,
        project_id=project_id,
        status="queued",
    )
    session.add(run)
    await session.flush()

    event = AgentRunEvent(
        tenant_id=tenant_id,
        run_id=run.id,
        seq_no=1,
        event_type="run_queued",
        event_payload={
            "ticket_id": ticket_id,
            "purpose": purpose,
            "project_id": str(project_id),
        },
        actor_id=DEFAULT_SUPERINTENDENT_ACTOR_ID,
    )
    session.add(event)
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


async def bridge_project_list(
    session: AsyncSession,
    *,
    tenant_id: int,
) -> dict[str, Any]:
    from backend.app.repositories.project import ProjectRepository

    repo = ProjectRepository(session)
    projects = await repo.list(tenant_id=tenant_id)
    return {
        "projects": [
            {
                "id": str(p.id),
                "slug": p.slug,
                "name": p.name,
                "status": p.status,
            }
            for p in projects
        ],
        "total": len(projects),
    }


async def bridge_context_auto(
    session: AsyncSession,
    *,
    tenant_id: int,
    cwd: str,
) -> dict[str, Any]:
    import os

    from backend.app.repositories.project import ProjectRepository

    repo = ProjectRepository(session)
    projects = await repo.list(tenant_id=tenant_id)

    dir_name = os.path.basename(cwd.rstrip("/"))
    dir_name_lower = dir_name.lower().replace("_", "-").replace(" ", "-")

    for p in projects:
        if p.slug == dir_name_lower or p.slug == dir_name:
            return {
                "project_id": str(p.id),
                "project_name": p.name,
                "project_slug": p.slug,
                "matched_by": "directory_name",
            }

    for p in projects:
        if dir_name_lower in p.slug or p.slug in dir_name_lower:
            return {
                "project_id": str(p.id),
                "project_name": p.name,
                "project_slug": p.slug,
                "matched_by": "partial_match",
            }

    return {"error": "no_matching_project", "cwd": cwd, "hint": "Use project_list to find available projects"}


async def bridge_ticket_list_all(
    session: AsyncSession,
    *,
    tenant_id: int,
    status: str = "open",
    limit: int = 50,
) -> dict[str, Any]:
    from sqlalchemy import text as sa_text

    result = await session.execute(
        sa_text("""
            SELECT t.id, t.title, t.status, t.priority, t.created_at,
                   p.slug as project_slug, p.name as project_name, p.id as project_id
            FROM tickets t
            JOIN projects p ON t.project_id = p.id AND t.tenant_id = p.tenant_id
            WHERE t.tenant_id = :tenant_id AND t.status = :status
            ORDER BY t.created_at DESC
            LIMIT :limit
        """),
        {"tenant_id": tenant_id, "status": status, "limit": limit},
    )
    rows = result.fetchall()
    return {
        "tickets": [
            {
                "id": str(r[0]),
                "title": r[1],
                "status": r[2],
                "priority": r[3],
                "created_at": r[4].isoformat() if r[4] else None,
                "project_slug": r[5],
                "project_name": r[6],
                "project_id": str(r[7]),
            }
            for r in rows
        ],
        "total": len(rows),
        "status_filter": status,
    }


async def bridge_ticket_search(
    session: AsyncSession,
    *,
    tenant_id: int,
    query: str,
    limit: int = 20,
) -> dict[str, Any]:
    from sqlalchemy import text as sa_text

    search_pattern = f"%{query}%"
    result = await session.execute(
        sa_text("""
            SELECT t.id, t.title, t.status, t.priority, t.created_at,
                   p.slug as project_slug, p.name as project_name, p.id as project_id
            FROM tickets t
            JOIN projects p ON t.project_id = p.id AND t.tenant_id = p.tenant_id
            WHERE t.tenant_id = :tenant_id AND t.title ILIKE :pattern
            ORDER BY t.created_at DESC
            LIMIT :limit
        """),
        {"tenant_id": tenant_id, "pattern": search_pattern, "limit": limit},
    )
    rows = result.fetchall()
    return {
        "tickets": [
            {
                "id": str(r[0]),
                "title": r[1],
                "status": r[2],
                "priority": r[3],
                "created_at": r[4].isoformat() if r[4] else None,
                "project_slug": r[5],
                "project_name": r[6],
                "project_id": str(r[7]),
            }
            for r in rows
        ],
        "total": len(rows),
        "query": query,
    }


async def bridge_ticket_comment(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    ticket_id: UUID,
    message: str,
    actor_id: UUID,
) -> dict[str, Any]:
    from backend.app.repositories.notification_event import NotificationEventRepository

    repo = NotificationEventRepository(session)
    event = await repo.append(
        tenant_id=tenant_id,
        event_type="ticket_comment",
        payload={
            "project_id": str(project_id),
            "ticket_id": str(ticket_id),
            "message": message,
        },
        recipient_actor_id=actor_id,
    )
    await session.commit()
    return {
        "comment_id": str(event.id),
        "ticket_id": str(ticket_id),
        "message": message,
    }


async def bridge_ticket_link(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    source_ticket_id: UUID,
    target_ticket_id: UUID,
    relation_type: str,
) -> dict[str, Any]:
    from backend.app.repositories.ticket_relation import TicketRelationRepository

    repo = TicketRelationRepository(session)
    relation = await repo.create_in_project(
        tenant_id=tenant_id,
        project_id=project_id,
        payload={
            "source_ticket_id": source_ticket_id,
            "target_ticket_id": target_ticket_id,
            "relation_type": relation_type,
        },
    )
    await session.commit()
    return {
        "relation_id": str(relation.id),
        "source_ticket_id": str(source_ticket_id),
        "target_ticket_id": str(target_ticket_id),
        "relation_type": relation_type,
    }


async def bridge_run_list(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    limit: int = 20,
) -> dict[str, Any]:
    result = await session.execute(
        select(AgentRun)
        .where(AgentRun.tenant_id == tenant_id, AgentRun.project_id == project_id)
        .order_by(AgentRun.created_at.desc())
        .limit(limit)
    )
    runs = result.scalars().all()
    return {
        "runs": [
            {
                "id": str(r.id),
                "status": r.status,
                "blocked_reason": r.blocked_reason,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in runs
        ],
        "total": len(runs),
    }
