from __future__ import annotations

from typing import Any, NoReturn, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select, Update

from backend.app.db.models.approval_revision_request import ApprovalRevisionRequest
from backend.app.repositories.base import BaseRepository

_REVISION_REQUEST_MUTABLE_FIELDS = frozenset({"superseded_by_approval_request_id", "metadata_"})

_UPDATE_FORBIDDEN_FIELDS = frozenset(
    {
        "id",
        "tenant_id",
        "approval_request_id",
        "requested_by_actor_id",
        "rationale",
        "artifact_hash",
        "diff_hash",
        "policy_version",
        "policy_pack_lock",
        "provider_request_fingerprint",
        "stale_after_event_seq",
        "created_at",
    }
)


class ApprovalRevisionRequestRepository(BaseRepository[ApprovalRevisionRequest]):
    def __init__(self, session: AsyncSession, tenant_id: int | None = None) -> None:
        super().__init__(session, ApprovalRevisionRequest, tenant_id=tenant_id)

    def statement_for_open_by_approval(
        self,
        tenant_id: int,
        approval_request_id: UUID,
    ) -> Select[tuple[ApprovalRevisionRequest]]:
        self._require_tenant_id(tenant_id)
        return select(ApprovalRevisionRequest).where(
            ApprovalRevisionRequest.tenant_id == tenant_id,
            ApprovalRevisionRequest.approval_request_id == approval_request_id,
            ApprovalRevisionRequest.superseded_by_approval_request_id.is_(None),
        )

    async def get_open_by_approval(
        self,
        tenant_id: int,
        approval_request_id: UUID,
    ) -> ApprovalRevisionRequest | None:
        await self._ensure_tenant_context(tenant_id)
        return cast(
            ApprovalRevisionRequest | None,
            await self.session.scalar(
                self.statement_for_open_by_approval(tenant_id, approval_request_id)
            ),
        )

    async def create_revision_request(
        self,
        *,
        tenant_id: int,
        approval_request_id: UUID,
        requested_by_actor_id: UUID,
        rationale: str,
        artifact_hash: str | None,
        diff_hash: str | None,
        policy_version: str,
        policy_pack_lock: str | None,
        provider_request_fingerprint: str | None,
        stale_after_event_seq: int | None,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRevisionRequest:
        await self._ensure_tenant_context(tenant_id)
        revision = ApprovalRevisionRequest(
            tenant_id=tenant_id,
            approval_request_id=approval_request_id,
            requested_by_actor_id=requested_by_actor_id,
            rationale=rationale,
            artifact_hash=artifact_hash,
            diff_hash=diff_hash,
            policy_version=policy_version,
            policy_pack_lock=policy_pack_lock,
            provider_request_fingerprint=provider_request_fingerprint,
            stale_after_event_seq=stale_after_event_seq,
            metadata_=metadata or {"rls_ready": True},
        )
        self.session.add(revision)
        await self.session.flush()
        return revision

    def statement_for_update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> Update:
        data = self._payload_for_revision_update(tenant_id, id, payload)
        return (
            update(ApprovalRevisionRequest)
            .where(
                ApprovalRevisionRequest.tenant_id == tenant_id,
                ApprovalRevisionRequest.id == id,
            )
            .values(**data)
            .returning(ApprovalRevisionRequest)
        )

    async def update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> ApprovalRevisionRequest | None:
        self._reject_forbidden_update_fields(payload)
        return await super().update(tenant_id=tenant_id, id=id, payload=payload)

    async def delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("ApprovalRevisionRequest は audit history。物理削除は禁止。")

    def statement_for_delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError(
            "ApprovalRevisionRequest は audit history。statement_for_delete は禁止。"
        )

    @classmethod
    def _payload_for_revision_update(
        cls,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        cls._reject_forbidden_update_fields(payload)
        data = cls._payload_for_update(tenant_id, id, payload)
        unexpected_fields = set(data) - _REVISION_REQUEST_MUTABLE_FIELDS
        if unexpected_fields:
            field_list = ", ".join(sorted(unexpected_fields))
            raise ValueError(f"approval revision request fields are not mutable: {field_list}")
        return data

    @staticmethod
    def _reject_forbidden_update_fields(payload: dict[str, Any]) -> None:
        forbidden_keys = sorted(set(payload) & _UPDATE_FORBIDDEN_FIELDS)
        if forbidden_keys:
            raise ValueError(
                "ApprovalRevisionRequest.update cannot modify protected fields "
                f"{forbidden_keys}; only supersession metadata can change."
            )


__all__ = ["ApprovalRevisionRequestRepository"]
