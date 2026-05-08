from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.tenant import Tenant


class TenantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: int) -> Tenant | None:
        self._require_tenant_id(tenant_id)
        return await self.session.get(Tenant, tenant_id)

    async def create(self, tenant_id: int, payload: dict[str, Any]) -> Tenant:
        self._require_tenant_id(tenant_id)
        data = dict(payload)

        if "id" in data and data["id"] != tenant_id:
            raise ValueError("payload id must match tenant_id.")

        data["id"] = tenant_id
        if "metadata" in data and "metadata_" not in data:
            data["metadata_"] = data.pop("metadata")

        tenant = Tenant(**data)
        self.session.add(tenant)
        await self.session.flush()
        return tenant

    @staticmethod
    def _require_tenant_id(tenant_id: int) -> None:
        if tenant_id < 1:
            raise ValueError("tenant_id must be a positive integer.")


__all__ = ["TenantRepository"]

