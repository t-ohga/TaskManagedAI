"""Tests for evidence_set_hash determinism (Sprint 10 BL-0117).

Sprint Pack 受け入れ条件:
- evidence_set_hash が同一 input で deterministic (NFC + JCS + sorted) —
  1000+ test で reproducibility 確認
- URL 正規化 invariant が NFC + percent-encoding + trailing slash +
  protocol downgrade をカバー
- PROV bundle hash が W3C PROV-DM minimal 5 relation を含む
"""

from __future__ import annotations

import secrets
import unicodedata
from uuid import UUID, uuid4

import pytest

from backend.app.services.research.evidence_set_hash import (
    EVIDENCE_ITEM_RELATIONS,
    PROV_RELATIONS_MINIMAL,
    ClaimNormalized,
    EvidenceItemNormalized,
    EvidenceSetHashError,
    SourceNormalized,
    _ecma_number_to_string,
    _jcs_dumps,
    compute_evidence_set_hash,
    normalize_url,
)


def _claim(text: str, claim_id: UUID | None = None) -> ClaimNormalized:
    return ClaimNormalized.from_raw(
        claim_id=claim_id or uuid4(),
        claim_text=text,
    )


def _source(
    url: str,
    content_hash: str | None = None,
    source_id: UUID | None = None,
) -> SourceNormalized:
    return SourceNormalized.from_raw(
        source_id=source_id or uuid4(),
        canonical_url=url,
        content_hash=content_hash or ("a" * 64),
    )


class TestHashDeterminism:
    def test_empty_set_is_stable(self) -> None:
        h1 = compute_evidence_set_hash([], [], {}, require_provenance=False)
        h2 = compute_evidence_set_hash([], [], {}, require_provenance=False)
        assert h1 == h2
        assert len(h1) == 64
        assert all(c in "0123456789abcdef" for c in h1)

    def test_single_claim_single_source_stable(self) -> None:
        cid = uuid4()
        sid = uuid4()
        claims = [_claim("statement A", claim_id=cid)]
        sources = [_source("https://example.com/page", source_id=sid)]
        h1 = compute_evidence_set_hash(claims, sources, {}, require_provenance=False)
        h2 = compute_evidence_set_hash(claims, sources, {}, require_provenance=False)
        assert h1 == h2

    def test_input_order_irrelevant(self) -> None:
        cid1, cid2 = uuid4(), uuid4()
        sid1, sid2 = uuid4(), uuid4()
        c1 = _claim("first", claim_id=cid1)
        c2 = _claim("second", claim_id=cid2)
        s1 = _source("https://a.example/x", source_id=sid1)
        s2 = _source("https://b.example/y", source_id=sid2)
        h_forward = compute_evidence_set_hash([c1, c2], [s1, s2], {}, require_provenance=False)
        h_reverse = compute_evidence_set_hash([c2, c1], [s2, s1], {}, require_provenance=False)
        assert h_forward == h_reverse

    def test_different_text_produces_different_hash(self) -> None:
        h1 = compute_evidence_set_hash([_claim("alpha")], [], {}, require_provenance=False)
        h2 = compute_evidence_set_hash([_claim("beta")], [], {}, require_provenance=False)
        assert h1 != h2

    def test_1000_replays_match(self) -> None:
        """Sprint Pack 受け入れ: 1000+ replay で identical hash."""
        cid = uuid4()
        sid = uuid4()
        claims = [_claim("stable claim text", claim_id=cid)]
        sources = [_source("https://example.com/article", source_id=sid)]
        prov = {
            cid: {
                "activities": [{"id": "act-1", "type": "research"}],
                "entities": [{"id": "ent-1", "type": "evidence"}],
                "agents": [{"id": "agt-1", "type": "human"}],
                "relations": {
                    "wasGeneratedBy": [
                        {"source": "ent-1", "target": "act-1"}
                    ],
                    "used": [{"source": "act-1", "target": "ent-1"}],
                },
            }
        }
        reference = compute_evidence_set_hash(claims, sources, prov)
        for _ in range(1000):
            assert compute_evidence_set_hash(claims, sources, prov) == reference


class TestNFC:
    def test_nfd_equals_nfc(self) -> None:
        """NFD-decomposed text → NFC normalized → same hash."""
        nfc_text = "café"  # canonical NFC composed (e + ´ → é)
        nfd_text = unicodedata.normalize("NFD", nfc_text)
        assert nfd_text != nfc_text  # bytes differ
        cid = uuid4()
        h_nfc = compute_evidence_set_hash(
            [_claim(nfc_text, claim_id=cid)], [], {}
        , require_provenance=False)
        h_nfd = compute_evidence_set_hash(
            [_claim(nfd_text, claim_id=cid)], [], {}
        , require_provenance=False)
        assert h_nfc == h_nfd  # NFC normalization erases the encoding diff

    def test_unicode_confusable_rejected_by_normalization(self) -> None:
        """Fullwidth 'A' (U+FF21) and ASCII 'A' (U+0041) are distinct codepoints
        even after NFC; the hash must reflect that."""
        h_ascii = compute_evidence_set_hash([_claim("Apple")], [], {}, require_provenance=False)
        h_fullwidth = compute_evidence_set_hash([_claim("Ａpple")], [], {}, require_provenance=False)
        assert h_ascii != h_fullwidth


