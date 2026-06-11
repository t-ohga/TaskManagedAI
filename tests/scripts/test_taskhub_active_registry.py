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
               status: str = "active",
               valid_from: str = "2026-05-01T00:00:00Z",
               valid_to: str = "2027-05-01T00:00:00Z") -> ar.FleetMembership:
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
                valid_from=valid_from,
                valid_to=valid_to,
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
        journal_tail_verifier=ar.accept_unverified_tail,
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
        counter_path, lock_path, journal_path, "host-1", "fp-1", signer,
        journal_tail_verifier=ar.accept_unverified_tail,
    )
    e2, _, _ = ar.allocate_next_epoch(
        counter_path, lock_path, journal_path, "host-1", "fp-1", signer,
        journal_tail_verifier=ar.accept_unverified_tail,
    )
    e3, _, _ = ar.allocate_next_epoch(
        counter_path, lock_path, journal_path, "host-1", "fp-1", signer,
        journal_tail_verifier=ar.accept_unverified_tail,
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
        counter_path, lock_path, journal_path, "host-1", "fp-1", signer,
        journal_tail_verifier=ar.accept_unverified_tail,
    )
    _, _, e2 = ar.allocate_next_epoch(
        counter_path, lock_path, journal_path, "host-1", "fp-1", signer,
        journal_tail_verifier=ar.accept_unverified_tail,
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

    ar.allocate_next_epoch(
            counter_path, lock_path, journal_path,
            "host-1", "fp-1", signer,
            journal_tail_verifier=ar.accept_unverified_tail,
        )
    # tamper: epoch を書き換えるが sha256 は更新しない
    tampered = json.loads(counter_path.read_bytes())
    tampered["epoch"] = 999
    counter_path.write_bytes(json.dumps(tampered).encode("utf-8"))

    with pytest.raises(RuntimeError, match="taskhub_active_registry_epoch_counter_tampered"):
        ar.allocate_next_epoch(
            counter_path, lock_path, journal_path,
            "host-1", "fp-1", signer,
            journal_tail_verifier=ar.accept_unverified_tail,
        )


# === Codex PR #82 R1 fix coverage ===


def test_rfc8785_canonical_nfc_normalization() -> None:
    """Codex PR #82 R1 F-003 fix (P2): NFC normalization で composed/decomposed が一致."""
    composed = "café"  # NFC form (é = U+00E9)
    decomposed = "café"  # NFD form (e + combining acute U+0301)
    payload_c = {"name": composed}
    payload_d = {"name": decomposed}
    assert ar._rfc8785_canonical_bytes(payload_c) == ar._rfc8785_canonical_bytes(payload_d)


def test_rfc8785_canonical_rejects_nan() -> None:
    """Codex PR #82 R1 F-006 fix (P2): RFC 8785 strict encoder で NaN を reject."""
    payload = {"value": float("nan")}
    with pytest.raises(ValueError, match="RFC 8785 forbids non-finite numbers"):
        ar._rfc8785_canonical_bytes(payload)


def test_rfc8785_canonical_rejects_infinity() -> None:
    """Codex PR #82 R1 F-006 fix (P2): RFC 8785 strict encoder で Infinity を reject."""
    payload = {"value": float("inf")}
    with pytest.raises(ValueError, match="RFC 8785 forbids non-finite numbers"):
        ar._rfc8785_canonical_bytes(payload)


def test_allocate_next_epoch_lock_file_race_free(tmp_path: Path) -> None:
    """Codex PR #82 R1 F-001 fix (P1): lock file initialization は race-free.

    O_EXCL を外したため、lock file が既存でも spurious FileExistsError にならない。
    """
    priv = Ed25519PrivateKey.generate()
    counter_path = tmp_path / "epoch.counter"
    lock_path = tmp_path / "epoch.lock"
    journal_path = tmp_path / "epoch.journal.signed.jsonl"

    def signer(data: bytes) -> bytes:
        return priv.sign(data)

    # pre-create lock file with looser permission to simulate prior state
    lock_path.touch(mode=0o644)

    # first allocate should still succeed (race-free)
    e1, _, _ = ar.allocate_next_epoch(
            counter_path, lock_path, journal_path,
            "host-1", "fp-1", signer,
            journal_tail_verifier=ar.accept_unverified_tail,
        )
    assert e1 == 1

    # permission must be tightened to 0o600 even though we created it with 0o644
    import stat as stat_mod
    actual_mode = stat_mod.S_IMODE(lock_path.stat().st_mode)
    assert actual_mode == 0o600


def test_allocate_next_epoch_torn_journal_tail_recovery(tmp_path: Path) -> None:
    """Codex PR #82 R1 F-005 fix (P1): torn JSONL tail (partial line) でも recovery 可能.

    journal の last line が partial / corrupted でも backward scan で valid entry を取得、
    allocation を block しない。
    """
    priv = Ed25519PrivateKey.generate()
    counter_path = tmp_path / "epoch.counter"
    lock_path = tmp_path / "epoch.lock"
    journal_path = tmp_path / "epoch.journal.signed.jsonl"

    def signer(data: bytes) -> bytes:
        return priv.sign(data)

    # 1st valid allocation
    ar.allocate_next_epoch(
            counter_path, lock_path, journal_path,
            "host-1", "fp-1", signer,
            journal_tail_verifier=ar.accept_unverified_tail,
        )
    # simulate torn write: append partial JSON line at end
    with journal_path.open("ab") as jf:
        jf.write(b'{"epoch":2,"issued_at":"2026-')  # truncated mid-string
    # 2nd allocation should still succeed by scanning backward
    e2, _, _ = ar.allocate_next_epoch(
            counter_path, lock_path, journal_path,
            "host-1", "fp-1", signer,
            journal_tail_verifier=ar.accept_unverified_tail,
        )
    assert e2 == 2  # derived from valid entry 1, not from torn line


def test_allocate_next_epoch_crash_recovery_no_duplicate(tmp_path: Path) -> None:
    """Codex PR #82 R1 F-002 fix (P1): journal append 後 counter rename 失敗の crash recovery.

    journal に entry が記録済 + counter が古い stale 状態でも、journal_tail_epoch から
    monotonic increment を導出するため duplicate epoch にならない。
    """
    priv = Ed25519PrivateKey.generate()
    counter_path = tmp_path / "epoch.counter"
    lock_path = tmp_path / "epoch.lock"
    journal_path = tmp_path / "epoch.journal.signed.jsonl"

    def signer(data: bytes) -> bytes:
        return priv.sign(data)

    # allocate epoch 1, 2, 3
    ar.allocate_next_epoch(
            counter_path, lock_path, journal_path,
            "host-1", "fp-1", signer,
            journal_tail_verifier=ar.accept_unverified_tail,
        )
    ar.allocate_next_epoch(
            counter_path, lock_path, journal_path,
            "host-1", "fp-1", signer,
            journal_tail_verifier=ar.accept_unverified_tail,
        )
    ar.allocate_next_epoch(
            counter_path, lock_path, journal_path,
            "host-1", "fp-1", signer,
            journal_tail_verifier=ar.accept_unverified_tail,
        )
    # simulate crash: rollback counter to epoch=1 with valid sha256
    counter_payload_stale = {"epoch": 1, "issued_at": "2026-05-21T10:00:00.000000Z"}
    counter_canonical = ar._rfc8785_canonical_bytes(counter_payload_stale)
    counter_payload_stale["sha256"] = ar._sha256_hex(counter_canonical)
    counter_path.write_bytes(json.dumps(counter_payload_stale).encode("utf-8"))
    # next allocation must derive epoch from journal tail (epoch=3), not counter (epoch=1)
    e_next, _, entry = ar.allocate_next_epoch(
            counter_path, lock_path, journal_path,
            "host-1", "fp-1", signer,
            journal_tail_verifier=ar.accept_unverified_tail,
        )
    assert e_next == 4  # max(1, 3) + 1 = 4
    assert entry.epoch == 4


def test_allocate_next_epoch_counter_replay_with_recomputed_sha_blocked(tmp_path: Path) -> None:
    """Codex PR #82 R1 F-004 fix (P1): counter tampering で lower epoch を sha256 と一緒に
    書き換えても、journal_tail_epoch から replay 不可能.
    """
    priv = Ed25519PrivateKey.generate()
    counter_path = tmp_path / "epoch.counter"
    lock_path = tmp_path / "epoch.lock"
    journal_path = tmp_path / "epoch.journal.signed.jsonl"

    def signer(data: bytes) -> bytes:
        return priv.sign(data)

    ar.allocate_next_epoch(
            counter_path, lock_path, journal_path,
            "host-1", "fp-1", signer,
            journal_tail_verifier=ar.accept_unverified_tail,
        )
    ar.allocate_next_epoch(
            counter_path, lock_path, journal_path,
            "host-1", "fp-1", signer,
            journal_tail_verifier=ar.accept_unverified_tail,
        )
    ar.allocate_next_epoch(
            counter_path, lock_path, journal_path,
            "host-1", "fp-1", signer,
            journal_tail_verifier=ar.accept_unverified_tail,
        )
    # attacker tampers counter to lower epoch + recomputes sha256
    tampered_payload = {"epoch": 1, "issued_at": "2026-05-21T10:00:00.000000Z"}
    tampered_canonical = ar._rfc8785_canonical_bytes(tampered_payload)
    tampered_payload["sha256"] = ar._sha256_hex(tampered_canonical)
    counter_path.write_bytes(json.dumps(tampered_payload).encode("utf-8"))
    # journal_tail_epoch=3 で max(1, 3)+1=4 を導出、attacker は epoch=2 を replay できない
    e_next, _, _ = ar.allocate_next_epoch(
            counter_path, lock_path, journal_path,
            "host-1", "fp-1", signer,
            journal_tail_verifier=ar.accept_unverified_tail,
        )
    assert e_next == 4  # not 2


def test_write_marker_atomic_short_write_resilient(tmp_path: Path) -> None:
    """Codex PR #82 R1 F-007 fix (P2): _write_all loop で short write 耐性."""
    marker_path = tmp_path / "test.signed"
    # large payload to exercise potential short write path
    large_payload = {"data": "x" * 100_000, "domain": "test.v1"}
    ar.write_marker_atomic(marker_path, large_payload)
    # read back and verify content
    fd = ar.os.open(str(marker_path), ar.os.O_RDONLY | ar.os.O_NOFOLLOW)
    try:
        from_disk = ar._read_all(fd, ar._MARKER_MAX_BYTES)
    finally:
        ar.os.close(fd)
    expected_canonical = ar._rfc8785_canonical_bytes(large_payload)
    assert from_disk == expected_canonical


def test_read_marker_doc_chunked_read(tmp_path: Path) -> None:
    """Codex PR #82 R1 F-008 fix (P2): _read_all で EOF まで loop、chunked OK."""
    marker_path = tmp_path / "test.signed"
    payload = {"a": 1, "b": "test", "data": "y" * 200_000}
    ar.write_marker_atomic(marker_path, payload)
    loaded = ar.read_marker_doc(marker_path)
    assert loaded == ar._normalize_strings_nfc(payload)  # NFC applied during write


def test_read_marker_doc_size_cap_enforced(tmp_path: Path) -> None:
    """Codex PR #82 R1 F-008 fix (P2): max_bytes 超過は OSError で reject (truncation defense)."""
    marker_path = tmp_path / "test.signed"
    # write file > 1 MiB directly (bypass write_marker_atomic)
    marker_path.write_bytes(b"x" * (2 * 1024 * 1024))
    with pytest.raises(OSError, match="exceeds max bytes limit"):
        ar.read_marker_doc(marker_path)


# === Codex PR #82 R2 fix coverage ===


def test_ownership_check_rejects_expired_host_lifecycle() -> None:
    """Codex PR #82 R2 F-001 fix (P1): host.valid_to <= now() は taskhub_active_registry_host_lifecycle_expired."""
    import datetime as dt
    fleet = _make_fleet(valid_to="2026-01-01T00:00:00Z")  # already expired
    now = dt.datetime(2026, 5, 21, tzinfo=dt.UTC)
    ok, reason = ar.verify_signer_host_ownership(
        fleet=fleet, marker_host_id="host-1", marker_signer_fingerprint="sig-fp-1",
        marker_kind="active", now=now,
    )
    assert ok is False
    assert reason == "taskhub_active_registry_host_lifecycle_expired"


def test_ownership_check_rejects_not_yet_active_host_lifecycle() -> None:
    """Codex PR #82 R2 F-001 fix (P1): now() < host.valid_from は host_lifecycle_expired."""
    import datetime as dt
    fleet = _make_fleet(valid_from="2027-01-01T00:00:00Z")  # future, not yet active
    now = dt.datetime(2026, 5, 21, tzinfo=dt.UTC)
    ok, reason = ar.verify_signer_host_ownership(
        fleet=fleet, marker_host_id="host-1", marker_signer_fingerprint="sig-fp-1",
        marker_kind="active", now=now,
    )
    assert ok is False
    assert reason == "taskhub_active_registry_host_lifecycle_expired"


def test_ownership_check_pass_within_lifecycle_window() -> None:
    """Codex PR #82 R2 F-001 fix (P1): lifecycle window 内は pass."""
    import datetime as dt
    fleet = _make_fleet(
        valid_from="2026-01-01T00:00:00Z",
        valid_to="2027-01-01T00:00:00Z",
    )
    now = dt.datetime(2026, 5, 21, tzinfo=dt.UTC)
    ok, reason = ar.verify_signer_host_ownership(
        fleet=fleet, marker_host_id="host-1", marker_signer_fingerprint="sig-fp-1",
        marker_kind="active", now=now,
    )
    assert ok is True
    assert reason == ""


def test_allocate_next_epoch_rejects_counter_symlink(tmp_path: Path) -> None:
    """Codex PR #82 R2 F-002 fix (P1): counter_path が symlink なら O_NOFOLLOW で reject (OSError)."""
    priv = Ed25519PrivateKey.generate()
    counter_path = tmp_path / "epoch.counter"
    lock_path = tmp_path / "epoch.lock"
    journal_path = tmp_path / "epoch.journal.signed.jsonl"
    target = tmp_path / "evil.json"
    target.write_text('{"epoch":1,"issued_at":"2026-01-01T00:00:00.000000Z","sha256":"fake"}')
    counter_path.symlink_to(target)

    def signer(data: bytes) -> bytes:
        return priv.sign(data)

    with pytest.raises(OSError):
        ar.allocate_next_epoch(
            counter_path, lock_path, journal_path,
            "host-1", "fp-1", signer,
            journal_tail_verifier=ar.accept_unverified_tail,
        )


def test_allocate_next_epoch_rejects_journal_symlink(tmp_path: Path) -> None:
    """Codex PR #82 R2 F-005 fix (P1): journal_path が symlink なら O_NOFOLLOW で reject."""
    priv = Ed25519PrivateKey.generate()
    counter_path = tmp_path / "epoch.counter"
    lock_path = tmp_path / "epoch.lock"
    journal_path = tmp_path / "epoch.journal.signed.jsonl"
    target = tmp_path / "victim.log"
    target.write_text("existing content\n")
    journal_path.symlink_to(target)

    def signer(data: bytes) -> bytes:
        return priv.sign(data)

    with pytest.raises(OSError):
        ar.allocate_next_epoch(
            counter_path, lock_path, journal_path,
            "host-1", "fp-1", signer,
            journal_tail_verifier=ar.accept_unverified_tail,
        )


def test_allocate_next_epoch_rejects_forged_journal_tail(tmp_path: Path) -> None:
    """Codex PR #82 R2 F-004 fix (P1): journal tail line に domain field がない forged entry は無視.

    forged tail (domain なし or signature なし or wrong domain) で epoch derivation を
    steal できないこと。pre-write entry が valid なら、forged 行は skip され有効 entry まで遡る。
    """
    priv = Ed25519PrivateKey.generate()
    counter_path = tmp_path / "epoch.counter"
    lock_path = tmp_path / "epoch.lock"
    journal_path = tmp_path / "epoch.journal.signed.jsonl"

    def signer(data: bytes) -> bytes:
        return priv.sign(data)

    # 1st valid allocation, then append a forged line with high epoch but wrong domain
    ar.allocate_next_epoch(
            counter_path, lock_path, journal_path,
            "host-1", "fp-1", signer,
            journal_tail_verifier=ar.accept_unverified_tail,
        )
    with journal_path.open("ab") as jf:
        jf.write(b'{"domain":"evil.fake.v1","epoch":9999,"signature":"forged","writer_signer_fingerprint":"x"}\n')
    # tamper counter to lower for replay attempt
    tampered = {"epoch": 1, "issued_at": "2026-05-21T10:00:00.000000Z"}
    tampered["sha256"] = ar._sha256_hex(ar._rfc8785_canonical_bytes(tampered))
    counter_path.write_bytes(json.dumps(tampered).encode("utf-8"))
    # next allocation should pick journal_tail_epoch=1 (forged line skipped due to wrong domain)
    e_next, _, _ = ar.allocate_next_epoch(
            counter_path, lock_path, journal_path,
            "host-1", "fp-1", signer,
            journal_tail_verifier=ar.accept_unverified_tail,
        )
    assert e_next == 2  # max(1, 1) + 1 = 2 (not 10000 from forged)


def test_allocate_next_epoch_bounded_tail_read(tmp_path: Path) -> None:
    """Codex PR #82 R2 F-003 fix (P2): bounded tail read (64 KiB) で large journal でも latency 一定."""
    priv = Ed25519PrivateKey.generate()
    counter_path = tmp_path / "epoch.counter"
    lock_path = tmp_path / "epoch.lock"
    journal_path = tmp_path / "epoch.journal.signed.jsonl"

    def signer(data: bytes) -> bytes:
        return priv.sign(data)

    ar.allocate_next_epoch(
            counter_path, lock_path, journal_path,
            "host-1", "fp-1", signer,
            journal_tail_verifier=ar.accept_unverified_tail,
        )
    # inject large prefix to journal (simulating long history)
    with journal_path.open("ab") as jf:
        jf.write(b"#" * (128 * 1024) + b"\n")  # 128 KiB of garbage prefix
    # subsequent allocation should still find tail entry within 64 KiB window
    e_next, _, _ = ar.allocate_next_epoch(
            counter_path, lock_path, journal_path,
            "host-1", "fp-1", signer,
            journal_tail_verifier=ar.accept_unverified_tail,
        )
    assert e_next == 2  # max(1, 1) + 1


def test_write_marker_atomic_uses_owner_only_permission(tmp_path: Path) -> None:
    """Codex PR #82 R2 F-006 fix (P2): marker file は 0o600 owner-only で create."""
    import stat as stat_mod
    marker_path = tmp_path / "test.signed"
    ar.write_marker_atomic(marker_path, {"a": 1, "domain": "test.v1"})
    mode = stat_mod.S_IMODE(marker_path.stat().st_mode)
    assert mode == 0o600


# === Codex PR #82 R3 fix coverage ===


def test_rfc8785_utf16_code_unit_sort() -> None:
    """Codex PR #82 R3 F-001 fix (P1): object key sort は UTF-16 code units 単位.

    BMP-only ASCII では Python の str ordering と同じだが、supplementary character
    (例: U+1F600 grinning face = surrogate pair D83D DE00) を含む key は UTF-16 code unit
    order と Python code point order で異なる。
    """
    # ASCII keys: orderings should match (sanity)
    payload_ascii = {"b": 1, "a": 2}
    encoded = ar._rfc8785_canonical_bytes(payload_ascii)
    assert encoded == b'{"a":2,"b":1}'

    # Supplementary character keys: high surrogate D83D < some BMP chars > U+E000
    # but Python str compare uses code points: U+1F600 > U+FFFD
    # UTF-16 BE encoded: U+1F600 -> b"\xD8\x3D\xDE\x00" starts with 0xD8
    # U+FFFD -> b"\xFF\xFD" starts with 0xFF
    # So UTF-16 BE byte-wise: 0xD8 < 0xFF, supplementary should sort BEFORE U+FFFD
    payload_supp = {"\U0001F600": "smile", "�": "replacement"}
    encoded_supp = ar._rfc8785_canonical_bytes(payload_supp)
    # in UTF-16 sort, U+1F600 (surrogate) comes before U+FFFD
    assert encoded_supp.find(b'"\xf0\x9f\x98\x80"') < encoded_supp.find(b'"\xef\xbf\xbd"')


def test_rfc8785_number_serialization_integer_valued_float() -> None:
    """Codex PR #82 R3 F-002 fix (P1): float 1.0 は ECMAScript ToString で "1" に."""
    payload = {"x": 1.0, "y": 2.5, "z": -0.0}
    encoded = ar._rfc8785_canonical_bytes(payload)
    # x=1.0 → "1" (integer-valued), y=2.5 → "2.5" (non-integer), z=-0.0 → "0"
    assert encoded == b'{"x":1,"y":2.5,"z":0}'


def test_rfc8785_number_serialization_integer() -> None:
    """integer は標準 decimal repr で encode."""
    encoded = ar._rfc8785_canonical_bytes({"v": 12345})
    assert encoded == b'{"v":12345}'


def test_rfc8785_number_serialization_negative_zero() -> None:
    """RFC 8785 §3.2.2.3: -0.0 は "0" に正規化 (ECMAScript ToString rule)."""
    encoded = ar._rfc8785_canonical_bytes({"v": -0.0})
    assert encoded == b'{"v":0}'


def test_rfc8785_bool_is_not_number() -> None:
    """bool は int subclass だが number として encode しない (true/false token)."""
    encoded = ar._rfc8785_canonical_bytes({"v": True})
    assert encoded == b'{"v":true}'
    encoded2 = ar._rfc8785_canonical_bytes({"w": False})
    assert encoded2 == b'{"w":false}'


def test_rfc8785_null_serialization() -> None:
    """null は "null" token."""
    encoded = ar._rfc8785_canonical_bytes({"v": None})
    assert encoded == b'{"v":null}'


def test_rfc8785_nested_dict_sorted() -> None:
    """nested dict も再帰的に sort される."""
    encoded = ar._rfc8785_canonical_bytes({"outer": {"z": 1, "a": 2}, "another": 3})
    assert encoded == b'{"another":3,"outer":{"a":2,"z":1}}'


def test_normalize_strings_nfc_collision_detection() -> None:
    """Codex PR #82 R3 F-003 fix (P2): NFC で collide する dict key を検出 → ValueError."""
    # "café" with NFC composed (é = U+00E9) vs NFD decomposed (e + U+0301)
    composed = "café"  # NFC form
    decomposed = "café"  # NFD form
    # both normalize to the same NFC form, so the dict has 2 distinct keys that collide
    colliding = {composed: 1, decomposed: 2}
    with pytest.raises(ValueError, match="NFC-colliding dict keys detected"):
        ar._normalize_strings_nfc(colliding)


def test_find_journal_tail_with_64kib_only(tmp_path: Path) -> None:
    """Codex PR #82 R3 F-004 fix (P2): journal valid entry が 64 KiB 内なら通常 return."""
    journal_path = tmp_path / "epoch.journal.signed.jsonl"
    valid_entry = {
        "domain": ar.DOMAIN_EPOCH_JOURNAL_V1,
        "epoch": 1,
        "issued_at": "2026-05-21T10:00:00.000000Z",
        "host_id": "host-1",
        "writer_signer_fingerprint": "fp-writer-1",
        "previous_entry_hash": "0" * 64,
        "signature": "fake-sig-base64",
    }
    journal_path.write_bytes(
        json.dumps(valid_entry, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    )
    found = ar._find_valid_journal_tail_entry(journal_path=journal_path, tail_verifier=None)
    assert found is not None
    assert found["epoch"] == 1


def test_find_journal_tail_progressive_expansion_beyond_64kib(tmp_path: Path) -> None:
    """Codex PR #82 R3 F-004 fix (P2): valid entry が 64 KiB を超えた position にあっても
    progressive expansion で発見される."""
    journal_path = tmp_path / "epoch.journal.signed.jsonl"
    valid_entry = {
        "domain": ar.DOMAIN_EPOCH_JOURNAL_V1,
        "epoch": 1,
        "issued_at": "2026-05-21T10:00:00.000000Z",
        "host_id": "host-1",
        "writer_signer_fingerprint": "fp-writer-1",
        "previous_entry_hash": "0" * 64,
        "signature": "fake-sig-base64",
    }
    with journal_path.open("wb") as f:
        f.write(json.dumps(valid_entry, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
        # 100 KiB of garbage / partial lines after the valid entry (> 64 KiB window)
        f.write(b"#" * (100 * 1024) + b"\n")
    found = ar._find_valid_journal_tail_entry(journal_path=journal_path, tail_verifier=None)
    assert found is not None
    assert found["epoch"] == 1


def test_find_journal_tail_signature_verifier_rejects_forged_entry(tmp_path: Path) -> None:
    """Codex PR #82 R3 F-005 fix (P1): tail_verifier callable で forged signature を reject."""
    journal_path = tmp_path / "epoch.journal.signed.jsonl"
    valid_entry = {
        "domain": ar.DOMAIN_EPOCH_JOURNAL_V1,
        "epoch": 1,
        "issued_at": "2026-05-21T10:00:00.000000Z",
        "host_id": "host-1",
        "writer_signer_fingerprint": "fp-writer-1",
        "previous_entry_hash": "0" * 64,
        "signature": "forged-sig-base64",
    }
    journal_path.write_bytes(
        json.dumps(valid_entry, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    )

    # verifier rejects all (simulating forged signature detection)
    def reject_all(entry: dict) -> bool:
        return False

    found = ar._find_valid_journal_tail_entry(journal_path=journal_path, tail_verifier=reject_all)
    assert found is None  # no valid entry passed signature verify


def test_find_journal_tail_signature_verifier_accepts_valid_entry(tmp_path: Path) -> None:
    """tail_verifier=lambda: True なら structural valid entry を accept (positive control)."""
    journal_path = tmp_path / "epoch.journal.signed.jsonl"
    valid_entry = {
        "domain": ar.DOMAIN_EPOCH_JOURNAL_V1,
        "epoch": 7,
        "issued_at": "2026-05-21T10:00:00.000000Z",
        "host_id": "host-1",
        "writer_signer_fingerprint": "fp-writer-1",
        "previous_entry_hash": "0" * 64,
        "signature": "verified-sig-base64",
    }
    journal_path.write_bytes(
        json.dumps(valid_entry, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    )
    found = ar._find_valid_journal_tail_entry(journal_path=journal_path, tail_verifier=lambda _: True)
    assert found is not None
    assert found["epoch"] == 7


def test_allocate_next_epoch_verifier_rejects_all_fail_closed(tmp_path: Path) -> None:
    """Codex PR #82 R4 F-004 fix (P2): journal が存在するが verifier で全 entry が reject される
    → silent genesis fallback ではなく fail-closed RuntimeError."""
    priv = Ed25519PrivateKey.generate()
    counter_path = tmp_path / "epoch.counter"
    lock_path = tmp_path / "epoch.lock"
    journal_path = tmp_path / "epoch.journal.signed.jsonl"

    def signer(data: bytes) -> bytes:
        return priv.sign(data)

    # initial allocation creates a valid entry (verifier=accept_all)
    ar.allocate_next_epoch(
        counter_path, lock_path, journal_path, "host-1", "fp-1", signer,
        journal_tail_verifier=ar.accept_unverified_tail,
    )

    # second allocation with reject_all verifier → fail-closed
    with pytest.raises(
        RuntimeError, match="taskhub_active_registry_epoch_journal_no_valid_tail_found"
    ):
        ar.allocate_next_epoch(
            counter_path, lock_path, journal_path, "host-1", "fp-1", signer,
            journal_tail_verifier=lambda _: False,
        )


def test_allocate_next_epoch_requires_explicit_verifier_kwarg(tmp_path: Path) -> None:
    """Codex PR #82 R4 F-003 fix (P1): journal_tail_verifier は keyword-only required arg。
    omit すると TypeError (caller が verifier を意識的に渡すよう強制、foot-gun 削除)."""
    priv = Ed25519PrivateKey.generate()
    counter_path = tmp_path / "epoch.counter"
    lock_path = tmp_path / "epoch.lock"
    journal_path = tmp_path / "epoch.journal.signed.jsonl"

    def signer(data: bytes) -> bytes:
        return priv.sign(data)

    with pytest.raises(TypeError, match="journal_tail_verifier"):
        ar.allocate_next_epoch(  # type: ignore[call-arg]
            counter_path, lock_path, journal_path, "host-1", "fp-1", signer,
        )


def test_encode_number_rejects_oversize_integer() -> None:
    """Codex PR #82 R4 F-005 fix (P2): I-JSON integer range (±2^53 - 1) を超えると ValueError."""
    # MAX_INTEGER + 1
    with pytest.raises(ValueError, match="I-JSON integer out of IEEE-754 double-precision range"):
        ar._encode_number(1 << 53)
    # MIN_INTEGER - 1
    with pytest.raises(ValueError, match="I-JSON integer out of IEEE-754 double-precision range"):
        ar._encode_number(-(1 << 53))


def test_encode_number_accepts_ijson_range_boundary() -> None:
    """I-JSON range boundary (±(2^53 - 1)) は accept される."""
    assert ar._encode_number(_IJSON_MAX := (1 << 53) - 1) == str(_IJSON_MAX)
    assert ar._encode_number(_IJSON_MIN := -((1 << 53) - 1)) == str(_IJSON_MIN)


def test_ecmascript_float_small_number_uses_fixed_notation() -> None:
    """Codex PR #82 R6 F-002 fix (P1、rfc8785 delegation): 1e-6 ≤ |n| < 1 で fixed notation."""
    # 2.559738902941283e-06 → "0.000002559738902941283" (rfc8785 lib ECMAScript ToString)
    encoded = ar._encode_number(2.559738902941283e-06)
    assert encoded == "0.000002559738902941283"
    # 1.5e-7 < 1e-6 → scientific notation
    encoded2 = ar._encode_number(1.5e-7)
    assert "e-7" in encoded2 or encoded2.startswith("1.5")


def test_ecmascript_float_handles_integer_valued_above_1e21() -> None:
    """integer-valued float >= 1e21 は scientific notation を使う (ECMAScript ToString rule)."""
    encoded = ar._encode_number(1e21)
    assert encoded == "1e+21"


def test_rfc8785_canonical_with_oversize_integer_rejected() -> None:
    """encoding-level でも I-JSON range 違反は reject される."""
    with pytest.raises(ValueError, match="I-JSON integer"):
        ar._rfc8785_canonical_bytes({"v": (1 << 53)})


# === Codex PR #82 R5 fix coverage ===


def test_encode_number_integer_valued_float_above_ijson_emits_integral() -> None:
    """Codex PR #82 R5 F-001 fix (P1): integer-valued float < 1e21 で I-JSON range 超過でも
    integral form (ECMAScript Number.toString) を emit、scientific には fall-back しない."""
    # 2^53 = 9007199254740992、abs < 1e21、ECMAScript ToString → "9007199254740992"
    encoded = ar._encode_number(float(1 << 53))
    assert encoded == "9007199254740992"
    # 1e16 → ECMAScript ToString → "10000000000000000"
    assert ar._encode_number(1e16) == "10000000000000000"
    # 1e20 → still integral form
    assert ar._encode_number(1e20) == "100000000000000000000"


def test_structural_validation_rejects_bool_epoch() -> None:
    """Codex PR #82 R5 F-003 fix (P2): epoch=True/False (bool is int subclass) を reject."""
    entry = {
        "domain": ar.DOMAIN_EPOCH_JOURNAL_V1,
        "epoch": True,  # bool — should be rejected
        "issued_at": "2026-05-21T10:00:00.000000Z",
        "host_id": "host-1",
        "writer_signer_fingerprint": "fp-1",
        "previous_entry_hash": "0" * 64,
        "signature": "sig",
    }
    assert ar._is_structurally_valid_journal_entry(entry) is False


def test_structural_validation_rejects_missing_host_id() -> None:
    """Codex PR #82 R5 F-004 fix (P2): host_id 不在は reject (full schema 必須)."""
    entry = {
        "domain": ar.DOMAIN_EPOCH_JOURNAL_V1,
        "epoch": 1,
        "issued_at": "2026-05-21T10:00:00.000000Z",
        "writer_signer_fingerprint": "fp-1",
        "previous_entry_hash": "0" * 64,
        "signature": "sig",
        # host_id missing
    }
    assert ar._is_structurally_valid_journal_entry(entry) is False


def test_structural_validation_rejects_missing_issued_at() -> None:
    """Codex PR #82 R5 F-004 fix (P2): issued_at 不在は reject."""
    entry = {
        "domain": ar.DOMAIN_EPOCH_JOURNAL_V1,
        "epoch": 1,
        "host_id": "host-1",
        "writer_signer_fingerprint": "fp-1",
        "previous_entry_hash": "0" * 64,
        "signature": "sig",
        # issued_at missing
    }
    assert ar._is_structurally_valid_journal_entry(entry) is False


def test_structural_validation_rejects_invalid_previous_entry_hash() -> None:
    """Codex PR #82 R5 F-004 fix (P2): previous_entry_hash は 64-char hex 必須."""
    entry = {
        "domain": ar.DOMAIN_EPOCH_JOURNAL_V1,
        "epoch": 1,
        "issued_at": "2026-05-21T10:00:00.000000Z",
        "host_id": "host-1",
        "writer_signer_fingerprint": "fp-1",
        "previous_entry_hash": "not-a-valid-hex-hash",  # invalid format
        "signature": "sig",
    }
    assert ar._is_structurally_valid_journal_entry(entry) is False


def test_structural_validation_rejects_negative_epoch() -> None:
    """epoch は 非負 integer 必須."""
    entry = {
        "domain": ar.DOMAIN_EPOCH_JOURNAL_V1,
        "epoch": -1,
        "issued_at": "2026-05-21T10:00:00.000000Z",
        "host_id": "host-1",
        "writer_signer_fingerprint": "fp-1",
        "previous_entry_hash": "0" * 64,
        "signature": "sig",
    }
    assert ar._is_structurally_valid_journal_entry(entry) is False


# === Batch D: 2PC PrepareMarker + CommitMarker + lease binding (§9.4-§9.7) ===


def _make_prepare_marker(
    *,
    cutover_id: str = "cutover-test",
    role: str = "source",
    host_id: str = "host-source",
) -> ar.PrepareMarker:
    return ar.PrepareMarker(
        cutover_id=cutover_id,
        host_id=host_id,
        role=role,
        migration_epoch=10,
        prepared_at="2026-05-21T10:00:00Z",
        signer_fingerprint="sig-fp",
        cutover_lease_snapshot_content_sha256="a" * 64,
        fleet_membership_snapshot_content_sha256="b" * 64,
        required_host_ids_hash=ar.compute_required_host_ids_hash(("host-source", "host-target")),
        lease_acquired_at="2026-05-21T09:55:00Z",
        lease_expires_at="2026-05-21T11:55:00Z",
        cutover_approval_id="approval-1",
        cutover_approval_claim_hash="c" * 64,
        signature="",
    )


def test_prepare_marker_canonical_includes_lease_binding() -> None:
    """§9.4 R2 F-002 + §9.5 R3 F-003: PrepareMarker は lease/fleet snapshot + required_host_ids
    hash を canonical に含む."""
    pm = _make_prepare_marker()
    payload = pm.canonical_payload()
    assert payload["domain"] == ar.DOMAIN_CUTOVER_PREPARE_V1
    assert "cutover_lease_snapshot_content_sha256" in payload
    assert "fleet_membership_snapshot_content_sha256" in payload
    assert "required_host_ids_hash" in payload
    assert "lease_acquired_at" in payload
    assert "lease_expires_at" in payload


def test_compute_required_host_ids_hash_canonical_order() -> None:
    """compute_required_host_ids_hash は順序非依存 deterministic hash (canonical sort)."""
    h1 = ar.compute_required_host_ids_hash(("host-1", "host-2", "host-3"))
    h2 = ar.compute_required_host_ids_hash(("host-3", "host-1", "host-2"))
    assert h1 == h2
    # different membership → different hash
    h3 = ar.compute_required_host_ids_hash(("host-1", "host-2"))
    assert h3 != h1


def _make_commit_marker(
    *,
    committed_at: str = "2026-05-21T10:01:30Z",
    lease_acquired_at: str = "2026-05-21T09:55:00Z",
    lease_expires_at: str = "2026-05-21T11:55:00Z",
    host_confirmations: tuple[tuple[str, str], ...] = (
        ("host-source", "2026-05-21T10:00:30Z"),
        ("host-target", "2026-05-21T10:01:00Z"),  # max confirmed = 10:01:00
    ),
    required_host_ids: tuple[str, ...] | None = None,
) -> ar.CommitMarker:
    """Helper: build a CommitMarker test fixture.

    `required_host_ids` defaults to the host_confirmations' host ids (matching scenario).
    Tests can override to simulate partial confirmation or tampered hash scenarios.
    """
    finalization_sigs = tuple(
        ar.HostFinalizationSignature(
            host_id=hid,
            signer_fingerprint=f"{hid}-fp",
            commit_confirmed_at=ts,
            signature=f"sig-{hid}",
        )
        for hid, ts in host_confirmations
    )
    actual_required = required_host_ids if required_host_ids is not None else tuple(h for h, _ in host_confirmations)
    # Build a proto marker to compute the real preimage hash from canonical bytes
    proto = ar.CommitMarker(
        cutover_id="cutover-test",
        committed_at=committed_at,
        source_prepare_marker_hash="p1" * 32,
        target_prepare_marker_hash="p2" * 32,
        cutover_lease_snapshot_content_sha256="a" * 64,
        fleet_membership_snapshot_content_sha256="b" * 64,
        required_host_ids_hash=ar.compute_required_host_ids_hash(actual_required),
        lease_acquired_at=lease_acquired_at,
        lease_expires_at=lease_expires_at,
        cutover_approval_id="approval-1",
        cutover_approval_claim_hash="c" * 64,
        commit_approval_claim_hash="d" * 64,
        host_finalization_signatures=finalization_sigs,
        commit_finalization_preimage_hash="0" * 64,  # placeholder
        signature="",
    )
    # compute actual preimage hash via recomputation
    recomputed = ar._sha256_hex(ar._rfc8785_canonical_bytes(proto.commit_finalization_preimage()))
    return ar.CommitMarker(
        cutover_id=proto.cutover_id,
        committed_at=proto.committed_at,
        source_prepare_marker_hash=proto.source_prepare_marker_hash,
        target_prepare_marker_hash=proto.target_prepare_marker_hash,
        cutover_lease_snapshot_content_sha256=proto.cutover_lease_snapshot_content_sha256,
        fleet_membership_snapshot_content_sha256=proto.fleet_membership_snapshot_content_sha256,
        required_host_ids_hash=proto.required_host_ids_hash,
        lease_acquired_at=proto.lease_acquired_at,
        lease_expires_at=proto.lease_expires_at,
        cutover_approval_id=proto.cutover_approval_id,
        cutover_approval_claim_hash=proto.cutover_approval_claim_hash,
        commit_approval_claim_hash=proto.commit_approval_claim_hash,
        host_finalization_signatures=proto.host_finalization_signatures,
        commit_finalization_preimage_hash=recomputed,
        signature="",
    )


def test_commit_marker_canonical_sorts_host_signatures() -> None:
    """commit marker canonical で host_finalization_signatures は host_id 昇順 sort."""
    cm = _make_commit_marker(host_confirmations=(
        ("host-z", "2026-05-21T10:00:00Z"),
        ("host-a", "2026-05-21T10:01:00Z"),
    ))
    payload = cm.canonical_payload()
    sigs = payload["host_finalization_signatures"]
    assert sigs[0]["host_id"] == "host-a"
    assert sigs[1]["host_id"] == "host-z"


def test_commit_marker_finalization_preimage_includes_required_fields() -> None:
    """commit_finalization_preimage() は §9.7 R6 F-001 で specified canonical schema 全 fields を含む.

    Codex PR #84 R3 F-002 fix: lease_acquired_at + lease_expires_at + cutover_id も必須化
    (host signature が lease window と cutover identity に binding される)."""
    cm = _make_commit_marker()
    preimage = cm.commit_finalization_preimage()
    expected_keys = sorted([
        "commit_approval_claim_hash", "committed_at", "cutover_approval_claim_hash",
        "cutover_approval_id", "cutover_id",  # R3 F-002 fix
        "cutover_lease_snapshot_content_sha256", "domain",
        "fleet_membership_snapshot_content_sha256",
        "lease_acquired_at", "lease_expires_at",  # R3 F-002 fix
        "required_host_ids_hash",
        "source_prepare_marker_hash", "target_prepare_marker_hash",
    ])
    assert sorted(preimage.keys()) == expected_keys


def test_verify_commit_marker_pass_for_valid_invariants() -> None:
    """§9.7 R6 F-001 + §9.9 R9 F-001 logic correction: 全 host confirmation + committed_at が正しい順序."""
    cm = _make_commit_marker()  # committed_at=10:05, max(confirmed)=10:01, lease=09:55-11:55
    ok, reason = ar.verify_commit_marker_invariants(
        cm,
        ("host-source", "host-target"),
        host_signer_public_key_resolver=ar.accept_unverified_commit_marker_signatures,
    )
    assert ok is True
    assert reason == ""


def test_verify_commit_marker_rejects_partial_host_confirmation() -> None:
    """§9.5 R3 F-003: required host 全件分の signature がないと partial_confirmation で reject."""
    # marker は required_host_ids_hash を ("host-source", "host-target") で計算するが、
    # host_finalization_signatures は host-source 1 件のみ → partial confirmation。
    cm = _make_commit_marker(
        host_confirmations=(
            ("host-source", "2026-05-21T10:00:00Z"),
            # missing host-target
        ),
        required_host_ids=("host-source", "host-target"),  # hash consistent with caller's expectation
    )
    ok, reason = ar.verify_commit_marker_invariants(
        cm,
        ("host-source", "host-target"),
        host_signer_public_key_resolver=ar.accept_unverified_commit_marker_signatures,
    )
    assert ok is False
    assert reason == "taskhub_cutover_lease_required_host_partial_confirmation"


def test_verify_commit_marker_rejects_required_host_ids_hash_mismatch() -> None:
    """Codex PR #84 R1 F-002 fix (P1、L628): marker.required_host_ids_hash が caller's required_host_ids hash と
    mismatch なら lease binding 違反として fail-closed."""
    # marker uses default required = host_confirmations hosts (source + target)
    cm = _make_commit_marker()  # required = ("host-source", "host-target")
    # caller passes a different set (extra host)
    ok, reason = ar.verify_commit_marker_invariants(
        cm, ("host-source", "host-target", "host-extra"),
        host_signer_public_key_resolver=ar.accept_unverified_commit_marker_signatures,
    )
    assert ok is False
    assert reason == "taskhub_cutover_required_host_ids_hash_mismatch"


def test_compute_required_host_ids_hash_rejects_duplicates() -> None:
    """Codex PR #84 R1 F-005 fix (P2、L676): duplicate host_id は ValueError で reject."""
    with pytest.raises(ValueError, match="duplicate host_id detected"):
        ar.compute_required_host_ids_hash(("host-a", "host-a", "host-b"))


def test_verify_commit_marker_rejects_empty_required_hosts() -> None:
    """Codex PR #84 R1 F-004 fix (P2、L650): empty required + empty signatures は partial_confirmation で
    fail-closed (max/min ValueError 回避).

    NOTE: empty tuple passes required_host_ids_hash check (sha256 of canonical []) but then fails
    on signed_host_ids != set(required_host_ids) — wait, signed_host_ids = set() and
    set(()) = set(), so equality passes. Then `if not marker.host_finalization_signatures` fires.
    """
    # 空 required_host_ids、空 host_confirmations
    cm = _make_commit_marker(
        host_confirmations=(),
        required_host_ids=(),
    )
    ok, reason = ar.verify_commit_marker_invariants(
        cm,
        (),
        host_signer_public_key_resolver=ar.accept_unverified_commit_marker_signatures,
    )
    assert ok is False
    assert reason == "taskhub_cutover_lease_required_host_partial_confirmation"


def test_verify_commit_marker_handles_duplicate_required_host_ids_via_fail_closed() -> None:
    """Codex PR #84 R2 F-001 fix (P1、L640): caller-supplied required_host_ids に duplicate があると
    compute_required_host_ids_hash が ValueError を raise するが、verify は catch して fail-closed."""
    cm = _make_commit_marker()  # default required = ("host-source", "host-target")
    # caller passes duplicates — should NOT crash, should return (False, reason)
    ok, reason = ar.verify_commit_marker_invariants(
        cm,
        ("host-source", "host-source", "host-target"),
        host_signer_public_key_resolver=ar.accept_unverified_commit_marker_signatures,
    )
    assert ok is False
    assert reason == "taskhub_cutover_required_host_ids_hash_mismatch"


def test_verify_commit_marker_rejects_duplicate_host_finalization_signatures() -> None:
    """Codex PR #84 R2 F-002 fix (P2、L646): host_finalization_signatures に duplicate host_id があると
    partial_confirmation で reject (set conversion で multiplicity drop の問題回避)."""
    # 直接 CommitMarker を組み立て (_make_commit_marker は default required を host_confirmations から
    # 取るが、duplicate signature を持たせるには直接構築が必要)
    duplicate_sigs = (
        ar.HostFinalizationSignature(
            host_id="host-source", signer_fingerprint="src-fp",
            commit_confirmed_at="2026-05-21T10:00:30Z", signature="sig-1",
        ),
        ar.HostFinalizationSignature(
            host_id="host-source", signer_fingerprint="src-fp",  # duplicate host_id
            commit_confirmed_at="2026-05-21T10:01:30Z", signature="sig-2",
        ),
        ar.HostFinalizationSignature(
            host_id="host-target", signer_fingerprint="tgt-fp",
            commit_confirmed_at="2026-05-21T10:01:00Z", signature="sig-3",
        ),
    )
    cm_with_duplicate = ar.CommitMarker(
        cutover_id="cutover-test",
        committed_at="2026-05-21T10:01:30Z",
        source_prepare_marker_hash="p1" * 32,
        target_prepare_marker_hash="p2" * 32,
        cutover_lease_snapshot_content_sha256="a" * 64,
        fleet_membership_snapshot_content_sha256="b" * 64,
        required_host_ids_hash=ar.compute_required_host_ids_hash(("host-source", "host-target")),
        lease_acquired_at="2026-05-21T09:55:00Z",
        lease_expires_at="2026-05-21T11:55:00Z",
        cutover_approval_id="approval-1",
        cutover_approval_claim_hash="c" * 64,
        commit_approval_claim_hash="d" * 64,
        host_finalization_signatures=duplicate_sigs,
        commit_finalization_preimage_hash="e" * 64,
        signature="",
    )
    ok, reason = ar.verify_commit_marker_invariants(
        cm_with_duplicate, ("host-source", "host-target"),
        host_signer_public_key_resolver=ar.accept_unverified_commit_marker_signatures,
    )
    assert ok is False
    assert reason == "taskhub_cutover_lease_required_host_partial_confirmation"


def test_verify_commit_marker_rejects_unknown_signer() -> None:
    """Codex PR #84 R2 F-003 fix (P1、L660): host_signer_public_key_resolver が None を返したら reject."""
    cm = _make_commit_marker()  # 2 hosts、unsigned (signature="sig-host-source"/"sig-host-target" placeholder)

    def resolver_returns_none(_host_id: str, _signer_fp: str) -> bytes | None:
        return None  # unknown signer

    ok, reason = ar.verify_commit_marker_invariants(
        cm, ("host-source", "host-target"),
        host_signer_public_key_resolver=resolver_returns_none,
    )
    assert ok is False
    assert reason == "taskhub_cutover_commit_finalization_signature_invalid"


def test_verify_commit_marker_rejects_forged_signature() -> None:
    """resolver は valid pubkey 返すが signature が forged (base64 placeholder) なら verify fail."""
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    cm = _make_commit_marker()  # signatures は placeholder "sig-host-source" etc.

    def resolver_returns_valid_pub(_host_id: str, _signer_fp: str) -> bytes | None:
        return pub_bytes

    ok, reason = ar.verify_commit_marker_invariants(
        cm, ("host-source", "host-target"),
        host_signer_public_key_resolver=resolver_returns_valid_pub,
    )
    assert ok is False
    assert reason == "taskhub_cutover_commit_finalization_signature_invalid"


def test_verify_commit_marker_accepts_valid_signature() -> None:
    """positive control: resolver が valid pub key を返し、signature も valid なら verify pass."""
    import base64
    priv1 = Ed25519PrivateKey.generate()
    pub1_bytes = priv1.public_key().public_bytes_raw()
    priv2 = Ed25519PrivateKey.generate()
    pub2_bytes = priv2.public_key().public_bytes_raw()

    # Generate valid signatures over the canonical payload
    cm_proto = _make_commit_marker(
        host_confirmations=(
            ("host-source", "2026-05-21T10:00:30Z"),
            ("host-target", "2026-05-21T10:01:00Z"),
        ),
    )
    # _make_commit_marker now computes the correct preimage_hash from marker fields
    preimage_hash = cm_proto.commit_finalization_preimage_hash

    def make_signed_hfs(host_id: str, ts: str, priv_key: Ed25519PrivateKey) -> ar.HostFinalizationSignature:
        signer_fp = f"{host_id}-fp"
        sig_payload = ar._rfc8785_canonical_bytes({
            "commit_confirmed_at": ts,
            "commit_finalization_preimage_hash": preimage_hash,
            "host_id": host_id,
            "signer_fingerprint": signer_fp,
        })
        sig_bytes = priv_key.sign(sig_payload)
        return ar.HostFinalizationSignature(
            host_id=host_id,
            signer_fingerprint=signer_fp,
            commit_confirmed_at=ts,
            signature=base64.b64encode(sig_bytes).decode("ascii"),
        )

    hfs1 = make_signed_hfs("host-source", "2026-05-21T10:00:30Z", priv1)
    hfs2 = make_signed_hfs("host-target", "2026-05-21T10:01:00Z", priv2)

    cm = ar.CommitMarker(
        cutover_id=cm_proto.cutover_id,
        committed_at=cm_proto.committed_at,
        source_prepare_marker_hash=cm_proto.source_prepare_marker_hash,
        target_prepare_marker_hash=cm_proto.target_prepare_marker_hash,
        cutover_lease_snapshot_content_sha256=cm_proto.cutover_lease_snapshot_content_sha256,
        fleet_membership_snapshot_content_sha256=cm_proto.fleet_membership_snapshot_content_sha256,
        required_host_ids_hash=cm_proto.required_host_ids_hash,
        lease_acquired_at=cm_proto.lease_acquired_at,
        lease_expires_at=cm_proto.lease_expires_at,
        cutover_approval_id=cm_proto.cutover_approval_id,
        cutover_approval_claim_hash=cm_proto.cutover_approval_claim_hash,
        commit_approval_claim_hash=cm_proto.commit_approval_claim_hash,
        host_finalization_signatures=(hfs1, hfs2),
        commit_finalization_preimage_hash=preimage_hash,
        signature="",
    )

    pub_map = {"host-source": pub1_bytes, "host-target": pub2_bytes}

    def resolver(host_id: str, _signer_fp: str) -> bytes | None:
        return pub_map.get(host_id)

    ok, reason = ar.verify_commit_marker_invariants(
        cm, ("host-source", "host-target"),
        host_signer_public_key_resolver=resolver,
    )
    assert ok is True, f"unexpected reason: {reason}"


def test_verify_commit_marker_rejects_confirmed_at_before_lease_acquired() -> None:
    """§9.7 R6 F-001: confirm_at が lease window 外 (acquired より前) → outside_lease_window."""
    cm = _make_commit_marker(host_confirmations=(
        ("host-source", "2026-05-21T09:50:00Z"),  # before lease_acquired_at 09:55
        ("host-target", "2026-05-21T10:01:00Z"),
    ))
    ok, reason = ar.verify_commit_marker_invariants(
        cm,
        ("host-source", "host-target"),
        host_signer_public_key_resolver=ar.accept_unverified_commit_marker_signatures,
    )
    assert ok is False
    assert reason == "taskhub_cutover_commit_confirmed_at_outside_lease_window"


def test_verify_commit_marker_rejects_confirmed_at_after_lease_expires() -> None:
    """confirm_at が lease_expires_at より後 → outside_lease_window."""
    cm = _make_commit_marker(host_confirmations=(
        ("host-source", "2026-05-21T10:00:00Z"),
        ("host-target", "2026-05-21T12:00:00Z"),  # after lease_expires_at 11:55
    ))
    ok, reason = ar.verify_commit_marker_invariants(
        cm,
        ("host-source", "host-target"),
        host_signer_public_key_resolver=ar.accept_unverified_commit_marker_signatures,
    )
    assert ok is False
    assert reason == "taskhub_cutover_commit_confirmed_at_outside_lease_window"


def test_verify_commit_marker_rejects_committed_before_max_confirmed() -> None:
    """§9.9 R9 F-001 logic correction: committed_at < max(host_confirmed) → backdate_attack reject."""
    cm = _make_commit_marker(
        committed_at="2026-05-21T09:59:00Z",  # before max confirmed 10:01
        host_confirmations=(
            ("host-source", "2026-05-21T10:00:00Z"),
            ("host-target", "2026-05-21T10:01:00Z"),
        ),
    )
    ok, reason = ar.verify_commit_marker_invariants(
        cm,
        ("host-source", "host-target"),
        host_signer_public_key_resolver=ar.accept_unverified_commit_marker_signatures,
    )
    assert ok is False
    assert reason == "taskhub_cutover_committed_at_after_confirmation_window_rejected"


def test_verify_commit_marker_rejects_committed_at_after_lease_expires() -> None:
    """committed_at >= lease_expires_at → outside_lease_window."""
    cm = _make_commit_marker(
        committed_at="2026-05-21T12:00:00Z",  # after lease_expires_at 11:55
        host_confirmations=(
            ("host-source", "2026-05-21T10:00:00Z"),
            ("host-target", "2026-05-21T10:01:00Z"),
        ),
    )
    ok, reason = ar.verify_commit_marker_invariants(
        cm,
        ("host-source", "host-target"),
        host_signer_public_key_resolver=ar.accept_unverified_commit_marker_signatures,
    )
    assert ok is False
    assert reason == "taskhub_cutover_commit_confirmed_at_outside_lease_window"


def test_verify_commit_marker_rejects_committed_at_exceeds_skew_tolerance() -> None:
    """§9.9 R9 F-001 (c): committed_at - max(confirmed) > ε → backdate or excessive skew reject."""
    cm = _make_commit_marker(
        committed_at="2026-05-21T11:50:00Z",  # max confirmed 10:01、diff = 109min > 60s default ε
        host_confirmations=(
            ("host-source", "2026-05-21T10:00:00Z"),
            ("host-target", "2026-05-21T10:01:00Z"),
        ),
    )
    ok, reason = ar.verify_commit_marker_invariants(
        cm,
        ("host-source", "host-target"),
        host_signer_public_key_resolver=ar.accept_unverified_commit_marker_signatures,
    )
    assert ok is False
    assert reason == "taskhub_cutover_committed_at_after_confirmation_window_rejected"


def test_find_journal_tail_verifier_exception_fail_soft(tmp_path: Path) -> None:
    """Codex PR #82 R5 F-002 fix (P1): verifier が exception raise しても backward scan を継続
    (fail-soft skip)、allocation を block しない."""
    journal_path = tmp_path / "epoch.journal.signed.jsonl"
    valid_entry = {
        "domain": ar.DOMAIN_EPOCH_JOURNAL_V1,
        "epoch": 1,
        "issued_at": "2026-05-21T10:00:00.000000Z",
        "host_id": "host-1",
        "writer_signer_fingerprint": "fp-1",
        "previous_entry_hash": "0" * 64,
        "signature": "sig",
    }
    journal_path.write_bytes(
        json.dumps(valid_entry, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    )

    def raising_verifier(_entry: dict) -> bool:
        raise RuntimeError("verifier crashed on this entry")

    # verifier が raise → entry を skip + scan 継続。本 fixture は entry 1 個のみなので結果 None
    found = ar._find_valid_journal_tail_entry(
        journal_path=journal_path, tail_verifier=raising_verifier
    )
    assert found is None  # all entries failed (raised), backward scan exhausted
