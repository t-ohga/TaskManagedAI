from __future__ import annotations

import builtins
from typing import Any, NoReturn, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.research_task import ResearchTask
from backend.app.repositories.base import BaseRepository


class ResearchTaskRepository(BaseRepository[ResearchTask]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ResearchTask)

    async def get(self, tenant_id: int, id: UUID) -> ResearchTask | None:
        raise NotImplementedError("Use get_research_task_by_id(...).")

    async def list(self, tenant_id: int) -> builtins.list[ResearchTask]:
        raise NotImplementedError("Use list_research_tasks_by_project(...).")

    async def create(self, tenant_id: int, payload: dict[str, Any]) -> ResearchTask:
        raise NotImplementedError("research_tasks are read-only in Sprint 10 batch 4.")

    async def update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> ResearchTask | None:
        raise NotImplementedError("research_tasks are read-only in Sprint 10 batch 4.")

    async def delete(self, tenant_id: int, id: UUID) -> int:
        raise NotImplementedError("research_tasks are read-only in Sprint 10 batch 4.")

    def statement_for_get(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Use project-scoped methods.")

    def statement_for_list(self, tenant_id: int) -> NoReturn:
        raise NotImplementedError("Use project-scoped methods.")

    def statement_for_update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> NoReturn:
        raise NotImplementedError("research_tasks are read-only in Sprint 10 batch 4.")

    def statement_for_delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("research_tasks are read-only in Sprint 10 batch 4.")

    async def list_research_tasks_by_project(
        self,
        tenant_id: int,
        project_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[builtins.list[ResearchTask], int]:
        self._require_page_bounds(limit=limit, offset=offset)
        await self._ensure_tenant_context(tenant_id)

        total = await self.session.scalar(
            select(func.count())
            .select_from(ResearchTask)
            .where(
                ResearchTask.tenant_id == tenant_id,
                ResearchTask.project_id == project_id,
            )
        )
        result = await self.session.execute(
            select(ResearchTask)
            .where(
                ResearchTask.tenant_id == tenant_id,
                ResearchTask.project_id == project_id,
            )
            .order_by(ResearchTask.created_at.desc(), ResearchTask.id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)

    async def get_research_task_by_id(
        self,
        tenant_id: int,
        project_id: UUID,
        research_task_id: UUID,
    ) -> ResearchTask | None:
        await self._ensure_tenant_context(tenant_id)
        stmt = select(ResearchTask).where(
            ResearchTask.tenant_id == tenant_id,
            ResearchTask.project_id == project_id,
            ResearchTask.id == research_task_id,
        )
        return cast(ResearchTask | None, await self.session.scalar(stmt))

    @staticmethod
    def _require_page_bounds(*, limit: int, offset: int) -> None:
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200.")
        if offset < 0:
            raise ValueError("offset must be nonnegative.")


async def list_research_tasks_by_project(
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ResearchTask], int]:
    return await ResearchTaskRepository(session).list_research_tasks_by_project(
        tenant_id=tenant_id,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )


async def get_research_task_by_id(
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    research_task_id: UUID,
) -> ResearchTask | None:
    return await ResearchTaskRepository(session).get_research_task_by_id(
        tenant_id=tenant_id,
        project_id=project_id,
        research_task_id=research_task_id,
    )


__all__ = [
    "ResearchTaskRepository",
    "get_research_task_by_id",
    "list_research_tasks_by_project",
]