class TestUrlNormalize:
    def test_scheme_lowercased(self) -> None:
        assert normalize_url("HTTPS://Example.COM/path") == "https://example.com/path"

    def test_default_port_stripped(self) -> None:
        assert normalize_url("http://example.com:80/") == "http://example.com/"
        assert normalize_url("https://example.com:443/x") == "https://example.com/x"

    def test_nondefault_port_kept(self) -> None:
        assert normalize_url("https://example.com:8443/x") == "https://example.com:8443/x"

    def test_trailing_slash_stripped_on_non_root(self) -> None:
        assert normalize_url("https://example.com/x/") == "https://example.com/x"

    def test_root_trailing_slash_preserved(self) -> None:
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_empty_path_becomes_root(self) -> None:
        assert normalize_url("https://example.com") == "https://example.com/"

    def test_fragment_dropped(self) -> None:
        assert (
            normalize_url("https://example.com/a#section")
            == "https://example.com/a"
        )

    def test_query_preserved(self) -> None:
        assert (
            normalize_url("https://example.com/a?b=1&c=2")
            == "https://example.com/a?b=1&c=2"
        )

    def test_url_type_rejected(self) -> None:
        with pytest.raises(EvidenceSetHashError) as exc:
            normalize_url(123)  # type: ignore[arg-type]
        assert exc.value.reason_code == "url_type_invalid"

    def test_percent_escape_case_canonical(self) -> None:
        """F-002 fix (Codex P2): RFC 3986 §6.2.2.1 — percent-encoded triplets
        must be uppercase. ``%7e`` and ``%7E`` are equivalent."""
        assert (
            normalize_url("https://example.com/a%7eb")
            == normalize_url("https://example.com/a%7Eb")
        )
        # also applies to the query string
        assert (
            normalize_url("https://example.com/p?k=%2fa")
            == normalize_url("https://example.com/p?k=%2Fa")
        )

    def test_dot_segments_removed(self) -> None:
        """F-005 fix (Codex P2): RFC 3986 §5.2.4 — remove "./" and "../"."""
        assert (
            normalize_url("https://example.com/a/../b")
            == "https://example.com/b"
        )
        assert (
            normalize_url("https://example.com/./a/b")
            == "https://example.com/a/b"
        )
        assert (
            normalize_url("https://example.com/a/b/..")
            == "https://example.com/a"
        )

    def test_ipv6_host_brackets_preserved(self) -> None:
        """F-004 fix (Codex P2): IPv6 literals must keep their ``[]`` after
        urlsplit/urlunsplit round-trip."""
        out = normalize_url("https://[2001:db8::1]/x")
        assert out == "https://[2001:db8::1]/x"
        # default port for IPv6 also stripped
        out_port = normalize_url("https://[2001:db8::1]:443/x")
        assert out_port == "https://[2001:db8::1]/x"
        # non-default port kept
        out_nondefault = normalize_url("https://[2001:db8::1]:8443/x")
        assert out_nondefault == "https://[2001:db8::1]:8443/x"


class TestPROVBundle:
    def test_minimal_relations_constant_is_5(self) -> None:
        assert PROV_RELATIONS_MINIMAL == {
            "wasGeneratedBy",
            "used",
            "wasAttributedTo",
            "wasInformedBy",
            "wasDerivedFrom",
        }
        assert len(PROV_RELATIONS_MINIMAL) == 5

    def test_unknown_relation_rejected(self) -> None:
        cid = uuid4()
        prov = {
            cid: {"relations": {"madeUp": [{"x": "y"}]}}
        }
        with pytest.raises(EvidenceSetHashError) as exc:
            compute_evidence_set_hash(
                [_claim("c", claim_id=cid)], [], prov
            )
        assert exc.value.reason_code == "prov_relation_unknown"

    def test_top_level_relations_change_hash(self) -> None:
        """F-001 fix (Codex P1): PROV relations at top level (ProvBundle schema)
        must affect evidence_set_hash. Previously the hash read
        ``prov.get("relations", {})`` and silently dropped real PROV content."""
        cid = uuid4()
        prov_with = {
            cid: {
                "activities": [{"id": "act-1"}],
                "entities": [{"id": "ent-1"}],
                "agents": [{"id": "agt-1"}],
                "wasGeneratedBy": [{"generated": "ent-1", "activity": "act-1"}],
                "used": [{"activity": "act-1", "used": "ent-1"}],
            }
        }
        prov_without = {cid: {}}
        h_with = compute_evidence_set_hash(
            [_claim("c", claim_id=cid)], [], prov_with
        )
        h_without = compute_evidence_set_hash(
            [_claim("c", claim_id=cid)], [], prov_without
        )
        assert h_with != h_without

    def test_legacy_relations_sub_mapping_still_accepted(self) -> None:
        """Legacy bundles that nest relations under ``relations`` still hash
        correctly (backward compat fallback path)."""
        cid = uuid4()
        prov_top = {
            cid: {
                "wasGeneratedBy": [{"generated": "e1", "activity": "a1"}],
            }
        }
        prov_legacy = {
            cid: {
                "relations": {
                    "wasGeneratedBy": [{"generated": "e1", "activity": "a1"}],
                },
            }
        }
        h_top = compute_evidence_set_hash(
            [_claim("c", claim_id=cid)], [], prov_top
        )
        h_legacy = compute_evidence_set_hash(
            [_claim("c", claim_id=cid)], [], prov_legacy
        )
        assert h_top == h_legacy

    def test_missing_prov_treated_as_empty(self) -> None:
        # No PROV entry for the claim → not an error, just hashes the empty
        # canonical PROV section.
        cid = uuid4()
        h = compute_evidence_set_hash(
            [_claim("c", claim_id=cid)], [], {}
        , require_provenance=False)
        assert len(h) == 64

    def test_prov_bundle_not_object_rejected(self) -> None:
        cid = uuid4()
        with pytest.raises(EvidenceSetHashError) as exc:
            compute_evidence_set_hash(
                [_claim("c", claim_id=cid)], [], {cid: "not a dict"}
            )
        assert exc.value.reason_code == "prov_bundle_not_object"

    def test_activities_not_list_rejected(self) -> None:
        cid = uuid4()
        prov = {cid: {"activities": "not a list"}}
        with pytest.raises(EvidenceSetHashError) as exc:
            compute_evidence_set_hash(
                [_claim("c", claim_id=cid)], [], prov
            )
        assert exc.value.reason_code == "prov_activities_not_list"


