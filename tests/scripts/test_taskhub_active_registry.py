"""Tests for scripts/taskhub_active_registry.py (SP-012 Batch B foundation).

`.claude/plans/sp012-split-brain-keyring.md` §3.B + §9.3-§9.10 hardening contract に
対応する core function の unit test。Batch B では canonical encoder + marker dataclass +
signer-host ownership exact match + epoch atomic counter + signed journal の
foundational logic を検証する。

Batch D で 142 fixture (約 60+ active-registry + 約 50 keyring + 残り approval issuance)
が追加される。本 file は Batch B 部分の foundation (約 12 fixture)。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# scripts/ を sys.path に追加
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import taskhub_active_registry as ar  # noqa: E402

# === RFC 8785 canonical encoder ===


def test_rfc8785_canonical_sorts_keys() -> None:
    """canonical encoder は sort_keys + nested sort を行う (§3.B.1 統一)."""
    payload = {"b": 2, "a": 1, "c": {"z": 3, "y": 4}}
    canonical = ar._rfc8785_canonical_bytes(payload)
    assert canonical == b'{"a":1,"b":2,"c":{"y":4,"z":3}}'


def test_rfc8785_canonical_separators_have_no_whitespace() -> None:
    """canonical encoder は no-whitespace separators (',', ':')."""
    payload = {"a": 1, "b": [1, 2, 3]}
    canonical = ar._rfc8785_canonical_bytes(payload)
    assert b" " not in canonical
    assert canonical == b'{"a":1,"b":[1,2,3]}'


def test_sha256_hex_is_deterministic() -> None:
    """_sha256_hex は deterministic + 64 chars hex."""
    digest = ar._sha256_hex(b"test")
    assert len(digest) == 64
    assert digest == "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"


# === iso8601 UTC validator ===


def test_iso8601_utc_accepts_z_suffix() -> None:
    dt = ar.validate_iso8601_utc("2026-05-21T10:00:00Z")
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0


def test_iso8601_utc_accepts_microseconds() -> None:
    dt = ar.validate_iso8601_utc("2026-05-21T10:00:00.123456Z")
    assert dt.microsecond == 123456


def test_iso8601_utc_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="invalid UTC iso8601 datetime format"):
        ar.validate_iso8601_utc("2026-05-21T10:00:00")


def test_iso8601_utc_rejects_non_string() -> None:
    with pytest.raises(ValueError, match="invalid UTC iso8601 datetime format"):
        ar.validate_iso8601_utc(123)  # type: ignore[arg-type]


# === Marker canonical_payload completeness ===


def test_freeze_marker_canonical_payload_keys() -> None:
    """FreezeMarker canonical_payload は必須 field + domain を持つ (§9.3 R1 F-010 統一)."""
    fm = ar.FreezeMarker(
        host_id="host-1",
        migration_epoch=1,
        migration_epoch_issued_at="2026-05-21T10:00:00Z",
        frozen_at="2026-05-21T10:00:01Z",
        reason_summary="migration prep",
        signer_fingerprint="a" * 64,
        signature="",
    )
    payload = fm.canonical_payload()
    assert payload["domain"] == ar.DOMAIN_FREEZE_V1
    assert sorted(payload.keys()) == [
        "domain",
        "frozen_at",
        "host_id",
        "migration_epoch",
        "migration_epoch_issued_at",
        "reason_summary",
        "signer_fingerprint",
    ]


def test_active_marker_canonical_includes_source_host_id() -> None:
    """ActiveMarker は source_host_id を canonical payload に含める (§9.3 R1 F-011)."""
    am = ar.ActiveMarker(
        host_id="host-target",
        migration_epoch=2,
        migration_epoch_issued_at="2026-05-21T10:00:00Z",
        activated_at="2026-05-21T10:00:10Z",
        signer_fingerprint="b" * 64,
        source_host_id="host-source",
        source_decommission_chain_hash="c" * 64,
        source_decommission_signer_fingerprint="d" * 64,
        cutover_id="cutover-abc",
        cutover_approval_id="approval-xyz",
        cutover_approval_claim_hash="e" * 64,
        signature="",
    )
    payload = am.canonical_payload()
    assert payload["source_host_id"] == "host-source"
    assert payload["source_decommission_chain_hash"] == "c" * 64
    # §9.3 R1 F-001: cutover_approval_id + claim_hash が signature root に bind
    assert payload["cutover_approval_id"] == "approval-xyz"
    assert payload["cutover_approval_claim_hash"] == "e" * 64


def test_decommission_marker_canonical_includes_prev_active_chain_hash() -> None:
    """DecommissionMarker は prev_active_chain_hash 必須 (§9.3 R1 F-013 active proof)."""
    dm = ar.DecommissionMarker(
        host_id="host-source",
        migration_epoch=2,
        migration_epoch_issued_at="2026-05-21T10:00:00Z",
        decommissioned_at="2026-05-21T10:00:05Z",
        signer_fingerprint="d" * 64,
        prev_active_chain_hash="f" * 64,
        cutover_id="cutover-abc",
        cutover_approval_id="approval-xyz",
        cutover_approval_claim_hash="e" * 64,
        signature="",
    )
    payload = dm.canonical_payload()
    assert payload["prev_active_chain_hash"] == "f" * 64
    assert payload["domain"] == ar.DOMAIN_DECOMMISSION_V1


# === Signer-host ownership exact match (§9.5 R3 F-002) ===


def _make_fleet(*, host_id: str = "host-1", signer_fp: str = "sig-fp-1",
               role: str = "source", marker_kinds: tuple[str, ...] = ("active", "decommission", "freeze"),
               status: str = "active") -> ar.FleetMembership:
    return ar.FleetMembership(
        generation=1,
        hosts=(
            ar.FleetHost(
                host_id=host_id,
                endpoint="https://host-1.example/api",
                role=role,
                status=status,
                allowed_marker_signer_fingerprints=(signer_fp,),
                allowed_marker_kinds=marker_kinds,
                valid_from="2026-05-01T00:00:00Z",
                valid_to="2027-05-01T00:00:00Z",
            ),
        ),
        head_signed_at="2026-05-21T10:00:00Z",
        root_signature="",
    )


def test_verify_signer_host_ownership_pass_for_active_host() -> None:
    """active host の allowed signer + allowed marker_kind は ownership pass."""
    fleet = _make_fleet()
    ok, reason = ar.verify_signer_host_ownership(
        fleet=fleet,
        marker_host_id="host-1",
        marker_signer_fingerprint="sig-fp-1",
        marker_kind="active",
    )
    assert ok is True
    assert reason == ""


def test_verify_signer_host_ownership_rejects_missing_host() -> None:
    """fleet 不在 host は taskhub_active_registry_fleet_membership_violation."""
    fleet = _make_fleet()
    ok, reason = ar.verify_signer_host_ownership(
        fleet=fleet,
        marker_host_id="host-unknown",
        marker_signer_fingerprint="sig-fp-1",
        marker_kind="active",
    )
    assert ok is False
    assert reason == "taskhub_active_registry_fleet_membership_violation"


def test_verify_signer_host_ownership_rejects_wrong_signer() -> None:
    """allowed signer に居ない fingerprint は taskhub_active_registry_signer_not_in_allowlist."""
    fleet = _make_fleet()
    ok, reason = ar.verify_signer_host_ownership(
        fleet=fleet,
        marker_host_id="host-1",
        marker_signer_fingerprint="sig-fp-evil",
        marker_kind="active",
    )
    assert ok is False
    assert reason == "taskhub_active_registry_signer_not_in_allowlist"


def test_verify_signer_host_ownership_rejects_disallowed_marker_kind() -> None:
    """role-based scope: source-only role が target-only marker_kind を発行できない."""
    fleet = _make_fleet(marker_kinds=("decommission",))  # active 不在
    ok, reason = ar.verify_signer_host_ownership(
        fleet=fleet,
        marker_host_id="host-1",
        marker_signer_fingerprint="sig-fp-1",
        marker_kind="active",
    )
    assert ok is False
    assert reason == "taskhub_active_registry_role_demoted_in_current_fleet"


def test_verify_signer_host_ownership_rejects_revoked_host() -> None:
    """status=revoked host は taskhub_active_registry_host_revoked_or_retired."""
    fleet = _make_fleet(status="revoked")
    ok, reason = ar.verify_signer_host_ownership(
        fleet=fleet,
        marker_host_id="host-1",
        marker_signer_fingerprint="sig-fp-1",
        marker_kind="active",
    )
    assert ok is False
    assert reason == "taskhub_active_registry_host_revoked_or_retired"


# === Ed25519 signature verify ===


def test_ed25519_verify_pass_for_valid_signature() -> None:
    """正しい signing key で署名した data は verify pass."""
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    payload = b"canonical payload"
    sig = priv.sign(payload)
    import base64

    sig_b64 = base64.b64encode(sig).decode("ascii")
    assert ar.verify_ed25519_signature(pub_bytes, sig_b64, payload) is True


def test_ed25519_verify_fail_for_tampered_payload() -> None:
    """payload を改変すると verify fail (fail-closed)."""
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    sig = priv.sign(b"original")
    import base64

    sig_b64 = base64.b64encode(sig).decode("ascii")
    assert ar.verify_ed25519_signature(pub_bytes, sig_b64, b"tampered") is False


def test_ed25519_verify_fail_for_wrong_public_key() -> None:
    """別 signer key だと verify fail."""
    priv1 = Ed25519PrivateKey.generate()
    priv2 = Ed25519PrivateKey.generate()
    pub2_bytes = priv2.public_key().public_bytes_raw()
    sig = priv1.sign(b"payload")
    import base64

    sig_b64 = base64.b64encode(sig).decode("ascii")
    assert ar.verify_ed25519_signature(pub2_bytes, sig_b64, b"payload") is False


def test_ed25519_verify_fail_for_malformed_base64() -> None:
    """malformed base64 signature は fail-closed で False."""
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    assert ar.verify_ed25519_signature(pub_bytes, "!!!not-base64!!!", b"data") is False


def test_ed25519_verify_fail_for_wrong_key_length() -> None:
    """32 bytes 以外の public key は fail-closed で False."""
    import base64

    sig_b64 = base64.b64encode(b"\x00" * 64).decode("ascii")
    assert ar.verify_ed25519_signature(b"\x00" * 16, sig_b64, b"data") is False


# === allocate_next_epoch atomic counter (§9.3 R1 F-007 + R1 F-010) ===


def test_allocate_next_epoch_initial(tmp_path: Path) -> None:
    """counter file 不在時の初回 allocate は epoch=1 + signed journal entry 生成."""
    priv = Ed25519PrivateKey.generate()
    counter_path = tmp_path / "epoch.counter"
    lock_path = tmp_path / "epoch.lock"
    journal_path = tmp_path / "epoch.journal.signed.jsonl"

    def signer(data: bytes) -> bytes:
        return priv.sign(data)

    new_epoch, issued_at, entry = ar.allocate_next_epoch(
        counter_path=counter_path,
        lock_path=lock_path,
        journal_path=journal_path,
        host_id="host-1",
        writer_signer_fingerprint="fp-writer-1",
        private_key_signer=signer,
    )
    assert new_epoch == 1
    assert entry.epoch == 1
    assert entry.previous_entry_hash == "0" * 64  # genesis
    assert entry.host_id == "host-1"
    assert entry.signature != ""
    # counter file が atomic rename で書込済
    assert counter_path.exists()
    counter_doc = json.loads(counter_path.read_bytes())
    assert counter_doc["epoch"] == 1
    assert counter_doc["issued_at"] == issued_at
    assert len(counter_doc["sha256"]) == 64
    # journal file に append 済
    assert journal_path.exists()
    journal_lines = journal_path.read_bytes().strip().split(b"\n")
    assert len(journal_lines) == 1


def test_allocate_next_epoch_monotonic_increment(tmp_path: Path) -> None:
    """連続 allocate で epoch は monotonic increment (§9.3 R1 F-007)."""
    priv = Ed25519PrivateKey.generate()
    counter_path = tmp_path / "epoch.counter"
    lock_path = tmp_path / "epoch.lock"
    journal_path = tmp_path / "epoch.journal.signed.jsonl"

    def signer(data: bytes) -> bytes:
        return priv.sign(data)

    e1, _, _ = ar.allocate_next_epoch(
        counter_path, lock_path, journal_path, "host-1", "fp-1", signer
    )
    e2, _, _ = ar.allocate_next_epoch(
        counter_path, lock_path, journal_path, "host-1", "fp-1", signer
    )
    e3, _, _ = ar.allocate_next_epoch(
        counter_path, lock_path, journal_path, "host-1", "fp-1", signer
    )
    assert (e1, e2, e3) == (1, 2, 3)
    # journal に 3 entry
    journal_lines = journal_path.read_bytes().strip().split(b"\n")
    assert len(journal_lines) == 3


def test_allocate_next_epoch_journal_chain_integrity(tmp_path: Path) -> None:
    """journal entry の previous_entry_hash は前 entry canonical sha256 と一致."""
    priv = Ed25519PrivateKey.generate()
    counter_path = tmp_path / "epoch.counter"
    lock_path = tmp_path / "epoch.lock"
    journal_path = tmp_path / "epoch.journal.signed.jsonl"

    def signer(data: bytes) -> bytes:
        return priv.sign(data)

    _, _, e1 = ar.allocate_next_epoch(
        counter_path, lock_path, journal_path, "host-1", "fp-1", signer
    )
    _, _, e2 = ar.allocate_next_epoch(
        counter_path, lock_path, journal_path, "host-1", "fp-1", signer
    )
    # e2.previous_entry_hash == sha256(canonical(e1 minus signature))
    e1_canonical_payload = e1.canonical_payload()
    e1_canonical_bytes = ar._rfc8785_canonical_bytes(e1_canonical_payload)
    expected_prev_hash = ar._sha256_hex(e1_canonical_bytes)
    assert e2.previous_entry_hash == expected_prev_hash


def test_allocate_next_epoch_counter_tamper_detected(tmp_path: Path) -> None:
    """counter file の sha256 mismatch (tamper) は RuntimeError で reject (§9.3 R1 F-007)."""
    priv = Ed25519PrivateKey.generate()
    counter_path = tmp_path / "epoch.counter"
    lock_path = tmp_path / "epoch.lock"
    journal_path = tmp_path / "epoch.journal.signed.jsonl"

    def signer(data: bytes) -> bytes:
        return priv.sign(data)

    ar.allocate_next_epoch(counter_path, lock_path, journal_path, "host-1", "fp-1", signer)
    # tamper: epoch を書き換えるが sha256 は更新しない
    tampered = json.loads(counter_path.read_bytes())
    tampered["epoch"] = 999
    counter_path.write_bytes(json.dumps(tampered).encode("utf-8"))

    with pytest.raises(RuntimeError, match="taskhub_active_registry_epoch_counter_tampered"):
        ar.allocate_next_epoch(counter_path, lock_path, journal_path, "host-1", "fp-1", signer)
