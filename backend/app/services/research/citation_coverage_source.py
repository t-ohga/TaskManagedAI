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

    # F-PR25-R6-001 + F-PR25-R7-002 fix: SP-010 QL-C spec line 165
    # mandates that a null ``ContextSnapshot.evidence_set_hash`` keep
    # the AgentRun in the **denominator** with **numerator=0**
    # (uncovered). R5-004 inadvertently regressed this by gating both
    # the denominator and the numerator on snapshot match; R6 split
    # the gates. R7 tightens the numerator gate to be **per-promotion**:
    #
    # - **Denominator scope** = all leaf promotion_rows regardless of
    #   snapshot match (R3-003 filtered superseded). Null / mismatched
    #   snapshot still counts the scope; coverage just reports 0.
    # - **Numerator scope** = only claims belonging to the active
    #   promotion(s) whose ``evidence_set_hash`` matches the
    #   ``ContextSnapshot.evidence_set_hash``. Pre-R7 a single
    #   snapshot match enabled the numerator over **all** active
    #   scopes, so a run with two promotions where only one matched
    #   the snapshot could count GroundingSupport rows for the
    #   unbound promotion as covered. R7 narrows the numerator's
    #   claim-set filter to the snapshot-bound subset.
    snapshot_bound_claim_ids: set[UUID] = set()
    snapshot_bound_task_ids: set[UUID] = set()
    if evidence_set_hash is not None:
        for row in promotion_rows:
            cjson = row[0] or {}
            promo_hash = cjson.get("evidence_set_hash")
            if not (isinstance(promo_hash, str) and promo_hash == evidence_set_hash):
                continue
            if "claim_ids" in cjson:
                claim_id_raw = cjson["claim_ids"]
                if claim_id_raw:
                    snapshot_bound_claim_ids.update(_parse_uuid_set(claim_id_raw))
            else:
                task_id_raw = cjson.get("research_task_id")
                if task_id_raw is not None:
                    try:
                        snapshot_bound_task_ids.add(UUID(str(task_id_raw)))
                    except (ValueError, AttributeError):
                        pass
    snapshot_matches_active = bool(
        snapshot_bound_claim_ids or snapshot_bound_task_ids
    )

    if not promotion_rows:
        # No research_promotion artifact at all: the AgentRun has no
        # defined citation scope. ``denominator_nonzero=False`` so
        # AC-KPI-04 gating can distinguish "no scope" from "scope
        # but uncovered".
        distinct_claims_count = 0
    else:
        # F-PR25-R6-002 fix (Codex R6 P2): count the **frozen**
        # ``claim_ids`` directly from ``content_jsonb`` instead of
        # re-querying the live ``claims`` table for non-legacy
        # artifacts. Pre-R6 a promoted claim deleted after promotion
        # disappeared from ``distinct_claims`` even though the
        # promotion artifact still scoped it — inflating coverage
        # retroactively. The frozen cardinality is immutable by
        # construction (R4-002).
        frozen_claim_ids: set[UUID] = set()
        for (content_jsonb,) in promotion_rows:
            cjson = content_jsonb or {}
            task_id_raw = cjson.get("research_task_id")
            # F-PR25-R5-001 fix: distinguish *present-but-empty*
            # ``claim_ids`` (R4-002 frozen all-claims for an empty
            # ResearchTask) from *missing* ``claim_ids`` (legacy
            # artifact). Frozen-empty is the canonical "zero claims"
            # scope; missing falls back to task expansion.
            if "claim_ids" in cjson:
                claim_id_raw = cjson["claim_ids"]
                if claim_id_raw:
                    frozen_claim_ids.update(_parse_uuid_set(claim_id_raw))
                    scope_claim_ids.update(_parse_uuid_set(claim_id_raw))
                # else: frozen empty scope — contributes 0 claims.
            elif task_id_raw is not None:
                # Legacy artifact lacking ``claim_ids`` — must
                # expand through ``claims`` (R6-002 explicitly carves
                # out legacy from the frozen-count fast path).
                try:
                    scope_task_ids.add(UUID(str(task_id_raw)))
                except (ValueError, AttributeError):
                    continue

        # Count distinct claims in scope:
        #   = explicit claim_ids + all claims of any open-scope task_ids
        # Both filtered by (tenant_id, project_id) for safety.
        # F-PR25-R6-002 + F-PR25-R7-001 fix: frozen claim_ids count is
        # immutable — use the in-memory cardinality directly rather
        # than re-querying the live ``claims`` table (which would
        # lose claims that have been deleted post-promotion). Only
        # legacy task-scope artifacts go through the SQL expansion
        # path, and the legacy count **excludes** claim IDs already
        # captured in ``frozen_claim_ids`` to preserve
        # ``count(distinct claim_id)`` semantics. Pre-R7 a mixed run
        # (legacy promotion overlapping a frozen promotion) added
        # ``len(frozen_claim_ids)`` to the legacy task count without
        # de-dup, under-reporting coverage by inflating the
        # denominator.
        if scope_task_ids:
            scope_stmt = select(func.count(distinct(Claim.id))).where(
                Claim.tenant_id == tenant_id,
                Claim.project_id == project_id,
                Claim.research_task_id.in_(scope_task_ids),
            )
            if frozen_claim_ids:
                scope_stmt = scope_stmt.where(Claim.id.notin_(frozen_claim_ids))
            legacy_count = (await session.scalar(scope_stmt)) or 0
            distinct_claims_count = int(legacy_count) + len(frozen_claim_ids)
        elif frozen_claim_ids:
            distinct_claims_count = len(frozen_claim_ids)
        else:
            # Promotion artifact present but the resolved scope is
            # empty (frozen all-claims with zero claims at promotion
            # time, or the artifact body is malformed). The
            # ``denominator_nonzero=False`` branch handles this.
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
    if distinct_claims_count > 0 and snapshot_matches_active:
        # F-PR25-R7-002 fix: restrict the numerator's claim-set filter
        # to **snapshot-bound** scopes only. Pre-R7 we used the union
        # of all active scopes (``scope_claim_ids`` /
        # ``scope_task_ids``), so a snapshot bound to promotion A let
        # GroundingSupport rows for promotion B (no matching snapshot)
        # count as covered. The per-promotion ``snapshot_bound_*``
        # sets are subsets of the denominator scopes by construction.
        scoped_claim_filter = []
        if snapshot_bound_claim_ids:
            scoped_claim_filter.append(
                GroundingSupport.claim_id.in_(snapshot_bound_claim_ids)
            )
        if snapshot_bound_task_ids:
            scoped_claim_filter.append(
                GroundingSupport.claim_id.in_(
                    select(Claim.id).where(
                        Claim.tenant_id == tenant_id,
                        Claim.project_id == project_id,
                        Claim.research_task_id.in_(snapshot_bound_task_ids),
                    )
                )
            )
        if scoped_claim_filter:
            grounded_stmt = grounded_stmt.where(or_(*scoped_claim_filter))

    # F-PR25-R2-003 + F-PR25-R4-004 + F-PR25-R5-004 + F-PR25-R6-001
    # fix: the numerator is forced to 0 unless at least one
    # ``research_promotion`` artifact's ``evidence_set_hash`` matches
    # the latest ``ContextSnapshot.evidence_set_hash``. R6 split this
    # from the denominator path so null/mismatched-snapshot runs stay
    # in the denominator (SP-010 §line 165 contract) while still
    # getting numerator=0.
    if not snapshot_matches_active:
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