class TestR2EvidenceItems:
    """F-R2-001 fix (Codex R2 P1): evidence_items must affect hash."""

    def _ei(
        self,
        claim_id: UUID,
        source_id: UUID,
        locator: str = "p1",
        relation: str = "supports",
        relevance_score: float | None = 0.9,
        ei_id: UUID | None = None,
    ) -> EvidenceItemNormalized:
        return EvidenceItemNormalized.from_raw(
            id=ei_id or uuid4(),
            claim_id=claim_id,
            source_id=source_id,
            locator=locator,
            relation=relation,
            relevance_score=relevance_score,
        )

    def test_locator_change_shifts_hash(self) -> None:
        cid = uuid4()
        sid = uuid4()
        c = _claim("c", claim_id=cid)
        s = _source("https://example.com/a", source_id=sid)
        ei_id = uuid4()
        ei_p1 = self._ei(cid, sid, locator="p1", ei_id=ei_id)
        ei_p2 = self._ei(cid, sid, locator="p2", ei_id=ei_id)
        h1 = compute_evidence_set_hash(
            [c], [s], {}, [ei_p1], require_provenance=False
        )
        h2 = compute_evidence_set_hash(
            [c], [s], {}, [ei_p2], require_provenance=False
        )
        assert h1 != h2

    def test_relation_change_shifts_hash(self) -> None:
        cid = uuid4()
        sid = uuid4()
        c = _claim("c", claim_id=cid)
        s = _source("https://example.com/a", source_id=sid)
        ei_id = uuid4()
        ei_s = self._ei(cid, sid, relation="supports", ei_id=ei_id)
        ei_c = self._ei(cid, sid, relation="contradicts", ei_id=ei_id)
        h_s = compute_evidence_set_hash(
            [c], [s], {}, [ei_s], require_provenance=False
        )
        h_c = compute_evidence_set_hash(
            [c], [s], {}, [ei_c], require_provenance=False
        )
        assert h_s != h_c

    def test_relevance_score_change_shifts_hash(self) -> None:
        cid = uuid4()
        sid = uuid4()
        c = _claim("c", claim_id=cid)
        s = _source("https://example.com/a", source_id=sid)
        ei_id = uuid4()
        ei_low = self._ei(cid, sid, relevance_score=0.3, ei_id=ei_id)
        ei_high = self._ei(cid, sid, relevance_score=0.9, ei_id=ei_id)
        h_low = compute_evidence_set_hash(
            [c], [s], {}, [ei_low], require_provenance=False
        )
        h_high = compute_evidence_set_hash(
            [c], [s], {}, [ei_high], require_provenance=False
        )
        assert h_low != h_high

    def test_evidence_items_order_irrelevant(self) -> None:
        cid = uuid4()
        sid = uuid4()
        c = _claim("c", claim_id=cid)
        s = _source("https://example.com/a", source_id=sid)
        ei1 = self._ei(cid, sid, locator="p1")
        ei2 = self._ei(cid, sid, locator="p2")
        h_forward = compute_evidence_set_hash(
            [c], [s], {}, [ei1, ei2], require_provenance=False
        )
        h_reverse = compute_evidence_set_hash(
            [c], [s], {}, [ei2, ei1], require_provenance=False
        )
        assert h_forward == h_reverse

    def test_relation_enum_invalid_rejected(self) -> None:
        with pytest.raises(EvidenceSetHashError) as exc:
            EvidenceItemNormalized.from_raw(
                id=uuid4(),
                claim_id=uuid4(),
                source_id=uuid4(),
                locator="p1",
                relation="madeup",
            )
        assert exc.value.reason_code == "evidence_item_relation_invalid"

    def test_relation_enum_constant_matches_db(self) -> None:
        assert EVIDENCE_ITEM_RELATIONS == {"supports", "contradicts", "context"}

    def test_relevance_out_of_range_rejected(self) -> None:
        with pytest.raises(EvidenceSetHashError) as exc:
            EvidenceItemNormalized.from_raw(
                id=uuid4(),
                claim_id=uuid4(),
                source_id=uuid4(),
                locator="p1",
                relation="supports",
                relevance_score=1.5,
            )
        assert exc.value.reason_code == "evidence_item_relevance_out_of_range"

    def test_relevance_bool_rejected(self) -> None:
        """bool is subclass of int; reject explicitly so True/False can't mask."""
        with pytest.raises(EvidenceSetHashError) as exc:
            EvidenceItemNormalized.from_raw(
                id=uuid4(),
                claim_id=uuid4(),
                source_id=uuid4(),
                locator="p1",
                relation="supports",
                relevance_score=True,  # type: ignore[arg-type]
            )
        assert exc.value.reason_code == "evidence_item_relevance_type_invalid"


