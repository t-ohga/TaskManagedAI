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
_PROMOTION_PAYLOAD_DATA_CLASS: str = "internal"
_PROMOTION_TRUST_LEVEL: str = "validated_artifact"
_PROMOTION_ALGORITHM_ID: str = "taskmanagedai.research_to_ticket.v1"


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

    # F-PR25-R1-007 fix (Codex R1 P2) + F-PR25-R1-006 wider fix:
    # establish the tenant context before the first read so an RLS-
    # enabled deployment does not reject a legitimate request because
    # ``app.tenant_id`` was unset on a pooled connection.
    current_tenant_id = await get_tenant_context(session)
    if current_tenant_id is None:
        await set_tenant_context(session, tenant_id)
    await assert_tenant_context(session, tenant_id)

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

    # Resolve claim count for the body so downstream Tickets can display
    # the promotion scope without re-fetching.
    claim_count = await session.scalar(
        _claim_count_for_reference(tenant_id, reference)
    )
    if claim_count is None:
        # Defensive: scalar can return None on empty result; treat as 0.
        claim_count = 0

    payload: dict[str, Any] = {
        "algorithm": _PROMOTION_ALGORITHM_ID,
        "project_id": str(project_id),
        "research_task_id": str(research_task_id),
        "evidence_set_hash": evidence_set_hash,
        "summary": _canonical_summary(summary),
        "claim_count": int(claim_count),
        "claim_ids": [str(c) for c in sorted(claim_ids)],
        "evidence_item_ids": [str(e) for e in sorted(evidence_item_ids)],
    }
    content_hash = _content_hash(payload)

    artifact = Artifact(
        tenant_id=tenant_id,
        run_id=run_id,
        kind=_RESEARCH_PROMOTION_KIND,
        content_hash=content_hash,
        content_jsonb=payload,
        payload_data_class=_PROMOTION_PAYLOAD_DATA_CLASS,
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
