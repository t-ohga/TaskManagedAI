from __future__ import annotations

from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Update

from backend.app.db.models.approval_request import ApprovalRequest
from backend.app.repositories.base import BaseRepository

_APPROVAL_REQUEST_MUTABLE_FIELDS = frozenset(
    {
        "artifact_hash",
        "diff_hash",
        "policy_version",
        "policy_pack_lock",
        "provider_request_fingerprint",
        "stale_after_event_seq",
        "metadata_",
    }
)

_UPDATE_FORBIDDEN_FIELDS = frozenset(
    {
        "id",
        "tenant_id",
        "run_id",
        "action_class",
        "resource_ref",
        "risk_level",
        "requested_by_actor_id",
        "requested_at",
        "status",
        "decided_by_actor_id",
        "decided_at",
        "rationale",
    }
)


class ApprovalRequestRepository(BaseRepository[ApprovalRequest]):
    def __init__(self, session: AsyncSession, tenant_id: int | None = None) -> None:
        super().__init__(session, ApprovalRequest, tenant_id=tenant_id)

    async def get_by_id(self, tenant_id: int, id: UUID) -> ApprovalRequest | None:
        return await super().get(tenant_id=tenant_id, id=id)

    async def list_pending(self, tenant_id: int) -> list[ApprovalRequest]:
        return await self.list_by_status(tenant_id=tenant_id, status="pending")

    async def list_by_status(self, tenant_id: int, status: str) -> list[ApprovalRequest]:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.status == status,
            )
            .order_by(ApprovalRequest.requested_at, ApprovalRequest.id)
        )
        return list(result.scalars().all())

    async def list_by_run(self, tenant_id: int, run_id: UUID) -> list[ApprovalRequest]:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.run_id == run_id,
            )
            .order_by(ApprovalRequest.requested_at, ApprovalRequest.id)
        )
        return list(result.scalars().all())

    async def create_pending_approval(
        self,
        *,
        tenant_id: int,
        action_class: str,
        resource_ref: str,
        risk_level: str,
        requested_by_actor_id: UUID,
        recipient_actor_id: UUID,
        policy_version: str,
        artifact_hash: str | None = None,
        diff_hash: str | None = None,
        policy_pack_lock: str | None = None,
        provider_request_fingerprint: str | None = None,
        stale_after_event_seq: int | None = None,
        run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        """Create a pending approval and append its notification in the same transaction.

        F-003 (R2): BL-0036/0037 must_ship requires approval pending creation
        to notify the receiver with an unread in-app notification. The caller owns
        transaction commit / rollback; this method only flushes rows.
        """

        from backend.app.services.agent_runtime.shadow_guard import assert_run_id_not_shadow
        from backend.app.services.notifications.approval_notifier import ApprovalNotifierService

        await self._ensure_tenant_context(tenant_id)

        # SP-029 (ADR-00055 §設計制約 3): shadow run は approval を起動できない。
        # approval は repo_write / pr_open / runner mutation の前提 gate なので、
        # ここで fail-closed に拒否すれば downstream の mutating 経路が transitively
        # 封鎖される (orchestrator stage skip と二重防御)。run 非紐付 (run_id=None) の
        # ticket-level approval は対象外。
        await assert_run_id_not_shadow(
            self.session,
            tenant_id=tenant_id,
            run_id=run_id,
            operation="approval_request_create",
        )

        approval = ApprovalRequest(
            tenant_id=tenant_id,
            action_class=action_class,
            resource_ref=resource_ref,
            risk_level=risk_level,
            status="pending",
            requested_by_actor_id=requested_by_actor_id,
            policy_version=policy_version,
            artifact_hash=artifact_hash,
            diff_hash=diff_hash,
            policy_pack_lock=policy_pack_lock,
            provider_request_fingerprint=provider_request_fingerprint,
            stale_after_event_seq=stale_after_event_seq,
            run_id=run_id,
            metadata_=metadata or {"rls_ready": True},
        )
        self.session.add(approval)
        await self.session.flush()

        notifier = ApprovalNotifierService(self.session)
        await notifier.notify_approval_pending(
            tenant_id=tenant_id,
            approval_id=approval.id,
            recipient_actor_id=recipient_actor_id,
            action_class=action_class,
            resource_ref=resource_ref,
            risk_level=risk_level,
        )

        return approval

    def statement_for_update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> Update:
        data = self._payload_for_approval_update(tenant_id, id, payload)
        return (
            update(ApprovalRequest)
            .where(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.id == id,
            )
            .values(**data)
            .returning(ApprovalRequest)
        )

    async def update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> ApprovalRequest | None:
        """Update mutable approval request evidence fields.

        F-001 (R2): delete is forbidden; approval_requests are append-only.
        F-002 (R2): status / decided_* / rationale changes must go through
        ApprovalDecisionService. This generic update only permits evidence fields
        used by stale invalidation and policy re-check flows.
        """

        self._reject_forbidden_update_fields(payload)
        return await super().update(tenant_id=tenant_id, id=id, payload=payload)

    async def delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError(
            "ApprovalRequest は append-only / status 遷移のみ。物理削除は禁止。"
        )

    def statement_for_delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError(
            "ApprovalRequest は append-only / status 遷移のみ。statement_for_delete は禁止。"
        )

    @classmethod
    def _payload_for_approval_update(
        cls,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        cls._reject_forbidden_update_fields(payload)
        data = cls._payload_for_update(tenant_id, id, payload)
        unexpected_fields = set(data) - _APPROVAL_REQUEST_MUTABLE_FIELDS
        if unexpected_fields:
            field_list = ", ".join(sorted(unexpected_fields))
            raise ValueError(f"approval request update fields are not mutable: {field_list}")
        return data

    @staticmethod
    def _reject_forbidden_update_fields(payload: dict[str, Any]) -> None:
        forbidden_keys = sorted(set(payload) & _UPDATE_FORBIDDEN_FIELDS)
        if forbidden_keys:
            raise ValueError(
                f"ApprovalRequest.update cannot modify protected fields {forbidden_keys}; "
                "use ApprovalDecisionService for status / decision changes "
                "or ApprovalStaleInvalidationService for invalidation."
            )


__all__ = ["ApprovalRequestRepository"]
