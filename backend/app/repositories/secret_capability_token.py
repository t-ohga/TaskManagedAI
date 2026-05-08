from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.secret_capability_token import SecretCapabilityToken
from backend.app.repositories.base import BaseRepository


class SecretCapabilityTokenRepository(BaseRepository[SecretCapabilityToken]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SecretCapabilityToken)

    async def get(self, tenant_id: int, id: UUID) -> SecretCapabilityToken | None:
        return await super().get(tenant_id=tenant_id, id=id)

    async def atomic_claim(
        self,
        *,
        tenant_id: int,
        token_hash: str,
        issued_to_actor_id: UUID,
        issued_run_id: UUID | None,
        expected_request_fingerprint: str,
        requested_operation: str,
    ) -> SecretCapabilityToken:
        raise NotImplementedError("Implemented in Sprint 4 SecretBroker service")


__all__ = ["SecretCapabilityTokenRepository"]

