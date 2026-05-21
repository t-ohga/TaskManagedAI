"""Tests for scripts/taskhub_keyring.py (SP-012 Batch C foundation).

`.claude/plans/sp012-split-brain-keyring.md` §3.A + §6.5 + §9.3-§9.9 hardening contract に
対応する keyring rotation の foundational logic を検証する。

Batch C foundation (約 25-30 fixture): SignedManifestEntry / SignedKeyringManifest /
KeyringStateHead / RevocationTombstoneEntry dataclass + canonical_payload + authorization vs
audit predicate 分離 + key format validation + signed manifest signature verify。

Batch D で 2PC marker + lease binding fixture (約 50-60 件) が追加される。
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# scripts/ を sys.path に追加
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import taskhub_active_registry as ar  # noqa: E402
import taskhub_keyring as tk  # noqa: E402


def _make_key() -> tuple[Ed25519PrivateKey, bytes, str, str]:
    """Helper: generate Ed25519 key + return (priv, pub_bytes, fingerprint, taskhub1_str)."""
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    fp = tk.compute_key_fingerprint(pub_bytes)
    key_str = tk.KEY_FORMAT_PREFIX + base64.b64encode(pub_bytes).decode("ascii")
    return priv, pub_bytes, fp, key_str


# === Key format validation (§6.2 ADV R1 F-011) ===


def test_validate_key_format_accepts_taskhub1_prefix() -> None:
    """taskhub1<base64> 形式は正しく decode + validate される."""
    _priv, pub_bytes, _fp, key_str = _make_key()
    decoded = tk.validate_key_format(key_str)
    assert decoded == pub_bytes
    assert len(decoded) == 32


def test_validate_key_format_rejects_missing_prefix() -> None:
    """taskhub1 prefix がない key string は ValueError."""
    _priv, pub_bytes, _fp, _key_str = _make_key()
    bad = base64.b64encode(pub_bytes).decode("ascii")  # no prefix
    with pytest.raises(ValueError, match="must start with .*taskhub1"):
        tk.validate_key_format(bad)


def test_validate_key_format_rejects_empty() -> None:
    """空 string は ValueError."""
    with pytest.raises(ValueError, match="non-empty"):
        tk.validate_key_format("")


def test_validate_key_format_rejects_invalid_base64() -> None:
    """invalid base64 (illegal chars) は ValueError."""
    with pytest.raises(ValueError, match="base64"):
        tk.validate_key_format(tk.KEY_FORMAT_PREFIX + "!!!not-base64!!!")


def test_validate_key_format_rejects_wrong_length() -> None:
    """32 bytes 以外 (e.g., 16 bytes) は ValueError."""
    short = base64.b64encode(b"\x00" * 16).decode("ascii")
    with pytest.raises(ValueError, match="32 bytes"):
        tk.validate_key_format(tk.KEY_FORMAT_PREFIX + short)


def test_compute_key_fingerprint_is_sha256_hex() -> None:
    """fingerprint は decoded 32 bytes の sha256 hex (64 chars)."""
    pub_bytes = b"\x00" * 32
    fp = tk.compute_key_fingerprint(pub_bytes)
    assert len(fp) == 64
    # known sha256 of 32 zero bytes
    assert fp == "66687aadf862bd776c8fc18b8e9f8e20089714856ee233b3902a591d0d5f2925"


def test_compute_key_fingerprint_rejects_wrong_length() -> None:
    """32 bytes 以外は ValueError."""
    with pytest.raises(ValueError, match="32 bytes"):
        tk.compute_key_fingerprint(b"\x00" * 16)


# === SignedManifestEntry canonical_payload ===


def test_signed_manifest_entry_canonical_required_fields() -> None:
    """active entry の canonical_payload に必須 fields が含まれる (optional 系は exclude)."""
    entry = tk.SignedManifestEntry(
        fingerprint="a" * 64,
        status="active",
        issued_at="2026-01-01T00:00:00Z",
        expires_at="2027-01-01T00:00:00Z",
        public_key_base64="taskhub1abc",
    )
    payload = entry.canonical_payload()
    assert sorted(payload.keys()) == [
        "expires_at", "fingerprint", "issued_at",
        "public_key_base64", "source", "status",
    ]
    # deprecated_at / revoked_at / revocation_reason_hash / incident_id は active で None → exclude
    assert "deprecated_at" not in payload
    assert "revoked_at" not in payload


def test_signed_manifest_entry_canonical_includes_deprecated_at() -> None:
    """deprecated 化された entry は deprecated_at を canonical に含む."""
    entry = tk.SignedManifestEntry(
        fingerprint="a" * 64,
        status="deprecated",
        issued_at="2026-01-01T00:00:00Z",
        expires_at="2027-01-01T00:00:00Z",
        deprecated_at="2026-06-01T00:00:00Z",
        public_key_base64="taskhub1abc",
    )
    payload = entry.canonical_payload()
    assert payload["deprecated_at"] == "2026-06-01T00:00:00Z"


def test_signed_manifest_entry_canonical_includes_revocation_fields() -> None:
    """revoked entry は revoked_at + revocation_reason_hash + incident_id を含む."""
    entry = tk.SignedManifestEntry(
        fingerprint="a" * 64,
        status="revoked",
        issued_at="2026-01-01T00:00:00Z",
        expires_at="2027-01-01T00:00:00Z",
        revoked_at="2026-07-15T00:00:00Z",
        revocation_reason_hash="b" * 64,
        incident_id="INC-2026-001",
        public_key_base64="taskhub1abc",
    )
    payload = entry.canonical_payload()
    assert payload["revoked_at"] == "2026-07-15T00:00:00Z"
    assert payload["revocation_reason_hash"] == "b" * 64
    assert payload["incident_id"] == "INC-2026-001"


# === SignedKeyringManifest canonical + sort ===


def _make_manifest(*, entries: tuple[tk.SignedManifestEntry, ...] = (),
                   generation: int = 1,
                   signer_fp: str = "root-fp-1") -> tk.SignedKeyringManifest:
    return tk.SignedKeyringManifest(
        generation=generation,
        entries=entries,
        previous_committed_manifest_hash="0" * 64,
        commit_log_chain_hash="0" * 64,
        signer_fingerprint=signer_fp,
        signed_at="2026-05-21T10:00:00Z",
        signature="",
    )


def test_manifest_canonical_sorts_entries_by_fingerprint() -> None:
    """entries は fingerprint 昇順で canonical に出力される (deterministic)."""
    e1 = tk.SignedManifestEntry(
        fingerprint="b" * 64, status="active",
        issued_at="2026-01-01T00:00:00Z", expires_at="2027-01-01T00:00:00Z",
        public_key_base64="taskhub1b",
    )
    e2 = tk.SignedManifestEntry(
        fingerprint="a" * 64, status="active",
        issued_at="2026-01-01T00:00:00Z", expires_at="2027-01-01T00:00:00Z",
        public_key_base64="taskhub1a",
    )
    manifest = _make_manifest(entries=(e1, e2))
    payload = manifest.canonical_payload()
    # entries は fingerprint 昇順
    assert payload["entries"][0]["fingerprint"] == "a" * 64
    assert payload["entries"][1]["fingerprint"] == "b" * 64


def test_manifest_find_entry() -> None:
    """find_entry で fingerprint match の entry を取得."""
    e = tk.SignedManifestEntry(
        fingerprint="a" * 64, status="active",
        issued_at="2026-01-01T00:00:00Z", expires_at="2027-01-01T00:00:00Z",
        public_key_base64="taskhub1a",
    )
    manifest = _make_manifest(entries=(e,))
    found = manifest.find_entry("a" * 64)
    assert found == e
    assert manifest.find_entry("b" * 64) is None


# === Signed manifest signature verify (root + chain integrity) ===


def test_verify_signed_manifest_valid_signature() -> None:
    """正しい root key で署名された manifest は verify pass."""
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    manifest_unsigned = _make_manifest()
    canonical = ar._rfc8785_canonical_bytes(manifest_unsigned.canonical_payload())
    sig = priv.sign(canonical)
    manifest_signed = tk.SignedKeyringManifest(
        generation=manifest_unsigned.generation,
        entries=manifest_unsigned.entries,
        previous_committed_manifest_hash=manifest_unsigned.previous_committed_manifest_hash,
        commit_log_chain_hash=manifest_unsigned.commit_log_chain_hash,
        signer_fingerprint=manifest_unsigned.signer_fingerprint,
        signed_at=manifest_unsigned.signed_at,
        signature=base64.b64encode(sig).decode("ascii"),
    )
    ok, reason = tk.verify_signed_manifest(manifest_signed, pub_bytes)
    assert ok is True
    assert reason == ""


def test_verify_signed_manifest_rejects_wrong_key() -> None:
    """別 root key で署名された manifest は signature_invalid."""
    priv1 = Ed25519PrivateKey.generate()
    priv2 = Ed25519PrivateKey.generate()
    pub2_bytes = priv2.public_key().public_bytes_raw()
    manifest_unsigned = _make_manifest()
    canonical = ar._rfc8785_canonical_bytes(manifest_unsigned.canonical_payload())
    sig = priv1.sign(canonical)  # signed by priv1
    manifest_signed = tk.SignedKeyringManifest(
        generation=manifest_unsigned.generation,
        entries=manifest_unsigned.entries,
        previous_committed_manifest_hash=manifest_unsigned.previous_committed_manifest_hash,
        commit_log_chain_hash=manifest_unsigned.commit_log_chain_hash,
        signer_fingerprint=manifest_unsigned.signer_fingerprint,
        signed_at=manifest_unsigned.signed_at,
        signature=base64.b64encode(sig).decode("ascii"),
    )
    # verify with priv2's public key → mismatch
    ok, reason = tk.verify_signed_manifest(manifest_signed, pub2_bytes)
    assert ok is False
    assert reason == "taskhub_signed_approval_keyring_manifest_signature_invalid"


def test_verify_signed_manifest_replay_defense() -> None:
    """previous_committed_manifest_hash mismatch は generation_replay_or_lower で reject (§9.3 R1 F-007)."""
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    manifest_unsigned = tk.SignedKeyringManifest(
        generation=2,
        entries=(),
        previous_committed_manifest_hash="a" * 64,  # claims previous was "a"*64
        commit_log_chain_hash="0" * 64,
        signer_fingerprint="root-fp-1",
        signed_at="2026-05-21T10:00:00Z",
        signature="",
    )
    canonical = ar._rfc8785_canonical_bytes(manifest_unsigned.canonical_payload())
    sig = priv.sign(canonical)
    manifest_signed = tk.SignedKeyringManifest(
        generation=manifest_unsigned.generation,
        entries=manifest_unsigned.entries,
        previous_committed_manifest_hash=manifest_unsigned.previous_committed_manifest_hash,
        commit_log_chain_hash=manifest_unsigned.commit_log_chain_hash,
        signer_fingerprint=manifest_unsigned.signer_fingerprint,
        signed_at=manifest_unsigned.signed_at,
        signature=base64.b64encode(sig).decode("ascii"),
    )
    # caller expects previous hash = "b"*64 (replay detection)
    ok, reason = tk.verify_signed_manifest(
        manifest_signed, pub_bytes, expected_previous_hash="b" * 64,
    )
    assert ok is False
    assert reason == "taskhub_signed_approval_keyring_generation_replay_or_lower"


def test_verify_signed_manifest_rejects_duplicate_fingerprints() -> None:
    """entries に同 fingerprint の重複があると manifest_tampered で reject."""
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    e1 = tk.SignedManifestEntry(
        fingerprint="a" * 64, status="active",
        issued_at="2026-01-01T00:00:00Z", expires_at="2027-01-01T00:00:00Z",
        public_key_base64="taskhub1a",
    )
    e2 = tk.SignedManifestEntry(
        fingerprint="a" * 64, status="deprecated",  # duplicate fingerprint
        issued_at="2026-01-01T00:00:00Z", expires_at="2027-01-01T00:00:00Z",
        deprecated_at="2026-06-01T00:00:00Z",
        public_key_base64="taskhub1a",
    )
    manifest_unsigned = _make_manifest(entries=(e1, e2))
    canonical = ar._rfc8785_canonical_bytes(manifest_unsigned.canonical_payload())
    sig = priv.sign(canonical)
    manifest_signed = tk.SignedKeyringManifest(
        generation=manifest_unsigned.generation,
        entries=manifest_unsigned.entries,
        previous_committed_manifest_hash=manifest_unsigned.previous_committed_manifest_hash,
        commit_log_chain_hash=manifest_unsigned.commit_log_chain_hash,
        signer_fingerprint=manifest_unsigned.signer_fingerprint,
        signed_at=manifest_unsigned.signed_at,
        signature=base64.b64encode(sig).decode("ascii"),
    )
    ok, reason = tk.verify_signed_manifest(manifest_signed, pub_bytes)
    assert ok is False
    assert reason == "taskhub_signed_approval_keyring_manifest_tampered"


# === authorization_verify vs audit_verify predicate 分離 (§9.4 R2 F-005) ===


def _entry(*, fp: str = "a" * 64, status: str = "active",
           deprecated_at: str | None = None,
           issued_at: str = "2026-01-01T00:00:00Z",
           expires_at: str = "2027-01-01T00:00:00Z") -> tk.SignedManifestEntry:
    return tk.SignedManifestEntry(
        fingerprint=fp, status=status,
        issued_at=issued_at, expires_at=expires_at,
        deprecated_at=deprecated_at,
        public_key_base64="taskhub1abc",
    )


def test_authorization_verify_active_key_pass() -> None:
    """active key + validity window 内 → pass."""
    manifest = _make_manifest(entries=(_entry(),))
    ok, reason = tk.authorization_verify_key(manifest, "a" * 64, "2026-06-01T00:00:00Z")
    assert ok is True
    assert reason == ""


def test_authorization_verify_deprecated_key_rejects_unconditionally() -> None:
    """deprecated key は record_signed_at に関係なく authorization_verify で reject (§9.4 R2 F-005)."""
    manifest = _make_manifest(entries=(_entry(status="deprecated", deprecated_at="2026-06-01T00:00:00Z"),))
    # signed_at < deprecated_at だが authorization mode では reject
    ok, reason = tk.authorization_verify_key(manifest, "a" * 64, "2026-03-01T00:00:00Z")
    assert ok is False
    assert reason == "taskhub_signed_approval_keyring_key_expired"


def test_audit_verify_deprecated_key_pass_for_historical_record() -> None:
    """deprecated key で record_signed_at < deprecated_at の historical record は audit_verify pass."""
    manifest = _make_manifest(entries=(_entry(status="deprecated", deprecated_at="2026-06-01T00:00:00Z"),))
    ok, reason = tk.audit_verify_key(manifest, "a" * 64, "2026-03-01T00:00:00Z")
    assert ok is True
    assert reason == ""


def test_audit_verify_deprecated_key_rejects_record_signed_after_deprecated_at() -> None:
    """deprecated key で record_signed_at >= deprecated_at の record は audit_verify でも reject."""
    manifest = _make_manifest(entries=(_entry(status="deprecated", deprecated_at="2026-06-01T00:00:00Z"),))
    ok, reason = tk.audit_verify_key(manifest, "a" * 64, "2026-07-01T00:00:00Z")  # after deprecated_at
    assert ok is False
    assert reason == "taskhub_signed_approval_keyring_key_expired"


def test_authorization_verify_revoked_key_unconditional_reject() -> None:
    """revoked key は signed_at に関係なく無条件 reject (§9.5 R3 F-001 tombstone)."""
    manifest = _make_manifest(entries=(_entry(status="revoked"),))
    ok, reason = tk.authorization_verify_key(manifest, "a" * 64, "2026-03-01T00:00:00Z")
    assert ok is False
    assert reason == "taskhub_signed_approval_keyring_key_revoked"


def test_audit_verify_revoked_key_unconditional_reject() -> None:
    """revoked key は audit_verify でも無条件 reject."""
    manifest = _make_manifest(entries=(_entry(status="revoked"),))
    ok, reason = tk.audit_verify_key(manifest, "a" * 64, "2026-03-01T00:00:00Z")
    assert ok is False
    assert reason == "taskhub_signed_approval_keyring_key_revoked"


def test_authorization_verify_tombstone_denylist_unconditional_reject() -> None:
    """tombstone denylist にある fingerprint は manifest entry がなくても reject (§9.5 R3 F-001)."""
    manifest = _make_manifest(entries=())  # empty manifest
    tombstones = frozenset({"a" * 64})
    ok, reason = tk.authorization_verify_key(
        manifest, "a" * 64, "2026-03-01T00:00:00Z", tombstone_fingerprints=tombstones,
    )
    assert ok is False
    assert reason == "taskhub_signed_approval_keyring_key_revoked"


def test_authorization_verify_key_expired_window() -> None:
    """active key だが signed_at が validity window 外なら key_expired."""
    manifest = _make_manifest(entries=(_entry(),))
    # signed_at > expires_at
    ok, reason = tk.authorization_verify_key(manifest, "a" * 64, "2028-01-01T00:00:00Z")
    assert ok is False
    assert reason == "taskhub_signed_approval_keyring_key_expired"
    # signed_at < issued_at
    ok2, reason2 = tk.authorization_verify_key(manifest, "a" * 64, "2025-06-01T00:00:00Z")
    assert ok2 is False
    assert reason2 == "taskhub_signed_approval_keyring_key_expired"


def test_authorization_verify_unknown_fingerprint() -> None:
    """manifest に存在しない fingerprint は no_valid_key."""
    manifest = _make_manifest(entries=(_entry(),))
    ok, reason = tk.authorization_verify_key(manifest, "z" * 64, "2026-03-01T00:00:00Z")
    assert ok is False
    assert reason == "taskhub_signed_approval_keyring_no_valid_key"


# === KeyringStateHead canonical_payload ===


def test_state_head_canonical_includes_required_fields() -> None:
    """state head canonical_payload に全必須 fields が含まれる."""
    head = tk.KeyringStateHead(
        initialized=True,
        legacy_fallback_disabled_at="2026-05-21T10:00:00Z",
        latest_manifest_generation=5,
        latest_manifest_content_sha256="a" * 64,
        latest_commit_log_chain_hash="b" * 64,
        latest_tombstone_chain_hash="c" * 64,
        latest_active_registry_epoch=10,
        latest_fleet_membership_generation=3,
        latest_approval_issuance_journal_chain_hash="d" * 64,
        latest_approval_issued_at="2026-05-21T10:00:00Z",
        latest_monotonic_sequence=42,
        latest_monotonic_clock_attestation_value=1234567890,
        signer_fingerprint="root-fp",
        head_signed_at="2026-05-21T10:00:00Z",
        signature="",
    )
    payload = head.canonical_payload()
    assert payload["domain"] == tk.DOMAIN_STATE_HEAD_V1
    assert payload["initialized"] is True
    assert payload["latest_manifest_generation"] == 5
    assert payload["latest_monotonic_sequence"] == 42


def test_state_head_canonical_excludes_legacy_disabled_when_none() -> None:
    """legacy_fallback_disabled_at が None なら canonical から exclude."""
    head = tk.KeyringStateHead(
        initialized=False, legacy_fallback_disabled_at=None,
        latest_manifest_generation=0,
        latest_manifest_content_sha256="0" * 64,
        latest_commit_log_chain_hash="0" * 64,
        latest_tombstone_chain_hash="0" * 64,
        latest_active_registry_epoch=0, latest_fleet_membership_generation=0,
        latest_approval_issuance_journal_chain_hash="0" * 64,
        latest_approval_issued_at="2026-01-01T00:00:00Z",
        latest_monotonic_sequence=0, latest_monotonic_clock_attestation_value=0,
        signer_fingerprint="fp", head_signed_at="2026-01-01T00:00:00Z", signature="",
    )
    payload = head.canonical_payload()
    assert "legacy_fallback_disabled_at" not in payload


# === RevocationTombstoneEntry canonical ===


def test_tombstone_entry_canonical_required_fields() -> None:
    """tombstone entry canonical 必須 fields."""
    tombstone = tk.RevocationTombstoneEntry(
        fingerprint="a" * 64,
        revoked_at="2026-07-15T00:00:00Z",
        revocation_reason_hash="b" * 64,
        incident_id="INC-2026-001",
        signer_fingerprint="root-fp",
        signature="",
    )
    payload = tombstone.canonical_payload()
    assert payload["domain"] == tk.DOMAIN_REVOCATION_TOMBSTONE_V1
    assert payload["fingerprint"] == "a" * 64
    assert payload["incident_id"] == "INC-2026-001"


# === is_keyring_initialized (§9.3 R1 F-005) ===


def test_is_keyring_initialized_returns_false_when_marker_absent(tmp_path: Path) -> None:
    """marker file 不在なら False."""
    marker = tmp_path / "approval_keyring_initialized.signed"
    assert tk.is_keyring_initialized(marker) is False


def test_is_keyring_initialized_returns_true_when_marker_present(tmp_path: Path) -> None:
    """marker file 存在で True."""
    marker = tmp_path / "approval_keyring_initialized.signed"
    marker.write_text("placeholder content")
    assert tk.is_keyring_initialized(marker) is True
