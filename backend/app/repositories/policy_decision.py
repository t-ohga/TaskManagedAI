from __future__ import annotations

from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.policy_decision import PolicyDecision
from backend.app.domain.policy.action_class import ActionClass
from backend.app.repositories.base import BaseRepository


class PolicyDecisionRepository(BaseRepository[PolicyDecision]):
    """Append-only repository for PolicyDecision."""

    def __init__(self, session: AsyncSession, tenant_id: int | None = None) -> None:
        super().__init__(session, PolicyDecision, tenant_id=tenant_id)

    async def append(self, tenant_id: int, **payload: Any) -> PolicyDecision:
        return await super().create(tenant_id=tenant_id, payload=payload)

    async def update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> NoReturn:
        raise NotImplementedError(
            "PolicyDecision is append-only. Generic update is forbidden."
        )

    async def delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError(
            "PolicyDecision is append-only. Generic delete is forbidden."
        )

    def statement_for_update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> NoReturn:
        raise NotImplementedError(
            "PolicyDecision is append-only. statement_for_update is forbidden."
        )

    def statement_for_delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError(
            "PolicyDecision is append-only. statement_for_delete is forbidden."
        )

    async def list_by_action_class(
        self,
        tenant_id: int,
        action_class: ActionClass,
    ) -> list[PolicyDecision]:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            select(PolicyDecision)
            .where(
                PolicyDecision.tenant_id == tenant_id,
                PolicyDecision.action_class == action_class,
            )
            .order_by(PolicyDecision.created_at, PolicyDecision.id)
        )
        return list(result.scalars().all())

    async def list_by_approval_request(
        self,
        tenant_id: int,
        approval_request_id: UUID,
    ) -> list[PolicyDecision]:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            select(PolicyDecision)
            .where(
                PolicyDecision.tenant_id == tenant_id,
                PolicyDecision.approval_request_id == approval_request_id,
            )
            .order_by(PolicyDecision.created_at, PolicyDecision.id)
        )
        return list(result.scalars().all())


__all__ = ["PolicyDecisionRepository"]

