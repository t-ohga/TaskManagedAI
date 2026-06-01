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
from datetime import date, datetime
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
from backend.app.api.dependencies.api_capability_token import maybe_require_cli_capability
from backend.app.db.models.audit_event import AuditEvent
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.repositories.notification_event import NotificationEventRepository
from backend.app.repositories.ticket import (
    ProjectArchivedError,
    TicketNotActionableError,
    TicketRepository,
)
from backend.app.schemas.ticket import TicketPriority, TicketRead, TicketStatus
from backend.app.services.notifications.ticket_comment import (
    TICKET_COMMENT_MESSAGE_MAX_LENGTH,
    create_ticket_comment_event,
    redact_comment_message,
)

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
    _cli_capability: object = Depends(maybe_require_cli_capability("task_list")),  # noqa: B008
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
    _cli_capability: object = Depends(maybe_require_cli_capability("task_show")),  # noqa: B008
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
    due_date: date | None = None
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
    due_date: date | None = None
    assignee_actor_id: UUID | None = None


@router.post("", response_model=TicketRead, status_code=status.HTTP_201_CREATED)
async def create_ticket_endpoint(
    project_id: UUID,
    payload: TicketCreateRequest,
    _cli_capability: object = Depends(maybe_require_cli_capability("task_create")),  # noqa: B008
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
    except ProjectArchivedError as exc:
        # Q-4 (ADR-00037 / Codex adversarial R5 #3): archived project への ticket create は 409
        # (create_in_project の archive freeze guard を HTTP contract に正しく写像する。未捕捉だと 500)。
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="project is archived; unarchive it before creating tickets",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # SP-012-11 BL-TCU-008: ticket_created audit event 記録
    # raw secret なし、ticket id / slug / status / actor のみ
    audit_event = AuditEvent(
        tenant_id=tenant_id,
        event_type="ticket_created",
        actor_id=actor_id,
        event_payload={
            "rls_ready": True,
            "ticket_id": str(ticket.id),
            "project_id": str(project_id),
            "slug": ticket.slug,
            "status": ticket.status,
            "priority": ticket.priority,
        },
    )
    session.add(audit_event)
    # Codex PR #119 R1 F-PR119-001 (P1) fix: `get_session` は auto-commit なし、
    # 既存 endpoint pattern (agent_runs/approval_inbox/claims 等) は明示 commit が
    # 必要。flush のみだと request close で rollback され、201 返しても persist しない。
    await session.commit()

    return TicketRead.model_validate(ticket)


@router.patch("/{ticket_id}", response_model=TicketRead)
async def update_ticket_endpoint(
    project_id: UUID,
    ticket_id: UUID,
    payload: TicketUpdateRequest,
    _cli_capability: object = Depends(maybe_require_cli_capability("task_write")),  # noqa: B008
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

    # status 変更検出 (audit event 詳細用)
    previous_status = existing.status
    new_status = update_data.get("status", previous_status)

    try:
        ticket = await repo.update_in_project(
            tenant_id=tenant_id,
            project_id=project_id,
            ticket_id=ticket_id,
            payload=update_data,
        )
    except ProjectArchivedError as exc:
        # Q-4 (ADR-00037 / Codex adversarial R5 #3): archived project への ticket update は 409。
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="project is archived; unarchive it before updating tickets",
        ) from exc
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

    # SP-012-11 BL-TCU-008: ticket_status_changed (or ticket_updated) audit event 記録
    event_type = (
        "ticket_status_changed" if previous_status != new_status else "ticket_updated"
    )
    audit_event = AuditEvent(
        tenant_id=tenant_id,
        event_type=event_type,
        actor_id=actor_id,
        event_payload={
            "rls_ready": True,
            "ticket_id": str(ticket.id),
            "project_id": str(project_id),
            "slug": ticket.slug,
            "previous_status": previous_status,
            "new_status": new_status,
            "updated_fields": sorted(payload.model_dump(exclude_unset=True).keys()),
        },
    )
    session.add(audit_event)
    # Codex PR #119 R1 F-PR119-002 (P1) fix: PATCH success path で commit 必須。
    # 既存 endpoint pattern (claims/evidence_items 等) と同じく flush のみでは
    # rollback されるため明示 commit。
    await session.commit()

    return TicketRead.model_validate(ticket)


# ---------------------------------------------------------------------------
# ADR-00041 N-1 / N-2: ticket コメント + activity timeline
# ---------------------------------------------------------------------------


class TicketComment(BaseModel):
    id: UUID
    message: str
    # legacy row は payload.actor_id を持たないため recipient_actor_id fallback (R2-2)。
    actor_id: UUID | None
    created_at: datetime


class TicketCommentListResponse(BaseModel):
    comments: list[TicketComment]


class CreateTicketCommentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=TICKET_COMMENT_MESSAGE_MAX_LENGTH)


class TicketActivityEntry(BaseModel):
    id: str
    # "created" | "comment" | "status_change" | "updated"
    type: str
    message: str | None = None
    actor_id: UUID | None = None
    created_at: datetime
    previous_status: str | None = None
    new_status: str | None = None


class TicketActivityListResponse(BaseModel):
    entries: list[TicketActivityEntry]


def _comment_author(payload: dict[str, Any], recipient_actor_id: UUID) -> UUID | None:
    """payload.actor_id を優先、無ければ recipient_actor_id fallback (legacy row、R2-2)."""
    raw = payload.get("actor_id")
    if isinstance(raw, str) and raw:
        try:
            return UUID(raw)
        except ValueError:
            return None
    return recipient_actor_id


