from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.config import Settings, get_settings
from backend.app.domain.artifact.data_class import PayloadDataClass
from backend.app.domain.memory.record_kind import MemoryRecordKind
from backend.app.domain.memory.redaction_status import MemoryRedactionStatus
from backend.app.schemas.memory import MemoryRetrievalRequest
from backend.app.services.memory.retrieval import (
    MemoryRetrievalDenied,
    MemoryRetrievalResult,
    MemoryRetrievalService,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}/memory", tags=["memory"])


class MemoryRetrievalRecordRead(BaseModel):
    memory_record_id: UUID
    record_kind: MemoryRecordKind
    content_artifact_ref: str
    content_hash: str
    data_class: PayloadDataClass
    redaction_status: MemoryRedactionStatus
    trust_level: str
    created_at: datetime


class MemoryRetrievalArtifactRead(BaseModel):
    retrieval_artifact_ref: str
    retrieval_hash: str
    context_snapshot_id: UUID | None
    trust_level: str


class MemoryRetrievalResponse(BaseModel):
    items: list[MemoryRetrievalRecordRead]
    retrieval_artifacts: list[MemoryRetrievalArtifactRead]
    sanitizer_policy_version: str | None
    retrieval_hash: str | None
    trust_level: str = "untrusted_content"


def _settings_from_request(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, Settings):
        return settings
    return get_settings()


def require_memory_api_enabled(request: Request) -> None:
    settings = _settings_from_request(request)
    if not settings.memory_api_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="memory api disabled",
        )


def _to_response(result: MemoryRetrievalResult) -> MemoryRetrievalResponse:
    return MemoryRetrievalResponse(
        items=[
            MemoryRetrievalRecordRead(
                memory_record_id=record.id,
                record_kind=record.record_kind,
                content_artifact_ref=record.content_artifact_ref,
                content_hash=record.content_hash,
                data_class=record.data_class,
                redaction_status=record.redaction_status,
                trust_level="untrusted_content",
                created_at=record.created_at,
            )
            for record in result.records
        ],
        retrieval_artifacts=[
            MemoryRetrievalArtifactRead(
                retrieval_artifact_ref=artifact.retrieval_artifact_ref,
                retrieval_hash=artifact.retrieval_hash,
                context_snapshot_id=artifact.context_snapshot_id,
                trust_level=artifact.trust_level,
            )
            for artifact in result.retrieval_artifacts
        ],
        sanitizer_policy_version=result.sanitizer_policy_version,
        retrieval_hash=result.retrieval_hash,
    )


def _memory_retrieval_denied_http(exc: MemoryRetrievalDenied) -> HTTPException:
    reason = str(exc)
    if reason == "stale_sanitizer":
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="stale_sanitizer",
        )
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="memory retrieval not found",
    )


@router.get("/retrievals", response_model=MemoryRetrievalResponse)
async def retrieve_memory_endpoint(
    project_id: UUID,
    retrieval_run_id: Annotated[UUID, Query()],
    memory_record_id: Annotated[list[UUID] | None, Query()] = None,
    record_kind: Annotated[list[MemoryRecordKind] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    _enabled: None = Depends(require_memory_api_enabled),  # noqa: B008
    _actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> MemoryRetrievalResponse:
    request = MemoryRetrievalRequest(
        project_id=project_id,
        retrieval_run_id=retrieval_run_id,
        memory_record_ids=tuple(memory_record_id or ()),
        record_kinds=tuple(record_kind or ()),
        limit=limit,
    )
    try:
        result = await MemoryRetrievalService(session).retrieve(
            tenant_id=tenant_id,
            request=request,
        )
    except MemoryRetrievalDenied as exc:
        raise _memory_retrieval_denied_http(exc) from exc
    return _to_response(result)


__all__ = [
    "MemoryRetrievalArtifactRead",
    "MemoryRetrievalRecordRead",
    "MemoryRetrievalResponse",
    "require_memory_api_enabled",
    "router",
]
