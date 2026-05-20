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
    # SP022-T02 Phase 3 adopt: "migrate" を使用 (backup/restore は claim 必須化されたため、
    # generic positive test には不適切。claim 専用 test は別途追加)
    allowed, reason, extras = sa.verify_signed_approval(
        "drill-2026-07-01-abc123de", "migrate",
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


# --- SP022-T02 Phase 4 / R1 F-001 + R2 F-002 + ADV R1 F-010 adopt: restore_rollback_claim tests ---


def _make_restore_rollback_claim(**overrides: object) -> sa.RestoreRollbackApprovalClaim:
    defaults: dict[str, object] = {
        "pre_restore_ts": "20260520T100000",
        "pre_restore_dir": "/var/lib/taskhub/data/_pre-restore-20260520T100000",
        "snapshot_manifest_sha256": "a" * 64,
        "target_pg_dsn_components": {
            "host": "127.0.0.1", "port": "5432",
            "db": "taskmanagedai", "user": "taskmanagedai",
        },
        "target_redis_endpoint": "127.0.0.1:6379",
        "target_artifacts_dir": "/var/lib/taskhub/data/artifacts",
        "target_artifacts_container_path": "/app/data/artifacts",
        "target_compose_project_name": "taskmanagedai",
        "target_compose_file_path": "/home/op/taskhub/docker-compose.yml",
        "expected_postgres_major_version": "16",
    }
    defaults.update(overrides)
    return sa.RestoreRollbackApprovalClaim(**defaults)  # type: ignore[arg-type]


def test_signed_approval_verify_restore_rollback_phase1_record_denied(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Phase 1 record (rrc 不在) は restore-rollback で deny。"""
    priv, pub_bytes, fingerprint = _make_keypair()
    approval_dir = _setup_isolated_taskhub(monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint=fingerprint)
    _write_approval_record(
        approval_dir, priv=priv,
        allowed_subcommands=("restore-rollback",),
        drill_kind="restore_only",
    )
    rrc = _make_restore_rollback_claim()
    allowed, reason, _ = sa.verify_signed_approval(
        "drill-2026-07-01-abc123de", "restore-rollback",
        restore_rollback_claim=rrc,
    )
    assert allowed is False
    assert reason == "taskhub_signed_approval_restore_rollback_claim_required"


def test_require_approval_for_destructive_restore_rollback_allow_unsigned_rejected() -> None:
    """R1 F-002 adopt: restore-rollback + allow_unsigned_manual_skeleton 物理 deny."""
    allowed, reason, _ = sa.require_approval_for_destructive(
        "restore-rollback", None, from_automation=False,
        allow_unsigned_manual_skeleton=True,
    )
    assert allowed is False
    assert reason == "taskhub_signed_approval_restore_rollback_allow_unsigned_skeleton_rejected"


def test_parse_restore_rollback_claim_strict_type_validate() -> None:
    """ADV R1 F-010 adopt: per-field type/format validate."""
    # valid baseline
    valid_dict = {
        "pre_restore_ts": "20260520T100000",
        "pre_restore_dir": "/abs/path",
        "snapshot_manifest_sha256": "f" * 64,
        "target_pg_dsn_components": {"host": "h", "port": "5432", "db": "d", "user": "u"},
        "target_redis_endpoint": "h:6379",
        "target_artifacts_dir": "/abs/art",
        "target_artifacts_container_path": "/abs/cont",
        "target_compose_project_name": "p",
        "target_compose_file_path": "/abs/compose.yml",
        "expected_postgres_major_version": "16",
    }
    assert sa._parse_restore_rollback_claim_dict(valid_dict) is not None

    # invalid sha256 (not hex)
    bad = dict(valid_dict, snapshot_manifest_sha256="z" * 64)
    assert sa._parse_restore_rollback_claim_dict(bad) is None

    # invalid postgres major (with semver / leading zero / space)
    for bad_pg in ("16.0", " 16", "016", "0", ""):
        bad = dict(valid_dict, expected_postgres_major_version=bad_pg)
        assert sa._parse_restore_rollback_claim_dict(bad) is None

    # ts format invalid
    for bad_ts in ("foo", "2026-05-20T10:00:00Z", "20260520"):
        bad = dict(valid_dict, pre_restore_ts=bad_ts)
        assert sa._parse_restore_rollback_claim_dict(bad) is None

    # non-absolute path
    bad = dict(valid_dict, pre_restore_dir="rel/path")
    assert sa._parse_restore_rollback_claim_dict(bad) is None

    # dsn missing key
    bad = dict(valid_dict, target_pg_dsn_components={"host": "h", "port": "5432", "db": "d"})
    assert sa._parse_restore_rollback_claim_dict(bad) is None

    # dsn port non-digit
    bad = dict(valid_dict, target_pg_dsn_components={"host": "h", "port": "abc", "db": "d", "user": "u"})
    assert sa._parse_restore_rollback_claim_dict(bad) is None

    # extra key
    bad = dict(valid_dict, extra_field="x")
    assert sa._parse_restore_rollback_claim_dict(bad) is None


def test_canonical_for_signature_remote_hosts_domain_layout() -> None:
    """ADV R2 F-002 adopt: shared canonicalizer domain layout."""
    payload = {"hosts": {"a": 1}, "signed_at": "2026-05-20T00:00:00Z"}
    canonical = sa.canonical_for_signature("remote_hosts.v1", payload)
    # jcs canonical of {"domain": "remote_hosts.v1", "payload": payload}
    import json as _json
    expected_obj = {"domain": "remote_hosts.v1", "payload": payload}
    expected = _json.dumps(expected_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert canonical == expected


def test_signed_approval_verify_phase1_record_no_rrc_backward_compat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """ADV R2 F-002 adopt: PR #75/77/78 record (rrc 不在) は backward compat で verify pass."""
    priv, pub_bytes, fingerprint = _make_keypair()
    approval_dir = _setup_isolated_taskhub(monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint=fingerprint)
    _write_approval_record(approval_dir, priv=priv)
    # migrate subcommand は rrc 不要、既存 Phase 1 record の layout で verify OK
    allowed, reason, _ = sa.verify_signed_approval(
        "drill-2026-07-01-abc123de", "migrate",
    )
    assert allowed is True, (reason,)


# --- negative (19) ---


def test_verify_approval_id_path_traversal_denied(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    allowed, reason, _ = sa.verify_signed_approval("../etc/passwd", "migrate")
    assert allowed is False
    assert reason == "taskhub_signed_approval_approval_id_malformed"


def test_verify_approval_id_allowlist_violation_denied(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    allowed, reason, _ = sa.verify_signed_approval("bad id with space", "migrate")
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
    allowed, reason, _ = sa.verify_signed_approval("nonexistent-approval", "migrate")
    assert allowed is False
    assert reason == "taskhub_signed_approval_record_not_found"


def test_verify_record_malformed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    approval_dir = tmp_path / ".taskhub" / "approvals"
    approval_dir.mkdir(parents=True)
    (approval_dir / "drill-foo.signed").write_text("not valid json {{{", encoding="utf-8")
    allowed, reason, _ = sa.verify_signed_approval("drill-foo", "migrate")
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
    allowed, reason, _ = sa.verify_signed_approval("drill-different-name-y", "migrate")
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
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "migrate")
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
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "migrate")
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
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "migrate")
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
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "migrate")
    assert allowed is False
    assert reason == "taskhub_signed_approval_ttl_exceeded"


