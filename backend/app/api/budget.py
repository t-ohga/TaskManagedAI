"""Budget global kill-switch endpoints (SP-PHASE1 B6、ADR-00048 §A-8).

budget 起因の **コスト緊急停止** (global_kill_switch) を engage / clear / query する operator surface。
emergency-stop latch (human 即時全停止、``superintendent.py``) とは **別目的** だが、両者は autonomy /
budget choke point で **OR 評価** される (どちらか engaged なら新規活動を deny。OR 配線は B5a の policy
engine で済、本 endpoint は budget 側 flag を operator が toggle する surface)。

- ``POST /api/v1/budget/global-kill-switch``       : engage (global budget の kill switch を ON)。
- ``POST /api/v1/budget/global-kill-switch/clear`` : clear (OFF)。
- ``GET  /api/v1/budget/global-kill-switch``       : status (engaged / budget_id)。

owner gate (``_require_authenticated_owner``、emergency-stop と同 owner boundary) で authenticated +
human + configured owner を fail-closed enforce。MCP には露出しない (AI agent surface に kill switch を
出さない)。response は raw secret / token を含まない (budget metadata + flag のみ)。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import get_db_session, get_tenant_id
from backend.app.api.dependencies.emergency_stop_operator import (
    require_emergency_stop_operator,
)
from backend.app.repositories.budget import BudgetRepository

router = APIRouter(prefix="/api/v1/budget", tags=["budget"])


class GlobalKillSwitchStatusResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    engaged: bool
    budget_id: str | None


class GlobalKillSwitchMutationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    engaged: bool
    budget_id: str


@router.post("/global-kill-switch", response_model=GlobalKillSwitchMutationResponse)
async def engage_global_kill_switch_endpoint(
    operator_actor_id: UUID = Depends(require_emergency_stop_operator),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> GlobalKillSwitchMutationResponse:
    """budget global_kill_switch を engage する (human-only、コスト緊急停止)。

    active な global budget が無ければ flag だけ持つ minimal global budget を find-or-create する。
    choke point の OR 評価 (B5a) により、engage 後は autonomy auto-allow が deny される。
    """
    budget = await BudgetRepository(session).set_global_kill_switch(
        tenant_id=tenant_id,
        engaged=True,
        actor_id=operator_actor_id,
    )
    await session.commit()
    return GlobalKillSwitchMutationResponse(
        engaged=True,
        budget_id=str(budget.id),
    )


@router.post("/global-kill-switch/clear", response_model=GlobalKillSwitchMutationResponse)
async def clear_global_kill_switch_endpoint(
    operator_actor_id: UUID = Depends(require_emergency_stop_operator),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> GlobalKillSwitchMutationResponse:
    """budget global_kill_switch を clear する (human-only)。"""
    budget = await BudgetRepository(session).set_global_kill_switch(
        tenant_id=tenant_id,
        engaged=False,
        actor_id=operator_actor_id,
    )
    await session.commit()
    return GlobalKillSwitchMutationResponse(
        engaged=False,
        budget_id=str(budget.id),
    )


@router.get("/global-kill-switch", response_model=GlobalKillSwitchStatusResponse)
async def get_global_kill_switch_status_endpoint(
    operator_actor_id: UUID = Depends(require_emergency_stop_operator),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> GlobalKillSwitchStatusResponse:
    """active global budget の kill switch status を返す (human-only)。"""
    budget = await BudgetRepository(session).get_active_global(tenant_id)
    if budget is None:
        return GlobalKillSwitchStatusResponse(engaged=False, budget_id=None)
    return GlobalKillSwitchStatusResponse(
        engaged=budget.global_kill_switch is True,
        budget_id=str(budget.id),
    )


__all__ = ["router"]
