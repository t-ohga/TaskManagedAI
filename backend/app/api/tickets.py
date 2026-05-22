"""Tickets API endpoint (SP-012-9 BL-UIW-001/002).

P0 UI Pack (SP-009) で skeleton として実装された Tickets page の実 backend
wiring。既存 TicketRepository + Pydantic schema を活用、新規 API route 2 件:

- GET /api/v1/projects/{project_id}/tickets : list (pagination + tenant + project boundary)
- GET /api/v1/projects/{project_id}/tickets/{ticket_id} : detail

invariant:
- server-owned-boundary §1: tenant_id / project_id は session 経由 resolve、
  caller-supplied 経路なし (research_tasks API と同 pattern)
- repository は list_in_project / get_in_project で project boundary 強制
- response は TicketRead Pydantic schema、unknown field なし

Codex SP-012-9 BL-UIW-001/002。
"""

from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.repositories.ticket import TicketRepository
from backend.app.schemas.ticket import TicketRead

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/tickets",
    tags=["tickets"],
)

_TRACE_ID_RE = re.compile(
    r"^[0-9a-fA-F]{16,32}$"
    r"|^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _correlation_id(request: Request) -> str:
    value = request.headers.get("x-correlation-id")
    if value and _TRACE_ID_RE.fullmatch(value):
        return value
    fallback = str(getattr(request.state, "request_id", ""))
    if fallback and _TRACE_ID_RE.fullmatch(fallback):
        return fallback
    return ""


class TicketListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[TicketRead]
    total: int
    limit: int
    offset: int


@router.get("", response_model=TicketListResponse)
async def list_tickets_endpoint(
    project_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008  # FastAPI Depends pattern
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> TicketListResponse:
    """List tickets in project (paginated)."""
    repo = TicketRepository(session)
    tickets = await repo.list_in_project(tenant_id=tenant_id, project_id=project_id)
    total = len(tickets)
    paginated = tickets[offset : offset + limit]
    return TicketListResponse(
        items=[TicketRead.model_validate(ticket) for ticket in paginated],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{ticket_id}", response_model=TicketRead)
async def get_ticket_endpoint(
    project_id: UUID,
    ticket_id: UUID,
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> TicketRead:
    """Get ticket detail by id (tenant + project boundary enforced by repository)."""
    repo = TicketRepository(session)
    ticket = await repo.get_in_project(
        tenant_id=tenant_id,
        project_id=project_id,
        ticket_id=ticket_id,
    )
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ticket not found",
        )
    return TicketRead.model_validate(ticket)
