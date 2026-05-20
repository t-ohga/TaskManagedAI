"""SP022-T02 Phase 1: signed approval Ed25519 verify module unit tests.

R1 18 + R2 5 + R3 1 = 24 plan-review findings 全件 adopt 反映後の verification。

Coverage:
- positive (5): valid signature / target_host match / non-destructive skip / RFC 8785 reference vector
- negative (19): path traversal, allowlist, ID mismatch, datetime format, expiration,
  signed_at future, max_ttl, reason_summary, allowed_subcommands, target_host,
  drill_kind mismatch, signature malformed / invalid, verify_key missing / fingerprint
  mismatch / allowlist missing / empty / permission, automation gates, default deny.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import taskhub_signed_approval as sa


def _utc_str(dt: datetime) -> str:
    """Format datetime as strict UTC `YYYY-MM-DDTHH:MM:SSZ`."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_keypair() -> tuple[Ed25519PrivateKey, bytes, str]:
    """Return (private_key, public_key_bytes (32), fingerprint hex)."""
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    fingerprint = sha256(pub_bytes).hexdigest()
    return priv, pub_bytes, fingerprint


def _write_approval_record(
    approval_dir: Path,
    *,
    priv: Ed25519PrivateKey,
    approval_id: str = "drill-2026-07-01-abc123de",
    decider: str = "t-ohga",
    reason_summary: str = "half-yearly-drill",
    signed_at: datetime | None = None,
    expires_at: datetime | None = None,
    drill_kind: str = "host_migration_mac_vps",
    allowed_subcommands: tuple[str, ...] = ("backup", "migrate", "restore"),
    target_host: str | None = "t-ohga-vps",
    sign_with_payload_override: bytes | None = None,
    signature_override: str | None = None,
    extra_fields: dict[str, Any] | None = None,
    omit_field: str | None = None,
) -> Path:
    """Write a signed approval record file. Returns the file path."""
    if signed_at is None:
        signed_at = datetime.now(UTC) - timedelta(hours=1)
    if expires_at is None:
        expires_at = datetime.now(UTC) + timedelta(hours=2)

    record_for_signing = sa.ApprovalRecord(
        approval_id=approval_id,
        decider=decider,
        reason_summary=reason_summary,
        signed_at_str=_utc_str(signed_at),
        expires_at_str=_utc_str(expires_at),
        drill_kind=drill_kind,
        allowed_subcommands=allowed_subcommands,
        target_host=target_host,
        signature_b64="A" * 88,  # placeholder, replaced below
    )
    payload = sign_with_payload_override or sa._rfc8785_canonical_payload_bytes(record_for_signing)
    signature_b64 = signature_override or base64.b64encode(priv.sign(payload)).decode("ascii")

    data: dict[str, Any] = {
        "approval_id": approval_id,
        "decider": decider,
        "reason_summary": reason_summary,
        "signed_at": _utc_str(signed_at),
        "expires_at": _utc_str(expires_at),
        "drill_kind": drill_kind,
        "allowed_subcommands": list(allowed_subcommands),
        "target_host": target_host,
        "signature": signature_b64,
    }
    if extra_fields:
        data.update(extra_fields)
    if omit_field:
        data.pop(omit_field, None)

    approval_dir.mkdir(parents=True, exist_ok=True)
    path = approval_dir / f"{approval_id}.signed"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _setup_isolated_taskhub(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, pub_bytes: bytes, fingerprint: str,
    write_allowlist: bool = True, allowlist_entries: list[str] | None = None,
) -> Path:
    """Set up an isolated ~/.taskhub via HOME redirect + monkeypatch allowlist path."""
    monkeypatch.setenv("HOME", str(tmp_path))
    keys_dir = tmp_path / ".taskhub" / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    pub_key_path = keys_dir / "approval-verify-key.pub"
    pub_key_path.write_bytes(pub_bytes)
    pub_key_path.chmod(0o600)

    allowlist_path = tmp_path / "allowlist.txt"
    if write_allowlist:
        entries = allowlist_entries if allowlist_entries is not None else [fingerprint]
        allowlist_path.write_text("\n".join(entries) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        sa, "_verify_key_fingerprint_allowlist_path", lambda: allowlist_path,
    )
    return tmp_path / ".taskhub" / "approvals"


