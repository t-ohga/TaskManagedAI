"""Current actor / current project resolution endpoint (SP-012-11.1 BL-TCU-013).

Codex PR #121 R1 F-PR121-002/003 (P1) carry-over fix:
DEFAULT_PROJECT_ID hardcode を frontend から排除し、session 経由 current
project を resolve する path を提供。session の actor が属する tenant の
first project (created_at 順) を current project として返す。

multi-tenant + multi-project への将来拡張は workspace / actor membership
table 追加後に拡張 (現状は single-tenant single-project の simplification)。

invariant:
- server-owned-boundary §1: tenant_id / actor_id は session 経由 resolve、
  caller-supplied 経路なし
- response: raw secret なし (project_id / slug / name / workspace_id / tenant_id のみ)
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.api.dependencies.api_capability_token import maybe_require_cli_capability
from backend.app.db.models.project import Project
from backend.app.domain.policy.autonomy_level import AutonomyLevel
from backend.app.services.policy.autonomy_settings import ProjectAutonomySettingsService

router = APIRouter(prefix="/api/v1/me", tags=["me"])


class CurrentProjectResponse(BaseModel):
    """Current actor's resolved project.

    SP-012-11.1 BL-TCU-013: single-project mode で actor の tenant 内 first project
    を返す。multi-project 化は将来の `actor_project_membership` table 追加で拡張。
    """

    model_config = ConfigDict(populate_by_name=True)

    tenant_id: int
    project_id: UUID
    workspace_id: UUID
    slug: str
    name: str


class ProjectListItem(BaseModel):
    """Read-only project metadata safe for Settings UI."""

    model_config = ConfigDict(populate_by_name=True)

    tenant_id: int
    project_id: UUID
    workspace_id: UUID
    slug: str
    name: str
    status: str
    policy_profile: str
    autonomy_level: AutonomyLevel


class ProjectListResponse(BaseModel):
    current_project_id: UUID
    projects: list[ProjectListItem]


class ProjectAutonomySettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    autonomy_level: AutonomyLevel


def _to_project_item(project: Project) -> ProjectListItem:
    return ProjectListItem(
        tenant_id=project.tenant_id,
        project_id=project.id,
        workspace_id=project.workspace_id,
        slug=project.slug,
        name=project.name,
        status=project.status,
        policy_profile=project.policy_profile,
        autonomy_level=project.autonomy_level,
    )


@router.get("/current_project", response_model=CurrentProjectResponse)
async def get_current_project_endpoint(
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> CurrentProjectResponse:
    """Resolve current project for the authenticated actor.

    Single-project mode: return tenant 内 first project (order by created_at)。
    """
    stmt = (
        select(Project)
        .where(Project.tenant_id == tenant_id)
        .order_by(Project.created_at, Project.slug)
        .limit(1)
    )
    project = (await session.execute(stmt)).scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no project found for tenant",
        )

    return CurrentProjectResponse(
        tenant_id=tenant_id,
        project_id=project.id,
        workspace_id=project.workspace_id,
        slug=project.slug,
        name=project.name,
    )


@router.get("/projects", response_model=ProjectListResponse)
async def list_current_actor_projects_endpoint(
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ProjectListResponse:
    """List current tenant projects for the authenticated actor.

    P0.1 still uses single-tenant membership semantics. Project switching is
    read-only in the UI until an actor-project membership table exists.
    """
    result = await session.execute(
        select(Project)
        .where(Project.tenant_id == tenant_id)
        .order_by(Project.created_at, Project.slug)
    )
    projects = list(result.scalars())
    if not projects:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no project found for tenant",
        )

    return ProjectListResponse(
        current_project_id=projects[0].id,
        projects=[_to_project_item(project) for project in projects],
    )


@router.patch("/projects/{project_id}/autonomy", response_model=ProjectListItem)
async def update_project_autonomy_endpoint(
    project_id: UUID,
    payload: ProjectAutonomySettingsUpdate,
    _cli_capability: object = Depends(maybe_require_cli_capability("task_write")),  # noqa: B008
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ProjectListItem:
    """Update caller-visible autonomy_level only.

    ``policy_profile`` remains server-owned and is resolved by
    ProjectAutonomySettingsService. The request schema forbids extra fields, so
    callers cannot smuggle a policy_profile setter into this surface.
    """

    project = await ProjectAutonomySettingsService(session).update_autonomy_level(
        tenant_id=tenant_id,
        project_id=project_id,
        autonomy_level=payload.autonomy_level,
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found for tenant",
        )
    await session.commit()
    return _to_project_item(project)
