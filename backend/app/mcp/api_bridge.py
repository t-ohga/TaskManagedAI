"""MCP → FastAPI API bridge.

Resolves session context (tenant_id, actor_id, project_id) from
MCP server state and calls backend services directly.
Server-owned fields are never accepted from MCP tool input.
"""

from __future__ import annotations

import re
import time
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.audit_event import AuditEvent
from backend.app.repositories.ticket import TicketRepository

MAX_LIMIT = 200


def _clamp(limit: int, offset: int) -> tuple[int, int]:
    return min(max(1, limit), MAX_LIMIT), max(0, offset)


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
    clamped_limit, clamped_offset = _clamp(limit, offset)
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
        "limit": clamped_limit,
        "offset": clamped_offset,
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
    # Fetch children runs
    children_result = await session.execute(
        select(AgentRun.id, AgentRun.status, AgentRun.role_id).where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.parent_run_id == run_id,
        )
    )
    children = [
        {"run_id": str(c[0]), "status": c[1], "role_id": c[2]}
        for c in children_result.fetchall()
    ]

    # Fetch ticket_id from run_queued event
    from sqlalchemy import text as sa_text
    ticket_result = await session.execute(
        sa_text(
            "SELECT event_payload->>'ticket_id' FROM agent_run_events "
            "WHERE tenant_id = :tid AND run_id = :rid AND event_type = 'run_queued' LIMIT 1"
        ),
        {"tid": tenant_id, "rid": run_id},
    )
    ticket_row = ticket_result.fetchone()
    ticket_id = ticket_row[0] if ticket_row else None

    return {
        "run_id": str(run.id),
        "project_id": str(run.project_id),
        "status": run.status,
        "blocked_reason": run.blocked_reason,
        "error_code": run.error_code,
        "role_id": run.role_id,
        "parent_run_id": str(run.parent_run_id) if run.parent_run_id else None,
        "ticket_id": ticket_id,
        "children": children,
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
    limit, offset = _clamp(limit, offset)
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
    role_id: str | None = None,
    parent_run_id: UUID | None = None,
) -> dict[str, Any]:
    from backend.app.db.models.agent_run_event import AgentRunEvent
    from backend.app.mcp.context import DEFAULT_SUPERINTENDENT_ACTOR_ID

    run = AgentRun(
        tenant_id=tenant_id,
        project_id=project_id,
        status="queued",
        role_id=role_id,
        role_scope="project" if role_id else None,
        parent_run_id=parent_run_id,
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
            "role_id": role_id,
            "parent_run_id": str(parent_run_id) if parent_run_id else None,
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
        "role_id": role_id,
        "parent_run_id": str(parent_run_id) if parent_run_id else None,
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

    limit = min(max(1, limit), MAX_LIMIT)
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

    query = query[:200]
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
        .limit(min(max(1, limit), MAX_LIMIT))
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


async def bridge_run_update(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID,
    status: str,
    summary: str = "",
) -> dict[str, Any]:
    from backend.app.db.models.agent_run_event import AgentRunEvent
    from backend.app.mcp.context import DEFAULT_SUPERINTENDENT_ACTOR_ID

    valid_statuses = {
        "running", "completed", "failed", "blocked",
        "gathering_context", "generated_artifact",
    }
    if status not in valid_statuses:
        return {"error": "invalid_status", "valid": sorted(valid_statuses)}

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

    old_status = run.status
    run.status = status
    if status == "blocked":
        run.blocked_reason = "runtime_blocked"
    elif run.blocked_reason and status != "blocked":
        run.blocked_reason = None

    event_type_map = {
        "running": "context_gathered",
        "completed": "run_completed",
        "failed": "run_failed",
        "blocked": "runtime_blocked",
        "gathering_context": "context_gathered",
        "generated_artifact": "artifact_generated",
    }

    max_seq = await session.execute(
        sa.text("SELECT COALESCE(MAX(seq_no), 0) FROM agent_run_events WHERE tenant_id = :tid AND run_id = :rid"),
        {"tid": tenant_id, "rid": run_id},
    )
    next_seq = (max_seq.scalar() or 0) + 1

    event = AgentRunEvent(
        tenant_id=tenant_id,
        run_id=run_id,
        seq_no=next_seq,
        event_type=event_type_map.get(status, "context_gathered"),
        event_payload={
            "old_status": old_status,
            "new_status": status,
            "summary": summary,
        },
        actor_id=DEFAULT_SUPERINTENDENT_ACTOR_ID,
    )
    session.add(event)
    await session.commit()

    return {
        "run_id": str(run.id),
        "old_status": old_status,
        "new_status": status,
        "summary": summary,
    }


async def bridge_approval_request_create(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    ticket_id: str,
    action_class: str,
    requester_actor_id: UUID,
) -> dict[str, Any]:
    from backend.app.repositories.approval_request import ApprovalRequestRepository

    repo = ApprovalRequestRepository(session)
    approval = await repo.create_pending_approval(
        tenant_id=tenant_id,
        action_class=action_class,
        resource_ref=f"ticket:{ticket_id}",
        risk_level="medium",
        requested_by_actor_id=requester_actor_id,
        recipient_actor_id=requester_actor_id,
        policy_version="v1",
        artifact_hash=f"ticket:{ticket_id}",
    )
    await session.commit()
    return {
        "approval_id": str(approval.id),
        "action_class": action_class,
        "status": "pending",
        "ticket_id": ticket_id,
    }


async def bridge_delegation_create(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    parent_run_id: UUID,
    ticket_id: str,
    purpose: str,
    role_id: str,
    task_spec: dict[str, Any],
    sender_actor_id: UUID,
) -> dict[str, Any]:
    import hashlib
    import json as json_mod
    from datetime import UTC, datetime, timedelta

    child_run = await bridge_run_create(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        ticket_id=ticket_id,
        purpose=purpose,
        role_id=role_id,
        parent_run_id=parent_run_id,
    )
    if "error" in child_run:
        return child_run

    child_run_id = UUID(child_run["run_id"])
    spec_json = json_mod.dumps(task_spec, sort_keys=True, ensure_ascii=False)
    payload_hash = hashlib.sha256(spec_json.encode()).hexdigest()

    max_seq = await session.execute(
        sa.text(
            "SELECT COALESCE(MAX(seq_no), 0) FROM inter_agent_messages "
            "WHERE tenant_id = :tid AND parent_run_id = :prid"
        ),
        {"tid": tenant_id, "prid": parent_run_id},
    )
    next_seq = (max_seq.scalar() or 0) + 1

    msg_id = uuid4()
    await session.execute(
        sa.text("""
            INSERT INTO inter_agent_messages (
                id, tenant_id, project_id, parent_run_id, child_run_id,
                sender_actor_id, sender_run_id, receiver_kind, receiver_ref,
                payload_data_class, trust_level, payload_hash, artifact_ref,
                seq_no, schema_version, idempotency_key, expires_at
            ) VALUES (
                :id, :tid, :pid, :prid, :crid,
                :said, :srid, 'agent_run', NULL,
                'internal', 'untrusted_content', :phash, :aref,
                :seq, '1.0', :ikey, :exp
            )
        """),
        {
            "id": msg_id, "tid": tenant_id, "pid": project_id,
            "prid": parent_run_id, "crid": child_run_id,
            "said": sender_actor_id, "srid": parent_run_id,
             "phash": payload_hash,
            "aref": f"task_spec:{child_run_id}",
            "seq": next_seq, "ikey": f"delegation:{parent_run_id}:{next_seq}",
            "exp": datetime.now(UTC) + timedelta(hours=24),
        },
    )
    await session.commit()

    return {
        "delegation_id": str(msg_id),
        "child_run_id": str(child_run_id),
        "parent_run_id": str(parent_run_id),
        "role_id": role_id,
        "status": "pending",
        "task_spec": task_spec,
    }


async def bridge_delegation_inbox(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID,
    limit: int = 20,
) -> dict[str, Any]:
    limit = min(max(1, limit), MAX_LIMIT)
    result = await session.execute(
        sa.text("""
            SELECT id, sender_run_id, parent_run_id, artifact_ref, seq_no, created_at
            FROM inter_agent_messages
            WHERE tenant_id = :tid AND child_run_id = :crid AND consumed_at IS NULL
            ORDER BY created_at DESC
            LIMIT :lim
        """),
        {"tid": tenant_id, "crid": run_id, "lim": limit},
    )
    rows = result.fetchall()
    return {
        "messages": [
            {
                "id": str(r[0]),
                "sender_run_id": str(r[1]),
                "parent_run_id": str(r[2]),
                "artifact_ref": r[3],
                "seq_no": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


async def bridge_delegation_accept(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID,
    message_id: UUID,
) -> dict[str, Any]:
    result = await session.execute(
        select(AgentRun).where(AgentRun.tenant_id == tenant_id, AgentRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        return {"error": "not_found", "run_id": str(run_id)}
    if run.status != "queued":
        return {"error": "invalid_state", "status": run.status, "expected": "queued"}

    consume_result = await session.execute(
        sa.text(
            "UPDATE inter_agent_messages SET consumed_at = now(), consumed_by_run_id = :rid "
            "WHERE tenant_id = :tid AND id = :mid AND child_run_id = :rid AND consumed_at IS NULL "
            "RETURNING id"
        ),
        {"tid": tenant_id, "rid": run_id, "mid": message_id},
    )
    if consume_result.fetchone() is None:
        return {"error": "message_not_found_or_not_addressed_to_this_run", "run_id": str(run_id)}

    run.status = "running"
    await session.commit()
    return {"run_id": str(run_id), "status": "running", "accepted": True}


async def bridge_delegation_submit(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID,
    parent_run_id: UUID,
    project_id: UUID,
    result_status: str,
    result_summary: str,
    result_spec: dict[str, Any],
    actor_id: UUID,
) -> dict[str, Any]:
    import hashlib
    import json as json_mod
    from datetime import UTC, datetime, timedelta

    valid = {"completed", "failed", "needs_review"}
    if result_status not in valid:
        return {"error": "invalid_status", "valid": sorted(valid)}

    result = await session.execute(
        select(AgentRun).where(AgentRun.tenant_id == tenant_id, AgentRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        return {"error": "not_found", "run_id": str(run_id)}
    if run.parent_run_id and run.parent_run_id != parent_run_id:
        return {"error": "parent_run_id_mismatch", "expected": str(run.parent_run_id)}

    run_status = "completed" if result_status == "completed" else "failed" if result_status == "failed" else "running"
    run.status = run_status

    spec_json = json_mod.dumps(result_spec, sort_keys=True, ensure_ascii=False)
    payload_hash = hashlib.sha256(spec_json.encode()).hexdigest()

    max_seq = await session.execute(
        sa.text(
            "SELECT COALESCE(MAX(seq_no), 0) FROM inter_agent_messages "
            "WHERE tenant_id = :tid AND parent_run_id = :prid"
        ),
        {"tid": tenant_id, "prid": parent_run_id},
    )
    next_seq = (max_seq.scalar() or 0) + 1

    msg_id = uuid4()
    await session.execute(
        sa.text("""
            INSERT INTO inter_agent_messages (
                id, tenant_id, project_id, parent_run_id, child_run_id,
                sender_actor_id, sender_run_id, receiver_kind, receiver_ref,
                payload_data_class, trust_level, payload_hash, artifact_ref,
                seq_no, schema_version, idempotency_key, expires_at
            ) VALUES (
                :id, :tid, :pid, :prid, :crid,
                :said, :srid, 'agent_run', NULL,
                'internal', 'untrusted_content', :phash, :aref,
                :seq, '1.0', :ikey, :exp
            )
        """),
        {
            "id": msg_id, "tid": tenant_id, "pid": project_id,
            "prid": parent_run_id, "crid": run_id,
            "said": actor_id, "srid": run_id,
            "phash": payload_hash,
            "aref": f"result:{run_id}:{result_status}",
            "seq": next_seq,
            "ikey": f"submit:{run_id}:{next_seq}",
            "exp": datetime.now(UTC) + timedelta(hours=24),
        },
    )
    await session.commit()
    return {
        "submitted": True,
        "run_id": str(run_id),
        "status": run_status,
        "result_status": result_status,
        "message_id": str(msg_id),
    }


async def bridge_delegation_review(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID,
    reviewer_run_id: UUID,
    decision: str,
    quality_score: float,
    findings: str = "",
) -> dict[str, Any]:
    valid_decisions = {"adopt", "reject"}
    if decision not in valid_decisions:
        return {"error": "invalid_decision", "valid": sorted(valid_decisions)}
    quality_score = round(max(0.0, min(1.0, quality_score)), 6)

    result = await session.execute(
        select(AgentRun).where(AgentRun.tenant_id == tenant_id, AgentRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        return {"error": "not_found", "run_id": str(run_id)}

    reviewer_result = await session.execute(
        select(AgentRun).where(AgentRun.tenant_id == tenant_id, AgentRun.id == reviewer_run_id)
    )
    reviewer = reviewer_result.scalar_one_or_none()
    if reviewer is None:
        return {"error": "reviewer_not_found"}
    if reviewer.parent_run_id == run.parent_run_id and reviewer_run_id == run_id:
        return {"error": "self_review_forbidden"}

    from backend.app.db.models.agent_run_event import AgentRunEvent

    max_seq = await session.execute(
        sa.text(
            "SELECT COALESCE(MAX(seq_no), 0) FROM agent_run_events "
            "WHERE tenant_id = :tid AND run_id = :rid"
        ),
        {"tid": tenant_id, "rid": run_id},
    )
    next_seq = (max_seq.scalar() or 0) + 1

    event = AgentRunEvent(
        tenant_id=tenant_id,
        run_id=run_id,
        seq_no=next_seq,
        event_type="approval_decided",
        event_payload={
            "decision": decision,
            "quality_score": quality_score,
            "reviewer_run_id": str(reviewer_run_id),
            "findings": findings,
        },
        actor_id=UUID("00000000-0000-4000-8000-000000000001"),
    )
    session.add(event)
    await session.commit()

    return {
        "reviewed": True,
        "run_id": str(run_id),
        "decision": decision,
        "quality_score": quality_score,
    }


async def bridge_delegation_tree(
    session: AsyncSession,
    *,
    tenant_id: int,
    root_run_id: UUID,
) -> dict[str, Any]:
    result = await session.execute(
        sa.text("""
            WITH RECURSIVE tree AS (
                SELECT id, parent_run_id, project_id, status, role_id, 0 as depth
                FROM agent_runs
                WHERE tenant_id = :tid AND id = :rid
                UNION ALL
                SELECT ar.id, ar.parent_run_id, ar.project_id, ar.status, ar.role_id, t.depth + 1
                FROM agent_runs ar
                JOIN tree t ON ar.parent_run_id = t.id AND ar.tenant_id = :tid
                WHERE t.depth < 10
            )
            SELECT id, parent_run_id, status, role_id, depth FROM tree ORDER BY depth, id
        """),
        {"tid": tenant_id, "rid": root_run_id},
    )
    rows = result.fetchall()
    if not rows:
        return {"error": "not_found", "run_id": str(root_run_id)}
    return {
        "tree": [
            {
                "run_id": str(r[0]),
                "parent_run_id": str(r[1]) if r[1] else None,
                "status": r[2],
                "role_id": r[3],
                "depth": r[4],
            }
            for r in rows
        ],
        "total_nodes": len(rows),
        "max_depth": max(r[4] for r in rows),
    }


async def bridge_delegation_cancel(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID,
) -> dict[str, Any]:
    result = await session.execute(
        sa.text("""
            WITH RECURSIVE tree AS (
                SELECT id, 0 as depth FROM agent_runs
                WHERE tenant_id = :tid AND id = :rid
                UNION ALL
                SELECT ar.id, t.depth + 1 FROM agent_runs ar
                JOIN tree t ON ar.parent_run_id = t.id AND ar.tenant_id = :tid
                WHERE t.depth < 10
            )
            UPDATE agent_runs SET status = 'cancelled', blocked_reason = NULL
            WHERE tenant_id = :tid AND id IN (SELECT id FROM tree)
              AND status NOT IN ('completed', 'failed', 'cancelled', 'provider_refused', 'repair_exhausted')
            RETURNING id
        """),
        {"tid": tenant_id, "rid": run_id},
    )
    cancelled_ids = [str(r[0]) for r in result.fetchall()]
    await session.commit()
    return {
        "cancelled": cancelled_ids,
        "count": len(cancelled_ids),
    }


async def bridge_workflow_status(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID | None = None,
) -> dict[str, Any]:
    if project_id:
        result = await session.execute(
            sa.text(
                "SELECT status, role_id, count(*) as cnt FROM agent_runs "
                "WHERE tenant_id = :tid AND project_id = :pid "
                "GROUP BY status, role_id ORDER BY status, role_id"
            ),
            {"tid": tenant_id, "pid": project_id},
        )
    else:
        result = await session.execute(
            sa.text(
                "SELECT status, role_id, count(*) as cnt FROM agent_runs "
                "WHERE tenant_id = :tid "
                "GROUP BY status, role_id ORDER BY status, role_id"
            ),
            {"tid": tenant_id},
        )
    rows = result.fetchall()

    total = sum(r[2] for r in rows)
    by_status: dict[str, int] = {}
    by_role: dict[str, int] = {}
    for r in rows:
        by_status[r[0]] = by_status.get(r[0], 0) + r[2]
        if r[1]:
            by_role[r[1]] = by_role.get(r[1], 0) + r[2]

    active = by_status.get("running", 0) + by_status.get("queued", 0) + by_status.get("gathering_context", 0)
    completed = by_status.get("completed", 0)
    failed = by_status.get("failed", 0)
    cancelled = by_status.get("cancelled", 0)

    return {
        "total_runs": total,
        "active": active,
        "completed": completed,
        "failed": failed,
        "cancelled": cancelled,
        "by_status": by_status,
        "by_role": by_role,
        "success_rate": round(completed / (completed + failed) * 100, 1) if (completed + failed) > 0 else 0,
    }