# --- positive (5) ---


def test_verify_valid_signature_allows_subcommand(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    priv, pub_bytes, fingerprint = _make_keypair()
    approval_dir = _setup_isolated_taskhub(monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint=fingerprint)
    _write_approval_record(approval_dir, priv=priv)
    # R2-F-001 adopt: "restore" を使用 (backup は backup_claim 必須化されたため、generic positive
    # test には不適切。backup_claim 専用 test は別途追加)
    allowed, reason, extras = sa.verify_signed_approval(
        "drill-2026-07-01-abc123de", "restore",
    )
    assert allowed is True, (reason, extras)
    assert reason == "taskhub_signed_approval_verified"
    assert extras["verify_key_fingerprint"] == fingerprint


def test_verify_target_host_match_allows_migrate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    priv, pub_bytes, fingerprint = _make_keypair()
    approval_dir = _setup_isolated_taskhub(monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint=fingerprint)
    _write_approval_record(approval_dir, priv=priv, target_host="t-ohga-vps")
    allowed, reason, _ = sa.verify_signed_approval(
        "drill-2026-07-01-abc123de", "migrate", target_host="t-ohga-vps",
    )
    assert allowed is True
    assert reason == "taskhub_signed_approval_verified"


def test_detect_automation_returns_empty_in_interactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in sa.AUTOMATION_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    ctx = sa.detect_automation_context()
    assert ctx["env_hits"] == []


def test_require_approval_non_destructive_subcommand_always_allowed() -> None:
    allowed, reason, _ = sa.require_approval_for_destructive(
        "status", None, from_automation=False, allow_unsigned_manual_skeleton=False,
    )
    assert allowed is True
    assert reason == "taskhub_signed_approval_skipped_non_destructive"


def test_rfc8785_canonical_encoder_reference_vector_match() -> None:
    """R1-F-001 adopt: reference vector で deterministic encoder verify."""
    reference_record = sa.ApprovalRecord(
        approval_id="drill-2026-07-01-abc123de",
        decider="t-ohga",
        reason_summary="half-yearly-drill",
        signed_at_str="2026-06-30T15:00:00Z",
        expires_at_str="2026-07-02T15:00:00Z",
        drill_kind="host_migration_mac_vps",
        allowed_subcommands=("backup", "migrate", "restore"),
        target_host="t-ohga-vps",
        signature_b64="A" * 88,
    )
    expected = (
        b'{"allowed_subcommands":["backup","migrate","restore"],'
        b'"approval_id":"drill-2026-07-01-abc123de","decider":"t-ohga",'
        b'"drill_kind":"host_migration_mac_vps",'
        b'"expires_at":"2026-07-02T15:00:00Z","reason_summary":"half-yearly-drill",'
        b'"signed_at":"2026-06-30T15:00:00Z","target_host":"t-ohga-vps"}'
    )
    assert sa._rfc8785_canonical_payload_bytes(reference_record) == expected


# --- negative (19) ---


def test_verify_approval_id_path_traversal_denied(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    allowed, reason, _ = sa.verify_signed_approval("../etc/passwd", "restore")
    assert allowed is False
    assert reason == "taskhub_signed_approval_approval_id_malformed"


def test_verify_approval_id_allowlist_violation_denied(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    allowed, reason, _ = sa.verify_signed_approval("bad id with space", "restore")
    assert allowed is False
    assert reason == "taskhub_signed_approval_approval_id_malformed"


def test_verify_approval_id_too_long_denied(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    long_id = "a" * 129  # 129 > 128 char limit
    allowed, reason, _ = sa.verify_signed_approval(long_id, "backup")
    assert allowed is False
    assert reason == "taskhub_signed_approval_approval_id_malformed"


def test_verify_record_not_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    allowed, reason, _ = sa.verify_signed_approval("nonexistent-approval", "restore")
    assert allowed is False
    assert reason == "taskhub_signed_approval_record_not_found"


def test_verify_record_malformed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    approval_dir = tmp_path / ".taskhub" / "approvals"
    approval_dir.mkdir(parents=True)
    (approval_dir / "drill-foo.signed").write_text("not valid json {{{", encoding="utf-8")
    allowed, reason, _ = sa.verify_signed_approval("drill-foo", "restore")
    assert allowed is False
    assert reason == "taskhub_signed_approval_record_malformed"


def test_verify_record_id_mismatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    priv, pub_bytes, fingerprint = _make_keypair()
    approval_dir = _setup_isolated_taskhub(monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint=fingerprint)
    # Write record with approval_id="x" but caller asks for "y"
    _write_approval_record(approval_dir, priv=priv, approval_id="drill-record-name-x")
    # rename file to "drill-different-name-y"
    src = approval_dir / "drill-record-name-x.signed"
    dst = approval_dir / "drill-different-name-y.signed"
    src.rename(dst)
    allowed, reason, _ = sa.verify_signed_approval("drill-different-name-y", "restore")
    assert allowed is False
    assert reason == "taskhub_signed_approval_record_id_mismatch"


def test_verify_datetime_format_invalid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    priv, pub_bytes, fingerprint = _make_keypair()
    approval_dir = _setup_isolated_taskhub(monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint=fingerprint)
    # Write record with `+00:00` instead of `Z`
    _write_approval_record(
        approval_dir, priv=priv,
        extra_fields={"signed_at": "2026-06-30T15:00:00+00:00"},
    )
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "restore")
    assert allowed is False
    assert reason == "taskhub_signed_approval_datetime_format_invalid"


def test_verify_signed_at_future(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    priv, pub_bytes, fingerprint = _make_keypair()
    approval_dir = _setup_isolated_taskhub(monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint=fingerprint)
    future = datetime.now(UTC) + timedelta(hours=1)  # 1h future > 5min skew
    _write_approval_record(
        approval_dir, priv=priv,
        signed_at=future,
        expires_at=future + timedelta(hours=2),
    )
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "restore")
    assert allowed is False
    assert reason == "taskhub_signed_approval_signed_at_future"


def test_verify_expired(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    priv, pub_bytes, fingerprint = _make_keypair()
    approval_dir = _setup_isolated_taskhub(monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint=fingerprint)
    past = datetime.now(UTC) - timedelta(hours=2)
    _write_approval_record(
        approval_dir, priv=priv,
        signed_at=past - timedelta(hours=1),
        expires_at=past,  # expired
    )
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "restore")
    assert allowed is False
    assert reason == "taskhub_signed_approval_expired"


def test_verify_ttl_exceeded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    priv, pub_bytes, fingerprint = _make_keypair()
    approval_dir = _setup_isolated_taskhub(monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint=fingerprint)
    now = datetime.now(UTC)
    # signed_at very old, expires_at far future = ttl > 48h
    _write_approval_record(
        approval_dir, priv=priv,
        signed_at=now - timedelta(days=10),
        expires_at=now + timedelta(days=10),  # ttl = 20d
    )
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "restore")
    assert allowed is False
    assert reason == "taskhub_signed_approval_ttl_exceeded"


def test_verify_reason_summary_malformed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    priv, pub_bytes, fingerprint = _make_keypair()
    approval_dir = _setup_isolated_taskhub(monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint=fingerprint)
    _write_approval_record(
        approval_dir, priv=priv,
        reason_summary="has spaces and control\nchars",
    )
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "restore")
    assert allowed is False
    assert reason == "taskhub_signed_approval_reason_summary_malformed"


def test_verify_subcommand_not_allowed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    priv, pub_bytes, fingerprint = _make_keypair()
    approval_dir = _setup_isolated_taskhub(monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint=fingerprint)
    _write_approval_record(
        approval_dir, priv=priv,
        drill_kind="backup_only",
        allowed_subcommands=("backup",),
    )
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "migrate")
    assert allowed is False
    assert reason == "taskhub_signed_approval_subcommand_not_allowed"


