"""Research-to-Ticket artifact adapter (Sprint 10 BL-0118).

Promotes a server-owned ResearchTask + selected claim set into an
immutable ``artifacts`` row of ``kind='research_promotion'`` that a
downstream Ticket creation flow can consume.

server-owned-boundary §1 invariants:
- ``content_hash`` is computed by this adapter, never caller-supplied.
- The promoted ``evidence_set_hash`` is computed via
  ``compute_evidence_set_hash`` from the same ResearchSetReference;
  callers cannot smuggle a pre-computed value through.
- ``payload_data_class`` is bounded to ``internal`` (no provider call
  involved at promotion time — provider compliance gating happens at
  the downstream consumer that produces a generated artifact).
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.approval_request import ApprovalRequest
from backend.app.db.models.artifact import Artifact
from backend.app.db.models.claim import Claim
from backend.app.db.models.research_task import ResearchTask
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.repositories.artifact import assert_sha256_hex
from backend.app.schemas.research.evidence_set import ResearchSetReference
from backend.app.services.research.evidence_set_hash import (
    EMPTY_EVIDENCE_SET_HASH,
    compute_evidence_set_hash,
)

_RESEARCH_PROMOTION_KIND: str = "research_promotion"
_PROMOTION_TRUST_LEVEL: str = "validated_artifact"
_PROMOTION_ALGORITHM_ID: str = "taskmanagedai.research_to_ticket.v1"

# F-PR25-R8-003 fix (Codex R8 P1): payload_data_class is no longer
# hard-coded — accept caller-supplied classification (validated
# against the Provider Compliance Matrix ordinal). Stage 2 (server-
# side automatic classification from research/session metadata) is
# deferred to SP-011 / DD-04 classifier integration; in the meantime
# the caller is responsible for upgrading the class above ``internal``
# when the promotion content warrants ``confidential`` / ``pii``.
_ALLOWED_PAYLOAD_DATA_CLASSES: frozenset[str] = frozenset(
    {"public", "internal", "confidential", "pii"}
)


class ResearchToTicketError(ValueError):
    """Raised when a Research-to-Ticket promotion fails fail-closed.

    ``reason_code`` exposes the structured error category so downstream
    handlers can map it to audit events / API error responses.
    """

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"[{reason_code}] {message}")


@dataclass(frozen=True)
class ResearchToTicketArtifactView:
    """Read-side projection of the promoted artifact.

    Returns the ``Artifact`` ORM row plus a separate
    ``evidence_set_hash`` field so consumers do not need to re-parse the
    canonical body.
    """

    artifact: Artifact
    evidence_set_hash: str


def _canonical_summary(summary: str) -> str:
    """NFC-normalize + trim caller-supplied summary text.

    The promotion record stores a redacted/normalized summary in the
    artifact body. We avoid free-form caller content drift by collapsing
    to NFC + stripping leading/trailing whitespace.
    """

    return unicodedata.normalize("NFC", summary).strip()


def _content_hash(payload: dict[str, Any]) -> str:
    """Compute the artifact ``content_hash`` server-side.

    The payload is canonicalized via ``compute_evidence_set_hash``-style
    NFC + sha256 over the JCS body. We delegate canonicalization to the
    evidence_set_hash module's helpers via the embedded
    ``evidence_set_hash`` field (which is already server-canonical) and
    hash the additional promotion-specific fields here.
    """

    # Reuse the same canonical JSON path as evidence_set_hash for
    # cross-implementation reproducibility. Importing the private
    # canonical serializer locally keeps the dependency surface
    # contained to this adapter.
    from backend.app.services.research.evidence_set_hash import (
        _jcs_canonical_json,
    )

    canonical = _jcs_canonical_json(payload)
    normalized = unicodedata.normalize("NFC", canonical)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def promote_research_to_ticket(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    research_task_id: UUID,
    claim_ids: tuple[UUID, ...] = (),
    evidence_item_ids: tuple[UUID, ...] = (),
    run_id: UUID,
    summary: str,
    parent_artifact_id: UUID | None = None,
    approval_request_id: UUID | None = None,
    payload_data_class: str = "internal",
) -> ResearchToTicketArtifactView:
    """Create a Research-to-Ticket promotion artifact.

    Args:
        session: AsyncSession bound to the calling request's transaction.
        tenant_id: caller-supplied tenant context (server enforces match).
        project_id: project boundary that scopes the claim / evidence set.
        research_task_id: ResearchTask the promotion derives from.
        claim_ids: optional subset of claims to include. Empty tuple
            means "all claims of the ResearchTask" (matches
            ``ResearchSetReference`` semantics).
        evidence_item_ids: optional subset of evidence items.
        run_id: AgentRun id the promotion attributes to. The artifact
            row is bound to ``(tenant_id, run_id)`` via the existing
            ``artifacts.run_id`` FK so cross-run promotions are
            rejected at the DB layer.
        summary: caller-supplied free-text summary (NFC-normalized and
            stored in the artifact body for downstream Ticket display).
        parent_artifact_id: optional parent artifact (e.g. a previous
            promotion that this one supersedes).

    Returns:
        ``ResearchToTicketArtifactView`` holding the newly created
        ``artifacts`` row and the computed ``evidence_set_hash``.

    Raises:
        ResearchToTicketError: input invalid or the ResearchTask does
            not belong to the supplied project.
    """

    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
        raise ResearchToTicketError(
            "tenant_id_invalid",
            "tenant_id must be a positive integer.",
        )
    if not isinstance(summary, str) or not summary.strip():
        raise ResearchToTicketError(
            "summary_required",
            "summary must be a non-empty string.",
        )

    # F-PR25-R1-007 + F-PR25-R9-002 + F-PR25-R10-001 fix:
    # establish ``app.tenant_id`` BEFORE any tenant-scoped read —
    # including the ApprovalRequest lookup that follows. R9 added
    # the prologue comment but accidentally left the block at the
    # bottom of the function (line ~308). R10 moves the actual
    # set/assert calls to the top so the first tenant-scoped query
    # (the approval lookup) runs under the correct RLS context.
    current_tenant_id = await get_tenant_context(session)
    if current_tenant_id is None:
        await set_tenant_context(session, tenant_id)
    await assert_tenant_context(session, tenant_id)

    # F-PR25-R3-002 + F-PR25-R8-001 fix Stage 2 (Codex R3 P1 + R8 P1):
    # Research-to-Ticket promotion is ``task_write`` action class per
    # ADR-00003 and must bind an **approved** ApprovalRequest before
    # the artifact is created. Stage 1 (presence-only) was insufficient
    # — any non-null UUID (random, pending, rejected, cross-run) used
    # to pass. Stage 2 loads the row and verifies:
    #
    # - tenant_id matches (cross-tenant Approval reuse blocked)
    # - run_id matches (cross-run Approval reuse blocked)
    # - action_class == 'task_write' (Approval for a different
    #   action class cannot authorise a promotion)
    # - status == 'approved' (pending / rejected / expired /
    #   invalidated all reject)
    #
    # Full 4-binding verification (artifact_hash + policy_version +
    # provider_request_fingerprint additional checks) is deferred to
    # SP-008 once the Approval contract stabilises across all
    # ``task_write`` callers. The four checks here cover the security
    # boundary the R8 finding flagged: unapproved promotion seeding
    # Ticket work.
    if approval_request_id is None:
        raise ResearchToTicketError(
            "approval_request_required",
            "approval_request_id is required for Research-to-Ticket promotion "
            "(ADR-00003 task_write action class).",
        )
    # F-PR25-R9-004 fix (Codex R9 P1): lock the ApprovalRequest row
    # with ``FOR UPDATE`` so a concurrent invalidation/decision
    # cannot flip ``status`` from ``approved`` to ``invalidated``
    # between the verify query and the artifact INSERT below. The
    # whole adapter runs inside the request transaction; the row
    # lock is released on commit/rollback alongside the new
    # promotion artifact.
    approval_row = (
        await session.execute(
            select(
                ApprovalRequest.tenant_id,
                ApprovalRequest.run_id,
                ApprovalRequest.action_class,
                ApprovalRequest.status,
            )
            .where(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.id == approval_request_id,
            )
            .with_for_update()
        )
    ).one_or_none()
    if approval_row is None:
        raise ResearchToTicketError(
            "approval_request_not_found",
            f"approval_request_id {approval_request_id} not found for "
            f"tenant {tenant_id}.",
        )
    approval_tenant, approval_run_id, approval_action_class, approval_status = (
        approval_row
    )
    if approval_tenant != tenant_id:  # belt-and-braces (the WHERE clause already filtered)
        raise ResearchToTicketError(
            "approval_request_tenant_mismatch",
            f"approval_request_id {approval_request_id} belongs to a "
            f"different tenant.",
        )
    # F-PR25-R9-001 fix (Codex R9 P1): require ``approval_run_id ==
    # run_id`` strictly. Pre-R9 we accepted null ``run_id`` (the
    # "project-scope approval" case), but the schema does not yet
    # carry a project_id on ApprovalRequest, so an unbound approval
    # could be replayed across runs in the same tenant — letting a
    # previously approved promotion seed Ticket work for a different
    # AgentRun. Until the project-scope approval contract lands,
    # require an exact run binding.
    if approval_run_id is None:
        raise ResearchToTicketError(
            "approval_request_run_unbound",
            f"approval_request_id {approval_request_id} has run_id=NULL; "
            f"Research-to-Ticket requires run-bound approvals until the "
            f"project-scope approval contract lands.",
        )
    if approval_run_id != run_id:
        raise ResearchToTicketError(
            "approval_request_run_mismatch",
            f"approval_request_id {approval_request_id} is bound to run "
            f"{approval_run_id}, not {run_id}.",
        )
    if approval_action_class != "task_write":
        raise ResearchToTicketError(
            "approval_request_action_class_mismatch",
            f"approval_request_id {approval_request_id} has action_class "
            f"{approval_action_class!r}; Research-to-Ticket requires "
            f"'task_write'.",
        )
    if approval_status != "approved":
        raise ResearchToTicketError(
            "approval_request_not_approved",
            f"approval_request_id {approval_request_id} has status "
            f"{approval_status!r}; promotion requires 'approved'.",
        )

    # F-PR25-R8-003 fix Stage 1 (Codex R8 P1): caller-supplied
    # payload_data_class validated against the Provider Compliance
    # Matrix enum. Hard-coded ``"internal"`` would under-classify a
    # promotion whose summary or claim content is ``confidential``
    # or ``pii`` and downstream export/provider gates would let the
    # data pass under the wrong policy. Stage 2 (server-side
    # automatic classification from research/session metadata) is
    # deferred to SP-011 / DD-04 classifier integration.
    if payload_data_class not in _ALLOWED_PAYLOAD_DATA_CLASSES:
        raise ResearchToTicketError(
            "payload_data_class_invalid",
            f"payload_data_class {payload_data_class!r} must be one of "
            f"{sorted(_ALLOWED_PAYLOAD_DATA_CLASSES)}.",
        )

    # F-PR25-R1-004 fix (Codex R1 P1): the adapter bypasses
    # ``ArtifactRepository.create_artifact``, so the free-form summary
    # would skip the shared raw-secret scanner. Run the scanner here
    # against the caller-supplied string so a token-shaped value
    # (e.g. an OpenAI key copy-pasted into a summary) is rejected
    # **before** it lands in ``content_jsonb`` and becomes exportable.
    #
    # F-PR25-R2-007 fix (Codex R2 P2): ``assert_no_raw_secret`` raises a
    # plain ``ValueError`` rather than ``ResearchToTicketError``. Wrap
    # so the API handler maps it to a 4xx instead of a 500.
    try:
        assert_no_raw_secret({"summary": summary}, path="$research_to_ticket.summary")
    except ValueError as exc:
        raise ResearchToTicketError(
            "summary_contains_secret",
            f"summary failed raw-secret scan: {exc}",
        ) from exc

    # F-PR25-R10-001 fix: tenant context is established at the
    # function prologue (see top) ahead of the approval lookup.
    # The duplicate block that used to live here has been removed.

    # F-PR25-R1-001 fix (Codex R1 P1): also load the AgentRun and
    # require its ``project_id`` to match. The
    # ``artifacts_run_fkey`` is only ``(tenant_id, run_id)``, so a run
    # belonging to project B could otherwise receive a promotion
    # artifact whose payload says it promotes a project A research task.
    run_project_id = await session.scalar(
        select(AgentRun.project_id).where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.id == run_id,
        )
    )
    if run_project_id is None:
        raise ResearchToTicketError(
            "agent_run_not_found",
            f"agent_run_id {run_id} not found for tenant {tenant_id}.",
        )
    if run_project_id != project_id:
        raise ResearchToTicketError(
            "agent_run_project_mismatch",
            f"agent_run_id {run_id} does not belong to project {project_id}.",
        )

    # Verify the ResearchTask belongs to the tenant + project. Bypassing
    # this would let a caller promote claims that exist in a different
    # project (the FK chain catches this at insert, but failing here
    # produces a structured error_code instead of a raw IntegrityError).
    task_id = await session.scalar(
        select(ResearchTask.id).where(
            ResearchTask.tenant_id == tenant_id,
            ResearchTask.project_id == project_id,
            ResearchTask.id == research_task_id,
        )
    )
    if task_id is None:
        raise ResearchToTicketError(
            "research_task_not_in_project",
            f"research_task_id {research_task_id} does not belong to project {project_id}.",
        )

    # F-PR25-R1-008 fix (Codex R1 P2): ``ResearchSetReference`` rejects
    # duplicate claim_ids / evidence_item_ids via Pydantic validators,
    # which raises ``ValidationError`` rather than
    # ``ResearchToTicketError`` and would surface as a 500 to the
    # caller. Wrap so the API can return a structured 4xx instead.
    try:
        reference = ResearchSetReference(
            project_id=project_id,
            research_task_id=research_task_id,
            claim_ids=tuple(claim_ids),
            evidence_item_ids=tuple(evidence_item_ids),
        )
    except ValidationError as exc:
        raise ResearchToTicketError(
            "research_set_reference_invalid",
            f"ResearchSetReference validation failed: {exc}",
        ) from exc

    # F-PR25-R4-003 fix (Codex R4 P2): when ``parent_artifact_id`` is
    # supplied, verify the parent is (1) an existing artifact for the
    # same ``(tenant_id, run_id)`` (the ``artifacts_parent_artifact_fkey``
    # would also catch this at flush, but we want a structured 4xx
    # error_code instead of a raw IntegrityError) and (2) a
    # ``research_promotion`` for the same ``research_task_id``. Pre-R4
    # any same-run promotion could name an unrelated promotion as its
    # parent, and the downstream coverage query would treat the
    # unrelated parent as superseded — letting a malicious caller
    # shrink the active denominator and inflate citation_coverage.
    if parent_artifact_id is not None:
        parent_row = (
            await session.execute(
                select(Artifact.kind, Artifact.content_jsonb).where(
                    Artifact.tenant_id == tenant_id,
                    Artifact.run_id == run_id,
                    Artifact.id == parent_artifact_id,
                )
            )
        ).one_or_none()
        if parent_row is None:
            raise ResearchToTicketError(
                "parent_artifact_not_in_run",
                f"parent_artifact_id {parent_artifact_id} does not belong "
                f"to run {run_id} for tenant {tenant_id}.",
            )
        parent_kind, parent_body = parent_row
        if parent_kind != _RESEARCH_PROMOTION_KIND:
            raise ResearchToTicketError(
                "parent_artifact_wrong_kind",
                f"parent_artifact_id {parent_artifact_id} has kind "
                f"{parent_kind!r}, expected {_RESEARCH_PROMOTION_KIND!r}.",
            )
        parent_task_id = (parent_body or {}).get("research_task_id")
        if str(parent_task_id) != str(research_task_id):
            raise ResearchToTicketError(
                "parent_artifact_research_task_mismatch",
                f"parent_artifact_id {parent_artifact_id} promotes a "
                f"different research_task ({parent_task_id!r}); supersede "
                f"only promotions of the same research_task.",
            )

    # F-PR25-R4-002 + F-PR25-R5-006 fix: the documented "all claims of
    # the ResearchTask" path (empty ``claim_ids``) previously stored
    # only the task id in ``content_jsonb`` and let
    # ``compute_citation_coverage`` re-query the ``claims`` table at
    # read time. If claims were added after promotion the same run's
    # coverage shifted retroactively — the immutable
    # ``evidence_set_hash`` was bound to the older set. Resolve the
    # actual claim_ids server-side now and persist them in
    # ``content_jsonb`` so the scope is frozen at promotion time.
    # R5-006: sort the *explicit* claim_ids path too so the artifact
    # body's JSON array order is canonical and two requests with the
    # same claim_ids in different orders produce the same
    # ``content_hash`` (otherwise approval / dedup keyed on the hash
    # would diverge).
    resolved_claim_ids: tuple[UUID, ...] = tuple(sorted(claim_ids))
    if not resolved_claim_ids:
        rows = await session.execute(
            select(Claim.id).where(
                Claim.tenant_id == tenant_id,
                Claim.project_id == project_id,
                Claim.research_task_id == research_task_id,
            )
        )
        resolved_claim_ids = tuple(sorted(rows.scalars().all()))

    # F-PR25-R5-002 fix (Codex R5 P2): same immutability concern for
    # ``evidence_item_ids``. Pre-R5 the empty-tuple path let the hash
    # cover all current evidence items but persisted ``[]`` in the
    # artifact body, so an evidence item attached later would alter
    # the resolved set and diverge from the stored
    # ``evidence_set_hash``. Resolve and freeze the evidence_items
    # scope at promotion time too.
    resolved_evidence_item_ids: tuple[UUID, ...] = tuple(sorted(evidence_item_ids))
    if not resolved_evidence_item_ids and resolved_claim_ids:
        # Match compute_evidence_set_hash's ``_fetch_evidence_items``
        # logic: when no explicit evidence_item_ids are requested,
        # include all evidence_items attached to the promoted claims.
        from backend.app.db.models.evidence_item import EvidenceItem

        rows = await session.execute(
            select(EvidenceItem.id).where(
                EvidenceItem.tenant_id == tenant_id,
                EvidenceItem.project_id == project_id,
                EvidenceItem.claim_id.in_(resolved_claim_ids),
            )
        )
        resolved_evidence_item_ids = tuple(sorted(rows.scalars().all()))

    # F-PR25-R5-003 fix (Codex R5 P2): rebuild the
    # ``ResearchSetReference`` with the resolved (frozen) ID sets
    # before computing ``evidence_set_hash``. Pre-R5 the hash query
    # used the original open-ended reference, so under READ COMMITTED
    # isolation a concurrent INSERT between the resolve query and
    # the hash query could let the hash cover a claim/evidence item
    # not persisted in ``content_jsonb`` — splitting the artifact
    # body and its server-owned hash across different scopes.
    if resolved_claim_ids != tuple(sorted(claim_ids)) or (
        resolved_evidence_item_ids != tuple(sorted(evidence_item_ids))
    ):
        try:
            reference = ResearchSetReference(
                project_id=project_id,
                research_task_id=research_task_id,
                claim_ids=resolved_claim_ids,
                evidence_item_ids=resolved_evidence_item_ids,
            )
        except ValidationError as exc:
            raise ResearchToTicketError(
                "research_set_reference_invalid",
                f"ResearchSetReference rebuild failed: {exc}",
            ) from exc

    # Server-owned evidence_set_hash. Catches dangling claim_ids /
    # evidence_item_ids before we hash anything.
    try:
        evidence_set_hash = await compute_evidence_set_hash(
            session, tenant_id, reference
        )
    except ValueError as exc:
        raise ResearchToTicketError(
            "evidence_set_hash_compute_failed",
            f"compute_evidence_set_hash rejected the reference: {exc}",
        ) from exc

    if evidence_set_hash == EMPTY_EVIDENCE_SET_HASH:
        # Empty promotions are allowed for "ResearchTask exists but no
        # claims yet" workflows. We log this via the empty hash itself
        # so consumers can distinguish it.
        pass

    # Validate sha256 hex shape one more time as defense-in-depth.
    assert_sha256_hex(evidence_set_hash, field_name="evidence_set_hash")

    # F-PR25-R4-002 fix continued: persist the *resolved* claim_ids
    # in the artifact body so the scope is frozen at promotion time.
    # ``claim_count`` equals ``len(resolved_claim_ids)`` by
    # construction now.
    payload: dict[str, Any] = {
        "algorithm": _PROMOTION_ALGORITHM_ID,
        "project_id": str(project_id),
        "research_task_id": str(research_task_id),
        "evidence_set_hash": evidence_set_hash,
        "summary": _canonical_summary(summary),
        "claim_count": len(resolved_claim_ids),
        "claim_ids": [str(c) for c in resolved_claim_ids],
        # F-PR25-R5-002 fix: persist the resolved (frozen) evidence_item_ids
        # so the artifact body matches the evidence_set_hash exactly.
        "evidence_item_count": len(resolved_evidence_item_ids),
        "evidence_item_ids": [str(e) for e in resolved_evidence_item_ids],
        # F-PR25-R4-003 trace: record parent for audit even though it
        # is also on the artifact row (downstream consumers reading
        # only content_jsonb need it).
        "parent_artifact_id": (
            str(parent_artifact_id) if parent_artifact_id is not None else None
        ),
    }
    content_hash = _content_hash(payload)

    artifact = Artifact(
        tenant_id=tenant_id,
        run_id=run_id,
        kind=_RESEARCH_PROMOTION_KIND,
        content_hash=content_hash,
        content_jsonb=payload,
        payload_data_class=payload_data_class,
        trust_level=_PROMOTION_TRUST_LEVEL,
        exportable=True,
        parent_artifact_id=parent_artifact_id,
    )
    session.add(artifact)
    await session.flush()
    return ResearchToTicketArtifactView(
        artifact=artifact,
        evidence_set_hash=evidence_set_hash,
    )


def _claim_count_for_reference(
    tenant_id: int,
    reference: ResearchSetReference,
) -> Select[tuple[int]]:
    """SELECT count(*) FROM claims WHERE ... — kept as a helper so the
    caller's await scalar(...) reads cleanly."""

    stmt = select(Claim.id).where(
        Claim.tenant_id == tenant_id,
        Claim.project_id == reference.project_id,
        Claim.research_task_id == reference.research_task_id,
    )
    requested = frozenset(reference.claim_ids)
    if requested:
        stmt = stmt.where(Claim.id.in_(requested))

    # session.scalar(select(count(...))) avoids hydrating ORM rows.
    return select(func.count()).select_from(stmt.subquery())


__all__ = [
    "ResearchToTicketArtifactView",
    "ResearchToTicketError",
    "promote_research_to_ticket",
]
