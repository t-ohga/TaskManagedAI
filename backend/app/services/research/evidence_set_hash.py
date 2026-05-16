from __future__ import annotations

import hashlib
import json
import math
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


# RFC 8785 / I-JSON safe integer range (IEEE-754 double precision interior).
# Values outside (-2^53, 2^53) cannot round-trip through JCS-compliant
# JavaScript implementations (they use double-precision floats), so we
# reject them to keep ``evidence_set_hash`` interoperable.
_JCS_SAFE_INT_MAX = 2**53


def _jcs_expand_exponential_to_fixed(rendered: str) -> str:
    """Expand a Python exponential repr (``"1e-06"``) to its JCS fixed form.

    ``f"{x:.{N}f}"`` exposes IEEE-754 rounding artifacts for many small
    floats (e.g. ``f"{1e-06:.21f}" == "0.000001000000000000000"`` but
    ``f"{1e-06:.16f} != "0.000001..."`` cleanly), so we instead walk the
    shortest-round-trip mantissa digits returned by ``repr(x)`` and shift
    the decimal point by the explicit exponent. This preserves the
    shortest-decimal property (F-PR22-R3-004 P2 adopt).
    """

    lowered = rendered.lower()
    if "e" not in lowered:
        return rendered

    mantissa_str, exp_str = lowered.split("e")
    exp_int = int(exp_str)

    sign = ""
    if mantissa_str.startswith("-"):
        sign = "-"
        mantissa_str = mantissa_str[1:]
    elif mantissa_str.startswith("+"):
        mantissa_str = mantissa_str[1:]

    if "." in mantissa_str:
        int_part, frac_part = mantissa_str.split(".", 1)
    else:
        int_part, frac_part = mantissa_str, ""

    digits = int_part + frac_part
    decimal_pos = len(int_part) + exp_int

    if decimal_pos <= 0:
        result = "0." + "0" * (-decimal_pos) + digits
    elif decimal_pos >= len(digits):
        result = digits + "0" * (decimal_pos - len(digits))
    else:
        result = digits[:decimal_pos] + "." + digits[decimal_pos:]

    if "." in result:
        result = result.rstrip("0").rstrip(".")
    if not result:
        result = "0"
    return sign + result


def _jcs_format_number(value: int | float) -> str:
    """Format a number per RFC 8785 §3.2.2.3 / ECMA-262 §7.1.12.1.

    Python ``json.dumps`` diverges from RFC 8785 (JCS) in several ways
    that matter for cross-implementation reproducibility of
    ``evidence_set_hash``:

    - Whole-number floats emit a trailing ``.0`` (``1.0`` -> ``"1.0"``)
      while JCS / ECMAScript ``Number.prototype.toString`` collapses them
      to integer form (``"1"``) when inside the fixed-notation range
      (F-PR22-003 P2 adopt).
    - Very small floats emit exponential form (``1e-06``) even when the
      exponent is within the ECMAScript fixed-notation range
      ``[-6, 21)`` where JCS expects fixed-decimal form (``"0.000001"``)
      (F-PR22-R2-004 P2 adopt).
    - Integer-valued floats whose magnitude is outside the ECMAScript
      fixed-notation range must serialize in exponential form
      (e.g. ``1e21`` -> ``"1e+21"`` per ECMAScript Number.toString,
      F-PR22-R3-001 P2 adopt).
    - Integers outside the I-JSON safe range cannot round-trip through
      JCS-compliant JavaScript implementations and are rejected
      (F-PR22-R3-003 P2 adopt).
    - Fixed-form decimals for small floats use the shortest round-trip
      representation rather than precision-bounded ``f"{x:.21f}"``
      output, which exposes IEEE-754 rounding artifacts
      (F-PR22-R3-004 P2 adopt).

    NaN / +-Infinity are rejected as JSON-incompatible.
    """

    if isinstance(value, bool):  # bool is subclass of int; reject early
        raise TypeError(
            "bool must be encoded as JSON true/false, not as a number."
        )
    if isinstance(value, int):
        if not (-_JCS_SAFE_INT_MAX < value < _JCS_SAFE_INT_MAX):
            raise ValueError(
                f"integer {value!r} is outside the JCS I-JSON safe range "
                f"(|n| < 2^53); convert to bounded-precision form before hashing."
            )
        return str(value)
    if not isinstance(value, float):
        raise TypeError(
            f"unsupported numeric type for JCS serialization: {type(value)!r}"
        )

    if math.isnan(value) or math.isinf(value):
        raise ValueError(
            f"NaN / Infinity are not permitted in canonical JSON: {value!r}"
        )

    if value == 0.0:
        return "0"

    abs_value = abs(value)
    decimal_exp = math.floor(math.log10(abs_value))

    if -6 <= decimal_exp < 21:
        # Fixed notation per ECMA-262.
        if value.is_integer():
            # 1.0 -> "1", 1234.0 -> "1234". F-PR22-R3-003 P2 adopt: the
            # I-JSON safe-range check is enforced for Python ``int``
            # sources (which carry arbitrary precision and would otherwise
            # diverge from JavaScript-side round-tripping) but not for
            # ``float`` sources -- IEEE-754 floats are already in
            # double-precision representation, so integer-valued floats
            # in the ECMAScript fixed range (e.g. ``1e20``) reproduce
            # consistently across JCS implementations.
            return str(int(value))
        rendered = repr(value)
        if "e" in rendered or "E" in rendered:
            rendered = _jcs_expand_exponential_to_fixed(rendered)
        if not rendered or rendered in {"-", "-."}:
            rendered = "0"
        return rendered

    # Exponential notation per ECMA-262: dE+/-n with no trailing zeros on
    # the mantissa and no leading zeros on the exponent. Both integer-
    # valued floats outside the fixed range (e.g. 1e21 -> "1e+21",
    # F-PR22-R3-001 P2 adopt) and small floats below 1e-6 land here.
    rendered = repr(value)
    if "e" not in rendered and "E" not in rendered:
        rendered = format(value, ".17e")
    mantissa_str, exp_str = rendered.lower().split("e")
    if "." in mantissa_str:
        mantissa_str = mantissa_str.rstrip("0").rstrip(".")
    if not mantissa_str or mantissa_str == "-":
        mantissa_str = "0"
    exp_int = int(exp_str)
    return f"{mantissa_str}e{exp_int:+d}"