def test_verify_target_host_mismatch_migrate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    priv, pub_bytes, fingerprint = _make_keypair()
    approval_dir = _setup_isolated_taskhub(monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint=fingerprint)
    _write_approval_record(approval_dir, priv=priv, target_host="t-ohga-vps")
    allowed, reason, _ = sa.verify_signed_approval(
        "drill-2026-07-01-abc123de", "migrate", target_host="t-ohga-linux",
    )
    assert allowed is False
    assert reason == "taskhub_signed_approval_target_host_mismatch"


def test_verify_target_host_null_record_denies_migrate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """R2-F-003 adopt: record.target_host が null/empty なら CLI --target に関わらず deny."""
    priv, pub_bytes, fingerprint = _make_keypair()
    approval_dir = _setup_isolated_taskhub(monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint=fingerprint)
    _write_approval_record(approval_dir, priv=priv, target_host=None)
    allowed, reason, _ = sa.verify_signed_approval(
        "drill-2026-07-01-abc123de", "migrate", target_host="anything",
    )
    assert allowed is False
    assert reason == "taskhub_signed_approval_target_host_mismatch"


def test_verify_drill_kind_subcommands_mismatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    priv, pub_bytes, fingerprint = _make_keypair()
    approval_dir = _setup_isolated_taskhub(monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint=fingerprint)
    # backup_only allows only "backup" but record claims "migrate" too
    _write_approval_record(
        approval_dir, priv=priv,
        drill_kind="backup_only",
        allowed_subcommands=("backup", "migrate"),
    )
    # query with "migrate" (in allowed_subcommands but not in drill_kind allowlist)
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "migrate")
    assert allowed is False
    assert reason == "taskhub_signed_approval_drill_kind_subcommands_mismatch"


