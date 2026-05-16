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
import ipaddress
import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

# F-003 fix (Codex P2): sha256 hex shape regex (lowercase or uppercase).
_SHA256_HEX_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-fA-F]{64}$")
# F-002 fix (Codex P2): percent-escape canonicalization (RFC 3986 §6.2.2.1 —
# percent-encoded triplets MUST be uppercase hex digits).
_PERCENT_ESCAPE_RE: Final[re.Pattern[str]] = re.compile(r"%([0-9a-fA-F]{2})")

# F-R2-002 + F-R3-003 fix (Codex R2 P2 + R3 P1): mirror prov_validator's
# _PROV_TOP_LEVEL_ALIASES so bundles persisted with ``prov:`` prefixes still
# hash identically to their unprefixed counterparts. **R3 fix**: also alias
# the *node* sections (``prov:activities`` / ``prov:entities`` /
# ``prov:agents``); a claim that uses these prefixed keys would otherwise
# hash with empty node sections even though the validator accepts them.
# Keep in sync with backend/app/services/research/prov_validator.py
# (cross-source-enum-integrity §1).
_PROV_NAMESPACE_ALIASES: Final[dict[str, str]] = {
    # relation aliases
    "prov:wasGeneratedBy": "wasGeneratedBy",
    "prov:used": "used",
    "prov:wasAttributedTo": "wasAttributedTo",
    "prov:wasInformedBy": "wasInformedBy",
    "prov:wasDerivedFrom": "wasDerivedFrom",
    # node section aliases (F-R3-003)
    "prov:activities": "activities",
    "prov:entities": "entities",
    "prov:agents": "agents",
}

# F-R2-003 fix (Codex R2 P2): allowed evidence_item relations per
# evidence_items_ck_relation_enum (mirror of DB CHECK).
EVIDENCE_ITEM_RELATIONS: Final[frozenset[str]] = frozenset(
    {"supports", "contradicts", "context"}
)

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
class EvidenceItemNormalized:
    """F-R2-001 fix (Codex R2 P1): server-owned normalized evidence_item shape.

    Mirrors the ``evidence_items`` table columns that affect citation /
    reproducibility identity:

    - ``id`` — evidence_item PK (UUID)
    - ``claim_id`` — owning claim
    - ``source_id`` — referenced evidence_source
    - ``locator`` — NFC-normalized text (page anchor / quote span / etc.)
    - ``relation`` — supports / contradicts / context (DB CHECK enum)
    - ``relevance_score`` — optional float ∈ [0, 1]

    Changing any of these on an existing snapshot's evidence_items must change
    evidence_set_hash; pre-R2 producers omitted this layer entirely so two
    snapshots with different citation locators / relations could share a hash.
    """

    id: UUID
    claim_id: UUID
    source_id: UUID
    locator: str
    relation: str
    relevance_score: float | None

    @classmethod
    def from_raw(
        cls,
        id: UUID | str,  # noqa: A002 — match DB column name
        claim_id: UUID | str,
        source_id: UUID | str,
        locator: Any,  # noqa: ANN401
        relation: Any,  # noqa: ANN401
        relevance_score: float | int | None = None,
    ) -> EvidenceItemNormalized:
        if not isinstance(locator, str):
            raise EvidenceSetHashError(
                "evidence_item_locator_type_invalid",
                f"locator must be str, got {type(locator).__name__}",
            )
        if not isinstance(relation, str) or relation not in EVIDENCE_ITEM_RELATIONS:
            raise EvidenceSetHashError(
                "evidence_item_relation_invalid",
                f"relation must be in {sorted(EVIDENCE_ITEM_RELATIONS)}, got {relation!r}",
            )
        if relevance_score is not None:
            if isinstance(relevance_score, bool) or not isinstance(
                relevance_score, (int, float)
            ):
                raise EvidenceSetHashError(
                    "evidence_item_relevance_type_invalid",
                    (
                        f"relevance_score must be float or None, "
                        f"got {type(relevance_score).__name__}"
                    ),
                )
            score = float(relevance_score)
            if not (0.0 <= score <= 1.0):
                raise EvidenceSetHashError(
                    "evidence_item_relevance_out_of_range",
                    f"relevance_score must be in [0,1], got {score}",
                )
        else:
            score = None
        eid = id if isinstance(id, UUID) else UUID(str(id))
        cid = claim_id if isinstance(claim_id, UUID) else UUID(str(claim_id))
        sid = source_id if isinstance(source_id, UUID) else UUID(str(source_id))
        return cls(
            id=eid,
            claim_id=cid,
            source_id=sid,
            locator=unicodedata.normalize("NFC", locator),
            relation=relation,
            relevance_score=score,
        )


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
        # F-003 fix (Codex P2): length check alone accepted ``zzzz...`` (non-hex 64
        # chars). Add explicit regex so server-owned producer fails closed on
        # malformed source hashes even if the DB constraint is bypassed.
        if not isinstance(content_hash, str) or not _SHA256_HEX_RE.fullmatch(content_hash):
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


