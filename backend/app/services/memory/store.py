from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.artifact import Artifact
from backend.app.db.models.memory_record import MemoryRecord
from backend.app.db.models.sanitizer_policy_version import SanitizerPolicyVersion
from backend.app.domain.artifact.data_class import PayloadDataClass
from backend.app.repositories.artifact import ArtifactRepository
from backend.app.repositories.memory import MemoryRecordRepository
from backend.app.schemas.memory import MemoryRecordCreate, MemoryStoreRequest
from backend.app.services.input_trust.payload_classifier import classify_payload_data_class
from backend.app.services.memory.sanitizer import (
    MemoryPayloadRejected,
    SanitizedMemoryPayload,
    sanitize_memory_payload,
)
from backend.app.services.orchestrator._shared import ensure_tenant_context


class MemoryStoreError(ValueError):
    """Raised when a memory store request cannot pass server-side guards."""


@dataclass(frozen=True)
class MemoryStoreResult:
    record: MemoryRecord
    artifact: Artifact
    payload_data_class: PayloadDataClass
    sanitizer_policy_version: str
    sanitized_payload: SanitizedMemoryPayload


@dataclass(frozen=True)
class _ActiveSanitizerPolicy:
    id: UUID
    version: str


class MemoryStoreService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def store(
        self,
        *,
        tenant_id: int,
        request: MemoryStoreRequest,
        source_artifact_id: UUID | None = None,
    ) -> MemoryStoreResult:
        await ensure_tenant_context(self.session, tenant_id)
        self._assert_retention_window(request.retention_until)
        await self._assert_run_boundary(
            tenant_id=tenant_id,
            project_id=request.project_id,
            run_id=request.run_id,
        )
        if source_artifact_id is not None:
            await self._assert_source_artifact_boundary(
                tenant_id=tenant_id,
                project_id=request.project_id,
                run_id=request.run_id,
                source_artifact_id=source_artifact_id,
            )
        sanitizer_policy = await self._current_sanitizer_policy(tenant_id=tenant_id)
        classification = classify_payload_data_class(request.classification)
        try:
            sanitized = sanitize_memory_payload(
                request.payload,
                schema_version=request.schema_version,
                sanitizer_policy_version=sanitizer_policy.version,
            )
        except MemoryPayloadRejected as exc:
            raise MemoryStoreError(exc.reason_code) from exc

        artifact = await ArtifactRepository(self.session).create_artifact(
            tenant_id=tenant_id,
            run_id=request.run_id,
            project_id=request.project_id,
            kind="other",
            content_hash=sanitized.content_hash,
            content_jsonb=sanitized.content_jsonb,
            payload_data_class=classification.payload_data_class,
            exportable=False,
        )

        record_payload = MemoryRecordCreate(
            project_id=request.project_id,
            record_kind=request.record_kind,
            content_artifact_ref=f"artifact://memory/{artifact.id}",
            content_hash=artifact.content_hash,
            data_class=classification.payload_data_class,
            redaction_status=sanitized.redaction_status,
            sanitizer_version_id=sanitizer_policy.id,
            source_artifact_id=source_artifact_id or artifact.id,
            trust_level="untrusted_content",
            retention_until=request.retention_until,
        )
        record = await MemoryRecordRepository(self.session).create_memory_record(
            tenant_id=tenant_id,
            payload=record_payload,
        )
        return MemoryStoreResult(
            record=record,
            artifact=artifact,
            payload_data_class=classification.payload_data_class,
            sanitizer_policy_version=sanitizer_policy.version,
            sanitized_payload=sanitized,
        )

    @staticmethod
    def _assert_retention_window(retention_until: datetime) -> None:
        if retention_until.tzinfo is None or retention_until.utcoffset() is None:
            raise MemoryStoreError("retention_until must be timezone-aware.")
        if retention_until <= datetime.now(tz=UTC):
            raise MemoryStoreError("retention_until must be in the future.")

    async def _assert_run_boundary(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        run_id: UUID,
    ) -> None:
        exists = await self.session.scalar(
            sa.select(AgentRun.id).where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.project_id == project_id,
                AgentRun.id == run_id,
            )
        )
        if exists is None:
            raise MemoryStoreError("run_id not found in tenant/project boundary.")

    async def _assert_source_artifact_boundary(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        run_id: UUID,
        source_artifact_id: UUID,
    ) -> None:
        exists = await self.session.scalar(
            sa.select(Artifact.id).where(
                Artifact.tenant_id == tenant_id,
                Artifact.project_id == project_id,
                Artifact.run_id == run_id,
                Artifact.id == source_artifact_id,
            )
        )
        if exists is None:
            raise MemoryStoreError(
                "source_artifact_id not found in tenant/project/run boundary."
            )

    async def _current_sanitizer_policy(
        self,
        *,
        tenant_id: int,
    ) -> _ActiveSanitizerPolicy:
        row = (
            await self.session.execute(
                sa.select(SanitizerPolicyVersion.id, SanitizerPolicyVersion.version)
                .where(
                    SanitizerPolicyVersion.tenant_id == tenant_id,
                    SanitizerPolicyVersion.deprecated_at.is_(None),
                )
                .order_by(
                    SanitizerPolicyVersion.activated_at.desc(),
                    SanitizerPolicyVersion.version.desc(),
                )
                .limit(1)
            )
        ).one_or_none()
        if row is None or not isinstance(row.version, str) or not row.version.strip():
            raise MemoryStoreError("active sanitizer_policy_versions row not found.")
        return _ActiveSanitizerPolicy(id=row.id, version=row.version)


__all__ = [
    "MemoryStoreError",
    "MemoryStoreResult",
    "MemoryStoreService",
]