class TestR2ProvNamespaceAlias:
    """F-R2-002 fix (Codex R2 P2): prov: namespace aliases hash identically."""

    def test_prefixed_relation_same_as_unprefixed(self) -> None:
        cid = uuid4()
        prov_unprefixed = {
            cid: {
                "wasGeneratedBy": [
                    {"generated": "ent-1", "activity": "act-1"}
                ],
            }
        }
        prov_prefixed = {
            cid: {
                "prov:wasGeneratedBy": [
                    {"generated": "ent-1", "activity": "act-1"}
                ],
            }
        }
        h_un = compute_evidence_set_hash(
            [_claim("c", claim_id=cid)], [], prov_unprefixed
        )
        h_pre = compute_evidence_set_hash(
            [_claim("c", claim_id=cid)], [], prov_prefixed
        )
        assert h_un == h_pre

    def test_duplicate_aliased_key_with_conflict_rejected(self) -> None:
        cid = uuid4()
        prov = {
            cid: {
                "wasGeneratedBy": [{"a": 1}],
                "prov:wasGeneratedBy": [{"a": 2}],
            }
        }
        with pytest.raises(EvidenceSetHashError) as exc:
            compute_evidence_set_hash([_claim("c", claim_id=cid)], [], prov)
        assert exc.value.reason_code == "prov_duplicate_aliased_key"


class TestR2UrlPortWrap:
    """F-R2-003 fix (Codex R2 P2): malformed port → EvidenceSetHashError."""

    def test_non_numeric_port_wrapped(self) -> None:
        with pytest.raises(EvidenceSetHashError) as exc:
            normalize_url("https://example.com:abc/x")
        assert exc.value.reason_code == "url_port_invalid"

    def test_out_of_range_port_wrapped(self) -> None:
        with pytest.raises(EvidenceSetHashError) as exc:
            normalize_url("https://example.com:99999/x")
        assert exc.value.reason_code == "url_port_invalid"


class TestR2ProvenanceFailClosed:
    """F-R2-004 fix (Codex R2 P2): missing provenance fails closed."""

    def test_missing_provenance_default_fails_closed(self) -> None:
        cid = uuid4()
        with pytest.raises(EvidenceSetHashError) as exc:
            compute_evidence_set_hash(
                [_claim("c", claim_id=cid)],
                [],
                {},
            )
        assert exc.value.reason_code == "provenance_missing_for_claim"

    def test_require_provenance_false_test_fixture_still_works(self) -> None:
        cid = uuid4()
        h = compute_evidence_set_hash(
            [_claim("c", claim_id=cid)],
            [],
            {},
            require_provenance=False,
        )
        assert len(h) == 64


class TestInputValidation:
    def test_claim_text_non_string_rejected(self) -> None:
        with pytest.raises(EvidenceSetHashError) as exc:
            ClaimNormalized.from_raw(claim_id=uuid4(), claim_text=42)
        assert exc.value.reason_code == "claim_text_type_invalid"

    def test_source_content_hash_wrong_length(self) -> None:
        with pytest.raises(EvidenceSetHashError) as exc:
            SourceNormalized.from_raw(
                source_id=uuid4(),
                canonical_url="https://example.com",
                content_hash="abc",
            )
        assert exc.value.reason_code == "content_hash_shape_invalid"

    def test_source_content_hash_non_hex_rejected(self) -> None:
        """F-003 fix (Codex P2): a 64-char non-hex string (e.g. 'zzzz...')
        previously passed the length check; require regex hex validation."""
        with pytest.raises(EvidenceSetHashError) as exc:
            SourceNormalized.from_raw(
                source_id=uuid4(),
                canonical_url="https://example.com",
                content_hash="z" * 64,
            )
        assert exc.value.reason_code == "content_hash_shape_invalid"

    def test_source_content_hash_uppercase_hex_accepted_normalized_lower(self) -> None:
        """sha256 hex MAY be uppercase from some callers; we accept and
        lowercase canonically so the stored value is stable."""
        s = SourceNormalized.from_raw(
            source_id=uuid4(),
            canonical_url="https://example.com",
            content_hash="A" * 64,
        )
        assert s.content_hash == "a" * 64

    def test_source_canonical_url_non_string(self) -> None:
        with pytest.raises(EvidenceSetHashError) as exc:
            SourceNormalized.from_raw(
                source_id=uuid4(),
                canonical_url=None,
                content_hash="0" * 64,
            )
        assert exc.value.reason_code == "canonical_url_type_invalid"


