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
