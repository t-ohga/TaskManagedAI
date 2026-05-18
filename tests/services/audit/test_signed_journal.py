"""Sprint 12 batch 10: signed journal hash chain tests (pure function, no DB)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from backend.app.db.models.audit_event import AuditEvent
from backend.app.services.audit.signed_journal import (
    SIGNED_JOURNAL_INITIAL_HASH,
    SignedJournalChain,
    build_signed_journal_chain,
    verify_signed_journal_chain,
)


def _make_event(
    *,
    event_type: str,
    event_payload: dict[str, Any],
    audit_event_id: UUID | None = None,
    created_at: datetime | None = None,
    actor_id: UUID | None = None,
    correlation_id: str | None = None,
) -> AuditEvent:
    """Create a synthetic AuditEvent ORM instance (no DB).

    `created_at` is normally server-side default; for hashing tests we set it
    explicitly via attribute assignment (Mapped fields permit direct assign
    on detached instances).
    """
    audit_event = AuditEvent(
        id=audit_event_id if audit_event_id is not None else uuid4(),
        tenant_id=1,
        event_type=event_type,
        event_payload=event_payload,
        actor_id=actor_id,
        principal_id=None,
        correlation_id=correlation_id,
        trace_id=None,
    )
    # AuditEvent.created_at default は server side、test fixture では explicit set.
    audit_event.created_at = (
        created_at if created_at is not None else datetime(2026, 5, 18, tzinfo=UTC)
    )
    return audit_event


def test_empty_chain_returns_initial_hash() -> None:
    """No audit events → final_hash = SIGNED_JOURNAL_INITIAL_HASH."""
    chain = build_signed_journal_chain([])
    assert isinstance(chain, SignedJournalChain)
    assert chain.entry_count == 0
    assert chain.final_hash == SIGNED_JOURNAL_INITIAL_HASH
    assert chain.entries == ()


def test_initial_hash_constant_is_64_hex_zeros() -> None:
    """genesis sentinel は 64-char zero string (convention)."""
    assert SIGNED_JOURNAL_INITIAL_HASH == "0" * 64
    assert len(SIGNED_JOURNAL_INITIAL_HASH) == 64


def test_single_entry_chain_first_previous_hash_is_initial() -> None:
    """1 event chain: 最初の previous_hash = INITIAL_HASH."""
    event = _make_event(
        event_type="p0_acceptance_report_generated",
        event_payload={"final_chain_sha256": "a" * 64},
    )
    chain = build_signed_journal_chain([event])
    assert chain.entry_count == 1
    assert chain.entries[0].previous_hash == SIGNED_JOURNAL_INITIAL_HASH
    assert chain.entries[0].entry_hash != SIGNED_JOURNAL_INITIAL_HASH
    assert chain.final_hash == chain.entries[0].entry_hash


def test_two_entry_chain_links_previous_hash() -> None:
    """2 event chain: entry[1].previous_hash == entry[0].entry_hash."""
    e1 = _make_event(
        event_type="evt1",
        event_payload={"data": "first"},
        audit_event_id=UUID("11111111-1111-4111-8111-111111111111"),
    )
    e2 = _make_event(
        event_type="evt2",
        event_payload={"data": "second"},
        audit_event_id=UUID("22222222-2222-4222-8222-222222222222"),
    )
    chain = build_signed_journal_chain([e1, e2])
    assert chain.entry_count == 2
    assert chain.entries[0].previous_hash == SIGNED_JOURNAL_INITIAL_HASH
    assert chain.entries[1].previous_hash == chain.entries[0].entry_hash
    assert chain.final_hash == chain.entries[1].entry_hash


def test_chain_is_deterministic_for_same_input() -> None:
    """同 input は同 final_hash を返す (hash chain reproducibility)."""
    e1 = _make_event(
        event_type="evt1",
        event_payload={"data": "deterministic"},
        audit_event_id=UUID("33333333-3333-4333-8333-333333333333"),
    )
    chain1 = build_signed_journal_chain([e1])
    chain2 = build_signed_journal_chain([e1])
    assert chain1.final_hash == chain2.final_hash
    assert chain1.entries[0].entry_hash == chain2.entries[0].entry_hash


def test_chain_changes_when_payload_is_modified() -> None:
    """event_payload 変更で chain hash が変わる (tamper detection)."""
    e_original = _make_event(
        event_type="evt1",
        event_payload={"data": "original"},
        audit_event_id=UUID("44444444-4444-4444-8444-444444444444"),
    )
    e_tampered = _make_event(
        event_type="evt1",
        event_payload={"data": "tampered"},
        audit_event_id=UUID("44444444-4444-4444-8444-444444444444"),
        # id / event_type / created_at は同じ、payload のみ差分
    )
    chain_original = build_signed_journal_chain([e_original])
    chain_tampered = build_signed_journal_chain([e_tampered])
    assert chain_original.final_hash != chain_tampered.final_hash


def test_chain_changes_when_event_inserted_in_middle() -> None:
    """中間 event 挿入で chain hash が変わる (tamper detection)."""
    e1 = _make_event(
        event_type="evt1",
        event_payload={"data": 1},
        audit_event_id=UUID("11111111-1111-4111-8111-111111111111"),
    )
    e2 = _make_event(
        event_type="evt2",
        event_payload={"data": 2},
        audit_event_id=UUID("22222222-2222-4222-8222-222222222222"),
    )
    e_inserted = _make_event(
        event_type="evt_inserted",
        event_payload={"data": "malicious"},
        audit_event_id=UUID("99999999-9999-4999-8999-999999999999"),
    )
    chain_clean = build_signed_journal_chain([e1, e2])
    chain_inserted = build_signed_journal_chain([e1, e_inserted, e2])
    assert chain_clean.final_hash != chain_inserted.final_hash


def test_chain_changes_when_order_swapped() -> None:
    """順序 swap で chain hash が変わる (順序 binding 確認)."""
    e1 = _make_event(
        event_type="evt1",
        event_payload={"data": "a"},
        audit_event_id=UUID("11111111-1111-4111-8111-111111111111"),
    )
    e2 = _make_event(
        event_type="evt2",
        event_payload={"data": "b"},
        audit_event_id=UUID("22222222-2222-4222-8222-222222222222"),
    )
    chain_12 = build_signed_journal_chain([e1, e2])
    chain_21 = build_signed_journal_chain([e2, e1])
    assert chain_12.final_hash != chain_21.final_hash


def test_verify_chain_returns_true_for_matching_input() -> None:
    """build → verify roundtrip で True."""
    e1 = _make_event(
        event_type="evt1",
        event_payload={"data": "x"},
        audit_event_id=UUID("11111111-1111-4111-8111-111111111111"),
    )
    e2 = _make_event(
        event_type="evt2",
        event_payload={"data": "y"},
        audit_event_id=UUID("22222222-2222-4222-8222-222222222222"),
    )
    chain = build_signed_journal_chain([e1, e2])
    assert verify_signed_journal_chain(chain, [e1, e2]) is True


def test_verify_chain_returns_false_when_event_modified() -> None:
    """build 後の event 改ざんで verify False (tamper detection)."""
    e1 = _make_event(
        event_type="evt1",
        event_payload={"data": "original"},
        audit_event_id=UUID("11111111-1111-4111-8111-111111111111"),
    )
    chain = build_signed_journal_chain([e1])
    e_tampered = _make_event(
        event_type="evt1",
        event_payload={"data": "tampered"},
        audit_event_id=UUID("11111111-1111-4111-8111-111111111111"),
    )
    assert verify_signed_journal_chain(chain, [e_tampered]) is False


def test_verify_chain_returns_false_when_entry_count_changed() -> None:
    """build 後の event 追加で verify False (entry_count mismatch)."""
    e1 = _make_event(
        event_type="evt1",
        event_payload={"data": "a"},
        audit_event_id=UUID("11111111-1111-4111-8111-111111111111"),
    )
    e2 = _make_event(
        event_type="evt2",
        event_payload={"data": "b"},
        audit_event_id=UUID("22222222-2222-4222-8222-222222222222"),
    )
    chain = build_signed_journal_chain([e1])
    assert verify_signed_journal_chain(chain, [e1, e2]) is False


def test_chain_uses_canonical_json_nfc_utf8() -> None:
    """NFC normalization + sorted keys で同 logical content の異 encoding が同 hash."""
    # `é` (U+00E9) と `e + ́` (U+0065 + U+0301) は NFC normalize 後 identical.
    event_nfc = _make_event(
        event_type="evt_nfc",
        event_payload={"name": "café"},  # NFC form
        audit_event_id=UUID("11111111-1111-4111-8111-111111111111"),
    )
    event_nfd = _make_event(
        event_type="evt_nfc",
        event_payload={"name": "café"},  # NFD form
        audit_event_id=UUID("11111111-1111-4111-8111-111111111111"),
    )
    chain_nfc = build_signed_journal_chain([event_nfc])
    chain_nfd = build_signed_journal_chain([event_nfd])
    assert chain_nfc.final_hash == chain_nfd.final_hash, (
        "NFC / NFD form must hash to the same final_hash after normalization"
    )


def test_chain_includes_tenant_id_in_hash_computation() -> None:
    """tenant_id 変更で chain hash が変わる (cross-tenant isolation in audit)."""
    e_t1 = _make_event(
        event_type="evt",
        event_payload={"data": "x"},
        audit_event_id=UUID("11111111-1111-4111-8111-111111111111"),
    )
    e_t2 = _make_event(
        event_type="evt",
        event_payload={"data": "x"},
        audit_event_id=UUID("11111111-1111-4111-8111-111111111111"),
    )
    e_t2.tenant_id = 2  # cross-tenant emit
    chain1 = build_signed_journal_chain([e_t1])
    chain2 = build_signed_journal_chain([e_t2])
    assert chain1.final_hash != chain2.final_hash


def test_build_chain_rejects_unflushed_audit_event() -> None:
    """F-PR66-002 P2 fix: created_at=None (unflushed row) は ValueError reject."""
    import pytest

    event = _make_event(
        event_type="evt",
        event_payload={"data": "x"},
        audit_event_id=UUID("11111111-1111-4111-8111-111111111111"),
    )
    event.created_at = None  # type: ignore[assignment]  # simulate unflushed row
    with pytest.raises(ValueError, match="signed journal requires"):
        build_signed_journal_chain([event])


def test_build_chain_normalizes_created_at_to_utc() -> None:
    """F-PR66-004 P2 fix: 異 TimeZone offset の同 instant は同 hash."""
    from datetime import timedelta, timezone

    # 2026-05-18T12:00:00+00:00 (UTC) と同 instant な 2026-05-18T17:00:00+05:00 (IST).
    utc_event = _make_event(
        event_type="evt",
        event_payload={"data": "tz"},
        audit_event_id=UUID("22222222-2222-4222-8222-222222222222"),
        created_at=datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC),
    )
    ist_offset = timezone(timedelta(hours=5))
    ist_event = _make_event(
        event_type="evt",
        event_payload={"data": "tz"},
        audit_event_id=UUID("22222222-2222-4222-8222-222222222222"),
        created_at=datetime(2026, 5, 18, 17, 0, 0, tzinfo=ist_offset),
    )
    chain_utc = build_signed_journal_chain([utc_event])
    chain_ist = build_signed_journal_chain([ist_event])
    assert chain_utc.final_hash == chain_ist.final_hash, (
        "UTC normalize: 同 instant の異 offset は hash 不変"
    )


def test_build_chain_rejects_nan_in_event_payload() -> None:
    """F-PR66-005 P2 fix: NaN float は ValueError reject (JCS spec invariant)."""
    import pytest

    event = _make_event(
        event_type="evt",
        event_payload={"metric": float("nan")},
        audit_event_id=UUID("33333333-3333-4333-8333-333333333333"),
    )
    with pytest.raises(ValueError, match="non-finite float"):
        build_signed_journal_chain([event])


def test_build_chain_rejects_infinity_in_event_payload() -> None:
    """F-PR66-005 P2 fix: Infinity float は ValueError reject."""
    import pytest

    event = _make_event(
        event_type="evt",
        event_payload={"duration": float("inf")},
        audit_event_id=UUID("44444444-4444-4444-8444-444444444444"),
    )
    with pytest.raises(ValueError, match="non-finite float"):
        build_signed_journal_chain([event])


def test_verify_returns_false_for_malformed_chain_with_truncated_entries() -> None:
    """F-PR66-001 P2 fix: malformed chain (entry_count vs len(entries) 不一致) は False、ValueError raise しない."""
    e1 = _make_event(
        event_type="evt1",
        event_payload={"data": "a"},
        audit_event_id=UUID("11111111-1111-4111-8111-111111111111"),
    )
    e2 = _make_event(
        event_type="evt2",
        event_payload={"data": "b"},
        audit_event_id=UUID("22222222-2222-4222-8222-222222222222"),
    )
    # build via 2 events ですが、entries だけ truncate した malformed snapshot.
    chain = build_signed_journal_chain([e1, e2])
    malformed = SignedJournalChain(
        entry_count=chain.entry_count,  # 2 のまま
        final_hash=chain.final_hash,
        entries=(chain.entries[0],),  # 1 entry に truncate
    )
    # 旧コードでは zip(strict=True) で ValueError raise していたが、新版は False 返す.
    assert verify_signed_journal_chain(malformed, [e1, e2]) is False


def test_chain_entry_count_matches_len_entries() -> None:
    """invariant: entry_count == len(entries)."""
    events = [
        _make_event(
            event_type=f"evt{i}",
            event_payload={"i": i},
            audit_event_id=UUID(int=i, version=4),
        )
        for i in range(1, 6)
    ]
    chain = build_signed_journal_chain(events)
    assert chain.entry_count == len(chain.entries)
    assert chain.entry_count == 5
