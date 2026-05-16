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

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.artifact import Artifact
from backend.app.db.models.claim import Claim
from backend.app.db.models.context_snapshot import ContextSnapshot
from backend.app.db.models.grounding_support import GroundingSupport


# F-PR25-R2-006 (Codex R2 P1): the promotion payload stores claim_ids /
# research_task_id as JSON strings. ``asyncpg`` requires ``uuid.UUID``
# values when binding to PG ``uuid`` columns; passing raw strings via
# ``IN`` raises ``DBAPIError`` at execute time. Parse the JSON strings
# back to UUID here so the SQL bind matches the column type.
def _parse_uuid_set(values: object) -> set[UUID]:
    result: set[UUID] = set()
    if not isinstance(values, (list, tuple, set)):
        return result
    for v in values:
        try:
            result.add(UUID(str(v)))
        except (ValueError, AttributeError):
            # Skip malformed entries silently — the producer is server-
            # owned (BL-0118 adapter) so this is defensive only.
            continue
    return result


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

    # F-PR25-R1-006 fix (Codex R1 P1): establish tenant context before
    # any tenant-scoped read so RLS-enabled deployments do not silently
    # return empty rows on a fresh / pooled connection where
    # ``app.tenant_id`` has not been set yet.
    current_tenant_id = await get_tenant_context(session)
    if current_tenant_id is None:
        await set_tenant_context(session, tenant_id)
    await assert_tenant_context(session, tenant_id)

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

    # F-PR25-R1-005 fix (Codex R1 P2): scope (denominator) is now
    # derived from the **research_promotion artifact** (BL-0118) bound
    # to this AgentRun, not from GroundingSupport rows. Previously, an
    # AgentRun that produced 0 GroundingSupports would report
    # ``distinct_claims=0`` and ``denominator_nonzero=False``, masking
    # the all-uncovered failure that AC-KPI-04 must catch.
    #
    # The research_promotion artifact's ``content_jsonb.claim_ids`` is
    # the canonical scope. If the artifact lists explicit ``claim_ids``,
    # that exact set is the denominator (caller chose specific claims).
    # If ``claim_ids`` is empty, the scope is **all** claims of the
    # promotion's ``research_task_id`` — same semantics as
    # ``ResearchSetReference`` empty-tuple convention.
    # F-PR25-R3-003 fix (Codex R3 P2): a later promotion can supersede
    # an earlier one via ``parent_artifact_id``. Pre-R3 every
    # ``research_promotion`` row was unioned into the scope, so a
    # narrowing promotion left stale claims from its parent counted in
    # the denominator and citation coverage was under-reported. Filter
    # out artifacts that are themselves a ``parent_artifact_id`` of
    # another ``research_promotion`` for the same run, keeping only
    # the leaf-most active chain links.
    superseded_subq = (
        select(Artifact.parent_artifact_id)
        .where(
            Artifact.tenant_id == tenant_id,
            Artifact.run_id == agent_run_id,
            Artifact.kind == "research_promotion",
            Artifact.parent_artifact_id.isnot(None),
        )
        .subquery()
    )
    promotion_rows = (
        await session.execute(
            select(Artifact.content_jsonb)
            .where(
                Artifact.tenant_id == tenant_id,
                Artifact.run_id == agent_run_id,
                Artifact.kind == "research_promotion",
                Artifact.id.notin_(select(superseded_subq)),
            )
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
    ).all()

    # Initialise scope sets up-front so the post-loop numerator filter
    # branch can rely on them even when ``promotion_rows`` is empty.
    # F-PR25-R2-006 fix (Codex R2 P1): bind as ``uuid.UUID`` rather
    # than ``str`` — asyncpg requires UUID type for PG ``uuid`` column
    # IN predicates.
    scope_claim_ids: set[UUID] = set()
    scope_task_ids: set[UUID] = set()

    if not promotion_rows:
        # No research_promotion artifact: the AgentRun has no defined
        # citation scope. ``denominator_nonzero=False`` so AC-KPI-04
        # gating can distinguish "no scope" from "scope but uncovered".
        distinct_claims_count = 0
    else:
        # Union of all promotion artifacts' scopes (an AgentRun may
        # promote multiple times). Each promotion contributes either a
        # specific claim_id set or the full ResearchTask scope.
        for (content_jsonb,) in promotion_rows:
            cjson = content_jsonb or {}
            task_id_raw = cjson.get("research_task_id")
            claim_id_raw = cjson.get("claim_ids", [])
            if claim_id_raw:
                scope_claim_ids.update(_parse_uuid_set(claim_id_raw))
            elif task_id_raw is not None:
                try:
                    scope_task_ids.add(UUID(str(task_id_raw)))
                except (ValueError, AttributeError):
                    continue

        # Count distinct claims in scope:
        #   = explicit claim_ids + all claims of any open-scope task_ids
        # Both filtered by (tenant_id, project_id) for safety.
        if scope_task_ids or scope_claim_ids:
            scope_stmt = select(func.count(distinct(Claim.id))).where(
                Claim.tenant_id == tenant_id,
                Claim.project_id == project_id,
            )
            id_filter = []
            if scope_claim_ids:
                id_filter.append(Claim.id.in_(scope_claim_ids))
            if scope_task_ids:
                id_filter.append(Claim.research_task_id.in_(scope_task_ids))
            scope_stmt = scope_stmt.where(or_(*id_filter))
            distinct_claims_count = (await session.scalar(scope_stmt)) or 0
        else:
            # Promotion artifact present but malformed (no claim_ids /
            # task_id) — defensively treat as no-scope.
            distinct_claims_count = 0

    # Numerator: distinct claims with >= 1 GroundingSupport from this
    # run, intersected with the scope (a stray GroundingSupport for a
    # claim outside the promoted scope should not inflate coverage).
    grounded_stmt = (
        select(func.count(distinct(GroundingSupport.claim_id)))
        .where(
            GroundingSupport.tenant_id == tenant_id,
            GroundingSupport.project_id == project_id,
            GroundingSupport.agent_run_id == agent_run_id,
        )
    )
    if distinct_claims_count > 0:
        # Restrict numerator to scope to avoid >100% coverage.
        if promotion_rows:
            scoped_claim_filter = []
            if scope_claim_ids:
                scoped_claim_filter.append(
                    GroundingSupport.claim_id.in_(scope_claim_ids)
                )
            if scope_task_ids:
                scoped_claim_filter.append(
                    GroundingSupport.claim_id.in_(
                        select(Claim.id).where(
                            Claim.tenant_id == tenant_id,
                            Claim.project_id == project_id,
                            Claim.research_task_id.in_(scope_task_ids),
                        )
                    )
                )
            if scoped_claim_filter:
                grounded_stmt = grounded_stmt.where(or_(*scoped_claim_filter))

    # F-PR25-R2-003 + F-PR25-R4-004 fix: the numerator is forced to 0
    # unless the ContextSnapshot.evidence_set_hash actually binds the
    # **promoted** scope. SP-010 QL-C spec line 165 only requires
    # checking that the hash is non-null, but a stale or unrelated
    # snapshot hash with a non-null value can otherwise pass
    # AC-KPI-04 with positive coverage on a run whose ContextSnapshot
    # never bound the promoted claim/evidence set. Verify the snapshot
    # hash matches one of the resolved promotion artifacts'
    # ``evidence_set_hash`` before allowing a non-zero numerator.
    promotion_hashes: set[str] = set()
    for (content_jsonb,) in promotion_rows:
        cjson = content_jsonb or {}
        promo_hash = cjson.get("evidence_set_hash")
        if isinstance(promo_hash, str):
            promotion_hashes.add(promo_hash)

    snapshot_matches_promotion = (
        evidence_set_hash is not None
        and evidence_set_hash in promotion_hashes
    )

    if not snapshot_matches_promotion:
        # null / mismatched snapshot hash → numerator=0 (uncovered).
        grounded_claims_final = 0
    else:
        grounded_claims_final = int((await session.scalar(grounded_stmt)) or 0)
    distinct_claims = distinct_claims_count

    if distinct_claims == 0:
        # 0/0 path — denominator_nonzero=False, coverage=0.0 so the
        # AC-KPI-04 gate can reject it instead of treating it as success.
        coverage = 0.0
        denominator_nonzero = False
    else:
        coverage = grounded_claims_final / distinct_claims
        denominator_nonzero = True
    grounded_claims = grounded_claims_final

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
