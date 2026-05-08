from __future__ import annotations

from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.policy_rule import PolicyRule
from backend.app.domain.policy.action_class import ActionClass
from backend.app.repositories.base import BaseRepository


class PolicyRuleRepository(BaseRepository[PolicyRule]):
    """Read-only repository for PolicyRule.

    F-002 (R2): policy_rules は initial policy matrix と policy_version の authority source。
    汎用 mutation API (create/update/delete) を経由した rule 変更は versioned seed
    管理を bypass するため禁止する。新 policy_version を発行する operation は
    Sprint 4 以降の policy management service / migration seed のみが行う。
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PolicyRule)

    async def get(self, tenant_id: int, id: UUID) -> PolicyRule | None:
        return await super().get(tenant_id=tenant_id, id=id)

    async def create(self, tenant_id: int, payload: dict[str, Any]) -> NoReturn:
        raise NotImplementedError(
            "PolicyRule は migration seed 経由でのみ作成。汎用 create は禁止。"
        )

    async def update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> NoReturn:
        raise NotImplementedError(
            "PolicyRule は新 policy_version 発行で扱う。汎用 update は禁止。"
        )

    async def delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError(
            "PolicyRule は append-only。汎用 delete は禁止。"
        )

    def statement_for_update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> NoReturn:
        raise NotImplementedError(
            "PolicyRule は新 policy_version 発行で扱う。statement_for_update は禁止。"
        )

    def statement_for_delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError(
            "PolicyRule は append-only。statement_for_delete は禁止。"
        )

    async def list_by_action_class(
        self,
        tenant_id: int,
        action_class: ActionClass,
        policy_version: str | None = None,
    ) -> list[PolicyRule]:
        await self._ensure_tenant_context(tenant_id)
        stmt = select(PolicyRule).where(
            PolicyRule.tenant_id == tenant_id,
            PolicyRule.action_class == action_class,
        )
        if policy_version is not None:
            stmt = stmt.where(PolicyRule.policy_version == policy_version)
        stmt = stmt.order_by(PolicyRule.created_at, PolicyRule.id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_policy_version(
        self,
        tenant_id: int,
        policy_version: str,
    ) -> list[PolicyRule]:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            select(PolicyRule)
            .where(
                PolicyRule.tenant_id == tenant_id,
                PolicyRule.policy_version == policy_version,
            )
            .order_by(PolicyRule.action_class, PolicyRule.id)
        )
        return list(result.scalars().all())


__all__ = ["PolicyRuleRepository"]

