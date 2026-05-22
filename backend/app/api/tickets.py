"""Tickets API endpoint (SP-012-9 BL-UIW-001/002 + SP-012-11 BL-TCU-001/002).

P0 UI Pack (SP-009) で skeleton として実装された Tickets page の実 backend
wiring。既存 TicketRepository + Pydantic schema を活用、API route 4 件:

- GET /api/v1/projects/{project_id}/tickets : list (pagination + tenant + project boundary)
- GET /api/v1/projects/{project_id}/tickets/{ticket_id} : detail
- POST /api/v1/projects/{project_id}/tickets : 新規作成 (SP-012-11 BL-TCU-001)
- PATCH /api/v1/projects/{project_id}/tickets/{ticket_id} : status / title / etc 更新 (SP-012-11 BL-TCU-002)

invariant:
- server-owned-boundary §1: tenant_id / project_id は session 経由 resolve、
  caller-supplied 経路なし (research_tasks API と同 pattern)
- repository は list_in_project / get_in_project / create_in_project / update_in_project で
  project boundary 強制
- response は TicketRead Pydantic schema、unknown field なし
- created_by_actor_id は server 側で current actor から resolve (caller-supplied 禁止)
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.repositories.ticket import TicketRepository
from backend.app.schemas.ticket import TicketPriority, TicketRead, TicketStatus

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


_SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class TicketCreateRequest(BaseModel):
    """SP-012-11 BL-TCU-001: server-owned-boundary §1 invariant に従い、
    caller-supplied 経路を排除した shape。created_by_actor_id は server 側
    Depends(get_current_actor_id) から resolve、payload に含めない。
    """

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, pattern=_SLUG_PATTERN)
    title: str = Field(min_length=1)
    description: str | None = None
    status: TicketStatus = "open"
    priority: TicketPriority | None = None
    assignee_actor_id: UUID | None = None


class TicketUpdateRequest(BaseModel):
    """SP-012-11 BL-TCU-002: PATCH 用 partial update shape。

    project_id / tenant_id / created_by_actor_id は更新不可 (server-owned-boundary §1)。
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    status: TicketStatus | None = None
    priority: TicketPriority | None = None
    assignee_actor_id: UUID | None = None


@router.post("", response_model=TicketRead, status_code=status.HTTP_201_CREATED)
async def create_ticket_endpoint(
    project_id: UUID,
    payload: TicketCreateRequest,
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> TicketRead:
    """新規 Ticket 作成 (SP-012-11 BL-TCU-001、本格的タスク管理運用).

    created_by_actor_id は server 側 (Depends 経由) で resolve、caller payload
    から受け取らない (server-owned-boundary §1 遵守)。
    """
    repo = TicketRepository(session)
    create_data: dict[str, Any] = payload.model_dump(exclude_unset=True)
    create_data["created_by_actor_id"] = actor_id
    create_data["metadata_"] = {"rls_ready": True, "user_edited": True}
    try:
        ticket = await repo.create_in_project(
            tenant_id=tenant_id,
            project_id=project_id,
            payload=create_data,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return TicketRead.model_validate(ticket)


@router.patch("/{ticket_id}", response_model=TicketRead)
async def update_ticket_endpoint(
    project_id: UUID,
    ticket_id: UUID,
    payload: TicketUpdateRequest,
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> TicketRead:
    """Ticket update (SP-012-11 BL-TCU-002、partial update).

    project_id / tenant_id / created_by_actor_id は更新不可。
    user 編集が seed re-apply で上書きされないよう metadata.user_edited=true を立てる。
    """
    repo = TicketRepository(session)
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="empty update payload",
        )
    # user 編集 marker (seed re-apply 衝突回避、SP-012-11 BL-TCU-009)
    # metadata は repository が既存 metadata と merge せず、明示的に新規 dict なので、
    # 既存 dogfooding_source は preservation が必要 → get_in_project で取得して merge
    existing = await repo.get_in_project(
        tenant_id=tenant_id,
        project_id=project_id,
        ticket_id=ticket_id,
    )
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ticket not found",
        )
    merged_metadata = dict(existing.metadata_ or {})
    merged_metadata["user_edited"] = True
    update_data["metadata"] = merged_metadata
    try:
        ticket = await repo.update_in_project(
            tenant_id=tenant_id,
            project_id=project_id,
            ticket_id=ticket_id,
            payload=update_data,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ticket not found",
        )
    return TicketRead.model_validate(ticket)
