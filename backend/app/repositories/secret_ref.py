from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.secret_ref import SecretRef, SecretRefScope, SecretRefStatus
from backend.app.repositories.base import BaseRepository


class SecretRefRepository(BaseRepository[SecretRef]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SecretRef)

    async def get(self, tenant_id: int, id: UUID) -> SecretRef | None:
        return await super().get(tenant_id=tenant_id, id=id)

    async def list_by_status(
        self,
        tenant_id: int,
        status: SecretRefStatus,
    ) -> list[SecretRef]:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            select(SecretRef)
            .where(
                SecretRef.tenant_id == tenant_id,
                SecretRef.status == status,
            )
            .order_by(SecretRef.created_at, SecretRef.id)
        )
        return list(result.scalars().all())

    async def assert_active(
        self,
        tenant_id: int,
        scope: SecretRefScope,
        name: str,
    ) -> SecretRef:
        await self._ensure_tenant_context(tenant_id)
        secret_ref = await self.session.scalar(
            select(SecretRef).where(
                SecretRef.tenant_id == tenant_id,
                SecretRef.scope == scope,
                SecretRef.name == name,
                SecretRef.status == "active",
            )
        )
        if secret_ref is None:
            raise LookupError("Active secret_ref is not registered for this tenant, scope, and name.")
        return secret_ref


__all__ = ["SecretRefRepository"]

