"""Approval Inbox API (Sprint 3 Batch 3, BL-0036)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.actor import Actor
from backend.app.db.models.approval_request import ApprovalRequest
from backend.app.db.session import get_session
from backend.app.repositories.approval_request import ApprovalRequestRepository
from backend.app.repositories.ticket import ProjectArchivedError, TicketNotActionableError
from backend.app.services.policy.approval_active_scope import is_approval_target_actionable
from backend.app.services.policy.decision_service import ApprovalDecisionService
from backend.app.services.policy.revision_request_service import (
    ApprovalRevisionConflictError,
    ApprovalRevisionRequestService,
    ApprovalRevisionValidationError,
)

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])

ActionClassLiteral = Literal[
    "task_write",
    "repo_write",
    "pr_open",
    "secret_access",
    "merge",
    "deploy",
    "provider_call",
]
ApprovalStatusLiteral = Literal["pending", "approved", "rejected", "expired", "invalidated"]
RiskLevelLiteral = Literal["low", "medium", "high", "critical"]


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


def get_tenant_id(request: Request) -> int:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant context missing",
        )
    return tenant_id


async def get_current_actor_id(
    request: Request,
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> UUID:
    actor_reference = getattr(request.state, "actor_id", None)
    if actor_reference is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="actor context missing",
        )

    actor_ref = str(actor_reference)
    conditions = [Actor.actor_id == actor_ref]

    try:
        conditions.append(Actor.id == UUID(actor_ref))
    except ValueError:
        pass

    actor_id = await session.scalar(
        select(Actor.id)
        .where(
            Actor.tenant_id == tenant_id,
            or_(*conditions),
        )
        .limit(1)
    )
    if actor_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="actor not found",
        )
    return actor_id


class ApprovalListItem(BaseModel):
    """Approval Inbox pending list item."""

    id: UUID
    action_class: ActionClassLiteral
    resource_ref: str
    risk_level: RiskLevelLiteral
    status: ApprovalStatusLiteral
    requested_by_actor_id: UUID
    requested_at: datetime


class ApprovalDetail(BaseModel):
    """Approval Inbox detail item."""

    id: UUID
    action_class: ActionClassLiteral
    resource_ref: str
    risk_level: RiskLevelLiteral
    status: ApprovalStatusLiteral
    requested_by_actor_id: UUID
    decided_by_actor_id: UUID | None
    requested_at: datetime
    decided_at: datetime | None
    rationale: str | None
    artifact_hash: str | None
    diff_hash: str | None
    policy_version: str
    policy_pack_lock: str | None
    provider_request_fingerprint: str | None
    stale_after_event_seq: int | None = None


class ApprovalDecideRequest(BaseModel):
    """approve / reject API request body."""

    action: Literal["approve", "reject"]
    rationale: str | None = Field(default=None, max_length=2000)


class ApprovalRevisionRequestBody(BaseModel):
    """request_revision API request body."""

    rationale: str = Field(min_length=1, max_length=2000)

    @field_validator("rationale")
    @classmethod
    def rationale_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("rationale must not be blank")
        return normalized


class ApprovalRevisionResponse(BaseModel):
    """request_revision response."""

    approval: ApprovalDetail
    revision_request_id: UUID


def _to_list_item(approval: ApprovalRequest) -> ApprovalListItem:
    return ApprovalListItem(
        id=approval.id,
        action_class=approval.action_class,
        resource_ref=approval.resource_ref,
        risk_level=approval.risk_level,
        status=approval.status,
        requested_by_actor_id=approval.requested_by_actor_id,
        requested_at=approval.requested_at,
    )


def _to_detail(approval: ApprovalRequest) -> ApprovalDetail:
    return ApprovalDetail(
        id=approval.id,
        action_class=approval.action_class,
        resource_ref=approval.resource_ref,
        risk_level=approval.risk_level,
        status=approval.status,
        requested_by_actor_id=approval.requested_by_actor_id,
        decided_by_actor_id=approval.decided_by_actor_id,
        requested_at=approval.requested_at,
        decided_at=approval.decided_at,
        rationale=approval.rationale,
        artifact_hash=approval.artifact_hash,
        diff_hash=approval.diff_hash,
        policy_version=approval.policy_version,
        policy_pack_lock=approval.policy_pack_lock,
        provider_request_fingerprint=approval.provider_request_fingerprint,
        stale_after_event_seq=approval.stale_after_event_seq,
    )


@router.get("", response_model=list[ApprovalListItem])
async def list_pending_approvals(
    status_filter: Annotated[ApprovalStatusLiteral | None, Query(alias="status")] = None,
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[ApprovalListItem]:
    repo = ApprovalRequestRepository(session)
    # Mac 実機検証 C-8 fix: 旧版は status="pending" ハードコードで `?status=approved` 等を無視していた。
    # frontend approvals page は 5 status を filter UI で出すため、optional status query を honor する。
    # 未指定時は inbox default の "pending"。enum 外は FastAPI が 422 で reject (ApprovalStatusLiteral)。
    approvals = await repo.list_by_status(tenant_id=tenant_id, status=status_filter or "pending")
    # ADR-00037 R18 (Codex adversarial): soft-deleted ticket / archived project に bound な stale approval を
    # inbox から隠す (全 read path active-scope)。承認は decide guard で既に block されるが、列挙でも
    # 露出させない。restore で再び現れる。非 ticket resource_ref の approval は対象外。
    # 全 status に active-scope を適用 (decided 履歴も work-queue 一貫性で stale を隠す、restore で再表示)。
    items: list[ApprovalListItem] = []
    for approval in approvals:
        if await is_approval_target_actionable(
            session, tenant_id=tenant_id, resource_ref=approval.resource_ref
        ):
            items.append(_to_list_item(approval))
    return items


@router.get("/{approval_id}", response_model=ApprovalDetail)
async def get_approval_detail(
    approval_id: UUID,
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ApprovalDetail:
    repo = ApprovalRequestRepository(session)
    approval = await repo.get(tenant_id=tenant_id, id=approval_id)
    if approval is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="approval not found")
    # ADR-00037 R18: soft-deleted ticket / archived project に bound な approval は detail からも隠す
    # (restore で再表示)。
    if not await is_approval_target_actionable(
        session, tenant_id=tenant_id, resource_ref=approval.resource_ref
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="approval not found")
    return _to_detail(approval)


@router.post("/{approval_id}/decide", response_model=ApprovalDetail, status_code=200)
async def decide_approval(
    approval_id: UUID,
    body: ApprovalDecideRequest,
    actor_id: UUID = Depends(get_current_actor_id),
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ApprovalDetail:
    repo = ApprovalRequestRepository(session)
    approval = await repo.get(tenant_id=tenant_id, id=approval_id)
    if approval is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="approval not found")

    service = ApprovalDecisionService(session)
    try:
        if body.action == "approve":
            updated = await service.approve(
                tenant_id=tenant_id,
                approval=approval,
                decided_by_actor_id=actor_id,
                rationale=body.rationale,
            )
        else:
            updated = await service.reject(
                tenant_id=tenant_id,
                approval=approval,
                decided_by_actor_id=actor_id,
                rationale=body.rationale,
            )
    except (TicketNotActionableError, ProjectArchivedError) as exc:
        # ADR-00037 R18: stale (削除済 ticket / archived project bound) approval の approve は 409。
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await session.commit()
    return _to_detail(updated)


@router.post(
    "/{approval_id}/request_revision",
    response_model=ApprovalRevisionResponse,
    status_code=200,
)
async def request_approval_revision(
    approval_id: UUID,
    body: ApprovalRevisionRequestBody,
    actor_id: UUID = Depends(get_current_actor_id),
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ApprovalRevisionResponse:
    repo = ApprovalRequestRepository(session)
    approval = await repo.get(tenant_id=tenant_id, id=approval_id)
    if approval is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="approval not found")

    service = ApprovalRevisionRequestService(session)
    try:
        result = await service.request_revision(
            tenant_id=tenant_id,
            approval=approval,
            requested_by_actor_id=actor_id,
            rationale=body.rationale,
        )
    except ApprovalRevisionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ApprovalRevisionValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    await session.commit()
    return ApprovalRevisionResponse(
        approval=_to_detail(result.approval),
        revision_request_id=result.revision_request.id,
    )


__all__ = [
    "ActionClassLiteral",
    "ApprovalDecideRequest",
    "ApprovalDetail",
    "ApprovalListItem",
    "ApprovalRevisionRequestBody",
    "ApprovalRevisionResponse",
    "ApprovalStatusLiteral",
    "RiskLevelLiteral",
    "get_current_actor_id",
    "get_db_session",
    "get_tenant_id",
    "router",
]