def _normalize_percent_escapes(text: str) -> str:
    """RFC 3986 §6.2.2.1: percent-encoded triplets MUST be uppercase hex.

    ``%7e`` and ``%7E`` are equivalent; canonicalize to uppercase so two URLs
    that differ only in the case of percent-escapes hash identically.

    F-002 fix (Codex P2): we deliberately do **not** unescape unreserved
    characters here. While RFC 3986 §6.2.2.2 permits it, doing so requires a
    valid UTF-8 decoder pass over the bytes, and evidence URLs may legitimately
    contain percent-encoded non-UTF8 byte sequences (PDF anchors etc.).
    Case normalization alone covers the realistic drift surface for our hash.
    """
    return _PERCENT_ESCAPE_RE.sub(lambda m: "%" + m.group(1).upper(), text)


def _remove_dot_segments(path: str) -> str:
    """RFC 3986 §5.2.4: remove "./" and "../" path segments.

    Implements the algorithm directly (Python's stdlib does not expose it).
    Input is expected to be a path (the part of a URL after the authority,
    starting with ``/`` or empty / relative).
    """
    if not path:
        return path
    input_buf = path
    output_buf = ""
    while input_buf:
        # A. ../ or ./
        if input_buf.startswith("../"):
            input_buf = input_buf[3:]
        elif input_buf.startswith("./"):
            input_buf = input_buf[2:]
        # B. /./ or /. (end)
        elif input_buf.startswith("/./"):
            input_buf = "/" + input_buf[3:]
        elif input_buf == "/.":
            input_buf = "/"
        # C. /../ or /.. (end) — pop last segment from output
        elif input_buf.startswith("/../"):
            input_buf = "/" + input_buf[4:]
            output_buf = output_buf.rsplit("/", 1)[0] if "/" in output_buf else ""
        elif input_buf == "/..":
            input_buf = "/"
            output_buf = output_buf.rsplit("/", 1)[0] if "/" in output_buf else ""
        # D. only . or ..
        elif input_buf in (".", ".."):
            input_buf = ""
        # E. move first path segment from input to output
        else:
            # find next '/' starting at position 1 (preserve leading '/')
            slash = input_buf.find("/", 1)
            if slash == -1:
                output_buf += input_buf
                input_buf = ""
            else:
                output_buf += input_buf[:slash]
                input_buf = input_buf[slash:]
    return output_buf


def _format_host_for_netloc(hostname: str | None) -> str:
    """F-004 fix (Codex P2): preserve IPv6 brackets.

    ``urlsplit(...).hostname`` strips the surrounding ``[]`` from IPv6 literals,
    but ``urlunsplit`` requires them to produce a valid URL. Detect IPv6 by
    attempting to parse the hostname; if it parses, wrap with brackets.
    """
    if hostname is None or hostname == "":
        return ""
    # Try IPv6 (no brackets at this point — urlsplit stripped them).
    try:
        ipaddress.IPv6Address(hostname)
        return f"[{hostname}]"
    except (ipaddress.AddressValueError, ValueError):
        pass
    return hostname


