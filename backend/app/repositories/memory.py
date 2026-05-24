from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.memory_record import MemoryRecord, MemoryRetrievalArtifact
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
