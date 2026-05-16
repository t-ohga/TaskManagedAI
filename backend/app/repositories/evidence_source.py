from __future__ import annotations

import builtins
from typing import Any, NoReturn, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.evidence_source import EvidenceSource
from backend.app.repositories.base import BaseRepository


class EvidenceSourceRepository(BaseRepository[EvidenceSource]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, EvidenceSource)

    async def get(self, tenant_id: int, id: UUID) -> EvidenceSource | None:
        raise NotImplementedError("Use get_evidence_source_by_id(...).")

    async def list(self, tenant_id: int) -> builtins.list[EvidenceSource]:
        raise NotImplementedError("Use list_evidence_sources_by_tenant(...).")

    async def create(self, tenant_id: int, payload: dict[str, Any]) -> EvidenceSource:
        raise NotImplementedError("evidence_sources are read-only in Sprint 10 batch 4.")

    async def update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> EvidenceSource | None:
        raise NotImplementedError("evidence_sources are read-only in Sprint 10 batch 4.")

    async def delete(self, tenant_id: int, id: UUID) -> int:
        raise NotImplementedError("evidence_sources are read-only in Sprint 10 batch 4.")

    def statement_for_get(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Use tenant-scoped read methods.")

    def statement_for_list(self, tenant_id: int) -> NoReturn:
        raise NotImplementedError("Use tenant-scoped read methods.")

    def statement_for_update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> NoReturn:
        raise NotImplementedError("evidence_sources are read-only in Sprint 10 batch 4.")

    def statement_for_delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("evidence_sources are read-only in Sprint 10 batch 4.")

    async def list_evidence_sources_by_tenant(
        self,
        tenant_id: int,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[builtins.list[EvidenceSource], int]:
        self._require_page_bounds(limit=limit, offset=offset)
        await self._ensure_tenant_context(tenant_id)

        total = await self.session.scalar(
            select(func.count())
            .select_from(EvidenceSource)
            .where(EvidenceSource.tenant_id == tenant_id)
        )
        result = await self.session.execute(
            select(EvidenceSource)
            .where(EvidenceSource.tenant_id == tenant_id)
            .order_by(EvidenceSource.created_at.desc(), EvidenceSource.id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)

    async def get_evidence_source_by_id(
        self,
        tenant_id: int,
        evidence_source_id: UUID,
    ) -> EvidenceSource | None:
        await self._ensure_tenant_context(tenant_id)
        stmt = select(EvidenceSource).where(
            EvidenceSource.tenant_id == tenant_id,
            EvidenceSource.id == evidence_source_id,
        )
        return cast(EvidenceSource | None, await self.session.scalar(stmt))

    @staticmethod
    def _require_page_bounds(*, limit: int, offset: int) -> None:
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500.")
        if offset < 0:
            raise ValueError("offset must be nonnegative.")


async def list_evidence_sources_by_tenant(
    session: AsyncSession,
    tenant_id: int,
    *,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[EvidenceSource], int]:
    return await EvidenceSourceRepository(session).list_evidence_sources_by_tenant(
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
    )


async def get_evidence_source_by_id(
    session: AsyncSession,
    tenant_id: int,
    evidence_source_id: UUID,
) -> EvidenceSource | None:
    return await EvidenceSourceRepository(session).get_evidence_source_by_id(
        tenant_id=tenant_id,
        evidence_source_id=evidence_source_id,
    )


__all__ = [
    "EvidenceSourceRepository",
    "get_evidence_source_by_id",
    "list_evidence_sources_by_tenant",
]
