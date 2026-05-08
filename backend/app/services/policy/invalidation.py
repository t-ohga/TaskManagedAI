"""Approval stale invalidation service (Sprint 3 Batch 2, BL-0033, ADR-00009).

Detects five stale sources and transitions existing approvals to `invalidated`:
- artifact_hash change
- diff_hash change
- policy_version change
- policy_pack_lock change
- provider_request_fingerprint change
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import assert_tenant_context, get_tenant_context, set_tenant_context
from backend.app.db.models.approval_request import ApprovalRequest


@dataclass(frozen=True)
class StaleCheckPayload:
    """New verification input compared against stored approval values."""

    artifact_hash: str | None = None
    diff_hash: str | None = None
    policy_version: str | None = None
    policy_pack_lock: str | None = None
    provider_request_fingerprint: str | None = None


@dataclass(frozen=True)
class StaleCheckReason:
    """Reason that triggered stale invalidation."""

    field: str
    old: str | None
    new: str | None


class ApprovalStaleInvalidationService:
    """Detect and invalidate stale approval requests."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def detect_stale(
        self,
        approval: ApprovalRequest,
        payload: StaleCheckPayload,
    ) -> list[StaleCheckReason]:
        reasons: list[StaleCheckReason] = []
        for field in (
            "artifact_hash",
            "diff_hash",
            "policy_version",
            "policy_pack_lock",
            "provider_request_fingerprint",
        ):
            new_value = getattr(payload, field)
            old_value = getattr(approval, field)
            if new_value is None and old_value is None:
                continue
            if new_value != old_value:
                reasons.append(StaleCheckReason(field=field, old=old_value, new=new_value))
        return reasons

    async def invalidate_if_stale(
        self,
        tenant_id: int,
        approval: ApprovalRequest,
        payload: StaleCheckPayload,
    ) -> list[StaleCheckReason]:
        await self._ensure_tenant_context(tenant_id)

        if approval.status in {"invalidated", "expired"}:
            return []

        reasons = await self.detect_stale(approval, payload)
        if not reasons:
            return []

        result = await self.session.execute(
            update(ApprovalRequest)
            .where(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.id == approval.id,
                ApprovalRequest.status.in_(["pending", "approved", "rejected"]),
            )
            .values(status="invalidated")
            .returning(ApprovalRequest.id)
        )
        updated_ids = result.scalars().all()
        if not updated_ids:
            return []

        await self.session.refresh(approval)
        return reasons

    async def _ensure_tenant_context(self, tenant_id: int) -> None:
        if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
            raise ValueError("tenant_id must be a positive integer.")
        current = await get_tenant_context(self.session)
        if current is None:
            await set_tenant_context(self.session, tenant_id)
        await assert_tenant_context(self.session, tenant_id)


__all__ = [
    "ApprovalStaleInvalidationService",
    "StaleCheckPayload",
    "StaleCheckReason",
]

