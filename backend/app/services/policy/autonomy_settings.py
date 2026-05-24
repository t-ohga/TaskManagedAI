from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.project import Project
from backend.app.domain.policy.autonomy_level import AutonomyLevel
from backend.app.services.policy.autonomy_profile_resolver import (
    resolve_autonomy_policy_profile,
)


class ProjectAutonomySettingsService:
    """Server-owned autonomy settings writer.

    Generic ``ProjectRepository`` rejects both ``autonomy_level`` and
    ``policy_profile`` payloads. This service is the narrow settings surface
    that accepts only caller-visible ``autonomy_level`` and resolves
    ``policy_profile`` internally.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def update_autonomy_level(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        autonomy_level: AutonomyLevel,
    ) -> Project | None:
        await self._ensure_tenant_context(tenant_id)
        resolution = resolve_autonomy_policy_profile(
            autonomy_level,
            runtime_enabled=False,
        )
        project = await self.session.scalar(
            select(Project).where(
                Project.tenant_id == tenant_id,
                Project.id == project_id,
            )
        )
        if project is None:
            return None

        project.autonomy_level = resolution.autonomy_level
        project.policy_profile = resolution.policy_profile
        await self.session.flush()
        await self.session.refresh(project)
        return project

    async def _ensure_tenant_context(self, tenant_id: int) -> None:
        if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
            raise ValueError("tenant_id must be a positive integer.")
        current = await get_tenant_context(self.session)
        if current is None:
            await set_tenant_context(self.session, tenant_id)
        await assert_tenant_context(self.session, tenant_id)


__all__ = ["ProjectAutonomySettingsService"]
