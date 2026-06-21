"""Superintendent emergency-stop endpoints (SP-PHASE1 B3、ADR-00048 §C)。

human-only な「全 AI 即停止」安全弁の FastAPI surface。MCP には **露出しない** (human-only、ADR-00048
選択肢 1 却下理由: MCP は AI agent surface で human-only を enforce する自然な仕組みがない)。CLI/UI は
本 endpoint の client になる (B6)。

- ``POST /api/v1/superintendent/emergency-stop``       : engage (latch 設定 + active run block)。
- ``POST /api/v1/superintendent/emergency-stop/clear`` : clear (generation CAS + run resume)。
- ``GET  /api/v1/superintendent/emergency-stop``       : status (engaged / generation / engaged_at)。

operator gate (``require_emergency_stop_operator``) で authenticated + human + owner を fail-closed
enforce。response は raw secret / pid / token を含まない (latch metadata + 件数のみ)。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import get_db_session, get_tenant_id
from backend.app.api.dependencies.emergency_stop_operator import (
    require_emergency_stop_operator,
)
from backend.app.services.superintendent.emergency_stop import (
    EmergencyStopService,
    EmergencyStopServiceError,
    NotEngagedError,
    StaleGenerationError,
)

router = APIRouter(prefix="/api/v1/superintendent", tags=["superintendent"])


class EmergencyStopEngageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 操作理由 (任意)。raw secret は service 側 assert_no_raw_secret で防御。
    reason: str | None = Field(default=None, max_length=1000)


class EmergencyStopClearRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # B-3 generation CAS: 操作の基にした active latch generation。不一致なら 409 (stale clear reject)。
    expected_generation: int = Field(ge=1)


class EmergencyStopStatusResponse(BaseModel):
    """latch status (raw secret / pid / token 非含)。"""

    model_config = ConfigDict(populate_by_name=True)

    engaged: bool
    generation: int | None
    engaged_at: datetime | None


class EmergencyStopEngageResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    engaged: bool
    generation: int
    engaged_at: datetime
    blocked_run_count: int
    already_engaged: bool


class EmergencyStopClearResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    cleared: bool
    generation: int
    cleared_at: datetime
    resumed_run_count: int


@router.post("/emergency-stop", response_model=EmergencyStopEngageResponse)
async def engage_emergency_stop_endpoint(
    payload: EmergencyStopEngageRequest,
    operator_actor_id: UUID = Depends(require_emergency_stop_operator),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> EmergencyStopEngageResponse:
    """emergency-stop latch を engage し active run を block する (human-only)。

    冪等: 既 active latch があれば no-op で同一 latch を返す (``already_engaged=true``)。commit は本
    endpoint で行い、advisory lock を engage→block→commit まで保持する。
    """
    service = EmergencyStopService(session)
    try:
        result = await service.engage(
            tenant_id=tenant_id,
            operator_actor_id=operator_actor_id,
            reason=payload.reason,
        )
    except EmergencyStopServiceError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    await session.commit()
    return EmergencyStopEngageResponse(
        engaged=result.engaged,
        generation=result.generation,
        engaged_at=result.engaged_at,
        blocked_run_count=result.blocked_run_count,
        already_engaged=result.already_engaged,
    )


@router.post("/emergency-stop/clear", response_model=EmergencyStopClearResponse)
async def clear_emergency_stop_endpoint(
    payload: EmergencyStopClearRequest,
    operator_actor_id: UUID = Depends(require_emergency_stop_operator),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> EmergencyStopClearResponse:
    """emergency-stop latch を clear し block 中 run を pre_stop_status へ復元する (human-only、CAS)。

    ``expected_generation`` 不一致は 409 (stale clear reject)、active latch 不在も 409。復元は一律
    running ではなく pre_stop_status 復元表に従う (gate skip 防止)。
    """
    service = EmergencyStopService(session)
    try:
        result = await service.clear(
            tenant_id=tenant_id,
            operator_actor_id=operator_actor_id,
            expected_generation=payload.expected_generation,
        )
    except (StaleGenerationError, NotEngagedError) as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except EmergencyStopServiceError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    await session.commit()
    return EmergencyStopClearResponse(
        cleared=result.cleared,
        generation=result.generation,
        cleared_at=result.cleared_at,
        resumed_run_count=result.resumed_run_count,
    )


@router.get("/emergency-stop", response_model=EmergencyStopStatusResponse)
async def get_emergency_stop_status_endpoint(
    operator_actor_id: UUID = Depends(require_emergency_stop_operator),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> EmergencyStopStatusResponse:
    """active emergency-stop latch の status を返す (human-only、raw secret / pid 非含)。"""
    latch = await EmergencyStopService(session).get_active(tenant_id)
    if latch is None:
        return EmergencyStopStatusResponse(
            engaged=False, generation=None, engaged_at=None
        )
    return EmergencyStopStatusResponse(
        engaged=True,
        generation=latch.generation,
        engaged_at=latch.engaged_at,
    )


__all__ = ["router"]