class TestR3ProvNodeSectionAlias:
    """F-R3-003 fix (Codex R3 P1): ``prov:activities`` / ``prov:entities`` /
    ``prov:agents`` are accepted by the validator and MUST hash identically to
    their unprefixed forms. Pre-R3 the alias map only covered relations, so a
    bundle persisted with prefixed node sections silently hashed with empty
    activities/entities/agents."""

    def test_prefixed_activities_same_as_unprefixed(self) -> None:
        cid = uuid4()
        unprefixed = {
            cid: {
                "activities": [{"id": "act-1", "type": "prov:Activity"}],
                "wasGeneratedBy": [
                    {"generated": "ent-1", "activity": "act-1"}
                ],
            }
        }
        prefixed = {
            cid: {
                "prov:activities": [{"id": "act-1", "type": "prov:Activity"}],
                "wasGeneratedBy": [
                    {"generated": "ent-1", "activity": "act-1"}
                ],
            }
        }
        h_un = compute_evidence_set_hash([_claim("c", claim_id=cid)], [], unprefixed)
        h_pre = compute_evidence_set_hash([_claim("c", claim_id=cid)], [], prefixed)
        assert h_un == h_pre

    def test_prefixed_entities_same_as_unprefixed(self) -> None:
        cid = uuid4()
        unprefixed = {
            cid: {
                "entities": [{"id": "ent-1", "type": "prov:Entity"}],
                "wasGeneratedBy": [
                    {"generated": "ent-1", "activity": "act-1"}
                ],
            }
        }
        prefixed = {
            cid: {
                "prov:entities": [{"id": "ent-1", "type": "prov:Entity"}],
                "wasGeneratedBy": [
                    {"generated": "ent-1", "activity": "act-1"}
                ],
            }
        }
        h_un = compute_evidence_set_hash([_claim("c", claim_id=cid)], [], unprefixed)
        h_pre = compute_evidence_set_hash([_claim("c", claim_id=cid)], [], prefixed)
        assert h_un == h_pre

    def test_prefixed_agents_same_as_unprefixed(self) -> None:
        cid = uuid4()
        unprefixed = {
            cid: {
                "agents": [{"id": "agent-1", "type": "prov:Agent"}],
                "wasGeneratedBy": [
                    {"generated": "ent-1", "activity": "act-1"}
                ],
            }
        }
        prefixed = {
            cid: {
                "prov:agents": [{"id": "agent-1", "type": "prov:Agent"}],
                "wasGeneratedBy": [
                    {"generated": "ent-1", "activity": "act-1"}
                ],
            }
        }
        h_un = compute_evidence_set_hash([_claim("c", claim_id=cid)], [], unprefixed)
        h_pre = compute_evidence_set_hash([_claim("c", claim_id=cid)], [], prefixed)
        assert h_un == h_pre

    def test_prefixed_and_unprefixed_node_section_conflict_rejected(self) -> None:
        cid = uuid4()
        prov = {
            cid: {
                "activities": [{"id": "a1"}],
                "prov:activities": [{"id": "a2"}],
                "wasGeneratedBy": [{"generated": "ent-1", "activity": "act-1"}],
            }
        }
        with pytest.raises(EvidenceSetHashError) as exc:
            compute_evidence_set_hash([_claim("c", claim_id=cid)], [], prov)
        assert exc.value.reason_code == "prov_duplicate_aliased_key"


class TestR3JCSNumberCanonical:
    """F-R3-004 fix (Codex R3 P2): RFC 8785 / ECMA-262 ToString(Number)
    canonicalization. Python ``json.dumps`` deviates from JCS for several
    float subcases that ride in the canonical body via
    ``evidence_items.relevance_score``."""

    def test_integer_float_emits_no_decimal_point(self) -> None:
        assert _ecma_number_to_string(1.0) == "1"
        assert _ecma_number_to_string(0.0) == "0"
        assert _ecma_number_to_string(-0.0) == "0"  # collapse signed zero

    def test_small_magnitude_uses_decimal_form_not_scientific(self) -> None:
        assert _ecma_number_to_string(1e-06) == "0.000001"
        assert _ecma_number_to_string(1e-05) == "0.00001"

    def test_normal_floats_round_trip_shortest_decimal(self) -> None:
        assert _ecma_number_to_string(0.5) == "0.5"
        assert _ecma_number_to_string(0.9) == "0.9"

    def test_int_emits_str(self) -> None:
        assert _ecma_number_to_string(0) == "0"
        assert _ecma_number_to_string(1) == "1"
        assert _ecma_number_to_string(42) == "42"

    def test_nan_rejected(self) -> None:
        with pytest.raises(EvidenceSetHashError) as exc:
            _ecma_number_to_string(float("nan"))
        assert exc.value.reason_code == "jcs_nan_forbidden"

    def test_infinity_rejected(self) -> None:
        with pytest.raises(EvidenceSetHashError) as exc:
            _ecma_number_to_string(float("inf"))
        assert exc.value.reason_code == "jcs_infinity_forbidden"

    def test_bool_rejected_as_number(self) -> None:
        """bool is a subclass of int in Python; the JCS encoder must short-
        circuit booleans to ``true`` / ``false`` and never hash them as
        numbers."""
        with pytest.raises(EvidenceSetHashError) as exc:
            _ecma_number_to_string(True)  # type: ignore[arg-type]
        assert exc.value.reason_code == "jcs_bool_not_number"

    def test_jcs_dumps_emits_canonical_floats(self) -> None:
        body = {"a": 1.0, "b": 1e-06, "c": -0.0}
        out = _jcs_dumps(body)
        # keys sorted, no spaces, floats canonical
        assert out == '{"a":1,"b":0.000001,"c":0}'

    def test_jcs_dumps_emits_canonical_strings_and_bools(self) -> None:
        out = _jcs_dumps({"k": "v", "b": True, "n": None, "l": [1, 2]})
        assert out == '{"b":true,"k":"v","l":[1,2],"n":null}'

    def test_jcs_dumps_unsupported_type_rejected(self) -> None:
        with pytest.raises(EvidenceSetHashError) as exc:
            _jcs_dumps({"k": object()})  # type: ignore[dict-item]
        assert exc.value.reason_code == "jcs_unsupported_type"

    def test_jcs_dumps_non_string_key_rejected(self) -> None:
        with pytest.raises(EvidenceSetHashError) as exc:
            _jcs_dumps({1: "v"})  # type: ignore[dict-item]
        assert exc.value.reason_code == "jcs_non_string_key"

    def test_float_drift_in_relevance_score_visible_in_hash(self) -> None:
        """End-to-end: an evidence_item with relevance_score=1.0 must hash
        identically to relevance_score=1 (int); pre-R3 they would have
        diverged via ``1.0`` vs ``1`` JSON encoding."""
        cid = uuid4()
        sid = uuid4()
        eid = uuid4()
        prov = {cid: {"wasGeneratedBy": [{"generated": "e1", "activity": "a1"}]}}
        h_float = compute_evidence_set_hash(
            [_claim("c", claim_id=cid)],
            [_source("https://example.com", source_id=sid)],
            prov,
            evidence_items=[
                EvidenceItemNormalized.from_raw(
                    id=eid,
                    claim_id=cid,
                    source_id=sid,
                    locator="p.1",
                    relation="supports",
                    relevance_score=1.0,
                )
            ],
        )
        h_int = compute_evidence_set_hash(
            [_claim("c", claim_id=cid)],
            [_source("https://example.com", source_id=sid)],
            prov,
            evidence_items=[
                EvidenceItemNormalized.from_raw(
                    id=eid,
                    claim_id=cid,
                    source_id=sid,
                    locator="p.1",
                    relation="supports",
                    relevance_score=1,
                )
            ],
        )
        assert h_float == h_int


