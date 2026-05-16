from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.actor import Actor
from backend.app.db.models.approval_request import ApprovalRequest
from backend.app.db.models.claim import Claim
from backend.app.db.models.evidence_item import EvidenceItem
from backend.app.db.models.evidence_source import EvidenceSource
from backend.app.db.models.research_task import ResearchTask
from backend.app.domain.agent_runtime.operation_context import canonical_json_dumps
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.repositories.ticket import TicketRepository
from backend.app.schemas.research.evidence_set import ResearchSetReference
from backend.app.schemas.research.research_to_ticket import (
    ResearchToTicketOutcome,
    ResearchToTicketRequest,
)
from backend.app.schemas.ticket import TicketCreate
from backend.app.services.policy_pack.loader import get_policy_pack
from backend.app.services.research.evidence_set_hash import compute_evidence_set_hash
from backend.app.services.research.prov_validator import validate_provenance_json

_ARTIFACT_SCHEMA_VERSION = "1.0.0"
_ARTIFACT_KIND = "research_summary"
_AUDIT_EVENT_TYPE = "research_to_ticket_promoted"
_TITLE_MAX_CHARS = 200


@dataclass(frozen=True, slots=True)
class _ResearchBundle:
    task: ResearchTask
    claims: tuple[Claim, ...]
    evidence_items: tuple[EvidenceItem, ...]
    evidence_sources: tuple[EvidenceSource, ...]


@dataclass(frozen=True, slots=True)
class PromotionArtifactPreview:
    """Server-computed canonical promotion artifact preview (no DB mutation).

    Returned by ``ResearchToTicketAdapter.prepare_promotion_artifact``. The
    caller uses ``artifact_hash`` to bind an ApprovalRequest before
    invoking ``promote`` (which validates the same hash against the
    approved ApprovalRequest).
    """

    artifact_hash: str
    evidence_set_hash: str
    policy_version: str
    provenance_json_hash_prefix: str
    title: str
    slug: str
    description: str
    claim_count: int
    evidence_item_count: int


