from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.project import Project
from backend.app.db.models.workspace import Workspace
from backend.app.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Project)

    async def get_in_workspace(
        self,
        tenant_id: int,
        workspace_id: UUID,
        project_id: UUID,
    ) -> Project | None:
        await self._ensure_tenant_context(tenant_id)
        stmt = select(Project).where(
            Project.tenant_id == tenant_id,
            Project.workspace_id == workspace_id,
            Project.id == project_id,
        )
        return cast(Project | None, await self.session.scalar(stmt))

    async def workspace_exists(self, tenant_id: int, workspace_id: UUID) -> bool:
        await self._ensure_tenant_context(tenant_id)
        workspace_id_result = await self.session.scalar(
            select(Workspace.id).where(
                Workspace.tenant_id == tenant_id,
                Workspace.id == workspace_id,
            )
        )
        return workspace_id_result is not None


__all__ = ["ProjectRepository"]