class TestR3EvidenceItemsTotalOrdering:
    """F-R3-005 fix (Codex R3 P2): evidence_items sort key must include the
    PK so two rows that share claim/source/locator/relation but differ in
    ``id`` (and downstream relevance_score) have a deterministic total
    ordering. Pre-R3 the stable sort leaked caller-side input order."""

    def test_same_compound_key_different_id_deterministic(self) -> None:
        cid = uuid4()
        sid = uuid4()
        # Pick IDs whose UUID ordering is known so we can flip caller-side
        # ordering and verify the producer re-sorts deterministically.
        eid_a = UUID("00000000-0000-0000-0000-000000000001")
        eid_b = UUID("00000000-0000-0000-0000-000000000002")
        prov = {cid: {"wasGeneratedBy": [{"generated": "e1", "activity": "a1"}]}}

        item_a = EvidenceItemNormalized.from_raw(
            id=eid_a,
            claim_id=cid,
            source_id=sid,
            locator="p.1",
            relation="supports",
            relevance_score=0.5,
        )
        item_b = EvidenceItemNormalized.from_raw(
            id=eid_b,
            claim_id=cid,
            source_id=sid,
            locator="p.1",
            relation="supports",
            relevance_score=0.7,
        )

        h_ab = compute_evidence_set_hash(
            [_claim("c", claim_id=cid)],
            [_source("https://example.com", source_id=sid)],
            prov,
            evidence_items=[item_a, item_b],
        )
        h_ba = compute_evidence_set_hash(
            [_claim("c", claim_id=cid)],
            [_source("https://example.com", source_id=sid)],
            prov,
            evidence_items=[item_b, item_a],
        )
        assert h_ab == h_ba

    def test_id_change_only_shifts_hash(self) -> None:
        """If the only difference is the evidence_item ``id`` (claim/source/
        locator/relation/score identical), the hash must still shift — the
        ``id`` is part of the canonical body, not just the sort key."""
        cid = uuid4()
        sid = uuid4()
        prov = {cid: {"wasGeneratedBy": [{"generated": "e1", "activity": "a1"}]}}
        h1 = compute_evidence_set_hash(
            [_claim("c", claim_id=cid)],
            [_source("https://example.com", source_id=sid)],
            prov,
            evidence_items=[
                EvidenceItemNormalized.from_raw(
                    id=UUID("00000000-0000-0000-0000-000000000001"),
                    claim_id=cid,
                    source_id=sid,
                    locator="p.1",
                    relation="supports",
                    relevance_score=0.5,
                )
            ],
        )
        h2 = compute_evidence_set_hash(
            [_claim("c", claim_id=cid)],
            [_source("https://example.com", source_id=sid)],
            prov,
            evidence_items=[
                EvidenceItemNormalized.from_raw(
                    id=UUID("00000000-0000-0000-0000-000000000002"),
                    claim_id=cid,
                    source_id=sid,
                    locator="p.1",
                    relation="supports",
                    relevance_score=0.5,
                )
            ],
        )
        assert h1 != h2


class TestR4EcmaScientificNotation:
    """F-R4-001 fix (Codex R4 P2): ECMA-262 ToString(Number) uses scientific
    notation for ``|x| < 1e-6`` and ``|x| >= 1e21``. Pre-R4 the producer
    used ``Decimal`` fixed-point formatting which emitted ``0.0000001``
    instead of the canonical ``1e-7``."""

    def test_tiny_relevance_score_uses_scientific(self) -> None:
        # 1e-7: ECMA-262 emits "1e-7" (n=-6 fails the "-6 < n ≤ 0" gate).
        assert _ecma_number_to_string(1e-7) == "1e-7"

    def test_subnormal_floor_uses_scientific(self) -> None:
        # 1e-308 is near the IEEE-754 double precision floor; must canonicalize.
        assert _ecma_number_to_string(1e-308) == "1e-308"

    def test_boundary_1e_minus_6_decimal(self) -> None:
        # 1e-6 sits on the boundary; ECMA emits "0.000001" (n=-5, in "-6 < n ≤ 0").
        assert _ecma_number_to_string(1e-6) == "0.000001"

    def test_large_magnitude_uses_scientific(self) -> None:
        # 1e21 crosses into scientific (n=22 > 21).
        assert _ecma_number_to_string(1e21) == "1e+21"

    def test_large_magnitude_boundary_decimal(self) -> None:
        # 1e20 stays decimal (n=21, in "k ≤ n ≤ 21").
        assert _ecma_number_to_string(1e20) == "100000000000000000000"

    def test_negative_number_preserves_sign(self) -> None:
        assert _ecma_number_to_string(-1.5) == "-1.5"
        assert _ecma_number_to_string(-1e-7) == "-1e-7"


