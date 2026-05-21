"""Tests for scripts/taskhub_approval_issuance.py (SP-012 Batch C 第 2 段).

`.claude/plans/sp012-split-brain-keyring.md` §9.9 R9 F-002 + §9.10 R10 F-002 hardening
contract に対応する server-owned approval issuance journal の chain integrity + monotonic
invariants + clock attestation 3 mode foundational logic を検証する。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import taskhub_active_registry as ar  # noqa: E402
import taskhub_approval_issuance as tai  # noqa: E402


def _make_entry(
    *,
    approval_id: str = "uuid-1",
    issued_at: str = "2026-05-21T10:00:00Z",
    monotonic_sequence: int = 1,
    previous_issued_at: str = "1970-01-01T00:00:00Z",
    previous_entry_hash: str = "0" * 64,
    monotonic_value: int = 1000,
    monotonic_previous_value: int = 0,
    claim_hash: str = "a" * 64,
    key_fingerprint_at_issue: str = "b" * 64,
) -> tai.IssuanceJournalEntry:
    att = tai.MonotonicClockAttestation(
        source="linux_clock_monotonic",
        value=monotonic_value,
        previous_value=monotonic_previous_value,
    )
    return tai.IssuanceJournalEntry(
        approval_id=approval_id,
        claim_hash=claim_hash,
        issued_at=issued_at,
        monotonic_sequence=monotonic_sequence,
        previous_issued_at=previous_issued_at,
        issuer_signer_fingerprint="issuer-fp",
        previous_entry_hash=previous_entry_hash,
        key_fingerprint_at_issue=key_fingerprint_at_issue,
        key_status_at_issue="active",
        monotonic_clock_attestation=att,
        signature="",
    )


# === Canonical payload completeness ===


def test_entry_canonical_includes_all_required_fields() -> None:
    entry = _make_entry()
    payload = entry.canonical_payload()
    assert sorted(payload.keys()) == [
        "approval_id", "claim_hash", "domain", "issued_at",
        "issuer_signer_fingerprint", "key_fingerprint_at_issue",
        "key_status_at_issue", "monotonic_clock_attestation",
        "monotonic_sequence", "previous_entry_hash", "previous_issued_at",
    ]
    assert payload["domain"] == tai.DOMAIN_ISSUANCE_JOURNAL_V1


def test_attestation_canonical_payload() -> None:
    att = tai.MonotonicClockAttestation(source="tpm_clock", value=12345, previous_value=12000)
    payload = att.canonical_payload()
    assert payload == {"previous_value": 12000, "source": "tpm_clock", "value": 12345}


# === Genesis entry validation ===


def test_genesis_entry_pass() -> None:
    """genesis entry: monotonic_sequence=1 + previous_entry_hash='0'*64 + monotonic > previous は pass."""
    entry = _make_entry()
    ok, reason = tai.verify_issuance_chain_invariants(new_entry=entry, previous_entry=None)
    assert ok is True
    assert reason == ""


def test_genesis_entry_rejects_wrong_monotonic_sequence() -> None:
    """genesis でも monotonic_sequence != 1 は reject."""
    entry = _make_entry(monotonic_sequence=2)
    ok, reason = tai.verify_issuance_chain_invariants(new_entry=entry, previous_entry=None)
    assert ok is False
    assert reason == "taskhub_approval_issuance_journal_monotonic_sequence_skip_detected"


def test_genesis_entry_rejects_non_zero_previous_entry_hash() -> None:
    """genesis でも previous_entry_hash != '0'*64 は reject."""
    entry = _make_entry(previous_entry_hash="a" * 64)
    ok, reason = tai.verify_issuance_chain_invariants(new_entry=entry, previous_entry=None)
    assert ok is False
    assert reason == "taskhub_approval_issuance_journal_chain_hash_mismatch"


def test_genesis_entry_rejects_non_monotonic_clock() -> None:
    """genesis でも monotonic_clock value <= previous_value は reject."""
    entry = _make_entry(monotonic_value=0, monotonic_previous_value=0)
    ok, reason = tai.verify_issuance_chain_invariants(new_entry=entry, previous_entry=None)
    assert ok is False
    assert reason == "taskhub_approval_issuance_journal_monotonic_regression_detected"


# === Non-genesis chain integrity ===


def _make_chain_pair() -> tuple[tai.IssuanceJournalEntry, tai.IssuanceJournalEntry]:
    """Generate a valid (prev, next) entry pair for chain integrity tests."""
    prev = _make_entry()
    prev_canonical_bytes = ar._rfc8785_canonical_bytes(prev.canonical_payload())
    prev_hash = ar._sha256_hex(prev_canonical_bytes)
    nxt = _make_entry(
        approval_id="uuid-2",
        issued_at="2026-05-21T10:01:00Z",
        monotonic_sequence=2,
        previous_issued_at=prev.issued_at,
        previous_entry_hash=prev_hash,
        monotonic_value=2000,
        monotonic_previous_value=1000,
    )
    return prev, nxt


def test_chain_pair_pass() -> None:
    prev, nxt = _make_chain_pair()
    ok, reason = tai.verify_issuance_chain_invariants(new_entry=nxt, previous_entry=prev)
    assert ok is True
    assert reason == ""


def test_chain_rejects_monotonic_sequence_skip() -> None:
    """monotonic_sequence skip (例: 1 → 3) は reject."""
    prev, _ = _make_chain_pair()
    bad = _make_entry(
        approval_id="uuid-2",
        issued_at="2026-05-21T10:01:00Z",
        monotonic_sequence=3,  # skip to 3 instead of 2
        previous_issued_at=prev.issued_at,
        previous_entry_hash=ar._sha256_hex(ar._rfc8785_canonical_bytes(prev.canonical_payload())),
        monotonic_value=2000, monotonic_previous_value=1000,
    )
    ok, reason = tai.verify_issuance_chain_invariants(new_entry=bad, previous_entry=prev)
    assert ok is False
    assert reason == "taskhub_approval_issuance_journal_monotonic_sequence_skip_detected"


def test_chain_rejects_wall_clock_regression_beyond_tolerance() -> None:
    """wall-clock が ε=5s より大きく backward は reject (Codex PR #82 R1 F-001 fix)."""
    prev, _ = _make_chain_pair()
    bad = _make_entry(
        approval_id="uuid-2",
        issued_at="2026-05-21T09:59:00Z",  # 1 分以上 backward
        monotonic_sequence=2,
        previous_issued_at=prev.issued_at,
        previous_entry_hash=ar._sha256_hex(ar._rfc8785_canonical_bytes(prev.canonical_payload())),
        monotonic_value=2000, monotonic_previous_value=1000,
    )
    ok, reason = tai.verify_issuance_chain_invariants(new_entry=bad, previous_entry=prev)
    assert ok is False
    assert reason == "taskhub_approval_issuance_journal_monotonic_regression_detected"


def test_chain_accepts_wall_clock_skew_within_tolerance() -> None:
    """ε=5s 以内の backward NTP correction は accept."""
    prev = _make_entry(issued_at="2026-05-21T10:00:00Z")
    nxt = _make_entry(
        approval_id="uuid-2",
        issued_at="2026-05-21T09:59:57Z",  # 3s backward (within ε=5s)
        monotonic_sequence=2,
        previous_issued_at=prev.issued_at,
        previous_entry_hash=ar._sha256_hex(ar._rfc8785_canonical_bytes(prev.canonical_payload())),
        monotonic_value=2000, monotonic_previous_value=1000,
    )
    ok, reason = tai.verify_issuance_chain_invariants(new_entry=nxt, previous_entry=prev)
    assert ok is True
    assert reason == ""


def test_chain_rejects_monotonic_clock_regression() -> None:
    """monotonic_clock value <= previous_value は reject (independent of wall-clock)."""
    prev, _ = _make_chain_pair()
    bad = _make_entry(
        approval_id="uuid-2",
        issued_at="2026-05-21T10:01:00Z",
        monotonic_sequence=2,
        previous_issued_at=prev.issued_at,
        previous_entry_hash=ar._sha256_hex(ar._rfc8785_canonical_bytes(prev.canonical_payload())),
        monotonic_value=500,  # less than previous's 1000
        monotonic_previous_value=1000,
    )
    ok, reason = tai.verify_issuance_chain_invariants(new_entry=bad, previous_entry=prev)
    assert ok is False
    assert reason == "taskhub_approval_issuance_journal_monotonic_regression_detected"


def test_chain_rejects_attestation_previous_value_mismatch() -> None:
    """new_entry.attestation.previous_value != previous_entry.attestation.value は reject."""
    prev, _ = _make_chain_pair()
    bad = _make_entry(
        approval_id="uuid-2",
        issued_at="2026-05-21T10:01:00Z",
        monotonic_sequence=2,
        previous_issued_at=prev.issued_at,
        previous_entry_hash=ar._sha256_hex(ar._rfc8785_canonical_bytes(prev.canonical_payload())),
        monotonic_value=2000,
        monotonic_previous_value=999,  # should be 1000 (prev's value)
    )
    ok, reason = tai.verify_issuance_chain_invariants(new_entry=bad, previous_entry=prev)
    assert ok is False
    assert reason == "taskhub_approval_issuance_journal_monotonic_regression_detected"


def test_chain_rejects_previous_entry_hash_mismatch() -> None:
    """previous_entry_hash mismatch は chain_hash_mismatch で reject."""
    prev, _ = _make_chain_pair()
    bad = _make_entry(
        approval_id="uuid-2",
        issued_at="2026-05-21T10:01:00Z",
        monotonic_sequence=2,
        previous_issued_at=prev.issued_at,
        previous_entry_hash="f" * 64,  # wrong hash
        monotonic_value=2000, monotonic_previous_value=1000,
    )
    ok, reason = tai.verify_issuance_chain_invariants(new_entry=bad, previous_entry=prev)
    assert ok is False
    assert reason == "taskhub_approval_issuance_journal_chain_hash_mismatch"


def test_chain_rejects_previous_issued_at_inconsistency() -> None:
    """new.previous_issued_at != previous_entry.issued_at は reject."""
    prev, _ = _make_chain_pair()
    bad = _make_entry(
        approval_id="uuid-2",
        issued_at="2026-05-21T10:01:00Z",
        monotonic_sequence=2,
        previous_issued_at="2025-01-01T00:00:00Z",  # not previous's issued_at
        previous_entry_hash=ar._sha256_hex(ar._rfc8785_canonical_bytes(prev.canonical_payload())),
        monotonic_value=2000, monotonic_previous_value=1000,
    )
    ok, reason = tai.verify_issuance_chain_invariants(new_entry=bad, previous_entry=prev)
    assert ok is False
    assert reason == "taskhub_approval_issuance_journal_chain_hash_mismatch"


# === Signature sign + verify ===


def test_sign_and_verify_entry() -> None:
    """sign_issuance_entry で signature を埋め込み、verify_issuance_entry_signature で pass."""
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    unsigned = _make_entry()
    signed = tai.sign_issuance_entry(unsigned=unsigned, signer=lambda data: priv.sign(data))
    assert signed.signature != ""
    assert tai.verify_issuance_entry_signature(signed, pub_bytes) is True


def test_verify_signature_fails_for_wrong_key() -> None:
    """別 issuer key で signature verify fail."""
    priv1 = Ed25519PrivateKey.generate()
    priv2 = Ed25519PrivateKey.generate()
    pub2_bytes = priv2.public_key().public_bytes_raw()
    unsigned = _make_entry()
    signed = tai.sign_issuance_entry(unsigned=unsigned, signer=lambda data: priv1.sign(data))
    assert tai.verify_issuance_entry_signature(signed, pub2_bytes) is False


def test_verify_signature_fails_for_tampered_payload() -> None:
    """signed entry の field を改変すると verify fail."""
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    unsigned = _make_entry()
    signed = tai.sign_issuance_entry(unsigned=unsigned, signer=lambda data: priv.sign(data))
    # construct a tampered entry (same signature, different content)
    tampered = tai.IssuanceJournalEntry(
        approval_id="uuid-evil",  # changed
        claim_hash=signed.claim_hash,
        issued_at=signed.issued_at,
        monotonic_sequence=signed.monotonic_sequence,
        previous_issued_at=signed.previous_issued_at,
        issuer_signer_fingerprint=signed.issuer_signer_fingerprint,
        previous_entry_hash=signed.previous_entry_hash,
        key_fingerprint_at_issue=signed.key_fingerprint_at_issue,
        key_status_at_issue=signed.key_status_at_issue,
        monotonic_clock_attestation=signed.monotonic_clock_attestation,
        signature=signed.signature,  # same signature
    )
    assert tai.verify_issuance_entry_signature(tampered, pub_bytes) is False


# === Caller-supplied signed_at reject (§9.9 R9 F-002) ===


def test_reject_caller_supplied_signed_at_accepts_none() -> None:
    """None や empty string は accept (no caller supplied)."""
    tai.reject_caller_supplied_signed_at(None)  # no raise
    tai.reject_caller_supplied_signed_at("")  # no raise


def test_reject_caller_supplied_signed_at_rejects_string() -> None:
    """caller-supplied signed_at string は ValueError."""
    with pytest.raises(ValueError, match="taskhub_approval_caller_supplied_signed_at_rejected"):
        tai.reject_caller_supplied_signed_at("2026-05-21T10:00:00Z")


# === Codex PR #83 R1 fix coverage ===


def test_chain_rejects_non_active_key_status_at_issue() -> None:
    """Codex PR #83 R1 F-002 fix (P1、L249): key_status_at_issue != 'active' は reject."""
    att = tai.MonotonicClockAttestation(source="linux_clock_monotonic", value=1000, previous_value=0)
    entry = tai.IssuanceJournalEntry(
        approval_id="uuid-evil", claim_hash="a" * 64, issued_at="2026-05-21T10:00:00Z",
        monotonic_sequence=1, previous_issued_at="1970-01-01T00:00:00Z",
        issuer_signer_fingerprint="fp", previous_entry_hash="0" * 64,
        key_fingerprint_at_issue="b" * 64,
        key_status_at_issue="deprecated",  # not active
        monotonic_clock_attestation=att, signature="",
    )
    ok, reason = tai.verify_issuance_chain_invariants(new_entry=entry, previous_entry=None)
    assert ok is False
    assert reason == "taskhub_approval_signed_after_key_expired_per_journal"


def test_chain_rejects_unknown_clock_attestation_source() -> None:
    """Codex PR #83 R1 F-006 fix (P2、L239): unknown source は reject."""
    att = tai.MonotonicClockAttestation(source="unknown_source", value=1000, previous_value=0)
    entry = tai.IssuanceJournalEntry(
        approval_id="uuid-1", claim_hash="a" * 64, issued_at="2026-05-21T10:00:00Z",
        monotonic_sequence=1, previous_issued_at="1970-01-01T00:00:00Z",
        issuer_signer_fingerprint="fp", previous_entry_hash="0" * 64,
        key_fingerprint_at_issue="b" * 64, key_status_at_issue="active",
        monotonic_clock_attestation=att, signature="",
    )
    ok, reason = tai.verify_issuance_chain_invariants(new_entry=entry, previous_entry=None)
    assert ok is False
    assert reason == "taskhub_approval_issuance_monotonic_clock_source_unavailable"


def test_chain_accepts_all_three_clock_modes() -> None:
    """Codex PR #83 R1 F-006: 3 allowed sources は accept (positive control)."""
    for source in ("linux_clock_monotonic", "tpm_clock", "trusted_time_attestation"):
        att = tai.MonotonicClockAttestation(source=source, value=1000, previous_value=0)
        entry = tai.IssuanceJournalEntry(
            approval_id=f"uuid-{source}", claim_hash="a" * 64, issued_at="2026-05-21T10:00:00Z",
            monotonic_sequence=1, previous_issued_at="1970-01-01T00:00:00Z",
            issuer_signer_fingerprint="fp", previous_entry_hash="0" * 64,
            key_fingerprint_at_issue="b" * 64, key_status_at_issue="active",
            monotonic_clock_attestation=att, signature="",
        )
        ok, reason = tai.verify_issuance_chain_invariants(new_entry=entry, previous_entry=None)
        assert ok is True, f"{source} failed: {reason}"


def test_genesis_rejects_wrong_previous_issued_at_sentinel() -> None:
    """Codex PR #83 R1 F-004 fix (P2、L214): genesis previous_issued_at != '1970-01-01T00:00:00Z' は reject."""
    att = tai.MonotonicClockAttestation(source="linux_clock_monotonic", value=1000, previous_value=0)
    entry = tai.IssuanceJournalEntry(
        approval_id="uuid-1", claim_hash="a" * 64, issued_at="2026-05-21T10:00:00Z",
        monotonic_sequence=1,
        previous_issued_at="2020-01-01T00:00:00Z",  # not genesis sentinel
        issuer_signer_fingerprint="fp", previous_entry_hash="0" * 64,
        key_fingerprint_at_issue="b" * 64, key_status_at_issue="active",
        monotonic_clock_attestation=att, signature="",
    )
    ok, reason = tai.verify_issuance_chain_invariants(new_entry=entry, previous_entry=None)
    assert ok is False
    assert reason == "taskhub_approval_issuance_journal_chain_hash_mismatch"


def test_chain_rejects_malformed_issued_at() -> None:
    """Codex PR #83 R1 F-004 fix (P2、L214): malformed issued_at は entry_signature_invalid."""
    att = tai.MonotonicClockAttestation(source="linux_clock_monotonic", value=1000, previous_value=0)
    entry = tai.IssuanceJournalEntry(
        approval_id="uuid-1", claim_hash="a" * 64,
        issued_at="not-an-iso8601-timestamp",  # malformed
        monotonic_sequence=1, previous_issued_at="1970-01-01T00:00:00Z",
        issuer_signer_fingerprint="fp", previous_entry_hash="0" * 64,
        key_fingerprint_at_issue="b" * 64, key_status_at_issue="active",
        monotonic_clock_attestation=att, signature="",
    )
    ok, reason = tai.verify_issuance_chain_invariants(new_entry=entry, previous_entry=None)
    assert ok is False
    assert reason == "taskhub_approval_issuance_journal_entry_signature_invalid"
