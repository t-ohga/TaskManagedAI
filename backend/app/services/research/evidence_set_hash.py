from __future__ import annotations

import hashlib
import unicodedata
from collections import defaultdict
from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit
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
from backend.app.schemas.research.evidence_set import ResearchSetReference

_ALGORITHM_ID = "taskmanagedai.evidence_set_hash.v1"


def _require_tenant_id(tenant_id: int) -> None:
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
        raise ValueError("tenant_id must be a positive integer.")


async def _ensure_tenant_context(session: AsyncSession, tenant_id: int) -> None:
    _require_tenant_id(tenant_id)
    current_tenant_id = await get_tenant_context(session)
    if current_tenant_id is None:
        await set_tenant_context(session, tenant_id)
    await assert_tenant_context(session, tenant_id)


def _normalize_string(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _hash_text(value: str) -> str:
    normalized = _normalize_string(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _hash_canonical_payload(payload: object) -> str:
    canonical_json = canonical_json_dumps(payload)
    normalized = unicodedata.normalize("NFC", canonical_json)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_url(value: str) -> str:
    normalized = _normalize_string(value).strip()
    try:
        parsed = urlsplit(normalized)
    except ValueError:
        return normalized.rstrip("/")

    scheme = parsed.scheme.lower()
    if not scheme or not parsed.netloc:
        return normalized.rstrip("/")

    hostname = parsed.hostname.lower() if parsed.hostname else ""
    if not hostname:
        return normalized.rstrip("/")

    try:
        port = parsed.port
    except ValueError:
        port = None

    default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    port_part = "" if port is None or default_port else f":{port}"

    userinfo = ""
    if parsed.username is not None:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo = f"{userinfo}:{parsed.password}"
        userinfo = f"{userinfo}@"

    host = hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"

    path = _normalize_string(parsed.path).rstrip("/")
    query = _normalize_string(parsed.query)
    fragment = _normalize_string(parsed.fragment)
    return urlunsplit((scheme, f"{userinfo}{host}{port_part}", path, query, fragment))


def _empty_payload() -> dict[str, object]:
    return {
        "algorithm": _ALGORITHM_ID,
        "research_task_id": None,
        "claims": [],
    }


EMPTY_EVIDENCE_SET_HASH = _hash_canonical_payload(_empty_payload())


async def compute_evidence_set_hash(
    session: AsyncSession,
    tenant_id: int,
    reference: ResearchSetReference | None,
) -> str:
    """Compute the server-owned normalized evidence set hash.

    The caller supplies only server-owned identifiers. Claims, evidence items,
    and sources are fetched under tenant_id + project_id + research_task_id
    binding before the canonical payload is hashed.
    """

    _require_tenant_id(tenant_id)

    if reference is None:
        return EMPTY_EVIDENCE_SET_HASH
    if not isinstance(reference, ResearchSetReference):
        raise TypeError("reference must be ResearchSetReference or None.")

    await _ensure_tenant_context(session, tenant_id)
    await _assert_research_task_belongs_to_project(session, tenant_id, reference)

    claims = await _fetch_claims(session, tenant_id, reference)
    evidence_items = await _fetch_evidence_items(session, tenant_id, reference, claims)
    evidence_sources = await _fetch_evidence_sources(session, tenant_id, evidence_items)

    payload = _build_evidence_payload(reference, claims, evidence_items, evidence_sources)
    return _hash_canonical_payload(payload)


async def _assert_research_task_belongs_to_project(
    session: AsyncSession,
    tenant_id: int,
    reference: ResearchSetReference,
) -> None:
    task_id = await session.scalar(
        select(ResearchTask.id).where(
            ResearchTask.tenant_id == tenant_id,
            ResearchTask.project_id == reference.project_id,
            ResearchTask.id == reference.research_task_id,
        )
    )
    if task_id is None:
        raise ValueError("research_task_id does not belong to tenant_id + project_id.")


async def _fetch_claims(
    session: AsyncSession,
    tenant_id: int,
    reference: ResearchSetReference,
) -> list[Claim]:
    stmt = select(Claim).where(
        Claim.tenant_id == tenant_id,
        Claim.project_id == reference.project_id,
        Claim.research_task_id == reference.research_task_id,
    )
    requested_claim_ids = frozenset(reference.claim_ids)
    if requested_claim_ids:
        stmt = stmt.where(Claim.id.in_(requested_claim_ids))

    result = await session.execute(stmt)
    claims = sorted(result.scalars().all(), key=lambda claim: str(claim.id))

    if requested_claim_ids and {claim.id for claim in claims} != requested_claim_ids:
        raise ValueError("claim_ids must all belong to tenant_id + project_id + research_task_id.")

    return claims


async def _fetch_evidence_items(
    session: AsyncSession,
    tenant_id: int,
    reference: ResearchSetReference,
    claims: list[Claim],
) -> list[EvidenceItem]:
    claim_ids = frozenset(claim.id for claim in claims)
    requested_item_ids = frozenset(reference.evidence_item_ids)

    if not claim_ids:
        if requested_item_ids:
            raise ValueError("evidence_item_ids cannot be attached to an empty claim set.")
        return []

    stmt = select(EvidenceItem).where(
        EvidenceItem.tenant_id == tenant_id,
        EvidenceItem.project_id == reference.project_id,
    )
    if requested_item_ids:
        stmt = stmt.where(EvidenceItem.id.in_(requested_item_ids))
    else:
        stmt = stmt.where(EvidenceItem.claim_id.in_(claim_ids))

    result = await session.execute(stmt)
    items = sorted(
        result.scalars().all(),
        key=lambda item: (str(item.source_id), str(item.claim_id), str(item.id)),
    )

    if requested_item_ids and {item.id for item in items} != requested_item_ids:
        raise ValueError("evidence_item_ids must all belong to tenant_id + project_id.")

    if any(item.claim_id not in claim_ids for item in items):
        raise ValueError("evidence_item_ids must belong to the referenced claim set.")

    return items


async def _fetch_evidence_sources(
    session: AsyncSession,
    tenant_id: int,
    evidence_items: list[EvidenceItem],
) -> dict[UUID, EvidenceSource]:
    source_ids = frozenset(item.source_id for item in evidence_items)
    if not source_ids:
        return {}

    result = await session.execute(
        select(EvidenceSource).where(
            EvidenceSource.tenant_id == tenant_id,
            EvidenceSource.id.in_(source_ids),
        )
    )
    sources = {source.id: source for source in result.scalars().all()}
    if set(sources) != source_ids:
        raise ValueError("evidence source binding is incomplete for referenced evidence items.")
    return sources


def _build_evidence_payload(
    reference: ResearchSetReference,
    claims: list[Claim],
    evidence_items: list[EvidenceItem],
    evidence_sources: Mapping[UUID, EvidenceSource],
) -> dict[str, object]:
    items_by_claim_id: dict[UUID, list[EvidenceItem]] = defaultdict(list)
    for item in evidence_items:
        items_by_claim_id[item.claim_id].append(item)

    claim_payloads: list[dict[str, object]] = []
    for claim in sorted(claims, key=lambda item: str(item.id)):
        claim_payloads.append(
            {
                "claim_id": str(claim.id),
                "claim_text_hash": _hash_text(claim.claim_text),
                "freshness_score": claim.freshness_score,
                "provenance_bundle_hash": _hash_canonical_payload(claim.provenance_json),
                "evidence_items": [
                    _evidence_item_payload(item, evidence_sources[item.source_id])
                    for item in sorted(
                        items_by_claim_id.get(claim.id, []),
                        key=lambda item: (str(item.source_id), str(item.id)),
                    )
                ],
            }
        )

    return {
        "algorithm": _ALGORITHM_ID,
        "project_id": str(reference.project_id),
        "research_task_id": str(reference.research_task_id),
        "claims": claim_payloads,
    }


def _evidence_item_payload(
    item: EvidenceItem,
    source: EvidenceSource,
) -> dict[str, object]:
    return {
        "evidence_item_id": str(item.id),
        "source_id": str(item.source_id),
        "source_url_hash": _hash_text(_normalize_url(source.canonical_url)),
        "source_content_hash": source.content_hash,
        "locator_hash": _hash_text(item.locator),
        "relation": item.relation,
        "relevance_score": item.relevance_score,
    }


__all__ = [
    "EMPTY_EVIDENCE_SET_HASH",
    "ResearchSetReference",
    "compute_evidence_set_hash",
]
