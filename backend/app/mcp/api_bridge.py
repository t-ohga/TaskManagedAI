"""MCP → FastAPI API bridge.

Resolves session context (tenant_id, actor_id, project_id) from
MCP server state and calls backend services directly.
Server-owned fields are never accepted from MCP tool input.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.repositories.ticket import TicketRepository


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
    repo = TicketRepository(session)
    ticket = await repo.create(
        tenant_id=tenant_id,
        payload={
            "project_id": project_id,
            "title": title,
            "description": description,
            "status": "open",
        },
    )
    await session.commit()
    return {
        "ticket_id": str(ticket.id),
        "title": ticket.title,
        "status": ticket.status,
    }