def _jcs_encode_string(value: str) -> str:
    """Encode a JSON string per RFC 8259 §7 with NFC-normalized contents.

    NFC normalization happens at the outer ``_hash_canonical_payload``
    boundary to keep the JCS encoding pure; here we delegate JSON string
    escaping to ``json.dumps`` (which is JCS-compatible for strings).
    """

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _jcs_utf16_sort_key(key: str) -> bytes:
    """Return a sort key matching JCS §3.2.3 UTF-16 code-unit ordering.

    JCS canonical JSON sorts object members by UTF-16 code-unit
    comparison rather than Unicode code-point comparison. Python's
    default ``str`` ordering compares code points, which diverges for
    non-BMP characters (surrogate-paired code points such as emoji).
    Encoding to UTF-16 big-endian bytes produces a sequence whose
    lexicographic byte comparison is equivalent to UTF-16 code-unit
    comparison (F-PR22-R3-002 P2 adopt).
    """

    return key.encode("utf-16-be")


def _jcs_canonical_json(value: object) -> str:
    """Minimal RFC 8785 canonical JSON serializer (F-PR22-R2-004 P2 adopt).

    Differs from ``backend.app.domain.agent_runtime.operation_context.
    canonical_json_dumps`` in that numbers go through ``_jcs_format_number``
    so whole-number floats collapse to integer form and small floats use
    fixed-decimal notation within the ECMAScript range, and object keys
    are ordered by UTF-16 code units (JCS §3.2.3) so non-BMP characters
    sort consistently with other JCS implementations.
    """

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return _jcs_format_number(value)
    if isinstance(value, str):
        return _jcs_encode_string(value)
    if isinstance(value, Mapping):
        ordered = sorted(value.items(), key=lambda kv: _jcs_utf16_sort_key(str(kv[0])))
        return (
            "{"
            + ",".join(
                f"{_jcs_encode_string(str(key))}:{_jcs_canonical_json(val)}"
                for key, val in ordered
            )
            + "}"
        )
    if isinstance(value, list | tuple):
        return "[" + ",".join(_jcs_canonical_json(item) for item in value) + "]"
    raise TypeError(
        f"unsupported type for canonical JSON: {type(value)!r}"
    )


def _hash_canonical_payload(payload: object) -> str:
    canonical_json = _jcs_canonical_json(payload)
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
    except ValueError as exc:
        # F-PR22-R2-005 P2 adopt: a malformed / out-of-range port (e.g.
        # ``http://example.com:99999/``) must be rejected at the URL
        # normalization boundary rather than silently dropped. Dropping it
        # collapses distinct evidence sources into the same hash, which
        # would make ``evidence_set_hash`` ambiguous for AC-HARD-03 and
        # AC-KPI-04 reproducibility. Fail-closed instead.
        raise ValueError(
            f"invalid port in evidence source URL: {value!r}"
        ) from exc

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
                        key=lambda item: (
                            str(item.source_id),
                            item.relation,
                            str(item.id),
                        ),
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
