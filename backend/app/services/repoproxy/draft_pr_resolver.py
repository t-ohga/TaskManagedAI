"""DB-backed Draft PR binding resolver for RepoProxy."""

from __future__ import annotations

from typing import cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import assert_tenant_context, get_tenant_context, set_tenant_context
from backend.app.db.models.approval_request import ApprovalRequest
from backend.app.db.models.context_snapshot import ContextSnapshot
from backend.app.services.repoproxy.repoproxy import (
    DraftPRApprovalState,
    DraftPRBinding,
    DraftPRRequest,
    DraftPRSnapshotState,
    RepoProxyDenyReason,
    build_draft_pr_request_from_server_state,
)

_INVALIDATING_DENY_REASONS = frozenset(
    {
        RepoProxyDenyReason.ARTIFACT_HASH_MISMATCH,
        RepoProxyDenyReason.POLICY_VERSION_MISMATCH,
        RepoProxyDenyReason.PROVIDER_FINGERPRINT_MISMATCH,
        RepoProxyDenyReason.REPO_STATE_MISMATCH,
    }
)


class DbDraftPRRequestResolver:
    """Resolve Draft PR bindings from server-owned DB state.

    The caller supplies only ``DraftPRBinding`` IDs. This resolver loads the
    ApprovalRequest and latest ContextSnapshot under the same tenant/run scope,
    then delegates all 4-binding checks to the pure RepoProxy builder.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve_draft_pr_request(
        self,
        binding: DraftPRBinding,
    ) -> DraftPRRequest | RepoProxyDenyReason:
        await self._ensure_tenant_context(binding.tenant_id)

        approval = await self._load_approval(binding)
        if approval is None:
            return RepoProxyDenyReason.APPROVAL_NOT_GRANTED

        snapshot = await self._load_latest_snapshot(binding)
        if snapshot is None:
            await self._invalidate_approved(approval, RepoProxyDenyReason.REPO_STATE_MISMATCH)
            return RepoProxyDenyReason.REPO_STATE_MISMATCH

        result = build_draft_pr_request_from_server_state(
            approval=DraftPRApprovalState(
                id=approval.id,
                run_id=approval.run_id,
                status=approval.status,
                action_class=approval.action_class,
                resource_ref=approval.resource_ref,
                diff_hash=approval.diff_hash,
                policy_version=approval.policy_version,
                provider_request_fingerprint=approval.provider_request_fingerprint,
            ),
            snapshot=DraftPRSnapshotState(
                run_id=snapshot.run_id,
                policy_version=snapshot.policy_version,
                repo_state=snapshot.repo_state,
                provider_request_fingerprint=snapshot.provider_request_fingerprint,
            ),
        )
        if isinstance(result, RepoProxyDenyReason):
            await self._invalidate_approved(approval, result)
        return result

    async def _load_approval(self, binding: DraftPRBinding) -> ApprovalRequest | None:
        return cast(
            ApprovalRequest | None,
            await self.session.scalar(
                select(ApprovalRequest).where(
                    ApprovalRequest.tenant_id == binding.tenant_id,
                    ApprovalRequest.id == binding.approval_id,
                    ApprovalRequest.run_id == binding.agent_run_id,
                )
            ),
        )

    async def _load_latest_snapshot(
        self,
        binding: DraftPRBinding,
    ) -> ContextSnapshot | None:
        return cast(
            ContextSnapshot | None,
            await self.session.scalar(
                select(ContextSnapshot)
                .where(
                    ContextSnapshot.tenant_id == binding.tenant_id,
                    ContextSnapshot.run_id == binding.agent_run_id,
                )
                .order_by(ContextSnapshot.created_at.desc(), ContextSnapshot.id.desc())
                .limit(1)
            )
        )

    async def _invalidate_approved(
        self,
        approval: ApprovalRequest,
        deny_reason: RepoProxyDenyReason,
    ) -> None:
        if approval.status != "approved" or deny_reason not in _INVALIDATING_DENY_REASONS:
            return

        result = await self.session.execute(
            update(ApprovalRequest)
            .where(
                ApprovalRequest.tenant_id == approval.tenant_id,
                ApprovalRequest.id == approval.id,
                ApprovalRequest.status == "approved",
            )
            .values(status="invalidated")
            .returning(ApprovalRequest.id)
        )
        if result.scalar_one_or_none() is not None:
            await self.session.refresh(approval)

    async def _ensure_tenant_context(self, tenant_id: int) -> None:
        if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
            raise ValueError("tenant_id must be a positive integer.")
        current = await get_tenant_context(self.session)
        if current is None:
            await set_tenant_context(self.session, tenant_id)
        await assert_tenant_context(self.session, tenant_id)


__all__ = ["DbDraftPRRequestResolver"]
