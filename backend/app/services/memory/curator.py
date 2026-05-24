from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.artifact import Artifact
from backend.app.domain.memory.record_kind import MemoryRecordKind
from backend.app.schemas.memory import MemoryCuratorRequest, MemoryStoreRequest
from backend.app.services.memory.store import MemoryStoreError, MemoryStoreResult, MemoryStoreService
from backend.app.services.orchestrator._shared import ensure_tenant_context


class MemoryCuratorError(ValueError):
    """Raised when curator memory generation violates source boundaries."""


@dataclass(frozen=True)
class CuratedMemoryResult:
    stored: MemoryStoreResult
    source_artifact: Artifact


_CURATOR_RECORD_KIND_BY_SOURCE: dict[str, MemoryRecordKind] = {
    "completed_run": "auto_completion",
    "failed_run": "auto_failure",
    "review_finding": "auto_review_finding",
}


class MemoryCuratorService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def curate(
        self,
        *,
        tenant_id: int,
        request: MemoryCuratorRequest,
    ) -> CuratedMemoryResult:
        await ensure_tenant_context(self.session, tenant_id)
        source_artifact = await self._load_source_artifact(
            tenant_id=tenant_id,
            request=request,
        )
        record_kind = _CURATOR_RECORD_KIND_BY_SOURCE[request.source_kind]
        payload = _build_curated_payload(
            request=request,
            source_artifact=source_artifact,
        )
        store_request = MemoryStoreRequest(
            project_id=request.project_id,
            run_id=request.run_id,
            record_kind=record_kind,
            payload=payload,
            classification=request.classification,
            schema_version=request.schema_version,
            retention_until=request.retention_until,
        )
        try:
            stored = await MemoryStoreService(self.session).store(
                tenant_id=tenant_id,
                request=store_request,
                source_artifact_id=source_artifact.id,
            )
        except MemoryStoreError as exc:
            raise MemoryCuratorError(str(exc)) from exc
        return CuratedMemoryResult(
            stored=stored,
            source_artifact=source_artifact,
        )

    async def _load_source_artifact(
        self,
        *,
        tenant_id: int,
        request: MemoryCuratorRequest,
    ) -> Artifact:
        row = await self.session.scalar(
            sa.select(Artifact).where(
                Artifact.tenant_id == tenant_id,
                Artifact.project_id == request.project_id,
                Artifact.run_id == request.run_id,
                Artifact.id == request.source_artifact_id,
            )
        )
        if row is None:
            raise MemoryCuratorError(
                "source_artifact_id not found in tenant/project/run boundary."
            )
        return row


def _build_curated_payload(
    *,
    request: MemoryCuratorRequest,
    source_artifact: Artifact,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "curator_schema": "memory-curator-source.v1",
        "source_kind": request.source_kind,
        "source": {
            "artifact_ref": f"artifact://source/{source_artifact.id}",
            "artifact_kind": source_artifact.kind,
            "artifact_digest": source_artifact.content_hash,
            "run_ref": f"agent-run://{source_artifact.run_id}",
        },
        "summary_ref": request.summary_ref,
    }
    if request.reason_code is not None:
        payload["reason_code"] = request.reason_code
    return payload


__all__ = [
    "CuratedMemoryResult",
    "MemoryCuratorError",
    "MemoryCuratorService",
]