def normalize_url(url: Any) -> str:  # noqa: ANN401
    """RFC 3986 + RFC 6596 URL normalization for evidence_set_hash.

    Steps (post-fix for Codex P2 findings):
    - lowercase scheme + host (RFC 3986 §6.2.2.1)
    - preserve IPv6 brackets after ``urlsplit`` strip (F-004)
    - strip default port (80 for http, 443 for https; RFC 3986 §6.2.3)
    - collapse empty path "" → "/"
    - remove dot-segments ``./`` / ``../`` (RFC 3986 §5.2.4, F-005)
    - strip single trailing slash on non-root paths
    - drop fragment (RFC 3986 §3.5 — fragments are client-side, not part of
      the resource identity)
    - uppercase percent-encoded triplets in both path and query
      (RFC 3986 §6.2.2.1, F-002)
    - keep query string content verbatim (caller-controlled, only case-
      normalize the percent triplets)

    NOTE: we still do not unescape unreserved characters because evidence URLs
    may legitimately contain non-UTF8 percent-encoded byte sequences (PDF
    anchors etc.). Case normalization alone covers the realistic drift surface.
    """
    if not isinstance(url, str):
        raise EvidenceSetHashError(
            "url_type_invalid",
            f"url must be str, got {type(url).__name__}",
        )
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        # urlsplit itself only raises on a few esoteric cases (e.g. NUL bytes
        # in Python 3.11+). Wrap so callers see EvidenceSetHashError.
        raise EvidenceSetHashError(
            "url_split_failed",
            f"urlsplit rejected url: {exc}",
        ) from exc
    scheme = parts.scheme.lower()
    host = _format_host_for_netloc(parts.hostname)
    # lowercase the registered host (DNS is case-insensitive; IPv6 literals
    # have already been bracket-wrapped, lowercase has no effect on them).
    host = host.lower()
    netloc = host
    # F-R2-003 fix (Codex R2 P2): ``parts.port`` raises a bare ``ValueError``
    # when the URL contains a non-numeric / out-of-range port (e.g.
    # ``https://example.com:abc/x``). Wrap so downstream sees a structured
    # EvidenceSetHashError instead of an uncontrolled exception.
    try:
        port = parts.port
    except ValueError as exc:
        raise EvidenceSetHashError(
            "url_port_invalid",
            f"url port is not a valid integer: {exc}",
        ) from exc
    if port is not None:
        default = {"http": 80, "https": 443}.get(scheme)
        if port != default:
            netloc = f"{host}:{port}"
    if parts.username or parts.password:
        # preserve userinfo verbatim (rare in evidence URLs, but stable)
        userinfo = parts.username or ""
        if parts.password is not None:
            userinfo = f"{userinfo}:{parts.password}"
        netloc = f"{userinfo}@{netloc}"
    path = parts.path or "/"
    # F-005: remove dot-segments before trailing-slash logic.
    path = _remove_dot_segments(path)
    if not path:
        # dot-segment removal can produce empty path (e.g. "/.." on root).
        path = "/"
    # strip single trailing slash on non-root paths
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    # F-002: uppercase percent triplets in path + query.
    path = _normalize_percent_escapes(path)
    query = _normalize_percent_escapes(parts.query)
    # drop fragment (RFC 3986 §3.5)
    return urlunsplit((scheme, netloc, path, query, ""))


