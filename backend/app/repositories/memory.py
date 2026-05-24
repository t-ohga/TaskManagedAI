from __future__ import annotations

from datetime import datetime
from typing import NoReturn
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.memory_record import MemoryRecord, MemoryRetrievalArtifact
from backend.app.domain.memory.record_kind import MemoryRecordKind
from backend.app.repositories.base import BaseRepository
from backend.app.schemas.memory import MemoryRecordCreate, MemoryRetrievalArtifactCreate


class MemoryRecordRepository(BaseRepository[MemoryRecord]):
    def __init__(self, session: AsyncSession, tenant_id: int | None = None) -> None:
        super().__init__(session, MemoryRecord, tenant_id=tenant_id)

    async def create_memory_record(
        self,
        *,
        tenant_id: int,
        payload: MemoryRecordCreate,
    ) -> MemoryRecord:
        await self._ensure_tenant_context(tenant_id)
        record = MemoryRecord(tenant_id=tenant_id, **payload.model_dump())
        self.session.add(record)
        await self.session.flush()
        return record

    async def list_active_for_retrieval(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        now: datetime,
        limit: int,
        memory_record_ids: tuple[UUID, ...] = (),
        record_kinds: tuple[MemoryRecordKind, ...] = (),
    ) -> list[MemoryRecord]:
        await self._ensure_tenant_context(tenant_id)
        stmt = (
            sa.select(MemoryRecord)
            .where(
                MemoryRecord.tenant_id == tenant_id,
                MemoryRecord.project_id == project_id,
                MemoryRecord.archived_at.is_(None),
                MemoryRecord.retention_until > now,
            )
            .order_by(MemoryRecord.created_at.desc(), MemoryRecord.id)
            .limit(limit)
        )
        if memory_record_ids:
            stmt = stmt.where(MemoryRecord.id.in_(memory_record_ids))
        if record_kinds:
            stmt = stmt.where(MemoryRecord.record_kind.in_(record_kinds))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, object],
    ) -> NoReturn:
        raise NotImplementedError("Memory records are append-only. update is prohibited.")


class MemoryRetrievalArtifactRepository(BaseRepository[MemoryRetrievalArtifact]):
    def __init__(self, session: AsyncSession, tenant_id: int | None = None) -> None:
        super().__init__(session, MemoryRetrievalArtifact, tenant_id=tenant_id)

    async def create_retrieval_artifact(
        self,
        *,
        tenant_id: int,
        payload: MemoryRetrievalArtifactCreate,
    ) -> MemoryRetrievalArtifact:
        await self._ensure_tenant_context(tenant_id)
        artifact = MemoryRetrievalArtifact(tenant_id=tenant_id, **payload.model_dump())
        self.session.add(artifact)
        await self.session.flush()
        return artifact

    async def update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, object],
    ) -> NoReturn:
        raise NotImplementedError(
            "Memory retrieval artifacts are append-only. update is prohibited."
        )


__all__ = [
    "MemoryRecordRepository",
    "MemoryRetrievalArtifactRepository",
]
