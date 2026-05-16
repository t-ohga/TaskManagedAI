"""citation_coverage metric source (Sprint 10 BL-0119 / AC-KPI-04 source).

SP-010 QL-C spec line 162-165:

- ``citation_coverage`` is claim-level:
  ``count(distinct claim_id with >= 1 GroundingSupport) /
   count(distinct claim_id within evaluated AgentRun)``.
- An AgentRun whose ``ContextSnapshot.evidence_set_hash`` is null is
  **included in the denominator with numerator=0** (uncovered). This
  prevents AgentRuns missing Research/Evidence wiring from inflating
  coverage by being silently excluded.
- ``denominator_nonzero`` is reported so AC-KPI-04 P0 acceptance gate
  can reject divide-by-zero masking.

This module is the source-side metric producer (BL-0119). The eval
harness aggregator (Sprint 11 BL-0126) consumes the per-AgentRun
records this service emits.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.claim import Claim
from backend.app.db.models.context_snapshot import ContextSnapshot
from backend.app.db.models.grounding_support import GroundingSupport
from backend.app.db.models.research_task import ResearchTask


class CitationCoverageError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"[{reason_code}] {message}")


@dataclass(frozen=True)
class CitationCoverageMetric:
    """Per-AgentRun citation_coverage source record.

    SP-010 QL-C spec maps these to the Sprint 11 RetrievalEvalRun fields
    (``citation_coverage`` + ``denominator_nonzero`` gate).
    """

    agent_run_id: UUID
    tenant_id: int
    project_id: UUID
    evidence_set_hash: str | None
    distinct_claims: int
    grounded_claims: int
    coverage: float
    denominator_nonzero: bool


async def compute_citation_coverage(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    agent_run_id: UUID,
) -> CitationCoverageMetric:
    """Compute claim-level citation_coverage for a single AgentRun.

    The numerator counts distinct claims that have at least one
    ``GroundingSupport`` row attributing the AgentRun's generated
    artifacts to them. The denominator counts distinct claims attached
    to the AgentRun's ResearchTask scope.

    null evidence_set_hash semantics
    --------------------------------
    Per QL-C spec line 165, AgentRuns whose latest
    ``ContextSnapshot.evidence_set_hash`` is null are included in the
    denominator with numerator=0 (uncovered). For runs that never
    attached a ResearchTask at all (no claims in scope), the metric
    reports ``denominator_nonzero=False`` and ``coverage=0.0`` so
    downstream AC-KPI-04 acceptance gating can reject these as masking
    failures rather than silently treating them as 0/0 success.
    """

    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
        raise CitationCoverageError(
            "tenant_id_invalid",
            "tenant_id must be a positive integer.",
        )

    # Confirm the AgentRun belongs to the supplied project. Bypassing
    # this lets a caller compute coverage for an AgentRun outside the
    # project boundary.
    run_row = (
        await session.execute(
            select(AgentRun.id, AgentRun.project_id).where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.project_id == project_id,
                AgentRun.id == agent_run_id,
            )
        )
    ).one_or_none()
    if run_row is None:
        raise CitationCoverageError(
            "agent_run_not_in_project",
            f"agent_run_id {agent_run_id} does not belong to project {project_id}.",
        )

    # Latest ContextSnapshot.evidence_set_hash. Per QL-C: a null /
    # missing ``evidence_set_hash`` row is allowed and means "no
    # Research/Evidence linkage" — the metric still reports the run.
    evidence_set_hash = await session.scalar(
        select(ContextSnapshot.evidence_set_hash)
        .where(
            ContextSnapshot.tenant_id == tenant_id,
            ContextSnapshot.run_id == agent_run_id,
        )
        .order_by(ContextSnapshot.created_at.desc(), ContextSnapshot.id.desc())
        .limit(1)
    )

    # Distinct claims in scope of the AgentRun. We resolve scope via
    # the ResearchTasks that the AgentRun's claims attach to — claims
    # are the canonical "what should be cited" unit (SP-010 §line 162).
    #
    # For P0 the AgentRun ↔ ResearchTask binding is single-tenant +
    # single-project; a run without any claim/research_task linkage has
    # ``denominator_nonzero=False`` and coverage=0.0 (uncovered) so the
    # AC-KPI-04 gate can distinguish "no scope" from "scope but all
    # uncovered".
    #
    # F-R5-003 mirror: dangling research_task / claim refs cannot leak
    # in because both are bound to the same (tenant_id, project_id)
    # via composite FKs from migration 0017.
    distinct_claim_stmt = (
        select(func.count(distinct(Claim.id)))
        .select_from(Claim)
        .join(
            ResearchTask,
            (Claim.tenant_id == ResearchTask.tenant_id)
            & (Claim.project_id == ResearchTask.project_id)
            & (Claim.research_task_id == ResearchTask.id),
        )
        .where(
            Claim.tenant_id == tenant_id,
            Claim.project_id == project_id,
            Claim.id.in_(
                select(GroundingSupport.claim_id).where(
                    GroundingSupport.tenant_id == tenant_id,
                    GroundingSupport.project_id == project_id,
                    GroundingSupport.agent_run_id == agent_run_id,
                )
            ),
        )
    )
    # Note: we evaluate scope by union of "claims grounded by this run"
    # plus "claims of the same ResearchTask as any grounded claim", to
    # match the QL-C definition ("claims within evaluated AgentRun").
    # Pre-Sprint-11 there is no separate AgentRun↔ResearchTask binding
    # column, so we use the claim → ResearchTask chain.
    scope_claims_stmt = (
        select(func.count(distinct(Claim.id)))
        .where(
            Claim.tenant_id == tenant_id,
            Claim.project_id == project_id,
            Claim.research_task_id.in_(
                select(distinct(Claim.research_task_id))
                .select_from(Claim)
                .join(
                    GroundingSupport,
                    (Claim.tenant_id == GroundingSupport.tenant_id)
                    & (Claim.project_id == GroundingSupport.project_id)
                    & (Claim.id == GroundingSupport.claim_id),
                )
                .where(
                    GroundingSupport.tenant_id == tenant_id,
                    GroundingSupport.project_id == project_id,
                    GroundingSupport.agent_run_id == agent_run_id,
                )
            ),
        )
    )

    distinct_claims = (await session.scalar(scope_claims_stmt)) or 0
    grounded_claims = (await session.scalar(distinct_claim_stmt)) or 0

    if distinct_claims == 0:
        # 0/0 path — denominator_nonzero=False, coverage=0.0 so the
        # AC-KPI-04 gate can reject it instead of treating it as success.
        coverage = 0.0
        denominator_nonzero = False
    else:
        coverage = grounded_claims / distinct_claims
        denominator_nonzero = True

    return CitationCoverageMetric(
        agent_run_id=agent_run_id,
        tenant_id=tenant_id,
        project_id=project_id,
        evidence_set_hash=evidence_set_hash,
        distinct_claims=int(distinct_claims),
        grounded_claims=int(grounded_claims),
        coverage=float(coverage),
        denominator_nonzero=denominator_nonzero,
    )


__all__ = [
    "CitationCoverageError",
    "CitationCoverageMetric",
    "compute_citation_coverage",
]
