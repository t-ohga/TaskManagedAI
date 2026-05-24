from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.audit_event import AuditEvent
from backend.app.db.models.memory_record import MemoryRecord
from backend.app.db.models.project import Project
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.schemas.memory import MemoryArchivePolicyRequest
from backend.app.services.orchestrator._shared import ensure_tenant_context

MEMORY_ARCHIVE_ENGAGED_EVENT_TYPE = "memory_archive_engaged"


class MemoryArchivePolicyError(ValueError):
    """Raised when memory archive policy cannot stay within project boundaries."""


@dataclass(frozen=True)
class MemoryArchivePolicyResult:
    archived_records: tuple[MemoryRecord, ...]
    audit_event: AuditEvent | None
    evaluated_at: datetime


class MemoryArchivePolicyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def archive_low_value(
        self,
        *,
        tenant_id: int,
        request: MemoryArchivePolicyRequest,
        evaluated_at: datetime | None = None,
        actor_id: UUID | None = None,
        principal_id: UUID | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> MemoryArchivePolicyResult:
        await ensure_tenant_context(self.session, tenant_id)
        now = evaluated_at or datetime.now(tz=UTC)
        _assert_timezone_aware(now)
        await self._assert_project_boundary(
            tenant_id=tenant_id,
            project_id=request.project_id,
        )
        candidates = await self._list_archive_candidates(
            tenant_id=tenant_id,
            request=request,
            evaluated_at=now,
        )
        if not candidates:
            return MemoryArchivePolicyResult(
                archived_records=(),
                audit_event=None,
                evaluated_at=now,
            )

        for record in candidates:
            record.archived_at = now
        await self.session.flush()

        audit_event = await AuditEventRepository(self.session).append(
            tenant_id=tenant_id,
            event_type=MEMORY_ARCHIVE_ENGAGED_EVENT_TYPE,
            payload=_build_archive_audit_payload(
                request=request,
                archived_records=candidates,
                archived_at=now,
            ),
            actor_id=actor_id,
            principal_id=principal_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
        return MemoryArchivePolicyResult(
            archived_records=tuple(candidates),
            audit_event=audit_event,
            evaluated_at=now,
        )

    async def _assert_project_boundary(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
    ) -> None:
        exists = await self.session.scalar(
            sa.select(Project.id).where(
                Project.tenant_id == tenant_id,
                Project.id == project_id,
            )
        )
        if exists is None:
            raise MemoryArchivePolicyError("project_id not found in tenant boundary.")

    async def _list_archive_candidates(
        self,
        *,
        tenant_id: int,
        request: MemoryArchivePolicyRequest,
        evaluated_at: datetime,
    ) -> list[MemoryRecord]:
        archive_before = evaluated_at - timedelta(days=request.minimum_age_days)
        result = await self.session.execute(
            sa.select(MemoryRecord)
            .where(
                MemoryRecord.tenant_id == tenant_id,
                MemoryRecord.project_id == request.project_id,
                MemoryRecord.archived_at.is_(None),
                MemoryRecord.retention_until > evaluated_at,
                MemoryRecord.created_at <= archive_before,
                MemoryRecord.record_kind.in_(request.record_kinds),
                MemoryRecord.record_kind != "manual_user",
            )
            .order_by(MemoryRecord.created_at.asc(), MemoryRecord.id)
            .limit(request.max_records)
        )
        return list(result.scalars().all())


def _build_archive_audit_payload(
    *,
    request: MemoryArchivePolicyRequest,
    archived_records: list[MemoryRecord],
    archived_at: datetime,
) -> dict[str, object]:
    return {
        "project_id": str(request.project_id),
        "event_name": MEMORY_ARCHIVE_ENGAGED_EVENT_TYPE,
        "archived_at": archived_at.isoformat(),
        "archived_count": len(archived_records),
        "policy": {
            "minimum_age_days": request.minimum_age_days,
            "max_records": request.max_records,
            "record_kinds": list(request.record_kinds),
            "manual_user_protected": True,
            "hard_delete": False,
        },
        "records": [
            {
                "memory_record_id": str(record.id),
                "record_kind": record.record_kind,
                "content_artifact_ref": record.content_artifact_ref,
                "content_hash": record.content_hash,
                "source_artifact_ref": (
                    f"artifact://source/{record.source_artifact_id}"
                    if record.source_artifact_id is not None
                    else None
                ),
            }
            for record in archived_records
        ],
    }


def _assert_timezone_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MemoryArchivePolicyError("evaluated_at must be timezone-aware.")


__all__ = [
    "MEMORY_ARCHIVE_ENGAGED_EVENT_TYPE",
    "MemoryArchivePolicyError",
    "MemoryArchivePolicyResult",
    "MemoryArchivePolicyService",
]