def _redacted_message(message: str) -> str:
    """legacy row に secret / canary が残っていても raw 表示しない defensive redaction (R2-1).

    canary-aware な共通 helper に委譲する (raw secret + `CANARY-FIXTURE-...` を同一判定で
    redaction、Codex adversarial R1 F-HIGH)。
    """
    return redact_comment_message(message)


async def _assert_ticket_readable(
    session: AsyncSession, tenant_id: int, project_id: UUID, ticket_id: UUID
) -> None:
    """GET 用 read guard: deleted_at IS NULL のみ確認 (archived は許可、R1-1)。"""
    ticket = await TicketRepository(session).get_in_project(
        tenant_id=tenant_id, project_id=project_id, ticket_id=ticket_id
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ticket not found")


@router.get("/{ticket_id}/comments", response_model=TicketCommentListResponse)
async def list_ticket_comments_endpoint(
    project_id: UUID,
    ticket_id: UUID,
    _cli_capability: object = Depends(maybe_require_cli_capability("task_show")),  # noqa: B008
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> TicketCommentListResponse:
    """ADR-00041 N-1: ticket コメント一覧 (read-only)。archived 許可 / deleted は 404 (R1-1)。"""
    await _assert_ticket_readable(session, tenant_id, project_id, ticket_id)
    events = await NotificationEventRepository(session).list_ticket_comments(
        tenant_id, ticket_id
    )
    return TicketCommentListResponse(
        comments=[
            TicketComment(
                id=event.id,
                message=_redacted_message(str(event.payload.get("message", ""))),
                actor_id=_comment_author(event.payload, event.recipient_actor_id),
                created_at=event.created_at,
            )
            for event in events
        ]
    )


@router.post(
    "/{ticket_id}/comments",
    response_model=TicketComment,
    status_code=status.HTTP_201_CREATED,
)
async def create_ticket_comment_endpoint(
    project_id: UUID,
    ticket_id: UUID,
    payload: CreateTicketCommentRequest,
    _cli_capability: object = Depends(maybe_require_cli_capability("task_write")),  # noqa: B008
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> TicketComment:
    """ADR-00041 N-1: ticket コメント作成 (human task-write 相当)。

    write guard は assert_ticket_actionable (soft-deleted / archived を拒否、R1-1)。
    message の raw secret / canary は共通 helper が永続化前に検出し ValueError → 422 (R1-2 / R2-1)。
    """
    try:
        await TicketRepository(session).assert_ticket_actionable(
            tenant_id, project_id, str(ticket_id)
        )
    except ProjectArchivedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="project is archived"
        ) from exc
    except TicketNotActionableError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="ticket not found"
        ) from exc

    try:
        event = await create_ticket_comment_event(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            ticket_id=ticket_id,
            message=payload.message,
            actor_id=actor_id,
        )
    except ValueError as exc:
        # secret canary / token / private key marker hit (fail-closed、R1-2)。raw 値は返さない。
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="comment rejected: message contains a forbidden secret pattern",
        ) from exc

    await session.commit()
    return TicketComment(
        id=event.id,
        message=payload.message,
        actor_id=actor_id,
        created_at=event.created_at,
    )


@router.get("/{ticket_id}/activity", response_model=TicketActivityListResponse)
async def list_ticket_activity_endpoint(
    project_id: UUID,
    ticket_id: UUID,
    _cli_capability: object = Depends(maybe_require_cli_capability("task_show")),  # noqa: B008
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> TicketActivityListResponse:
    """ADR-00041 N-2: comment + status 変更 audit event + 作成 を created_at 昇順でマージ。

    archived 許可 / deleted は 404 (R1-1)。既存 ticket_status_changed / ticket_updated audit event を
    含める (R1-4)。
    """
    ticket = await TicketRepository(session).get_in_project(
        tenant_id=tenant_id, project_id=project_id, ticket_id=ticket_id
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ticket not found")

    comments = await NotificationEventRepository(session).list_ticket_comments(
        tenant_id, ticket_id
    )
    activity = await AuditEventRepository(session).list_ticket_activity(tenant_id, ticket_id)

    entries: list[TicketActivityEntry] = []
    if ticket.created_at is not None:
        entries.append(
            TicketActivityEntry(
                id=f"created:{ticket.id}",
                type="created",
                actor_id=ticket.created_by_actor_id,
                created_at=ticket.created_at,
            )
        )
    for comment in comments:
        entries.append(
            TicketActivityEntry(
                id=f"comment:{comment.id}",
                type="comment",
                message=_redacted_message(str(comment.payload.get("message", ""))),
                actor_id=_comment_author(comment.payload, comment.recipient_actor_id),
                created_at=comment.created_at,
            )
        )
    for event in activity:
        is_status = event.event_type == "ticket_status_changed"
        entries.append(
            TicketActivityEntry(
                id=f"audit:{event.id}",
                type="status_change" if is_status else "updated",
                actor_id=event.actor_id,
                created_at=event.created_at,
                previous_status=(
                    str(event.event_payload.get("previous_status"))
                    if event.event_payload.get("previous_status") is not None
                    else None
                ),
                new_status=(
                    str(event.event_payload.get("new_status"))
                    if event.event_payload.get("new_status") is not None
                    else None
                ),
            )
        )
    entries.sort(key=lambda e: e.created_at)
    return TicketActivityListResponse(entries=entries)
