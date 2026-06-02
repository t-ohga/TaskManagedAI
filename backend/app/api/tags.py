"""ADR-00044 (A-5): ticket タグ/ラベル REST endpoint。

全て project-scoped (`/api/v1/projects/{project_id}/...`)。mutation は
``maybe_require_cli_capability("task_write")`` + actor/tenant 必須、read は task_list/task_show。
secret scan / active-project guard / 使用中 delete guard は repository 境界 (TagRepository) に集約。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.api.dependencies.api_capability_token import maybe_require_cli_capability
from backend.app.db.models.tag import Tag
from backend.app.repositories.tag import (
    TagColorInvalidError,
    TagInUseError,
    TagNameConflictError,
    TagNotFoundError,
    TagRepository,
)
from backend.app.repositories.ticket import (
    ProjectArchivedError,
    ProjectNotFoundError,
    TicketNotActionableError,
)
from backend.app.schemas.tag import (
    TagCreate,
    TagListResponse,
    TagRead,
    TagUpdate,
    TicketTagAttach,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}/tags", tags=["tags"])
ticket_tags_router = APIRouter(
    prefix="/api/v1/projects/{project_id}/tickets/{ticket_id}/tags", tags=["tags"]
)


_KNOWN_CONSTRAINTS = (
    "tags_uq_tenant_project_name",
    "ticket_tags_pkey",
    "ticket_tags_tag_fkey",
    "ticket_tags_ticket_fkey",
    "tags_ck_name_length",
    "tags_ck_color",
)


def _integrity_constraint(exc: IntegrityError) -> str:
    """IntegrityError から違反した constraint 名を抽出する (asyncpg の constraint_name 優先)。"""
    orig = getattr(exc, "orig", None)
    name = getattr(orig, "constraint_name", None)
    if name:
        return str(name)
    text = str(orig or exc)
    for cn in _KNOWN_CONSTRAINTS:
        if cn in text:
            return cn
    return ""


def _map_integrity_error(exc: IntegrityError, *, op: str) -> HTTPException:
    """race / raw 経路で DB 制約が発火した場合を documented な 409/422/404 に写像する
    (Codex code-review R2 HIGH-1。500 への degrade を防ぐ)。"""
    cn = _integrity_constraint(exc)
    if cn == "tags_uq_tenant_project_name":
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="a tag with this name already exists in this project.",
        )
    if cn == "ticket_tags_tag_fkey":
        if op == "delete":
            return HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail={"error": "tag_in_use"}
            )
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="tag not found for project."
        )
    if "_ck_" in cn:
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="tag value violates a database constraint.",
        )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="tag operation conflicts with the current state.",
    )


def _to_read(tag: Tag) -> TagRead:
    return TagRead.model_validate(tag)


def _map_tag_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ProjectArchivedError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, ProjectNotFoundError):
        # 存在しない path project_id → 404 (既存 import/bulk-delete の契約と整合、Codex R3 HIGH)
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, TicketNotActionableError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, TagNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, TagNameConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, TagInUseError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "tag_in_use", "attached_count": exc.attached_count},
        )
    if isinstance(exc, (TagColorInvalidError, ValueError)):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    raise exc


@router.get("", response_model=TagListResponse)
async def list_tags(
    project_id: UUID,
    _cli_capability: object = Depends(maybe_require_cli_capability("task_list")),  # noqa: B008
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> TagListResponse:
    repo = TagRepository(session)
    tags = await repo.list_tags(tenant_id, project_id)
    return TagListResponse(items=[_to_read(t) for t in tags])


@router.post("", response_model=TagRead, status_code=status.HTTP_201_CREATED)
async def create_tag(
    project_id: UUID,
    body: TagCreate,
    _cli_capability: object = Depends(maybe_require_cli_capability("task_write")),  # noqa: B008
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> TagRead:
    repo = TagRepository(session)
    try:
        tag = await repo.create_tag(
            tenant_id, project_id, name=body.name, color=body.color, actor_id=actor_id
        )
    except IntegrityError as exc:
        await session.rollback()
        raise _map_integrity_error(exc, op="create") from exc
    except Exception as exc:  # noqa: BLE001 - 既知 domain error を HTTP に写像
        raise _map_tag_error(exc) from exc
    await session.commit()
    return _to_read(tag)


@router.patch("/{tag_id}", response_model=TagRead)
async def update_tag(
    project_id: UUID,
    tag_id: UUID,
    body: TagUpdate,
    _cli_capability: object = Depends(maybe_require_cli_capability("task_write")),  # noqa: B008
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> TagRead:
    repo = TagRepository(session)
    try:
        tag = await repo.rename_tag(
            tenant_id, project_id, tag_id, name=body.name, color=body.color
        )
    except IntegrityError as exc:
        await session.rollback()
        raise _map_integrity_error(exc, op="rename") from exc
    except Exception as exc:  # noqa: BLE001
        raise _map_tag_error(exc) from exc
    await session.commit()
    return _to_read(tag)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    project_id: UUID,
    tag_id: UUID,
    _cli_capability: object = Depends(maybe_require_cli_capability("task_write")),  # noqa: B008
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> None:
    repo = TagRepository(session)
    try:
        await repo.delete_tag(tenant_id, project_id, tag_id, actor_id=actor_id)
    except IntegrityError as exc:
        await session.rollback()
        raise _map_integrity_error(exc, op="delete") from exc
    except Exception as exc:  # noqa: BLE001
        raise _map_tag_error(exc) from exc
    await session.commit()


@ticket_tags_router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def attach_tag(
    project_id: UUID,
    ticket_id: UUID,
    body: TicketTagAttach,
    _cli_capability: object = Depends(maybe_require_cli_capability("task_write")),  # noqa: B008
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> None:
    repo = TagRepository(session)
    try:
        if body.tag_id is not None:
            await repo.attach_tag(tenant_id, project_id, ticket_id, body.tag_id)
        elif body.name is None or body.color is None:
            # schema validator (TicketTagAttach._exactly_one_mode) が両在を保証するため通常到達しない
            # defensive narrowing。
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="新規タグには name と color の両方が必要です。",
            )
        else:
            # 新規 tag 作成 + 付与を同一 transaction で実行 (atomic、Codex R5 HIGH)。
            await repo.create_and_attach_tag(
                tenant_id,
                project_id,
                ticket_id,
                name=body.name,
                color=body.color,
                actor_id=actor_id,
            )
    except IntegrityError as exc:
        await session.rollback()
        # concurrent attach が同 row を作った場合は idempotent (既に付与済) として 204
        if _integrity_constraint(exc) == "ticket_tags_pkey":
            return None
        raise _map_integrity_error(exc, op="attach") from exc
    except Exception as exc:  # noqa: BLE001
        raise _map_tag_error(exc) from exc
    await session.commit()


@ticket_tags_router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def detach_tag(
    project_id: UUID,
    ticket_id: UUID,
    tag_id: UUID,
    _cli_capability: object = Depends(maybe_require_cli_capability("task_write")),  # noqa: B008
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> None:
    repo = TagRepository(session)
    try:
        await repo.detach_tag(tenant_id, project_id, ticket_id, tag_id)
    except Exception as exc:  # noqa: BLE001
        raise _map_tag_error(exc) from exc
    await session.commit()


__all__ = ["router", "ticket_tags_router"]