def test_verify_signature_malformed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    priv, pub_bytes, fingerprint = _make_keypair()
    approval_dir = _setup_isolated_taskhub(monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint=fingerprint)
    _write_approval_record(
        approval_dir, priv=priv,
        signature_override="not-a-valid-base64-sig",  # wrong length
    )
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "restore")
    assert allowed is False
    assert reason == "taskhub_signed_approval_signature_malformed"


def test_verify_signature_invalid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    priv, pub_bytes, fingerprint = _make_keypair()
    approval_dir = _setup_isolated_taskhub(monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint=fingerprint)
    # Sign payload with different content but write original record
    forged_sig = base64.b64encode(priv.sign(b"different payload")).decode("ascii")
    _write_approval_record(
        approval_dir, priv=priv,
        signature_override=forged_sig,
    )
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "restore")
    assert allowed is False
    assert reason == "taskhub_signed_approval_signature_invalid"


def test_verify_key_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    # Set up allowlist but no verify key file
    allowlist_path = tmp_path / "allowlist.txt"
    allowlist_path.write_text("00" * 32 + "\n", encoding="utf-8")
    monkeypatch.setattr(sa, "_verify_key_fingerprint_allowlist_path", lambda: allowlist_path)
    priv, _, _ = _make_keypair()
    approval_dir = tmp_path / ".taskhub" / "approvals"
    _write_approval_record(approval_dir, priv=priv)
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "restore")
    assert allowed is False
    assert reason == "taskhub_signed_approval_verify_key_missing"


def test_verify_key_fingerprint_mismatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    priv, pub_bytes, _fingerprint = _make_keypair()
    # write allowlist with a DIFFERENT fingerprint
    _setup_isolated_taskhub(
        monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint="dummy",
        allowlist_entries=["a" * 64],  # 64 hex char different fingerprint
    )
    approval_dir = tmp_path / ".taskhub" / "approvals"
    _write_approval_record(approval_dir, priv=priv)
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "restore")
    assert allowed is False
    assert reason == "taskhub_signed_approval_verify_key_fingerprint_mismatch"


