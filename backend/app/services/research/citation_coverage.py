from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.claim import Claim
from backend.app.db.models.evidence_item import EvidenceItem
from backend.app.db.models.research_task import ResearchTask
from backend.app.schemas.research.citation_coverage import CitationCoverageMetric


async def compute_citation_coverage(
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    research_task_id: UUID,
) -> CitationCoverageMetric:
    """Compute claim-level citation coverage for one ResearchTask.

    Sprint 10 batch 3 intentionally stops at the per-research_task source
    metric. Sprint 11 BL-0126 applies the AgentRun final-adopted artifact
    filter and aggregates this source into AC-KPI-04.
    """

    await _ensure_tenant_context(session, tenant_id)
    await _assert_research_task_reachable(
        session=session,
        tenant_id=tenant_id,
        project_id=project_id,
        research_task_id=research_task_id,
    )

    claim_ids = await _fetch_claim_ids(
        session=session,
        tenant_id=tenant_id,
        project_id=project_id,
        research_task_id=research_task_id,
    )
    denominator = len(claim_ids)
    if denominator == 0:
        return CitationCoverageMetric(
            research_task_id=research_task_id,
            numerator=0,
            denominator=0,
            computed_at=datetime.now(tz=UTC),
        )

    covered_claim_ids = await _fetch_covered_claim_ids(
        session=session,
        tenant_id=tenant_id,
        project_id=project_id,
        claim_ids=claim_ids,
    )
    numerator = sum(1 for claim_id in claim_ids if claim_id in covered_claim_ids)

    return CitationCoverageMetric(
        research_task_id=research_task_id,
        numerator=numerator,
        denominator=denominator,
        computed_at=datetime.now(tz=UTC),
    )


async def _ensure_tenant_context(session: AsyncSession, tenant_id: int) -> None:
    _require_tenant_id(tenant_id)
    current_tenant_id = await get_tenant_context(session)
    if current_tenant_id is None:
        await set_tenant_context(session, tenant_id)
    await assert_tenant_context(session, tenant_id)


def _require_tenant_id(tenant_id: int) -> None:
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
        raise ValueError("tenant_id must be a positive integer.")


async def _assert_research_task_reachable(
    *,
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    research_task_id: UUID,
) -> None:
    reachable_id = await session.scalar(
        select(ResearchTask.id).where(
            ResearchTask.tenant_id == tenant_id,
            ResearchTask.project_id == project_id,
            ResearchTask.id == research_task_id,
        )
    )
    if reachable_id is None:
        raise ValueError("research_task_id not reachable in tenant/project")


async def _fetch_claim_ids(
    *,
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    research_task_id: UUID,
) -> tuple[UUID, ...]:
    result = await session.execute(
        select(Claim.id)
        .where(
            Claim.tenant_id == tenant_id,
            Claim.project_id == project_id,
            Claim.research_task_id == research_task_id,
        )
        .order_by(Claim.id)
    )
    return tuple(result.scalars().all())


async def _fetch_covered_claim_ids(
    *,
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    claim_ids: tuple[UUID, ...],
) -> frozenset[UUID]:
    result = await session.execute(
        select(EvidenceItem.claim_id)
        .where(
            EvidenceItem.tenant_id == tenant_id,
            EvidenceItem.project_id == project_id,
            EvidenceItem.claim_id.in_(claim_ids),
        )
        .distinct()
    )
    return frozenset(result.scalars().all())


__all__ = ["compute_citation_coverage"]