def test_verify_reason_summary_malformed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    priv, pub_bytes, fingerprint = _make_keypair()
    approval_dir = _setup_isolated_taskhub(monkeypatch, tmp_path, pub_bytes=pub_bytes, fingerprint=fingerprint)
    _write_approval_record(
        approval_dir, priv=priv,
        reason_summary="has spaces and control\nchars",
    )
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "migrate")
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
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "migrate")
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
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "migrate")
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
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "migrate")
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
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "migrate")
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
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "migrate")
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
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "migrate")
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
    allowed, reason, _ = sa.verify_signed_approval("drill-2026-07-01-abc123de", "migrate")
    assert allowed is False
    assert reason == "taskhub_signed_approval_verify_key_permission_unsafe"


def test_automation_detected_without_flag_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    """R1-F-002 + R1-F-003 adopt."""
    monkeypatch.setenv("SYSTEMD_INVOCATION_ID", "fake-id")
    allowed, reason, _ = sa.require_approval_for_destructive(
        "migrate", None, from_automation=False, allow_unsigned_manual_skeleton=False,
    )
    assert allowed is False
    assert reason == "taskhub_signed_approval_automation_detected_without_flag"


def test_from_automation_without_approval_id_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    """R1-F-002 adopt."""
    monkeypatch.setenv("CRON_INVOCATION", "fake")
    allowed, reason, _ = sa.require_approval_for_destructive(
        "migrate", None, from_automation=True, allow_unsigned_manual_skeleton=False,
    )
    assert allowed is False
    assert reason == "taskhub_signed_approval_from_automation_requires_approval_id"


def test_destructive_manual_without_approval_denies_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """R1-F-002 adopt: manual exec も destructive subcommand では default deny."""
    for var in sa.AUTOMATION_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    allowed, reason, _ = sa.require_approval_for_destructive(
        "migrate", None, from_automation=False, allow_unsigned_manual_skeleton=False,
    )
    assert allowed is False
    assert reason == "taskhub_signed_approval_destructive_requires_approval"


def test_destructive_manual_with_allow_unsigned_skeleton_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """R1-F-002 adopt: --allow-unsigned-manual-skeleton で escape (skeleton mode)."""
    for var in sa.AUTOMATION_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    allowed, reason, extras = sa.require_approval_for_destructive(
        "migrate", None, from_automation=False, allow_unsigned_manual_skeleton=True,
    )
    assert allowed is True
    assert reason == "taskhub_signed_approval_unsigned_manual_skeleton_allowed"
    assert extras.get("unsigned_manual_skeleton_used") is True