def _normalize_prov_bundle(prov: Any) -> dict[str, Any]:  # noqa: ANN401
    """Canonicalize the PROV bundle subset embedded in a claim's
    ``provenance_json``.

    F-001 fix (Codex P1): align with the **actual** ProvBundle schema used by
    ``backend/app/services/research/prov_validator.py``. The validated shape
    is::

        {
            "activities": [...],
            "entities": [...],
            "agents": [...],
            "wasGeneratedBy": [...],   # top-level relation arrays
            "used": [...],
            "wasAttributedTo": [...],
            "wasInformedBy": [...],
            "wasDerivedFrom": [...],
        }

    The previous implementation hashed ``prov.get("relations", {})``, which
    always returned ``{}`` for production-shaped bundles and silently defeated
    the PROV-aware part of evidence_set_hash. We now read each PROV relation
    array at the top level; for backward compat we *also* honour a legacy
    ``relations`` sub-mapping if present (it must use the same relation
    names from ``PROV_RELATIONS_MINIMAL``).

    NFC-normalizes every string leaf and rejects unknown relation names
    (fail-closed: keeps evidence_set_hash stable against future spec drift).
    """
    if not isinstance(prov, dict):
        raise EvidenceSetHashError(
            "prov_bundle_not_object",
            f"provenance_json must be dict, got {type(prov).__name__}",
        )
    # F-R2-002 fix (Codex R2 P2): apply prov_validator's namespace alias map up
    # front so ``prov:wasGeneratedBy`` becomes ``wasGeneratedBy`` before the
    # relation lookup below. Without this, bundles persisted with the ``prov:``
    # prefix would hash as if they had no relations.
    aliased: dict[str, Any] = {}
    for k, v in prov.items():
        if not isinstance(k, str):
            raise EvidenceSetHashError(
                "prov_top_level_key_not_string",
                f"PROV top-level key must be str, got {type(k).__name__}",
            )
        normalized_key = _PROV_NAMESPACE_ALIASES.get(k, k)
        if normalized_key in aliased and aliased[normalized_key] != v:
            raise EvidenceSetHashError(
                "prov_duplicate_aliased_key",
                (
                    f"PROV bundle has both {k!r} and its alias "
                    f"{normalized_key!r} with conflicting values"
                ),
            )
        aliased[normalized_key] = v
    prov = aliased

    # F-R4-002 fix (Codex R4 P2): the prov_validator's ``ProvBundle`` has
    # ``extra="forbid"`` — any top-level key outside the known set (node
    # sections + minimal relations + legacy ``"relations"`` sub-map) means
    # the bundle was either bypassed past the validator or carries a new
    # PROV-DM concept that this helper hasn't been audited for. Fail closed
    # so two bundles that differ only in an unknown top-level key cannot
    # silently share a hash.
    _allowed_top_level_keys: frozenset[str] = (
        frozenset({"activities", "entities", "agents", "relations"})
        | PROV_RELATIONS_MINIMAL
    )
    unknown_top_level = set(prov.keys()) - _allowed_top_level_keys
    if unknown_top_level:
        raise EvidenceSetHashError(
            "prov_unknown_top_level_key",
            (
                f"provenance_json has unknown top-level key(s) "
                f"{sorted(unknown_top_level)!r}; allowed: "
                f"{sorted(_allowed_top_level_keys)!r}"
            ),
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

    # F-001 fix: pull each PROV relation array from the top-level keys, with a
    # legacy ``relations`` sub-mapping fallback. Unknown keys at the top level
    # are tolerated (the bundle may carry other PROV-DM extensions or the
    # caller's own metadata); only the relations we know are hashed so the
    # hash stays stable against unrelated schema additions.
    canonical_relations: dict[str, list[Any]] = {}
    for rel_name in sorted(PROV_RELATIONS_MINIMAL):
        rel_items: Any = prov.get(rel_name)
        if rel_items is None:
            # Legacy fallback: pre-Sprint-10 bundles may have nested under "relations".
            legacy = prov.get("relations")
            if isinstance(legacy, dict):
                rel_items = legacy.get(rel_name)
        if rel_items is None:
            canonical_relations[rel_name] = []
            continue
        if not isinstance(rel_items, list):
            raise EvidenceSetHashError(
                "prov_relation_not_list",
                (
                    f"provenance_json.{rel_name} must be list, "
                    f"got {type(rel_items).__name__}"
                ),
            )
        canonical_relations[rel_name] = [_nfc_walk(item) for item in rel_items]

    # Reject any explicitly-named relations that fall outside the minimal set.
    legacy_relations = prov.get("relations")
    if isinstance(legacy_relations, dict):
        unknown = set(legacy_relations.keys()) - PROV_RELATIONS_MINIMAL
        if unknown:
            raise EvidenceSetHashError(
                "prov_relation_unknown",
                (
                    f"provenance_json.relations contains unknown relation "
                    f"{sorted(unknown)!r}; allowed: {sorted(PROV_RELATIONS_MINIMAL)}"
                ),
            )

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


def _ecma_number_to_string(x: float | int) -> str:
    """RFC 8785 §3.2.2.3 / ECMA-262 §6.1.6.1.13 ``Number::toString`` for the
    JCS encoder.

    Python ``json.dumps`` deviates from RFC 8785 in several places; since
    ``evidence_items.relevance_score`` rides in the canonical body, drift
    here would silently change the hash across stacks.

    F-R3-004 fix (Codex R3 P2): the initial fix used fixed-point ``Decimal``
    formatting which produced ``0.0000001`` for ``1e-7``.

    F-R4-001 fix (Codex R4 P2): the corrected algorithm follows ECMA-262
    exactly — for any ``|x|`` in [1e-6, 1e21) we emit decimal form, and we
    fall through to scientific form (``1e-7``, ``1e+21``) outside that
    window. ``relevance_score`` is validated to ``[0, 1]`` and the score
    granularity is unconstrained (subnormal-floor floats like ``1e-308``
    are legitimately accepted), so the scientific branch is reachable in
    production.

    Algorithm (ECMA-262 ToString(Number) §6.1.6.1.13):

    - ``±0``, ``int`` short-circuit (``"0"`` / ``str(int)``)
    - reject ``NaN`` / ``±∞`` / ``bool`` with structured reason_codes
    - decompose finite ``x`` via ``Decimal(repr(x)).normalize().as_tuple()``
      into ``(sign, digits, exponent)`` where ``digits`` carries the
      shortest IEEE-754 round-trip mantissa, then compute ``k`` (digit
      count) and ``n = exponent + k`` (the ECMA "n" exponent).
    - emit per case table (k ≤ n ≤ 21 | 0 < n ≤ 21 | -6 < n ≤ 0 | else
      scientific). See `<https://262.ecma-international.org/15.0/#sec-numeric-types-number-tostring>`_.

    The PyPI ``jcs`` package is intentionally not used so the hash producer
    keeps zero third-party surface.
    """
    if isinstance(x, bool):  # bool ⊂ int — never hash as number
        raise EvidenceSetHashError(
            "jcs_bool_not_number",
            "bool must not appear where a JCS number is expected",
        )
    if isinstance(x, int):
        return str(x)
    if x != x:  # NaN
        raise EvidenceSetHashError("jcs_nan_forbidden", "NaN is not JSON")
    if x in (float("inf"), float("-inf")):
        raise EvidenceSetHashError("jcs_infinity_forbidden", "Infinity is not JSON")
    if x == 0:
        return "0"  # collapse +0.0 / -0.0
    if x < 0:
        return "-" + _ecma_finite_positive_to_string(-x)
    return _ecma_finite_positive_to_string(x)


def _ecma_finite_positive_to_string(x: float) -> str:
    """ECMA-262 §6.1.6.1.13 step 5+ for finite positive ``x``.

    Sub-helper isolated so the sign + special-value handling sits in
    ``_ecma_number_to_string`` and this function deals only with the
    positive-finite branch (the bulk of the algorithm).
    """
    # repr(x) is Python's shortest round-trip decimal (CPython 3.1+ uses
    # the same David Gay / dtoa "shortest" algorithm that V8 / SpiderMonkey
    # use under the hood for ECMA-262 ToString). Decimal(repr(x)) is
    # therefore exact for the IEEE-754 value, and .normalize() strips
    # trailing-zero artifacts so ``s`` has no trailing zeros (the algorithm
    # requires ``s % 10 != 0`` when ``k > 1`` for canonical form).
    d = Decimal(repr(x)).normalize()
    _sign, digit_tuple, exponent_raw = d.as_tuple()
    # exponent can be int or one of the special strings ('F', 'n', 'N');
    # _ecma_number_to_string already rejected NaN/∞ so this is always int.
    exponent = int(exponent_raw)
    k = len(digit_tuple)
    n = exponent + k
    s_str = "".join(str(d) for d in digit_tuple)
    if k <= n <= 21:
        return s_str + "0" * (n - k)
    if 0 < n <= 21:
        return s_str[:n] + "." + s_str[n:]
    if -6 < n <= 0:
        return "0." + "0" * (-n) + s_str
    # n < -5 or n > 21: scientific notation
    if k == 1:
        mantissa = s_str
    else:
        mantissa = s_str[0] + "." + s_str[1:]
    exp_disp = n - 1
    sign_char = "+" if exp_disp >= 0 else "-"
    return f"{mantissa}e{sign_char}{abs(exp_disp)}"


def _jcs_dumps(obj: Any) -> str:  # noqa: ANN401
    """RFC 8785 JSON Canonicalization Scheme (JCS) serialization.

    Walk the tree recursively and emit each node in JCS canonical form:

    - object keys are sorted by their UTF-16 code-unit ordering (Python's
      default ``sorted`` over Unicode code points happens to coincide for
      the BMP characters that appear in our canonical body; the canonical
      body never contains supplementary-plane keys);
    - array order is preserved (callers must sort beforehand for
      deterministic ordering, which is what ``compute_evidence_set_hash``
      does);
    - numbers use ECMA-262 ToString canonicalization via
      ``_ecma_number_to_string`` (F-R3-004 fix);
    - strings round-trip through ``json.dumps`` to share the escape
      sequence rules with the rest of the codebase;
    - booleans / null map to ``true`` / ``false`` / ``null`` verbatim.

    Reject any unsupported type with a structured ``EvidenceSetHashError``
    so callers cannot silently smuggle non-JSON inputs through.
    """
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, (int, float)):
        return _ecma_number_to_string(obj)
    if isinstance(obj, str):
        return json.dumps(obj, ensure_ascii=False)
    if isinstance(obj, list):
        return "[" + ",".join(_jcs_dumps(v) for v in obj) + "]"
    if isinstance(obj, dict):
        parts: list[str] = []
        for key in sorted(obj.keys()):
            if not isinstance(key, str):
                raise EvidenceSetHashError(
                    "jcs_non_string_key",
                    f"JCS requires string keys, got {type(key).__name__}",
                )
            parts.append(
                f"{json.dumps(key, ensure_ascii=False)}:{_jcs_dumps(obj[key])}"
            )
        return "{" + ",".join(parts) + "}"
    raise EvidenceSetHashError(
        "jcs_unsupported_type",
        f"unsupported type in canonical body: {type(obj).__name__}",
    )


