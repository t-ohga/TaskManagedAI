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
from backend.app.db.models.project import Project

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