class TestR4ProvUnknownTopLevelReject:
    """F-R4-002 fix (Codex R4 P2): unknown top-level PROV keys (not in the
    minimal 5 relations / 3 node sections / legacy ``relations`` map) must
    fail-closed. Pre-R4 the helper silently ignored them, so a bundle
    differing only in an extra relation hashed identically."""

    def test_unknown_top_level_relation_rejected(self) -> None:
        cid = uuid4()
        prov = {
            cid: {
                "wasGeneratedBy": [{"generated": "e1", "activity": "a1"}],
                "wasInvalidatedBy": [{"entity": "e1", "activity": "a1"}],
            }
        }
        with pytest.raises(EvidenceSetHashError) as exc:
            compute_evidence_set_hash([_claim("c", claim_id=cid)], [], prov)
        assert exc.value.reason_code == "prov_unknown_top_level_key"

    def test_unknown_top_level_metadata_rejected(self) -> None:
        cid = uuid4()
        prov = {
            cid: {
                "wasGeneratedBy": [{"generated": "e1", "activity": "a1"}],
                "custom_extension": {"foo": "bar"},
            }
        }
        with pytest.raises(EvidenceSetHashError) as exc:
            compute_evidence_set_hash([_claim("c", claim_id=cid)], [], prov)
        assert exc.value.reason_code == "prov_unknown_top_level_key"

    def test_known_top_level_keys_accepted(self) -> None:
        # All minimal relations + node sections + legacy "relations" allowed.
        cid = uuid4()
        prov = {
            cid: {
                "activities": [],
                "entities": [],
                "agents": [],
                "wasGeneratedBy": [{"generated": "e1", "activity": "a1"}],
                "used": [],
                "wasAttributedTo": [],
                "wasInformedBy": [],
                "wasDerivedFrom": [],
                "relations": {},  # legacy fallback
            }
        }
        h = compute_evidence_set_hash([_claim("c", claim_id=cid)], [], prov)
        assert len(h) == 64


class TestR4EvidenceItemDanglingReject:
    """F-R4-003 fix (Codex R4 P2): evidence_items referencing a claim_id or
    source_id absent from the input sets must fail-closed. Pre-R4 the
    producer hashed only the bare UUID + locator/relation/score so two
    snapshots with the same evidence_item UUID but *missing* claim text
    or source URL would collide on hash."""

    def test_dangling_claim_id_rejected(self) -> None:
        cid_in_set = uuid4()
        cid_dangling = uuid4()
        sid = uuid4()
        eid = uuid4()
        prov = {cid_in_set: {"wasGeneratedBy": [{"generated": "e1", "activity": "a1"}]}}
        with pytest.raises(EvidenceSetHashError) as exc:
            compute_evidence_set_hash(
                [_claim("c", claim_id=cid_in_set)],
                [_source("https://example.com", source_id=sid)],
                prov,
                evidence_items=[
                    EvidenceItemNormalized.from_raw(
                        id=eid,
                        claim_id=cid_dangling,  # NOT in claims input
                        source_id=sid,
                        locator="p.1",
                        relation="supports",
                    )
                ],
            )
        assert exc.value.reason_code == "evidence_item_claim_dangling"

    def test_dangling_source_id_rejected(self) -> None:
        cid = uuid4()
        sid_in_set = uuid4()
        sid_dangling = uuid4()
        eid = uuid4()
        prov = {cid: {"wasGeneratedBy": [{"generated": "e1", "activity": "a1"}]}}
        with pytest.raises(EvidenceSetHashError) as exc:
            compute_evidence_set_hash(
                [_claim("c", claim_id=cid)],
                [_source("https://example.com", source_id=sid_in_set)],
                prov,
                evidence_items=[
                    EvidenceItemNormalized.from_raw(
                        id=eid,
                        claim_id=cid,
                        source_id=sid_dangling,  # NOT in sources input
                        locator="p.1",
                        relation="supports",
                    )
                ],
            )
        assert exc.value.reason_code == "evidence_item_source_dangling"

    def test_valid_membership_accepted(self) -> None:
        cid = uuid4()
        sid = uuid4()
        eid = uuid4()
        prov = {cid: {"wasGeneratedBy": [{"generated": "e1", "activity": "a1"}]}}
        h = compute_evidence_set_hash(
            [_claim("c", claim_id=cid)],
            [_source("https://example.com", source_id=sid)],
            prov,
            evidence_items=[
                EvidenceItemNormalized.from_raw(
                    id=eid,
                    claim_id=cid,
                    source_id=sid,
                    locator="p.1",
                    relation="supports",
                )
            ],
        )
        assert len(h) == 64


