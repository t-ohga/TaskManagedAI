from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.project import Project
from backend.app.db.models.workspace import Workspace
from backend.app.repositories.base import BaseRepository

_SERVER_OWNED_POLICY_PROFILE_MESSAGE = (
    "policy_profile is server-owned and cannot be supplied by project callers."
)
_CALLER_SUPPLIED_AUTONOMY_LEVEL_MESSAGE = (
    "autonomy_level must use the autonomy settings service and cannot be supplied "
    "through generic project repository payloads."
)


class ProjectRepository(BaseRepository[Project]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Project)

    async def create(self, tenant_id: int, payload: dict[str, Any]) -> Project:
        self._reject_caller_supplied_policy_controls(payload)
        return await super().create(tenant_id, payload)

    async def update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> Project | None:
        self._reject_caller_supplied_policy_controls(payload)
        return await super().update(tenant_id, id, payload)

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

    @staticmethod
    def _reject_caller_supplied_policy_controls(payload: dict[str, Any]) -> None:
        if "policy_profile" in payload:
            raise ValueError(_SERVER_OWNED_POLICY_PROFILE_MESSAGE)
        if "autonomy_level" in payload:
            raise ValueError(_CALLER_SUPPLIED_AUTONOMY_LEVEL_MESSAGE)


__all__ = ["ProjectRepository"]
