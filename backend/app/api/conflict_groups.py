"""SP-032 (ADR-00052): conflict_groups API。

write は ``require_project_owner`` (P0 owner) + ``require_active_project``。read は認証 actor。
audit payload は ID + 変更フィールド名のみ (raw title / resolution_note 本文は含めない、R1 F-007)。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api._request_trace import correlation_id, trace_id
from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.api.dependencies.project_active_guard import require_active_project
from backend.app.api.me import require_project_owner
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.repositories.conflict_group import ConflictGroupRepository
from backend.app.repositories.research_task import get_research_task_by_id
from backend.app.schemas.conflict_group import (
    ConflictGroupCreate,
    ConflictGroupRead,
    ConflictGroupUpdate,
)
from backend.app.services.research.read_redaction import (
    to_conflict_group_read as _to_read,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/research-tasks/{research_task_id}/conflict-groups",
    tags=["conflict-groups"],
)


async def _require_research_task(
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    research_task_id: UUID,
) -> None:
    task = await get_research_task_by_id(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        research_task_id=research_task_id,
    )
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "research_task_not_found", "error_summary": "research task not found"},
        )


async def _audit(
    session: AsyncSession,
    request: Request,
    *,
    tenant_id: int,
    actor_id: UUID,
    event_type: str,
    payload: dict[str, object],
) -> None:
    corr = correlation_id(request)
    await AuditEventRepository(session).append(
        tenant_id=tenant_id,
        event_type=event_type,
        actor_id=actor_id,
        correlation_id=corr,
        trace_id=trace_id(request),
        payload={
            **payload,
            "tenant_id": tenant_id,
            "actor_id": str(actor_id),
            "correlation_id": corr,
            "timestamp": datetime.now(tz=UTC).isoformat(),
        },
    )


@router.post("", response_model=ConflictGroupRead, status_code=status.HTTP_201_CREATED)
async def create_conflict_group_endpoint(
    project_id: UUID,
    research_task_id: UUID,
    body: ConflictGroupCreate,
    request: Request,
    _active_project: None = Depends(require_active_project),  # noqa: B008
    owner_actor_id: UUID = Depends(require_project_owner),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ConflictGroupRead:
    await _require_research_task(session, tenant_id, project_id, research_task_id)
    repo = ConflictGroupRepository(session)
    try:
        group = await repo.create_conflict_group(
            tenant_id=tenant_id,
            project_id=project_id,
            research_task_id=research_task_id,
            title=body.title,
            created_by_actor_id=owner_actor_id,
        )
        await _audit(
            session,
            request,
            tenant_id=tenant_id,
            actor_id=owner_actor_id,
            event_type="conflict_group_created",
            payload={
                "conflict_group_id": str(group.id),
                "research_task_id": str(research_task_id),
            },
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "conflict_group_payload_validation_failed", "error_summary": str(exc)},
        ) from exc
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "conflict_group_create_failed", "error_summary": "conflict group binding failed"},
        ) from exc
    return _to_read(group)


@router.get("", response_model=list[ConflictGroupRead])
async def list_conflict_groups_endpoint(
    project_id: UUID,
    research_task_id: UUID,
    _actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> list[ConflictGroupRead]:
    repo = ConflictGroupRepository(session)
    groups = await repo.list_conflict_groups_by_research_task(
        tenant_id=tenant_id,
        project_id=project_id,
        research_task_id=research_task_id,
    )
    return [_to_read(g) for g in groups]


@router.patch("/{group_id}", response_model=ConflictGroupRead)
async def update_conflict_group_endpoint(
    project_id: UUID,
    research_task_id: UUID,
    group_id: UUID,
    body: ConflictGroupUpdate,
    request: Request,
    _active_project: None = Depends(require_active_project),  # noqa: B008
    owner_actor_id: UUID = Depends(require_project_owner),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ConflictGroupRead:
    repo = ConflictGroupRepository(session)
    existing = await repo.get_conflict_group(
        tenant_id=tenant_id,
        project_id=project_id,
        research_task_id=research_task_id,
        group_id=group_id,
    )
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "conflict_group_not_found", "error_summary": "conflict group not found"},
        )

    update_fields = body.model_dump(exclude_unset=True)
    if not update_fields:
        return _to_read(existing)

    # R1 F-002: resolved は resolution_note 必須 (本 PATCH か既存値のいずれかで note 存在を要求)。
    new_status = update_fields.get("status", existing.status)
    new_note = (
        update_fields["resolution_note"]
        if "resolution_note" in update_fields
        else existing.resolution_note
    )
    if new_status == "resolved" and new_note is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "resolution_note_required",
                "error_summary": "resolved status requires a resolution_note",
            },
        )

    try:
        group = await repo.update_conflict_group(
            tenant_id=tenant_id,
            project_id=project_id,
            research_task_id=research_task_id,
            group_id=group_id,
            values=update_fields,
        )
        if group is None:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_code": "conflict_group_not_found", "error_summary": "conflict group not found"},
            )
        await _audit(
            session,
            request,
            tenant_id=tenant_id,
            actor_id=owner_actor_id,
            event_type="conflict_group_updated",
            payload={
                "conflict_group_id": str(group_id),
                "research_task_id": str(research_task_id),
                "changed_fields": sorted(update_fields.keys()),
                "new_status": group.status,
            },
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "conflict_group_update_failed", "error_summary": str(exc)},
        ) from exc
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "conflict_group_update_failed",
                "error_summary": "conflict group constraint violation",
            },
        ) from exc
    return _to_read(group)


@router.post("/{group_id}/claims/{claim_id}", status_code=status.HTTP_204_NO_CONTENT)
async def assign_claim_endpoint(
    project_id: UUID,
    research_task_id: UUID,
    group_id: UUID,
    claim_id: UUID,
    request: Request,
    _active_project: None = Depends(require_active_project),  # noqa: B008
    owner_actor_id: UUID = Depends(require_project_owner),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> None:
    repo = ConflictGroupRepository(session)
    group = await repo.get_conflict_group(
        tenant_id=tenant_id,
        project_id=project_id,
        research_task_id=research_task_id,
        group_id=group_id,
    )
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "conflict_group_not_found", "error_summary": "conflict group not found"},
        )
    try:
        claim = await repo.assign_claim(
            tenant_id=tenant_id,
            project_id=project_id,
            research_task_id=research_task_id,
            group_id=group_id,
            claim_id=claim_id,
        )
        if claim is None:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_code": "claim_not_found", "error_summary": "claim not found in research task"},
            )
        await _audit(
            session,
            request,
            tenant_id=tenant_id,
            actor_id=owner_actor_id,
            event_type="conflict_group_claim_assigned",
            payload={
                "conflict_group_id": str(group_id),
                "research_task_id": str(research_task_id),
                "claim_id": str(claim_id),
            },
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "claim_assign_failed", "error_summary": "claim assignment constraint violation"},
        ) from exc


@router.delete("/{group_id}/claims/{claim_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_claim_endpoint(
    project_id: UUID,
    research_task_id: UUID,
    group_id: UUID,
    claim_id: UUID,
    request: Request,
    _active_project: None = Depends(require_active_project),  # noqa: B008
    owner_actor_id: UUID = Depends(require_project_owner),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> None:
    repo = ConflictGroupRepository(session)
    claim = await repo.unassign_claim(
        tenant_id=tenant_id,
        project_id=project_id,
        research_task_id=research_task_id,
        group_id=group_id,
        claim_id=claim_id,
    )
    if claim is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "claim_assignment_not_found",
                "error_summary": "claim is not assigned to this conflict group",
            },
        )
    await _audit(
        session,
        request,
        tenant_id=tenant_id,
        actor_id=owner_actor_id,
        event_type="conflict_group_claim_unassigned",
        payload={
            "conflict_group_id": str(group_id),
            "research_task_id": str(research_task_id),
            "claim_id": str(claim_id),
        },
    )
    await session.commit()


__all__ = ["router"]
