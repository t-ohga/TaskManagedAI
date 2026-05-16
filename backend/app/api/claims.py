from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.repositories.claim import ClaimRepository
from backend.app.schemas.claim import ClaimCreate, ClaimRead
from backend.app.services.research.prov_validator import (
    ProvValidationError,
    validate_provenance_json,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/research-tasks/{research_task_id}/claims",
    tags=["claims"],
)


def _provenance_json_hash(provenance_json: dict[str, Any]) -> str:
    canonical = json.dumps(
        provenance_json,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# F-PR19-R5-001 P1 adopt: trace_id format を narrow に、secret-shaped string (Bearer / API key / canary)
# が match しない char set + length 制限。OpenTelemetry / W3C Trace Context (16 or 32 hex) +
# UUID (with hyphen) + simple short structured ID (alphanumeric + - のみ、length 16-64) を許可。
# `_` (Bearer 系で頻出) / `.` (canary 系) / `:` (ARN 系) / `/` (path 系) を除外。
# F-PR19-R11-004 P1 adopt: structured ID branch (`^[A-Za-z0-9-]{16,64}$`) は OpenAI-style key
# (`sk-` + 20 alphanumerics) を許可してしまうため削除。W3C / OpenTelemetry hex (16-32) + UUID のみ許可、
# secret-shaped string (sk- / Bearer / api_key_ prefix 等) を完全 reject。
_TRACE_ID_RE = re.compile(
    r"^[0-9a-fA-F]{16,32}$"  # W3C / OpenTelemetry hex
    r"|^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"  # UUID
)


def _correlation_id(request: Request) -> str:
    value = request.headers.get("x-correlation-id")
    if value and _TRACE_ID_RE.fullmatch(value):
        return value
    # F-PR19-R6-003 P1 adopt: fallback request_id も sanitize、framework が caller-controlled
    # request_id を state に set する経路でも secret-shaped string を audit に保存させない。
    fallback = str(getattr(request.state, "request_id", ""))
    if fallback and _TRACE_ID_RE.fullmatch(fallback):
        return fallback
    return ""


def _trace_id(request: Request) -> str | None:
    # F-PR19-R4-001 P1 adopt: caller-controlled x-trace-id header に raw secret / canary が混入する経路を遮断
    # (audit 保存前に format 制約で sanitize、UUID / hex / structured trace ID のみ許可、不正 format は None)
    value = request.headers.get("x-trace-id")
    if value is None or not _TRACE_ID_RE.fullmatch(value):
        return None
    return value


@router.post("", response_model=ClaimRead, status_code=status.HTTP_201_CREATED)
async def create_claim_endpoint(
    project_id: UUID,
    research_task_id: UUID,
    body: ClaimCreate,
    request: Request,
    actor_id: UUID = Depends(get_current_actor_id),
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ClaimRead:
    try:
        validate_provenance_json(body.provenance_json)
    except ProvValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "prov_validation_failed",
                "error_summary": exc.detail,
            },
        ) from exc

    repo = ClaimRepository(session)
    try:
        try:
            claim = await repo.create_claim(
                tenant_id=tenant_id,
                project_id=project_id,
                research_task_id=research_task_id,
                claim_create=body,
            )
        except ValueError as exc:
            # F-PR19-R3-001 P2 adopt: assert_no_raw_secret / validate_provenance_json 失敗を 400 で返す
            # (uncontrolled 500 ではなく structured 4xx error code、caller が原因を区別可能)
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error_code": "claim_payload_validation_failed",
                    "error_summary": str(exc),
                },
            ) from exc
        correlation_id = _correlation_id(request)
        await AuditEventRepository(session).append(
            tenant_id=tenant_id,
            event_type="claim_created",
            actor_id=actor_id,
            correlation_id=correlation_id,
            trace_id=_trace_id(request),
            payload={
                "tenant_id": tenant_id,
                "actor_id": str(actor_id),
                "claim_id": str(claim.id),
                "research_task_id": str(research_task_id),
                "provenance_json_hash": _provenance_json_hash(body.provenance_json),
                "correlation_id": correlation_id,
                "timestamp": datetime.now(tz=UTC).isoformat(),
            },
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "claim_create_failed",
                "error_summary": "claim project/research_task binding failed",
            },
        ) from exc

    return ClaimRead.model_validate(claim)


@router.get("", response_model=list[ClaimRead])
async def list_claims_endpoint(
    project_id: UUID,
    research_task_id: UUID,
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[ClaimRead]:
    repo = ClaimRepository(session)
    claims = await repo.list_claims_by_research_task(
        tenant_id=tenant_id,
        project_id=project_id,
        research_task_id=research_task_id,
    )
    return [ClaimRead.model_validate(claim) for claim in claims]


__all__ = ["router"]