class ResearchToTicketAdapter:
    """Promote a project-scoped ResearchTask into a Ticket.

    The adapter accepts only server-owned identifiers through
    ``ResearchToTicketRequest``. ``artifact_hash`` and ``evidence_set_hash``
    are computed here from DB-loaded content and cannot be supplied by callers.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def prepare_promotion_artifact(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        research_task_id: UUID,
        requested_by_actor_id: UUID,
        ticket_title_override: str | None = None,
    ) -> PromotionArtifactPreview:
        """Compute the canonical promotion artifact WITHOUT mutating state.

        F-PR24-R1-004 P1 adopt: callers use the returned ``artifact_hash``
        to create an ApprovalRequest binding before calling ``promote``,
        which then validates that the approved ApprovalRequest carries the
        same hash. The preview is deterministic for a given
        ``(tenant_id, project_id, research_task_id, ticket_title_override)``
        DB snapshot.
        """

        await _ensure_tenant_context(self.session, tenant_id)
        bundle = await self._fetch_research_bundle(
            tenant_id=tenant_id,
            project_id=project_id,
            research_task_id=research_task_id,
        )
        reference = ResearchSetReference(
            project_id=project_id,
            research_task_id=research_task_id,
        )
        evidence_set_hash = await compute_evidence_set_hash(
            self.session,
            tenant_id,
            reference,
        )
        policy_version = get_policy_pack().policy_version
        provenance_json_hash_prefix = _provenance_hash_prefix(bundle.claims)
        research_summary = _build_research_summary_artifact(
            bundle=bundle,
            evidence_set_hash=evidence_set_hash,
            policy_version=policy_version,
            provenance_json_hash_prefix=provenance_json_hash_prefix,
        )
        title_source = ticket_title_override or bundle.task.title
        title = _normalize_title(title_source)
        slug = _ticket_slug(research_task_id)
        description = _render_ticket_description_pre_hash(
            research_task_id=research_task_id,
            claim_count=len(bundle.claims),
            evidence_item_count=len(bundle.evidence_items),
            evidence_set_hash=evidence_set_hash,
        )
        # F-PR24-R1-003 P1 adopt: hash includes the finalized ticket fields
        # (title / slug / description signature / status / priority /
        # created_by_actor_id) so two Tickets with different titles cannot
        # share the same artifact_hash.
        canonical_ticket_artifact = {
            **research_summary,
            "ticket": {
                "title": title,
                "slug": slug,
                "description_hash": _hash_text(description),
                "status": "open",
                "priority": "medium",
                "created_by_actor_id": str(requested_by_actor_id),
            },
        }
        artifact_hash = _hash_canonical_json(canonical_ticket_artifact)
        return PromotionArtifactPreview(
            artifact_hash=artifact_hash,
            evidence_set_hash=evidence_set_hash,
            policy_version=policy_version,
            provenance_json_hash_prefix=provenance_json_hash_prefix,
            title=title,
            slug=slug,
            description=description,
            claim_count=len(bundle.claims),
            evidence_item_count=len(bundle.evidence_items),
        )

    async def promote(self, request: ResearchToTicketRequest) -> ResearchToTicketOutcome:
        preview = await self.prepare_promotion_artifact(
            tenant_id=request.tenant_id,
            project_id=request.project_id,
            research_task_id=request.research_task_id,
            requested_by_actor_id=request.requested_by_actor_id,
            ticket_title_override=request.ticket_title_override,
        )
        artifact_hash = preview.artifact_hash
        evidence_set_hash = preview.evidence_set_hash
        policy_version = preview.policy_version
        provenance_json_hash_prefix = preview.provenance_json_hash_prefix
        title = preview.title
        slug = preview.slug
        description = preview.description

        # F-PR24-R1-004 P1 adopt: enforce Approval 4 整合 binding before any
        # Ticket mutation (ADR-00003 §"Approval 4 整合 (server-owned-boundary §3)").
        # The caller supplies ``approval_request_id`` referencing a
        # **pre-existing approved** ApprovalRequest whose artifact_hash MUST
        # equal the server-computed canonical_ticket_artifact hash. The
        # adapter never creates ApprovalRequest itself (caller manages submit
        # via the existing Approval repository) and never mutates Tickets
        # without a matching approval.
        await self._assert_approval_binding(
            tenant_id=request.tenant_id,
            project_id=request.project_id,
            research_task_id=request.research_task_id,
            approval_request_id=request.approval_request_id,
            requested_by_actor_id=request.requested_by_actor_id,
            artifact_hash=artifact_hash,
            policy_version=policy_version,
            expected_provider_request_fingerprint=request.expected_provider_request_fingerprint,
        )

        metadata = {
            "rls_ready": True,
            "research_task_id": str(request.research_task_id),
            "artifact_hash": artifact_hash,
            "evidence_set_hash": evidence_set_hash,
            "policy_version": policy_version,
            "claim_count": preview.claim_count,
            "evidence_item_count": preview.evidence_item_count,
            "provenance_json_hash": provenance_json_hash_prefix,
            "approval_request_id": str(request.approval_request_id),
            "research_to_ticket_schema_version": _ARTIFACT_SCHEMA_VERSION,
        }

        ticket_payload = TicketCreate(
            repository_id=None,
            slug=slug,
            title=title,
            description=description,
            status="open",
            priority="medium",
            created_by_actor_id=request.requested_by_actor_id,
            metadata=metadata,
        ).model_dump(exclude_none=True)

        ticket = await TicketRepository(self.session).create_in_project(
            tenant_id=request.tenant_id,
            project_id=request.project_id,
            payload=ticket_payload,
        )

        promoted_at = datetime.now(tz=UTC)
        audit_payload = {
            "tenant_id": request.tenant_id,
            "actor_id": str(request.requested_by_actor_id),
            "research_task_id": str(request.research_task_id),
            "ticket_id": str(ticket.id),
            "claim_id": None,
            "evidence_set_hash": evidence_set_hash,
            "provenance_json_hash": provenance_json_hash_prefix,
            "artifact_hash": artifact_hash,
            "approval_request_id": str(request.approval_request_id),
            "policy_version": policy_version,
            "trace_id": None,
            "correlation_id": None,
            "timestamp": promoted_at.isoformat(),
        }
        await AuditEventRepository(self.session).append(
            tenant_id=request.tenant_id,
            event_type=_AUDIT_EVENT_TYPE,
            payload=audit_payload,
            actor_id=request.requested_by_actor_id,
            trace_id=None,
            correlation_id=None,
        )

        return ResearchToTicketOutcome(
            ticket_id=ticket.id,
            approval_request_id=request.approval_request_id,
            artifact_hash=artifact_hash,
            evidence_set_hash=evidence_set_hash,
            claim_count=preview.claim_count,
            evidence_item_count=preview.evidence_item_count,
        )

    async def _assert_approval_binding(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        research_task_id: UUID,
        approval_request_id: UUID,
        requested_by_actor_id: UUID,
        artifact_hash: str,
        policy_version: str,
        expected_provider_request_fingerprint: str | None,
    ) -> None:
        """Validate ApprovalRequest before any Ticket mutation (F-PR24-R1-004 P1).

        Per ADR-00003 §"Approval 4 整合", Research-to-Ticket promotion must
        only mutate Tickets after a matching ApprovalRequest has reached
        ``status=approved`` with **field-by-field agreement** to the
        server-computed canonical promotion context (F-PR24-R2-001 P1 adopt:
        the policy_version snapshot must match too -- a pre-approval that
        was granted under a different policy version cannot be replayed).
        The decider must be a **human actor** (F-PR24-R2-003 P1 adopt:
        non-human deciders such as service/agent actors are rejected for
        Ticket mutations per project rules).

        The caller (orchestrator / research session worker) is responsible
        for submitting the ApprovalRequest through the existing Approval
        workflow; the adapter verifies the binding and is fail-closed
        otherwise.
        """

        # F-PR24-R3-005 P1 adopt: lock the approval row so a concurrent
        # invalidate / expire transition cannot occur between this read and
        # the Ticket INSERT. Without FOR UPDATE the default read-committed
        # isolation allows another transaction to set status='invalidated'
        # immediately after we observe 'approved', leading to a mutation
        # under a no-longer-valid approval.
        approval = await self.session.scalar(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.id == approval_request_id,
            )
            .with_for_update()
        )
        if approval is None:
            raise ValueError(
                "approval_request_id is not reachable in tenant"
            )
        if approval.status != "approved":
            raise ValueError(
                f"approval_request must be approved before promotion; "
                f"current status={approval.status!r}"
            )
        if approval.action_class != "task_write":
            raise ValueError(
                "approval_request must bind action_class='task_write' for "
                "Research-to-Ticket promotion"
            )
        if approval.artifact_hash != artifact_hash:
            # Caller-supplied approval reaches a different artifact than the
            # server-computed canonical promotion hash; reject without
            # surfacing either hash in the error (audit only).
            raise ValueError(
                "approval_request.artifact_hash does not match the canonical "
                "promotion artifact"
            )
        if approval.policy_version != policy_version:
            # F-PR24-R2-001 P1 adopt: stale policy_version reject -- prevents
            # replay of approval granted under a different policy pack.
            raise ValueError(
                "approval_request.policy_version does not match the current "
                "policy snapshot used for promotion"
            )
        # F-PR24-R3-002 P1 + F-PR24-R4-001 P1 adopt: provider_request_fingerprint
        # binding (Approval 4 整合 §3 stale/replay protection). The Research
        # session that produced the promotion artifact may or may not be
        # provider-driven; when it is, the approval row carries the provider
        # call's canonical OperationContext fingerprint, and the caller
        # passes the same value via ``expected_provider_request_fingerprint``.
        # Both must be None (non-provider workflow) OR both must match
        # (provider-bound workflow). Asymmetric None/non-None indicates
        # approval scope mismatch and is rejected fail-closed.
        if approval.provider_request_fingerprint != expected_provider_request_fingerprint:
            raise ValueError(
                "approval_request.provider_request_fingerprint does not "
                "match the caller-asserted fingerprint for this promotion "
                "(asymmetric None / mismatched value indicates approval "
                "scope mismatch)"
            )
        expected_resource_ref = f"research_task:{research_task_id}"
        if approval.resource_ref != expected_resource_ref:
            raise ValueError(
                "approval_request.resource_ref does not match the "
                "research_task_id binding"
            )
        if approval.requested_by_actor_id != requested_by_actor_id:
            raise ValueError(
                "approval_request.requested_by_actor_id does not match the "
                "promoting actor"
            )
        # F-PR24-R2-003 P1 adopt: human-decider invariant. The Approval
        # workflow allows service/agent deciders for some flows, but
        # Ticket mutations (task_write action_class) require a human
        # decider per project rules.
        if approval.decided_by_actor_id is None:
            raise ValueError(
                "approval_request must have a recorded decider before promotion"
            )
        decider_actor_type = await self.session.scalar(
            select(Actor.actor_type).where(
                Actor.tenant_id == tenant_id,
                Actor.id == approval.decided_by_actor_id,
            )
        )
        if decider_actor_type != "human":
            raise ValueError(
                "approval_request decider must be a human actor for "
                "Research-to-Ticket promotion"
            )

    async def _fetch_research_bundle(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        research_task_id: UUID,
    ) -> _ResearchBundle:
        task = await self.session.scalar(
            select(ResearchTask).where(
                ResearchTask.tenant_id == tenant_id,
                ResearchTask.project_id == project_id,
                ResearchTask.id == research_task_id,
            )
        )
        if task is None:
            raise ValueError("research_task_id not reachable in tenant/project")

        claims_result = await self.session.execute(
            select(Claim)
            .where(
                Claim.tenant_id == tenant_id,
                Claim.project_id == project_id,
                Claim.research_task_id == research_task_id,
            )
            .order_by(Claim.id)
        )
        claims = tuple(claims_result.scalars().all())

        # F-PR24-R2-004 P2 adopt: re-validate PROV at the promotion
        # boundary. ClaimRepository validates provenance_json at write
        # time, but claims imported / backfilled through other paths
        # may bypass that validation; re-running validate_provenance_json
        # here ensures malformed PROV fails closed before becoming part
        # of an approved Ticket artifact.
        for claim in claims:
            validate_provenance_json(claim.provenance_json)

        if not claims:
            return _ResearchBundle(
                task=task,
                claims=(),
                evidence_items=(),
                evidence_sources=(),
            )

        claim_ids = tuple(claim.id for claim in claims)
        evidence_items_result = await self.session.execute(
            select(EvidenceItem)
            .where(
                EvidenceItem.tenant_id == tenant_id,
                EvidenceItem.project_id == project_id,
                EvidenceItem.claim_id.in_(claim_ids),
            )
            .order_by(EvidenceItem.claim_id, EvidenceItem.id)
        )
        evidence_items = tuple(evidence_items_result.scalars().all())
        evidence_sources = await self._fetch_evidence_sources(
            tenant_id=tenant_id,
            evidence_items=evidence_items,
        )

        return _ResearchBundle(
            task=task,
            claims=claims,
            evidence_items=evidence_items,
            evidence_sources=evidence_sources,
        )

    async def _fetch_evidence_sources(
        self,
        *,
        tenant_id: int,
        evidence_items: tuple[EvidenceItem, ...],
    ) -> tuple[EvidenceSource, ...]:
        source_ids = tuple({item.source_id for item in evidence_items})
        if not source_ids:
            return ()

        result = await self.session.execute(
            select(EvidenceSource)
            .where(
                EvidenceSource.tenant_id == tenant_id,
                EvidenceSource.id.in_(source_ids),
            )
            .order_by(EvidenceSource.id)
        )
        sources = tuple(result.scalars().all())
        if {source.id for source in sources} != set(source_ids):
            raise ValueError("evidence source binding is incomplete for referenced evidence items.")
        return sources


async def promote_research_to_ticket(
    session: AsyncSession,
    request: ResearchToTicketRequest,
) -> ResearchToTicketOutcome:
    return await ResearchToTicketAdapter(session).promote(request)


async def _ensure_tenant_context(session: AsyncSession, tenant_id: int) -> None:
    _require_tenant_id(tenant_id)
    current_tenant_id = await get_tenant_context(session)
    if current_tenant_id is None:
        await set_tenant_context(session, tenant_id)
    await assert_tenant_context(session, tenant_id)


def _require_tenant_id(tenant_id: int) -> None:
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
        raise ValueError("tenant_id must be a positive integer.")


def _hash_canonical_json(payload: object) -> str:
    canonical_json = canonical_json_dumps(payload)
    normalized = unicodedata.normalize("NFC", canonical_json)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _hash_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _ticket_slug(research_task_id: UUID) -> str:
    # F-PR24-R1-002 P2 adopt: 32-bit (8-hex) suffix gives ~65k birthday-collision
    # tickets per project; tickets unique on (tenant_id, project_id, slug) would
    # then reject promotion of a research task whose suffix collides with another
    # already promoted task in the same project. Use the full UUID (128 bits)
    # for collision-resistance; CHECK ``^[a-z0-9]+(-[a-z0-9]+)*$`` accepts the
    # UUID hex+hyphen form.
    return f"research-{str(research_task_id).lower()}"


def _normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        normalized = "Untitled research task"
    return normalized[:_TITLE_MAX_CHARS]


def _provenance_hash_prefix(claims: tuple[Claim, ...]) -> str:
    provenance_hashes = [
        {
            "claim_id": str(claim.id),
            "provenance_json_hash": _hash_canonical_json(claim.provenance_json),
        }
        for claim in sorted(claims, key=lambda item: str(item.id))
    ]
    return _hash_canonical_json(
        {
            "algorithm": "taskmanagedai.research_to_ticket.provenance_hash.v1",
            "claims": provenance_hashes,
        }
    )[:16]


def _build_research_summary_artifact(
    *,
    bundle: _ResearchBundle,
    evidence_set_hash: str,
    policy_version: str,
    provenance_json_hash_prefix: str,
) -> dict[str, object]:
    return {
        "schema_version": _ARTIFACT_SCHEMA_VERSION,
        "artifact_kind": _ARTIFACT_KIND,
        "research_task": {
            "id": str(bundle.task.id),
            "project_id": str(bundle.task.project_id),
            "title": _normalize_title(bundle.task.title),
            "status": bundle.task.status,
        },
        "claim_count": len(bundle.claims),
        "evidence_item_count": len(bundle.evidence_items),
        "evidence_source_count": len(bundle.evidence_sources),
        "evidence_set_hash": evidence_set_hash,
        "policy_version": policy_version,
        "provenance_json_hash": provenance_json_hash_prefix,
        "claim_ids": [str(claim.id) for claim in sorted(bundle.claims, key=lambda item: str(item.id))],
        "evidence_item_ids": [
            str(item.id) for item in sorted(bundle.evidence_items, key=lambda item: str(item.id))
        ],
    }


def _render_ticket_description_pre_hash(
    *,
    research_task_id: UUID,
    claim_count: int,
    evidence_item_count: int,
    evidence_set_hash: str,
) -> str:
    """Build the ticket description text WITHOUT artifact_hash dependency.

    F-PR24-R1-003 P1 adopt: artifact_hash is computed over the canonical
    promotion artifact (which includes ``description_hash``), so the
    description text itself must not depend on artifact_hash (otherwise
    chicken-and-egg). Render the description from inputs that are stable
    before hashing.
    """

    return "\n".join(
        [
            f"Promoted from research task {research_task_id}.",
            f"Claims: {claim_count}",
            f"Evidence items: {evidence_item_count}",
            f"Evidence set hash: {evidence_set_hash[:16]}",
        ]
    )


def _render_ticket_description(
    *,
    research_task_id: UUID,
    claim_count: int,
    evidence_item_count: int,
    evidence_set_hash: str,
    artifact_hash: str,
) -> str:
    return "\n".join(
        [
            f"Promoted from research task {research_task_id}.",
            f"Claims: {claim_count}",
            f"Evidence items: {evidence_item_count}",
            f"Evidence set hash: {evidence_set_hash[:16]}",
            f"Artifact hash: {artifact_hash[:16]}",
        ]
    )


__all__ = [
    "PromotionArtifactPreview",
    "ResearchToTicketAdapter",
    "promote_research_to_ticket",
]
