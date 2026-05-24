"""Approval request_revision service.

The approval status enum stays unchanged. Requesting revision invalidates the
old pending approval and records a separate revision request snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.approval_request import ApprovalRequest
from backend.app.db.models.approval_revision_request import ApprovalRevisionRequest
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.repositories.approval_revision_request import (
    ApprovalRevisionRequestRepository,
)
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.services.notifications.approval_notifier import ApprovalNotifierService
from backend.app.services.policy.self_approval_guard import SelfApprovalGuardService


class ApprovalRevisionConflictError(ValueError):
    """Raised when the approval cannot receive a revision request."""


class ApprovalRevisionValidationError(ValueError):
    """Raised when request_revision input violates the contract."""


@dataclass(frozen=True)
class ApprovalRevisionResult:
    approval: ApprovalRequest
    revision_request: ApprovalRevisionRequest


class ApprovalRevisionRequestService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def request_revision(
        self,
        *,
        tenant_id: int,
        approval: ApprovalRequest,
        requested_by_actor_id: UUID,
        rationale: str,
    ) -> ApprovalRevisionResult:
        await self._ensure_tenant_context(tenant_id)

        if approval.status != "pending":
            raise ApprovalRevisionConflictError(
                f"approval {approval.id} cannot request revision: "
                f"current status is {approval.status!r}, expected 'pending'"
            )

        normalized_rationale = self._validate_rationale(rationale)

        guard = SelfApprovalGuardService()
        try:
            await guard.assert_not_delegated_same_human(
                session=self.session,
                approval=approval,
                decided_by_actor_id=requested_by_actor_id,
                action_description="approval request_revision",
            )
        except ValueError as exc:
            raise ApprovalRevisionConflictError(str(exc)) from exc

        revision_repo = ApprovalRevisionRequestRepository(self.session)
        existing_open = await revision_repo.get_open_by_approval(
            tenant_id=tenant_id,
            approval_request_id=approval.id,
        )
        if existing_open is not None:
            raise ApprovalRevisionConflictError(
                f"approval {approval.id} already has an open revision request "
                f"{existing_open.id}"
            )

        result = await self.session.execute(
            update(ApprovalRequest)
            .where(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.id == approval.id,
                ApprovalRequest.status == "pending",
            )
            .values(status="invalidated")
            .returning(ApprovalRequest.id)
        )
        updated_ids = result.scalars().all()
        if not updated_ids:
            raise ApprovalRevisionConflictError(
                f"approval {approval.id} could not be invalidated: "
                "row may have been concurrently modified or status changed from 'pending'"
            )

        revision_request = await revision_repo.create_revision_request(
            tenant_id=tenant_id,
            approval_request_id=approval.id,
            requested_by_actor_id=requested_by_actor_id,
            rationale=normalized_rationale,
            artifact_hash=approval.artifact_hash,
            diff_hash=approval.diff_hash,
            policy_version=approval.policy_version,
            policy_pack_lock=approval.policy_pack_lock,
            provider_request_fingerprint=approval.provider_request_fingerprint,
            stale_after_event_seq=approval.stale_after_event_seq,
            metadata={"rls_ready": True},
        )

        await AuditEventRepository(self.session).append(
            tenant_id=tenant_id,
            event_type="approval_revision_requested",
            actor_id=requested_by_actor_id,
            payload=self._audit_payload(approval=approval, revision_request=revision_request),
        )

        await ApprovalNotifierService(self.session).notify_approval_revision_requested(
            tenant_id=tenant_id,
            approval_id=approval.id,
            revision_request_id=revision_request.id,
            recipient_actor_id=approval.requested_by_actor_id,
        )

        await self.session.refresh(approval)
        await self.session.refresh(revision_request)
        return ApprovalRevisionResult(approval=approval, revision_request=revision_request)

    @staticmethod
    def _validate_rationale(rationale: str) -> str:
        normalized = rationale.strip()
        if not normalized:
            raise ApprovalRevisionValidationError("revision rationale must not be empty")
        if len(normalized) > 2000:
            raise ApprovalRevisionValidationError(
                "revision rationale must be at most 2000 characters"
            )
        try:
            assert_no_raw_secret({"rationale": normalized}, path="$request_revision")
        except ValueError as exc:
            raise ApprovalRevisionValidationError(
                "revision rationale failed raw-secret scan"
            ) from exc
        return normalized

    @staticmethod
    def _audit_payload(
        *,
        approval: ApprovalRequest,
        revision_request: ApprovalRevisionRequest,
    ) -> dict[str, object]:
        return {
            "approval_id": str(approval.id),
            "revision_request_id": str(revision_request.id),
            "action_class": approval.action_class,
            "resource_ref": approval.resource_ref,
            "risk_level": approval.risk_level,
            "decision_packet": {
                "artifact_hash_present": approval.artifact_hash is not None,
                "diff_hash_present": approval.diff_hash is not None,
                "policy_pack_lock_present": approval.policy_pack_lock is not None,
                "provider_request_fingerprint_present": (
                    approval.provider_request_fingerprint is not None
                ),
                "stale_after_event_seq_present": approval.stale_after_event_seq is not None,
            },
        }

    async def _ensure_tenant_context(self, tenant_id: int) -> None:
        if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
            raise ValueError("tenant_id must be a positive integer.")
        current = await get_tenant_context(self.session)
        if current is None:
            await set_tenant_context(self.session, tenant_id)
        await assert_tenant_context(self.session, tenant_id)


__all__ = [
    "ApprovalRevisionConflictError",
    "ApprovalRevisionRequestService",
    "ApprovalRevisionResult",
    "ApprovalRevisionValidationError",
]