def compute_evidence_set_hash(
    claims: Sequence[ClaimNormalized],
    sources: Sequence[SourceNormalized],
    provenance_per_claim: dict[UUID, Any],
    evidence_items: Sequence[EvidenceItemNormalized] = (),
    *,
    require_provenance: bool = True,
) -> str:
    """Compute evidence_set_hash from a normalized claim + source set.

    Args:
        claims: iterable of ``ClaimNormalized`` (claim_id + NFC claim_text)
        sources: iterable of ``SourceNormalized`` (source_id + URL-normalized
            canonical_url + sha256 content_hash)
        provenance_per_claim: mapping of ``claim_id`` → raw provenance JSON
            (W3C PROV-DM minimal subset). Each value is run through
            ``_normalize_prov_bundle`` before hashing.
        evidence_items: iterable of ``EvidenceItemNormalized`` (claim↔source
            attachments with locator / relation / relevance_score).
            **F-R2-001 fix**: changes at the evidence_item layer must change
            the hash. Pre-R2 producers omitted this layer entirely.
        require_provenance: when True (default, server-owned production
            invariant), every claim must have an entry in
            ``provenance_per_claim`` — caller-side assembly misses fail
            closed instead of silently hashing an empty PROV bundle.
            Set False only for test fixtures that intentionally exercise
            unprovenanced claim sets.

    Returns:
        sha256 hex (64 lowercase chars). Idempotent for identical input.

    Raises:
        EvidenceSetHashError: input shape / NFC / PROV relation invalid.
    """
    # Deterministic ordering (Sprint Pack §設計判断: claim_id / source_id 昇順)
    claim_list = sorted(claims, key=lambda c: c.claim_id)
    source_list = sorted(sources, key=lambda s: s.source_id)
    # F-R2-001 + F-R3-005 fix: evidence_items sorted by
    # (claim_id, source_id, locator, relation, id) so:
    #   * locator-level changes shift the hash deterministically
    #     (F-R2-001 layered input invariant), and
    #   * two evidence_items that share claim/source/locator/relation but
    #     differ on ``id`` (or downstream on relevance_score) hash to a
    #     **total** ordering (F-R3-005). Without the ``id`` tiebreaker the
    #     sort is stable, so caller-side row ordering would leak into the
    #     hash for that degenerate-but-legal case.
    item_list = sorted(
        evidence_items,
        key=lambda e: (e.claim_id, e.source_id, e.locator, e.relation, e.id),
    )

    # F-R4-003 fix (Codex R4 P2): evidence_item must reference a claim and
    # source from the same input set. A dangling claim_id / source_id means
    # the assembler dropped the underlying row from `claims`/`sources`
    # before passing them in, so the canonical body would record only the
    # bare UUID and two snapshots with the same evidence_item IDs but
    # different *omitted* claim text / source URL would collide. Fail
    # closed with structured reason_codes.
    _claim_id_set = {c.claim_id for c in claim_list}
    _source_id_set = {s.source_id for s in source_list}
    for item in item_list:
        if item.claim_id not in _claim_id_set:
            raise EvidenceSetHashError(
                "evidence_item_claim_dangling",
                (
                    f"evidence_item id={item.id} references claim_id "
                    f"{item.claim_id} which is not in the claims input set"
                ),
            )
        if item.source_id not in _source_id_set:
            raise EvidenceSetHashError(
                "evidence_item_source_dangling",
                (
                    f"evidence_item id={item.id} references source_id "
                    f"{item.source_id} which is not in the sources input set"
                ),
            )

    # F-R2-004 fix (Codex R2 P2): in production, every claim must carry a
    # validated provenance_json (API/repository enforce this via
    # prov_validator). A caller that omits a claim from provenance_per_claim
    # is a broken integration and must fail-closed rather than silently
    # hashing an empty PROV bundle. Test fixtures opt out via
    # ``require_provenance=False``.
    prov_canonical: dict[str, dict[str, Any]] = {}
    for claim in claim_list:
        if claim.claim_id in provenance_per_claim:
            raw = provenance_per_claim[claim.claim_id]
        else:
            if require_provenance:
                raise EvidenceSetHashError(
                    "provenance_missing_for_claim",
                    (
                        f"claim {claim.claim_id} has no provenance_json entry "
                        "in provenance_per_claim (set require_provenance=False "
                        "for test fixtures that intentionally exercise this case)"
                    ),
                )
            raw = {}
        prov_canonical[str(claim.claim_id)] = _normalize_prov_bundle(raw)

    canonical_body = {
        # schema_version bumped on every shape / serialization-affecting change:
        #   "1" — pre-R2 (claims + sources + provenance only)
        #   "2" — F-R2-001 evidence_items layer
        #   "3" — F-R3-003 PROV node-section alias map +
        #         F-R3-004 RFC 8785 / ECMA-262 number canonicalization +
        #         F-R3-005 total-ordering id tiebreaker
        "schema_version": "3",
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
        "evidence_items": [
            {
                "id": str(e.id),
                "claim_id": str(e.claim_id),
                "source_id": str(e.source_id),
                "locator": e.locator,
                "relation": e.relation,
                "relevance_score": e.relevance_score,
            }
            for e in item_list
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
    "EvidenceItemNormalized",
    "EvidenceSetHashError",
    "EVIDENCE_ITEM_RELATIONS",
    "PROV_RELATIONS_MINIMAL",
    "HASH_HEX_LEN",
    "SourceNormalized",
    "compute_evidence_set_hash",
    "normalize_url",
]
