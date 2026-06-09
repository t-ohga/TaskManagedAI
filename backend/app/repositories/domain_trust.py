"""SP-032 (ADR-00052): domain_trust_registry repository (tenant-scoped)。

domain は正規化済みの値を service から受け取る (repository は正規化しない)。rationale は persist 前に
secret scan。unique (tenant_id, domain) violation は IntegrityError として API 層で 409 にマップ。
"""

from __future__ import annotations

import builtins
from typing import Any, NoReturn, cast
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.domain_trust import DomainTrustRegistry, TrustTier
from backend.app.repositories.base import BaseRepository
from backend.app.services.security.secret_text_scan import assert_no_secret_in_text


class DomainTrustRepository(BaseRepository[DomainTrustRegistry]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, DomainTrustRegistry)

    # --- generic CRUD は server-owned 正規化 / scan を bypass するため block ---
    async def create(self, tenant_id: int, payload: dict[str, Any]) -> DomainTrustRegistry:
        raise NotImplementedError("Use create_domain_trust(...).")

    async def update(
        self, tenant_id: int, id: UUID, payload: dict[str, Any]
    ) -> DomainTrustRegistry | None:
        raise NotImplementedError("Use update_domain_trust(...).")

    def statement_for_update(self, tenant_id: int, id: UUID, payload: dict[str, Any]) -> NoReturn:
        raise NotImplementedError("Use update_domain_trust(...).")

    async def create_domain_trust(
        self,
        *,
        tenant_id: int,
        domain: str,
        trust_tier: TrustTier,
        rationale: str | None,
        created_by_actor_id: UUID,
    ) -> DomainTrustRegistry:
        await self._ensure_tenant_context(tenant_id)
        if rationale is not None:
            assert_no_secret_in_text(rationale, field="rationale")
        entry = DomainTrustRegistry(
            tenant_id=tenant_id,
            domain=domain,
            trust_tier=trust_tier,
            rationale=rationale,
            created_by_actor_id=created_by_actor_id,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def get_domain_trust(
        self, *, tenant_id: int, entry_id: UUID
    ) -> DomainTrustRegistry | None:
        await self._ensure_tenant_context(tenant_id)
        stmt = select(DomainTrustRegistry).where(
            DomainTrustRegistry.tenant_id == tenant_id,
            DomainTrustRegistry.id == entry_id,
        )
        return cast("DomainTrustRegistry | None", await self.session.scalar(stmt))

    async def list_domain_trust(self, *, tenant_id: int) -> builtins.list[DomainTrustRegistry]:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            select(DomainTrustRegistry)
            .where(DomainTrustRegistry.tenant_id == tenant_id)
            .order_by(DomainTrustRegistry.domain)
        )
        return list(result.scalars().all())

    async def get_by_domains(
        self, *, tenant_id: int, domains: builtins.list[str]
    ) -> dict[str, DomainTrustRegistry]:
        """正規化済み domain list から {domain: entry} を一括解決 (read-side enrichment)。"""
        await self._ensure_tenant_context(tenant_id)
        if not domains:
            return {}
        result = await self.session.execute(
            select(DomainTrustRegistry).where(
                DomainTrustRegistry.tenant_id == tenant_id,
                DomainTrustRegistry.domain.in_(domains),
            )
        )
        return {entry.domain: entry for entry in result.scalars().all()}

    async def update_domain_trust(
        self,
        *,
        tenant_id: int,
        entry_id: UUID,
        values: dict[str, Any],
    ) -> DomainTrustRegistry | None:
        """trust_tier / rationale の部分更新 (``values`` は server で組み立てる、domain は immutable)。"""
        await self._ensure_tenant_context(tenant_id)
        if "rationale" in values and isinstance(values["rationale"], str):
            assert_no_secret_in_text(values["rationale"], field="rationale")
        if not values:
            return await self.get_domain_trust(tenant_id=tenant_id, entry_id=entry_id)
        result = await self.session.execute(
            update(DomainTrustRegistry)
            .where(
                DomainTrustRegistry.tenant_id == tenant_id,
                DomainTrustRegistry.id == entry_id,
            )
            .values(**values)
            .returning(DomainTrustRegistry)
        )
        return result.scalar_one_or_none()

    async def delete_domain_trust(self, *, tenant_id: int, entry_id: UUID) -> bool:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            delete(DomainTrustRegistry)
            .where(
                DomainTrustRegistry.tenant_id == tenant_id,
                DomainTrustRegistry.id == entry_id,
            )
            .returning(DomainTrustRegistry.id)
        )
        return result.scalar_one_or_none() is not None


__all__ = ["DomainTrustRepository"]
