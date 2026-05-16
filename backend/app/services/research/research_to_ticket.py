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


class ResearchToTicketAdapter:
    """Promote a project-scoped ResearchTask into a Ticket.

    The adapter accepts only server-owned identifiers through
    ``ResearchToTicketRequest``. ``artifact_hash`` and ``evidence_set_hash``
    are computed here from DB-loaded content and cannot be supplied by callers.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def promote(self, request: ResearchToTicketRequest) -> ResearchToTicketOutcome:
        await _ensure_tenant_context(self.session, request.tenant_id)

        bundle = await self._fetch_research_bundle(
            tenant_id=request.tenant_id,
            project_id=request.project_id,
            research_task_id=request.research_task_id,
        )

        reference = ResearchSetReference(
            project_id=request.project_id,
            research_task_id=request.research_task_id,
        )
        evidence_set_hash = await compute_evidence_set_hash(
            self.session,
            request.tenant_id,
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
        artifact_hash = _hash_canonical_json(research_summary)

        title_source = request.ticket_title_override or bundle.task.title
        title = _normalize_title(title_source)
        metadata = {
            "rls_ready": True,
            "research_task_id": str(request.research_task_id),
            "artifact_hash": artifact_hash,
            "evidence_set_hash": evidence_set_hash,
            "policy_version": policy_version,
            "claim_count": len(bundle.claims),
            "evidence_item_count": len(bundle.evidence_items),
            "provenance_json_hash": provenance_json_hash_prefix,
            "research_to_ticket_schema_version": _ARTIFACT_SCHEMA_VERSION,
        }

        ticket_payload = TicketCreate(
            repository_id=None,
            slug=_ticket_slug(request.research_task_id),
            title=title,
            description=_render_ticket_description(
                research_task_id=request.research_task_id,
                claim_count=len(bundle.claims),
                evidence_item_count=len(bundle.evidence_items),
                evidence_set_hash=evidence_set_hash,
                artifact_hash=artifact_hash,
            ),
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
            artifact_hash=artifact_hash,
            evidence_set_hash=evidence_set_hash,
            claim_count=len(bundle.claims),
            evidence_item_count=len(bundle.evidence_items),
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
    return f"research-{research_task_id.hex[-8:].lower()}"


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
    "ResearchToTicketAdapter",
    "promote_research_to_ticket",
]
