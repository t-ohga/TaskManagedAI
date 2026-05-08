"""Approval decision service (Sprint 3 Batch 3, BL-0035/0036).

approved / rejected transitions are centralized here so every decision records
decided_by_actor_id + decided_at and passes SelfApprovalGuardService.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.approval_request import ApprovalRequest
from backend.app.services.policy.self_approval_guard import SelfApprovalGuardService


class ApprovalDecisionService:
    """Centralize approved / rejected approval transitions.

    - decided_by_actor_id / decided_at are mandatory
    - SelfApprovalGuardService always runs
    - only status='pending' can transition
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def approve(
        self,
        *,
        tenant_id: int,
        approval: ApprovalRequest,
        decided_by_actor_id: UUID,
        rationale: str | None = None,
        decided_at: datetime | None = None,
    ) -> ApprovalRequest:
        """Transition approval to approved."""

        return await self._decide(
            tenant_id=tenant_id,
            approval=approval,
            new_status="approved",
            decided_by_actor_id=decided_by_actor_id,
            rationale=rationale,
            decided_at=decided_at,
        )

    async def reject(
        self,
        *,
        tenant_id: int,
        approval: ApprovalRequest,
        decided_by_actor_id: UUID,
        rationale: str | None = None,
        decided_at: datetime | None = None,
    ) -> ApprovalRequest:
        """Transition approval to rejected."""

        return await self._decide(
            tenant_id=tenant_id,
            approval=approval,
            new_status="rejected",
            decided_by_actor_id=decided_by_actor_id,
            rationale=rationale,
            decided_at=decided_at,
        )

    async def _decide(
        self,
        *,
        tenant_id: int,
        approval: ApprovalRequest,
        new_status: str,
        decided_by_actor_id: UUID,
        rationale: str | None,
        decided_at: datetime | None,
    ) -> ApprovalRequest:
        await self._ensure_tenant_context(tenant_id)

        if approval.status != "pending":
            raise ValueError(
                f"approval {approval.id} cannot transition to {new_status!r}: "
                f"current status is {approval.status!r}, expected 'pending'"
            )

        guard = SelfApprovalGuardService()
        await guard.assert_not_delegated_self_approval(
            session=self.session,
            approval=approval,
            decided_by_actor_id=decided_by_actor_id,
        )

        actual_decided_at = decided_at if decided_at is not None else datetime.now(tz=UTC)

        result = await self.session.execute(
            update(ApprovalRequest)
            .where(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.id == approval.id,
                ApprovalRequest.status == "pending",
            )
            .values(
                status=new_status,
                decided_by_actor_id=decided_by_actor_id,
                decided_at=actual_decided_at,
                rationale=rationale,
            )
            .returning(ApprovalRequest.id)
        )
        updated_ids = result.scalars().all()
        if not updated_ids:
            raise ValueError(
                f"approval {approval.id} could not be updated: "
                "row may have been concurrently modified or status changed from 'pending'"
            )

        await self.session.refresh(approval)
        return approval

    async def _ensure_tenant_context(self, tenant_id: int) -> None:
        if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
            raise ValueError("tenant_id must be a positive integer.")
        current = await get_tenant_context(self.session)
        if current is None:
            await set_tenant_context(self.session, tenant_id)
        await assert_tenant_context(self.session, tenant_id)


__all__ = ["ApprovalDecisionService"]