def test_verify_key_fingerprint_allowlist_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """R3-F-001 adopt: allowlist file 不在 → hard fail."""
    priv, pub_bytes, fingerprint = _make_keypair()
    _setup_isolated_taskhub(
        monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint=fingerprint,
        write_allowlist=False,
    )
    # Override allowlist path to point to non-existent location
    monkeypatch.setattr(
        sa, "_verify_key_fingerprint_allowlist_path",
        lambda: tmp_path / "absent-allowlist.txt",
    )
    approval_dir = tmp_path / ".taskhub" / "approvals"
    _write_approval_record(approval_dir, priv=priv)
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "restore")
    assert allowed is False
    assert reason == "taskhub_signed_approval_verify_key_fingerprint_allowlist_missing"


def test_verify_key_fingerprint_allowlist_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """R3-F-001 adopt: allowlist file 空/comment-only → hard fail."""
    priv, pub_bytes, fingerprint = _make_keypair()
    _setup_isolated_taskhub(
        monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint=fingerprint,
        allowlist_entries=["# only a comment", ""],
    )
    approval_dir = tmp_path / ".taskhub" / "approvals"
    _write_approval_record(approval_dir, priv=priv)
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "restore")
    assert allowed is False
    assert reason == "taskhub_signed_approval_verify_key_fingerprint_allowlist_empty"


def test_verify_key_permission_unsafe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """R1-F-009 adopt: world-writable verify key → deny."""
    priv, pub_bytes, fingerprint = _make_keypair()
    approval_dir = _setup_isolated_taskhub(monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint=fingerprint)
    _write_approval_record(approval_dir, priv=priv)
    # Make verify key world-writable
    verify_key_path = tmp_path / ".taskhub" / "keys" / "approval-verify-key.pub"
    verify_key_path.chmod(0o666)  # group + others writable
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "restore")
    assert allowed is False
    assert reason == "taskhub_signed_approval_verify_key_permission_unsafe"


def test_automation_detected_without_flag_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    """R1-F-002 + R1-F-003 adopt."""
    monkeypatch.setenv("SYSTEMD_INVOCATION_ID", "fake-id")
    allowed, reason, _ = sa.require_approval_for_destructive(
        "restore", None, from_automation=False, allow_unsigned_manual_skeleton=False,
    )
    assert allowed is False
    assert reason == "taskhub_signed_approval_automation_detected_without_flag"


def test_from_automation_without_approval_id_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    """R1-F-002 adopt."""
    monkeypatch.setenv("CRON_INVOCATION", "fake")
    allowed, reason, _ = sa.require_approval_for_destructive(
        "restore", None, from_automation=True, allow_unsigned_manual_skeleton=False,
    )
    assert allowed is False
    assert reason == "taskhub_signed_approval_from_automation_requires_approval_id"


def test_destructive_manual_without_approval_denies_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """R1-F-002 adopt: manual exec も destructive subcommand では default deny."""
    for var in sa.AUTOMATION_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    allowed, reason, _ = sa.require_approval_for_destructive(
        "restore", None, from_automation=False, allow_unsigned_manual_skeleton=False,
    )
    assert allowed is False
    assert reason == "taskhub_signed_approval_destructive_requires_approval"


def test_destructive_manual_with_allow_unsigned_skeleton_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """R1-F-002 adopt: --allow-unsigned-manual-skeleton で escape (skeleton mode)."""
    for var in sa.AUTOMATION_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    allowed, reason, extras = sa.require_approval_for_destructive(
        "restore", None, from_automation=False, allow_unsigned_manual_skeleton=True,
    )
    assert allowed is True
    assert reason == "taskhub_signed_approval_unsigned_manual_skeleton_allowed"
    assert extras.get("unsigned_manual_skeleton_used") is True
