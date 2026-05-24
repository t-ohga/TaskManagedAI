from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.memory_record import MemoryRecord
from backend.app.db.models.project import Project
from backend.app.domain.memory.record_kind import MemoryRecordKind
from backend.app.schemas.memory import MemoryInsightRequest
from backend.app.services.orchestrator._shared import ensure_tenant_context


class MemoryInsightDenied(ValueError):
    """Raised when memory insight aggregation crosses project boundaries."""


@dataclass(frozen=True)
class MemoryInsightItem:
    memory_record_id: UUID
    record_kind: MemoryRecordKind
    content_hash: str
    source_artifact_ref: str | None
    aggregate_count: int
    score: float
    created_at: datetime


@dataclass(frozen=True)
class MemoryInsightResult:
    items: tuple[MemoryInsightItem, ...]
    generated_at: datetime
    trust_level: str = "untrusted_content"


class MemoryInsightService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def summarize(
        self,
        *,
        tenant_id: int,
        request: MemoryInsightRequest,
        generated_at: datetime | None = None,
    ) -> MemoryInsightResult:
        await ensure_tenant_context(self.session, tenant_id)
        now = generated_at or datetime.now(tz=UTC)
        _assert_timezone_aware(now)
        await self._assert_project_boundary(
            tenant_id=tenant_id,
            project_id=request.project_id,
        )
        aggregate_counts = await self._aggregate_counts(
            tenant_id=tenant_id,
            request=request,
            generated_at=now,
        )
        if not aggregate_counts:
            return MemoryInsightResult(items=(), generated_at=now)
        records = await self._list_ref_only_records(
            tenant_id=tenant_id,
            request=request,
            generated_at=now,
        )
        return MemoryInsightResult(
            items=tuple(
                _build_insight_item(
                    record=record,
                    aggregate_count=aggregate_counts[record.record_kind],
                    generated_at=now,
                )
                for record in records
            ),
            generated_at=now,
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
            raise MemoryInsightDenied("project_id not found in tenant boundary.")

    async def _aggregate_counts(
        self,
        *,
        tenant_id: int,
        request: MemoryInsightRequest,
        generated_at: datetime,
    ) -> dict[MemoryRecordKind, int]:
        stmt = (
            sa.select(MemoryRecord.record_kind, sa.func.count(MemoryRecord.id))
            .where(
                MemoryRecord.tenant_id == tenant_id,
                MemoryRecord.project_id == request.project_id,
                MemoryRecord.archived_at.is_(None),
                MemoryRecord.retention_until > generated_at,
            )
            .group_by(MemoryRecord.record_kind)
        )
        if request.record_kinds:
            stmt = stmt.where(MemoryRecord.record_kind.in_(request.record_kinds))
        result = await self.session.execute(stmt)
        return {
            record_kind: int(aggregate_count)
            for record_kind, aggregate_count in result.all()
        }

    async def _list_ref_only_records(
        self,
        *,
        tenant_id: int,
        request: MemoryInsightRequest,
        generated_at: datetime,
    ) -> list[MemoryRecord]:
        stmt = (
            sa.select(MemoryRecord)
            .where(
                MemoryRecord.tenant_id == tenant_id,
                MemoryRecord.project_id == request.project_id,
                MemoryRecord.archived_at.is_(None),
                MemoryRecord.retention_until > generated_at,
            )
            .order_by(MemoryRecord.created_at.desc(), MemoryRecord.id)
            .limit(request.limit)
        )
        if request.record_kinds:
            stmt = stmt.where(MemoryRecord.record_kind.in_(request.record_kinds))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


def _build_insight_item(
    *,
    record: MemoryRecord,
    aggregate_count: int,
    generated_at: datetime,
) -> MemoryInsightItem:
    return MemoryInsightItem(
        memory_record_id=record.id,
        record_kind=record.record_kind,
        content_hash=record.content_hash,
        source_artifact_ref=(
            f"artifact://source/{record.source_artifact_id}"
            if record.source_artifact_id is not None
            else None
        ),
        aggregate_count=aggregate_count,
        score=_score_record(record=record, aggregate_count=aggregate_count, generated_at=generated_at),
        created_at=record.created_at,
    )


def _score_record(
    *,
    record: MemoryRecord,
    aggregate_count: int,
    generated_at: datetime,
) -> float:
    created_at = record.created_at
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        created_at = created_at.replace(tzinfo=UTC)
    age_days = max((generated_at - created_at).total_seconds(), 0.0) / 86_400
    return round(aggregate_count / (1.0 + age_days), 6)


def _assert_timezone_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MemoryInsightDenied("generated_at must be timezone-aware.")


__all__ = [
    "MemoryInsightDenied",
    "MemoryInsightItem",
    "MemoryInsightResult",
    "MemoryInsightService",
]
