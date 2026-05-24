from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.db.models.project import Project
from backend.app.schemas.onboarding import (
    OnboardingDryRunPlanRequest,
    OnboardingDryRunPlanResponse,
)
from backend.app.services.onboarding.dry_run_plan import (
    OnboardingProjectContext,
    assert_onboarding_dry_run_request_has_no_raw_secret,
    build_onboarding_dry_run_plan,
)

router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])


@router.post("/dry_run_plan", response_model=OnboardingDryRunPlanResponse)
async def create_onboarding_dry_run_plan_endpoint(
    payload: Annotated[object, Body()],
    response: Response,
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> OnboardingDryRunPlanResponse:
    """Return a deterministic onboarding plan without creating workflow state."""

    response.headers["Cache-Control"] = "no-store"
    try:
        request = OnboardingDryRunPlanRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error_code": "onboarding_dry_run_invalid_schema",
                "message": "invalid onboarding dry-run request schema",
            },
        ) from exc

    try:
        assert_onboarding_dry_run_request_has_no_raw_secret(request)
        project = await _resolve_current_project(session, tenant_id=tenant_id)
        return await build_onboarding_dry_run_plan(
            session,
            project_context=OnboardingProjectContext(
                tenant_id=tenant_id,
                actor_id=actor_id,
                project_id=project.id,
                autonomy_level=project.autonomy_level,
            ),
            request=request,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "onboarding_dry_run_invalid_input",
                "message": "invalid onboarding dry-run request",
            },
        ) from exc


async def _resolve_current_project(session: AsyncSession, *, tenant_id: int) -> Project:
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
    return project


__all__ = ["router"]
