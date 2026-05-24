"""Approval Inbox API (Sprint 3 Batch 3, BL-0036)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.actor import Actor
from backend.app.db.models.approval_request import ApprovalRequest
from backend.app.db.session import get_session
from backend.app.repositories.approval_request import ApprovalRequestRepository
from backend.app.services.policy.decision_service import ApprovalDecisionService

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
    stale_after_event_seq: int | None


class ApprovalDecideRequest(BaseModel):
    """approve / reject API request body."""

    action: Literal["approve", "reject"]
    rationale: str | None = Field(default=None, max_length=2000)


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
    status_filter: ApprovalStatusLiteral = Query(default="pending", alias="status"),
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[ApprovalListItem]:
    repo = ApprovalRequestRepository(session)
    approvals = await repo.list_by_status(tenant_id=tenant_id, status=status_filter)
    return [_to_list_item(approval) for approval in approvals]


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
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await session.commit()
    return _to_detail(updated)


__all__ = [
    "ActionClassLiteral",
    "ApprovalDecideRequest",
    "ApprovalDetail",
    "ApprovalListItem",
    "ApprovalStatusLiteral",
    "RiskLevelLiteral",
    "get_current_actor_id",
    "get_db_session",
    "get_tenant_id",
    "router",
]