class TestR5LegacyRelationsValidation:
    """F-R5-001 fix (Codex R5 P2): legacy ``"relations"`` top-level key
    must be a dict if present; non-dict (array / string / number) silently
    skipped pre-R5 so a bad migration could share a hash with the no-
    relations variant."""

    def test_legacy_relations_array_rejected(self) -> None:
        cid = uuid4()
        prov = {
            cid: {
                "wasGeneratedBy": [{"generated": "e1", "activity": "a1"}],
                "relations": [],  # array instead of dict
            }
        }
        with pytest.raises(EvidenceSetHashError) as exc:
            compute_evidence_set_hash([_claim("c", claim_id=cid)], [], prov)
        assert exc.value.reason_code == "prov_legacy_relations_not_object"

    def test_legacy_relations_string_rejected(self) -> None:
        cid = uuid4()
        prov = {
            cid: {
                "wasGeneratedBy": [{"generated": "e1", "activity": "a1"}],
                "relations": "oops",  # string instead of dict
            }
        }
        with pytest.raises(EvidenceSetHashError) as exc:
            compute_evidence_set_hash([_claim("c", claim_id=cid)], [], prov)
        assert exc.value.reason_code == "prov_legacy_relations_not_object"

    def test_legacy_relations_dict_still_accepted(self) -> None:
        # Backward compat: legacy dict shape still works.
        cid = uuid4()
        prov = {
            cid: {
                "wasGeneratedBy": [{"generated": "e1", "activity": "a1"}],
                "relations": {
                    "used": [{"activity": "a1", "entity": "e2"}],
                },
            }
        }
        h = compute_evidence_set_hash([_claim("c", claim_id=cid)], [], prov)
        assert len(h) == 64


class TestR5SupplementaryPlaneKeyReject:
    """F-R5-002 fix (Codex R5 P3): JCS sorts by UTF-16 code units, not by
    Unicode code point. The two orderings diverge as soon as a key
    contains a supplementary-plane character. Reject so the hash stays
    portable across stacks (BMP-only paths are unaffected)."""

    def test_supplementary_plane_key_in_prov_rejected(self) -> None:
        cid = uuid4()
        # \U0001F600 (😀) is a supplementary-plane code point that JCS
        # would sort before BMP keys above U+DFFF — divergent from Python.
        prov = {
            cid: {
                "wasGeneratedBy": [{"generated": "e1", "activity": "a1"}],
                # Smuggle a supplementary-plane field name into a relation
                # item (bypasses prov_validator's strict schema — only
                # reachable when callers skip the validator).
                "used": [{"activity": "a1", "entity": "e1", "\U0001F600": "x"}],
            }
        }
        with pytest.raises(EvidenceSetHashError) as exc:
            compute_evidence_set_hash([_claim("c", claim_id=cid)], [], prov)
        assert exc.value.reason_code == "jcs_supplementary_plane_key"

    def test_bmp_key_accepted(self) -> None:
        # BMP characters (codepoint < 0x10000) sort identically to UTF-16
        # code units — accept.
        cid = uuid4()
        prov = {
            cid: {
                "wasGeneratedBy": [{"generated": "e1", "activity": "a1"}],
                # Latin-1 + CJK BMP characters
                "used": [{"activity": "a1", "entity": "e1", "日本語": "ok"}],
            }
        }
        h = compute_evidence_set_hash([_claim("c", claim_id=cid)], [], prov)
        assert len(h) == 64


class TestR5ExtraProvenanceReject:
    """F-R5-003 fix (Codex R5 P2): ``provenance_per_claim`` entries for
    claim_ids absent from the ``claims`` input set must fail-closed. Pre-
    R5 they were silently dropped, hiding snapshot-assembly bugs where
    a claim row is removed but its provenance lingers."""

    def test_extra_provenance_entry_rejected(self) -> None:
        cid_in_set = uuid4()
        cid_extra = uuid4()
        prov = {
            cid_in_set: {"wasGeneratedBy": [{"generated": "e1", "activity": "a1"}]},
            cid_extra: {"wasGeneratedBy": [{"generated": "e1", "activity": "a1"}]},
        }
        with pytest.raises(EvidenceSetHashError) as exc:
            compute_evidence_set_hash([_claim("c", claim_id=cid_in_set)], [], prov)
        assert exc.value.reason_code == "provenance_extra_claim_id"

    def test_extra_provenance_rejected_even_with_require_false(self) -> None:
        """Symmetric direction is always enforced; ``require_provenance``
        only controls whether *missing* provenance is fatal."""
        cid_in_set = uuid4()
        cid_extra = uuid4()
        prov = {
            cid_extra: {"wasGeneratedBy": [{"generated": "e1", "activity": "a1"}]},
        }
        with pytest.raises(EvidenceSetHashError) as exc:
            compute_evidence_set_hash(
                [_claim("c", claim_id=cid_in_set)],
                [],
                prov,
                require_provenance=False,
            )
        assert exc.value.reason_code == "provenance_extra_claim_id"


class TestRandomFuzz:
    @pytest.mark.parametrize("seed", range(20))
    def test_random_inputs_deterministic(self, seed: int) -> None:
        """Generate 20 random claim/source sets, each verified to be stable
        across two passes. Combined with the 1000-replay test above this gives
        the ≥ 1000 deterministic samples that SP-010 受け入れ条件 requires."""
        # PYTHONHASHSEED-resistant random: use ``secrets`` for IDs but
        # reproducible per-test data layout.
        rng_str = f"sample-{seed}"
        claims = [
            _claim(f"{rng_str}-claim-{i}", claim_id=uuid4())
            for i in range(3)
        ]
        sources = [
            _source(
                f"https://example.com/seed/{seed}/item/{i}",
                content_hash=secrets.token_hex(32),
                source_id=uuid4(),
            )
            for i in range(2)
        ]
        h1 = compute_evidence_set_hash(claims, sources, {}, require_provenance=False)
        h2 = compute_evidence_set_hash(claims, sources, {}, require_provenance=False)
        assert h1 == h2 and len(h1) == 64
