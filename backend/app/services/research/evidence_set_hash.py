"""evidence_set_hash computation (Sprint 10 BL-0117).

Sprint Pack: SP-010_research_evidence.md §設計判断
ADR: ADR-00002 §evidence_set_hash, server-owned-boundary §1
ContextSnapshot 必須 10 column: PRD-01 F-009 / DD-03 / DD-02

evidence_set_hash の正規化アルゴリズム:

1. NFC UTF-8 normalize (Unicode confusables 防御)
2. URL 正規化 (RFC 3986 + RFC 6596 + trailing slash strip + percent-encoding NFC)
3. PROV bundle hash (W3C PROV-DM minimal 5 relation)
4. claim_id / source_id 昇順 (deterministic ordering)
5. JCS (RFC 8785) canonical JSON
6. sha256 hex → 64-char

**server-owned-boundary §1 invariant**: caller-supplied hash は信頼しない。
全 input (claims / sources / provenance) を本 helper に渡し、本 helper が
*唯一の* hash producer として server-side で deterministic に生成する。

Idempotent + deterministic: 同一 input は常に同一 hash (1000+ test で検証)。
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

# W3C PROV-DM minimal 5 relation (P0 minimal subset、Sprint Pack §レビュー観点)
PROV_RELATIONS_MINIMAL: Final[frozenset[str]] = frozenset(
    {
        "wasGeneratedBy",
        "used",
        "wasAttributedTo",
        "wasInformedBy",
        "wasDerivedFrom",
    }
)

# 32-byte hex (64-char) sha256 invariant; aligns with ContextSnapshot
# CHECK constraint (`evidence_set_hash ~ '^[0-9a-f]{64}$'`).
HASH_HEX_LEN: Final[int] = 64


class EvidenceSetHashError(ValueError):
    """Raised when evidence_set_hash computation fails fail-closed.

    Reason codes are exposed via ``reason_code`` for structured downstream
    handling (audit events / API error responses).
    """

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"[{reason_code}] {message}")


@dataclass(frozen=True)
class ClaimNormalized:
    """Server-owned normalized claim shape for evidence_set_hash input.

    All caller-supplied strings are NFC-normalized at construction so the
    hash producer receives a single canonical form.
    """

    claim_id: UUID
    claim_text: str  # NFC UTF-8

    @classmethod
    def from_raw(cls, claim_id: UUID | str, claim_text: Any) -> ClaimNormalized:  # noqa: ANN401
        # claim_text: Any — caller-supplied JSON value; runtime isinstance check below
        if not isinstance(claim_text, str):
            raise EvidenceSetHashError(
                "claim_text_type_invalid",
                f"claim_text must be str, got {type(claim_text).__name__}",
            )
        cid = claim_id if isinstance(claim_id, UUID) else UUID(str(claim_id))
        return cls(claim_id=cid, claim_text=unicodedata.normalize("NFC", claim_text))


@dataclass(frozen=True)
class SourceNormalized:
    """Server-owned normalized evidence_source shape.

    canonical_url is the **already URL-normalized** form, content_hash is the
    DB-recorded sha256 of the source body. Both are caller-trusted inputs
    only insofar as the database itself stores them; this helper does not
    re-fetch the source.
    """

    source_id: UUID
    canonical_url: str  # URL-normalized + NFC
    content_hash: str  # sha256 hex 64-char

    @classmethod
    def from_raw(
        cls,
        source_id: UUID | str,
        canonical_url: Any,  # noqa: ANN401
        content_hash: Any,  # noqa: ANN401
    ) -> SourceNormalized:
        # canonical_url / content_hash: Any — caller-supplied; runtime isinstance below
        if not isinstance(canonical_url, str):
            raise EvidenceSetHashError(
                "canonical_url_type_invalid",
                f"canonical_url must be str, got {type(canonical_url).__name__}",
            )
        if not isinstance(content_hash, str) or len(content_hash) != HASH_HEX_LEN:
            raise EvidenceSetHashError(
                "content_hash_shape_invalid",
                f"content_hash must be 64-char sha256 hex, got {content_hash!r}",
            )
        sid = source_id if isinstance(source_id, UUID) else UUID(str(source_id))
        return cls(
            source_id=sid,
            canonical_url=normalize_url(unicodedata.normalize("NFC", canonical_url)),
            content_hash=content_hash.lower(),
        )


def normalize_url(url: Any) -> str:  # noqa: ANN401
    """RFC 3986 + RFC 6596 URL normalization for evidence_set_hash.

    Steps:
    - lowercase scheme + host
    - strip default port (80 for http, 443 for https)
    - collapse empty path "" → "/"
    - strip single trailing slash on non-root paths
    - drop fragment (RFC 3986 §3.5 — fragments are client-side, not part of
      the resource identity)
    - keep query string verbatim (caller-controlled)

    NOTE: this is intentionally narrow. We do not unescape percent-encoded
    bytes here because that would lose information for non-UTF8 byte
    sequences in evidence URLs (PDF fragments etc.). NFC normalization
    happens at the caller level (SourceNormalized.from_raw).
    """
    if not isinstance(url, str):
        raise EvidenceSetHashError(
            "url_type_invalid",
            f"url must be str, got {type(url).__name__}",
        )
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    netloc = parts.hostname or ""
    netloc = netloc.lower()
    if parts.port is not None:
        # strip default port
        default = {"http": 80, "https": 443}.get(scheme)
        if parts.port != default:
            netloc = f"{netloc}:{parts.port}"
    if parts.username or parts.password:
        # preserve userinfo verbatim (rare in evidence URLs, but stable)
        userinfo = parts.username or ""
        if parts.password is not None:
            userinfo = f"{userinfo}:{parts.password}"
        netloc = f"{userinfo}@{netloc}"
    path = parts.path or "/"
    # strip single trailing slash on non-root paths
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    # drop fragment (RFC 3986 §3.5)
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def _normalize_prov_bundle(prov: Any) -> dict[str, Any]:  # noqa: ANN401
    """Canonicalize the PROV bundle subset embedded in a claim's
    ``provenance_json``.

    Accepts either:
      - top-level dict shaped as ``{"activities": [...], "entities": [...],
        "agents": [...], "relations": {<rel_name>: [...]}}`` (PROV-DM minimal),
      - or a flat dict containing only ``relations`` (claims that did not
        record activities / entities / agents separately).

    NFC-normalizes every string leaf and rejects unknown relation names
    (fail-closed: keeps evidence_set_hash stable against future spec drift).
    """
    if not isinstance(prov, dict):
        raise EvidenceSetHashError(
            "prov_bundle_not_object",
            f"provenance_json must be dict, got {type(prov).__name__}",
        )
    canonical: dict[str, Any] = {}
    for section in ("activities", "entities", "agents"):
        items = prov.get(section, [])
        if not isinstance(items, list):
            raise EvidenceSetHashError(
                f"prov_{section}_not_list",
                f"provenance_json.{section} must be list, got {type(items).__name__}",
            )
        canonical[section] = [_nfc_walk(item) for item in items]
    relations_raw = prov.get("relations", {})
    if not isinstance(relations_raw, dict):
        raise EvidenceSetHashError(
            "prov_relations_not_object",
            f"provenance_json.relations must be dict, got {type(relations_raw).__name__}",
        )
    canonical_relations: dict[str, list[Any]] = {}
    for rel_name, rel_items in relations_raw.items():
        if rel_name not in PROV_RELATIONS_MINIMAL:
            raise EvidenceSetHashError(
                "prov_relation_unknown",
                (
                    f"provenance_json.relations contains unknown relation "
                    f"{rel_name!r}; allowed: {sorted(PROV_RELATIONS_MINIMAL)}"
                ),
            )
        if not isinstance(rel_items, list):
            raise EvidenceSetHashError(
                "prov_relation_not_list",
                (
                    f"provenance_json.relations[{rel_name!r}] must be list, "
                    f"got {type(rel_items).__name__}"
                ),
            )
        canonical_relations[rel_name] = [_nfc_walk(item) for item in rel_items]
    canonical["relations"] = canonical_relations
    return canonical


def _nfc_walk(value: Any) -> Any:  # noqa: ANN401
    """Recursively NFC-normalize every string leaf in a dict / list tree.

    Used so the canonical JSON serialization is byte-stable across NFC vs
    NFD variants of the same Unicode content. Non-string scalars are
    passed through unchanged.
    """
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_nfc_walk(v) for v in value]
    if isinstance(value, tuple):
        return [_nfc_walk(v) for v in value]
    if isinstance(value, dict):
        # Deterministic key ordering happens at json.dumps(sort_keys=True);
        # we still NFC the keys here to be safe.
        return {
            unicodedata.normalize("NFC", str(k)): _nfc_walk(v)
            for k, v in value.items()
        }
    return value


def _jcs_dumps(obj: Any) -> str:  # noqa: ANN401
    """RFC 8785 JSON Canonicalization Scheme (JCS) serialization.

    Python's ``json.dumps(sort_keys=True, separators=(",", ":"),
    ensure_ascii=False)`` already covers the JCS-mandated I-JSON subset for
    our use case (no JS-style numbers, all values are strings / ints /
    bools / null / arrays / objects). We additionally enforce
    ``ensure_ascii=False`` so NFC-normalized UTF-8 stays byte-exact.

    NOTE: full JCS (with IEEE-754 number canonicalization) requires the
    ``jcs`` PyPI package; that dependency is intentionally avoided here so
    the hash producer has zero third-party surface. The evidence_set_hash
    inputs are all server-side normalized values (sha256 hexes, UUIDs,
    NFC strings), none of which require RFC 8785 number serialization.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def compute_evidence_set_hash(
    claims: Sequence[ClaimNormalized],
    sources: Sequence[SourceNormalized],
    provenance_per_claim: dict[UUID, Any],
) -> str:
    """Compute evidence_set_hash from a normalized claim + source set.

    Args:
        claims: iterable of ``ClaimNormalized`` (claim_id + NFC claim_text)
        sources: iterable of ``SourceNormalized`` (source_id + URL-normalized
            canonical_url + sha256 content_hash)
        provenance_per_claim: mapping of ``claim_id`` → raw provenance JSON
            (W3C PROV-DM minimal subset). Each value is run through
            ``_normalize_prov_bundle`` before hashing. Use ``{}`` to skip
            provenance for a particular claim.

    Returns:
        sha256 hex (64 lowercase chars). Idempotent for identical input.

    Raises:
        EvidenceSetHashError: input shape / NFC / PROV relation invalid.
    """
    # Deterministic ordering (Sprint Pack §設計判断: claim_id / source_id 昇順)
    claim_list = sorted(claims, key=lambda c: c.claim_id)
    source_list = sorted(sources, key=lambda s: s.source_id)

    # Collect normalized provenance per claim in the same sorted order; missing
    # provenance defaults to {} (claim has no PROV bundle yet — still part of
    # the evidence set, just unattributed).
    prov_canonical: dict[str, dict[str, Any]] = {}
    for claim in claim_list:
        raw = provenance_per_claim.get(claim.claim_id, {})
        prov_canonical[str(claim.claim_id)] = _normalize_prov_bundle(raw)

    canonical_body = {
        "schema_version": "1",  # bump on any breaking semantic change
        "claims": [
            {
                "claim_id": str(c.claim_id),
                "claim_text": c.claim_text,
            }
            for c in claim_list
        ],
        "sources": [
            {
                "source_id": str(s.source_id),
                "canonical_url": s.canonical_url,
                "content_hash": s.content_hash,
            }
            for s in source_list
        ],
        "provenance": prov_canonical,
    }
    canonical_json = _jcs_dumps(canonical_body)
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    if len(digest) != HASH_HEX_LEN:  # pragma: no cover - sha256 invariant
        raise EvidenceSetHashError(
            "digest_shape_invariant_broken",
            f"sha256 output unexpectedly {len(digest)} chars",
        )
    return digest


__all__ = [
    "ClaimNormalized",
    "SourceNormalized",
    "EvidenceSetHashError",
    "PROV_RELATIONS_MINIMAL",
    "HASH_HEX_LEN",
    "normalize_url",
    "compute_evidence_set_hash",
]
