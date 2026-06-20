from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.secret_ref import (
    SecretMaterialState,
    SecretRef,
    SecretRefScope,
    SecretRefStatus,
)
from backend.app.repositories.base import BaseRepository
from backend.app.services.secrets.uri_pattern import build_secret_uri


class SecretRefRepository(BaseRepository[SecretRef]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SecretRef)

    async def get(self, tenant_id: int, id: UUID) -> SecretRef | None:
        return await super().get(tenant_id=tenant_id, id=id)

    async def create_metadata(
        self,
        *,
        tenant_id: int,
        backend: str,
        scope: SecretRefScope,
        name: str,
        version: str,
        status: SecretRefStatus,
        owner_actor_id: UUID,
        allowed_consumers: list[str],
        allowed_operations: list[str],
        metadata: dict[str, Any] | None = None,
        material_state: SecretMaterialState = "writing",
        rotated_from_id: UUID | None = None,
    ) -> SecretRef:
        """metadata-only の secret_ref row を insert する (server-owned URI 組立)。

        secret_uri は ``build_secret_uri`` で構造化 component から server が組み立てる (caller が任意
        URI 文字列を渡さない、components_match CHECK と整合)。raw secret は受け取らない・保存しない。
        commit は caller (crash-safe lifecycle を所有する SecretRegistrationService) が制御する。
        """
        await self._ensure_tenant_context(tenant_id)
        secret_uri = build_secret_uri(backend, scope, name, version)
        row = SecretRef(
            id=uuid4(),
            tenant_id=tenant_id,
            secret_uri=secret_uri,
            scope=scope,
            name=name,
            version=version,
            status=status,
            owner_actor_id=owner_actor_id,
            allowed_consumers=list(allowed_consumers),
            allowed_operations=list(allowed_operations),
            metadata_={"rls_ready": True, **(metadata or {})},
            material_state=material_state,
            rotated_from_id=rotated_from_id,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_all(self, tenant_id: int) -> list[SecretRef]:
        """tenant 内の全 secret_refs を安定順序 (scope, name, version) で返す。

        R-3 (ADR-00036) の read-only インベントリ用。tenant-scoped。raw secret は model に
        存在せず (DB CHECK)、本 method は metadata row を返すのみ。
        """
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            select(SecretRef)
            .where(SecretRef.tenant_id == tenant_id)
            .order_by(SecretRef.scope, SecretRef.name, SecretRef.version)
        )
        return list(result.scalars().all())

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

