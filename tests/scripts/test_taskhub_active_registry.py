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


def test_ecmascript_float_repr_strips_leading_zero_exponent() -> None:
    """Codex PR #82 R4 F-001 fix (P1): exponent leading zero を strip ("1e-07" → "1e-7")."""
    # repr(1.5e-7) → "1.5e-07" in Python, ECMAScript → "1.5e-7"
    encoded = ar._ecmascript_float_repr(1.5e-7)
    assert encoded == "1.5e-07".replace("e-07", "e-7")
    assert "e-7" in encoded
    assert "e-07" not in encoded
    # 3-digit exponent unchanged
    encoded3 = ar._ecmascript_float_repr(1.5e-100)
    assert "e-100" in encoded3


def test_ecmascript_float_repr_handles_integer_valued_above_1e21() -> None:
    """integer-valued float >= 1e21 は scientific notation を使う (ECMAScript ToString rule)."""
    # 1e21 は repr(1e21) → "1e+21" (Python はこの境界で scientific)
    encoded = ar._encode_number(1e21)
    assert encoded == "1e+21"  # exponent +21 (3 digit ではない、no strip needed)


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
