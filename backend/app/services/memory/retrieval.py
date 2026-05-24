from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.artifact import Artifact
from backend.app.db.models.context_snapshot import ContextSnapshot
from backend.app.db.models.memory_record import MemoryRecord, MemoryRetrievalArtifact
from backend.app.db.models.sanitizer_policy_version import SanitizerPolicyVersion
from backend.app.domain.artifact.data_class import (
    DATA_CLASS_ORDINAL,
    PayloadDataClass,
)
from backend.app.repositories.artifact import (
    ArtifactRepository,
    canonical_json_for_hash,
)
from backend.app.repositories.memory import (
    MemoryRecordRepository,
    MemoryRetrievalArtifactRepository,
)
from backend.app.schemas.memory import MemoryRetrievalArtifactCreate, MemoryRetrievalRequest
from backend.app.services.orchestrator._shared import ensure_tenant_context


class MemoryRetrievalDenied(ValueError):
    """Raised when a memory retrieval request crosses a project boundary."""


@dataclass(frozen=True)
class MemoryRetrievalResult:
    records: tuple[MemoryRecord, ...]
    artifact: Artifact | None
    retrieval_artifacts: tuple[MemoryRetrievalArtifact, ...]
    payload_data_class: PayloadDataClass | None
    retrieval_hash: str | None
    sanitizer_policy_version: str | None


@dataclass(frozen=True)
class _ActiveSanitizerPolicy:
    id: UUID
    version: str
    config_hash: str


class MemoryRetrievalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def retrieve(
        self,
        *,
        tenant_id: int,
        request: MemoryRetrievalRequest,
        context_snapshot_id: UUID | None = None,
    ) -> MemoryRetrievalResult:
        await ensure_tenant_context(self.session, tenant_id)
        await self._assert_run_boundary(
            tenant_id=tenant_id,
            project_id=request.project_id,
            run_id=request.retrieval_run_id,
        )
        if context_snapshot_id is not None:
            await self._assert_context_snapshot_boundary(
                tenant_id=tenant_id,
                run_id=request.retrieval_run_id,
                context_snapshot_id=context_snapshot_id,
            )
        now = datetime.now(tz=UTC)
        records = await MemoryRecordRepository(self.session).list_active_for_retrieval(
            tenant_id=tenant_id,
            project_id=request.project_id,
            now=now,
            limit=max(request.limit, len(request.memory_record_ids)),
            memory_record_ids=request.memory_record_ids,
            record_kinds=request.record_kinds,
        )
        self._assert_requested_records_resolved(request=request, records=records)
        if not records:
            return MemoryRetrievalResult(
                records=(),
                artifact=None,
                retrieval_artifacts=(),
                payload_data_class=None,
                retrieval_hash=None,
                sanitizer_policy_version=None,
            )

        sanitizer_policy = await self._current_sanitizer_policy(tenant_id=tenant_id)
        await self._assert_records_sanitizer_not_stale(
            tenant_id=tenant_id,
            records=records,
            active_policy=sanitizer_policy,
        )
        payload_data_class = _max_record_data_class(records)
        content_jsonb, retrieval_hash = _build_retrieval_content(
            request=request,
            records=records,
            retrieved_at=now,
            sanitizer_policy_version=sanitizer_policy.version,
            context_snapshot_id=context_snapshot_id,
        )
        artifact = await ArtifactRepository(self.session).create_artifact(
            tenant_id=tenant_id,
            run_id=request.retrieval_run_id,
            project_id=request.project_id,
            kind="other",
            content_hash=retrieval_hash,
            content_jsonb=content_jsonb,
            payload_data_class=payload_data_class,
            exportable=False,
        )
        retrieval_rows: list[MemoryRetrievalArtifact] = []
        repository = MemoryRetrievalArtifactRepository(self.session)
        for record in records:
            retrieval_rows.append(
                await repository.create_retrieval_artifact(
                    tenant_id=tenant_id,
                    payload=MemoryRetrievalArtifactCreate(
                        project_id=request.project_id,
                        memory_record_id=record.id,
                        retrieval_artifact_ref=f"artifact://memory-retrieval/{artifact.id}",
                        retrieval_hash=retrieval_hash,
                        sanitizer_version_id=sanitizer_policy.id,
                        retrieval_run_id=request.retrieval_run_id,
                        context_snapshot_id=context_snapshot_id,
                        trust_level="untrusted_content",
                    ),
                )
            )

        return MemoryRetrievalResult(
            records=tuple(records),
            artifact=artifact,
            retrieval_artifacts=tuple(retrieval_rows),
            payload_data_class=payload_data_class,
            retrieval_hash=retrieval_hash,
            sanitizer_policy_version=sanitizer_policy.version,
        )

    @staticmethod
    def _assert_requested_records_resolved(
        *,
        request: MemoryRetrievalRequest,
        records: list[MemoryRecord],
    ) -> None:
        if not request.memory_record_ids:
            return
        resolved = {record.id for record in records}
        requested = set(request.memory_record_ids)
        if resolved != requested:
            raise MemoryRetrievalDenied("memory_record_not_found_in_project")

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
            raise MemoryRetrievalDenied("retrieval_run_id not found in tenant/project boundary.")

    async def _assert_context_snapshot_boundary(
        self,
        *,
        tenant_id: int,
        run_id: UUID,
        context_snapshot_id: UUID,
    ) -> None:
        exists = await self.session.scalar(
            sa.select(ContextSnapshot.id).where(
                ContextSnapshot.tenant_id == tenant_id,
                ContextSnapshot.run_id == run_id,
                ContextSnapshot.id == context_snapshot_id,
            )
        )
        if exists is None:
            raise MemoryRetrievalDenied(
                "context_snapshot_id not found in tenant/run boundary."
            )

    async def _current_sanitizer_policy(
        self,
        *,
        tenant_id: int,
    ) -> _ActiveSanitizerPolicy:
        row = (
            await self.session.execute(
                sa.select(
                    SanitizerPolicyVersion.id,
                    SanitizerPolicyVersion.version,
                    SanitizerPolicyVersion.config_hash,
                )
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
            raise MemoryRetrievalDenied("active sanitizer_policy_versions row not found.")
        if not isinstance(row.config_hash, str) or not row.config_hash.strip():
            raise MemoryRetrievalDenied(
                "active sanitizer_policy_versions config_hash not found."
            )
        return _ActiveSanitizerPolicy(
            id=row.id,
            version=row.version,
            config_hash=row.config_hash,
        )

    async def _assert_records_sanitizer_not_stale(
        self,
        *,
        tenant_id: int,
        records: list[MemoryRecord],
        active_policy: _ActiveSanitizerPolicy,
    ) -> None:
        sanitizer_ids = {record.sanitizer_version_id for record in records}
        result = await self.session.execute(
            sa.select(SanitizerPolicyVersion.id, SanitizerPolicyVersion.config_hash).where(
                SanitizerPolicyVersion.tenant_id == tenant_id,
                SanitizerPolicyVersion.id.in_(sanitizer_ids),
            )
        )
        config_by_id = {row.id: row.config_hash for row in result}
        if set(config_by_id) != sanitizer_ids:
            raise MemoryRetrievalDenied("stale_sanitizer")
        if any(
            config_hash != active_policy.config_hash
            for config_hash in config_by_id.values()
        ):
            raise MemoryRetrievalDenied("stale_sanitizer")


def _max_record_data_class(records: list[MemoryRecord]) -> PayloadDataClass:
    return max(records, key=lambda record: DATA_CLASS_ORDINAL[record.data_class]).data_class


def _build_retrieval_content(
    *,
    request: MemoryRetrievalRequest,
    records: list[MemoryRecord],
    retrieved_at: datetime,
    sanitizer_policy_version: str,
    context_snapshot_id: UUID | None,
) -> tuple[dict[str, Any], str]:
    content: dict[str, Any] = {
        "schema_version": request.schema_version,
        "sanitizer_policy_version": sanitizer_policy_version,
        "project_id": str(request.project_id),
        "retrieved_at": retrieved_at.isoformat(),
        "trust_level": "untrusted_content",
        "context_snapshot_id": (
            str(context_snapshot_id) if context_snapshot_id is not None else None
        ),
        "records": [
            {
                "memory_record_id": str(record.id),
                "record_kind": record.record_kind,
                "content_artifact_ref": record.content_artifact_ref,
                "content_hash": record.content_hash,
                "data_class": record.data_class,
                "redaction_status": record.redaction_status,
                "sanitizer_version_id": str(record.sanitizer_version_id),
                "trust_level": "untrusted_content",
            }
            for record in records
        ],
    }
    canonical = canonical_json_for_hash(content)
    normalized = json.loads(canonical)
    if not isinstance(normalized, dict):
        raise ValueError("memory retrieval canonicalization must produce an object.")
    return normalized, sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "MemoryRetrievalDenied",
    "MemoryRetrievalResult",
    "MemoryRetrievalService",
]
