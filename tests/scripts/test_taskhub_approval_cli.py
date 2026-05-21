"""SP022-T08 batch 4: taskhub_approval_cli.py tests.

Coverage:
- issue_approval_record success path
- signing key validation (missing/permission/symlink/dir_permission/invalid_format)
- approval_id / reason_summary regex
- drill_kind / subcommand 整合
- claim required when subcommand in allowed
- TTL boundary (24h default, 48h max)
- atomic O_CREAT|O_EXCL|O_NOFOLLOW, --force 廃止
- chmod 0o600
- end-to-end issue→verify (signature_valid)
"""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts import taskhub_signed_approval as sa
from scripts.taskhub_approval_cli import (
    ApprovalIssueOptions,
    issue_approval_record,
)

# --- helpers ---


def _make_signing_key() -> tuple[bytes, bytes, str]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    priv = Ed25519PrivateKey.generate()
    seed = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    import hashlib as _h
    return seed, pub_bytes, _h.sha256(pub_bytes).hexdigest()


def _setup_taskhub_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> tuple[Path, Path, bytes, str]:
    """isolated ~/.taskhub setup. Returns (signing_key_path, approvals_dir, pub_bytes, fingerprint)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    taskhub_home = tmp_path / ".taskhub"
    keys_dir = taskhub_home / "keys"
    keys_dir.mkdir(parents=True, mode=0o700)
    seed, pub_bytes, fingerprint = _make_signing_key()
    signing_key_path = keys_dir / "approval-signing-key"
    signing_key_path.write_bytes(seed)
    signing_key_path.chmod(0o600)
    pub_path = keys_dir / "approval-verify-key.pub"
    pub_path.write_bytes(pub_bytes)
    pub_path.chmod(0o600)
    allowlist_path = tmp_path / "allowlist.txt"
    allowlist_path.write_text(f"{fingerprint}\n", encoding="utf-8")
    monkeypatch.setattr(sa, "_verify_key_fingerprint_allowlist_path", lambda: allowlist_path)
    approvals_dir = taskhub_home / "approvals"
    return signing_key_path, approvals_dir, pub_bytes, fingerprint


def _make_default_options(
    signing_key_path: Path, approvals_dir: Path,
    approval_id: str = "drill-2026-07-01-abc12345",
    allowed_subcommands: tuple[str, ...] = ("migrate",),
    drill_kind: str = "host_migration_mac_vps",
    reason_summary: str = "half-yearly-drill",
    target_host: str | None = "t-ohga-vps",
    ttl_hours: int = 24,
    **claim_overrides: object,
) -> ApprovalIssueOptions:
    signed_at = datetime.now(UTC) - timedelta(minutes=1)
    expires_at = signed_at + timedelta(hours=ttl_hours)
    return ApprovalIssueOptions(
        approval_id=approval_id,
        decider="t-ohga",
        reason_summary=reason_summary,
        signed_at=signed_at,
        expires_at=expires_at,
        drill_kind=drill_kind,
        allowed_subcommands=allowed_subcommands,
        target_host=target_host,
        signing_key_path=signing_key_path,
        output_dir=approvals_dir,
        backup_claim=claim_overrides.get("backup_claim"),  # type: ignore[arg-type]
        restore_claim=claim_overrides.get("restore_claim"),  # type: ignore[arg-type]
        restore_rollback_claim=claim_overrides.get("restore_rollback_claim"),  # type: ignore[arg-type]
    )


# --- positive ---


def test_issue_success_writes_signed_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    signing_key_path, approvals_dir, _, _ = _setup_taskhub_keys(monkeypatch, tmp_path)
    opts = _make_default_options(signing_key_path, approvals_dir)
    success, reason, path = issue_approval_record(opts)
    assert success is True, (reason,)
    assert reason == "approval_issue_ok"
    assert path is not None
    assert path.is_file()
    # mode 0o600 (ADV R1 F-004)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    # parse + verify signature via existing module
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["approval_id"] == "drill-2026-07-01-abc12345"
    assert data["drill_kind"] == "host_migration_mac_vps"


def test_issue_end_to_end_verify_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """issue した record を verify_signed_approval が allow にする (canonical payload binding)."""
    signing_key_path, approvals_dir, _, _ = _setup_taskhub_keys(monkeypatch, tmp_path)
    opts = _make_default_options(
        signing_key_path, approvals_dir,
        allowed_subcommands=("migrate",),
    )
    success, _, _ = issue_approval_record(opts)
    assert success is True
    allowed, reason, _ = sa.verify_signed_approval(
        "drill-2026-07-01-abc12345", "migrate", target_host="t-ohga-vps",
    )
    assert allowed is True, (reason,)
    assert reason == "taskhub_signed_approval_verified"


# --- negative ---


def test_issue_signing_key_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    bogus_path = tmp_path / "nonexistent_key"
    opts = _make_default_options(bogus_path, tmp_path / "approvals")
    success, reason, _ = issue_approval_record(opts)
    assert success is False
    assert reason == "approval_issue_signing_key_missing"


def test_issue_signing_key_world_readable_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """ADV R1 F-004 adopt: signing key chmod 0o644 で reason=signing_key_permission."""
    signing_key_path, approvals_dir, _, _ = _setup_taskhub_keys(monkeypatch, tmp_path)
    signing_key_path.chmod(0o644)
    opts = _make_default_options(signing_key_path, approvals_dir)
    success, reason, _ = issue_approval_record(opts)
    assert success is False
    assert reason == "approval_issue_signing_key_permission"


def test_issue_signing_key_symlink_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """ADV R1 F-005 adopt: symlink で signing_key_symlink reason_code."""
    signing_key_path, approvals_dir, _, _ = _setup_taskhub_keys(monkeypatch, tmp_path)
    # replace key with symlink
    target = tmp_path / "actual_seed"
    target.write_bytes(b"a" * 32)
    target.chmod(0o600)
    signing_key_path.unlink()
    os.symlink(str(target), str(signing_key_path))
    opts = _make_default_options(signing_key_path, approvals_dir)
    success, reason, _ = issue_approval_record(opts)
    assert success is False
    assert reason == "approval_issue_signing_key_symlink"


def test_issue_signing_key_dir_world_readable_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    signing_key_path, approvals_dir, _, _ = _setup_taskhub_keys(monkeypatch, tmp_path)
    signing_key_path.parent.chmod(0o755)
    opts = _make_default_options(signing_key_path, approvals_dir)
    success, reason, _ = issue_approval_record(opts)
    assert success is False
    assert reason == "approval_issue_signing_key_dir_permission"


def test_issue_signing_key_invalid_format_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """R1 F-008 adopt: 32 bytes 以外 (PEM/DER) で reason=invalid_format."""
    signing_key_path, approvals_dir, _, _ = _setup_taskhub_keys(monkeypatch, tmp_path)
    # overwrite with 64-byte content (not 32)
    signing_key_path.write_bytes(b"a" * 64)
    signing_key_path.chmod(0o600)
    opts = _make_default_options(signing_key_path, approvals_dir)
    success, reason, _ = issue_approval_record(opts)
    assert success is False
    assert reason == "approval_issue_signing_key_invalid_format"


def test_issue_approval_id_malformed_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    signing_key_path, approvals_dir, _, _ = _setup_taskhub_keys(monkeypatch, tmp_path)
    opts = _make_default_options(
        signing_key_path, approvals_dir, approval_id="bad id with spaces",
    )
    success, reason, _ = issue_approval_record(opts)
    assert success is False
    assert reason == "approval_issue_approval_id_malformed"


def test_issue_reason_summary_malformed_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """ADV R1 F-017 adopt: REASON_SUMMARY_REGEX 違反 (空白) で reason_summary_malformed."""
    signing_key_path, approvals_dir, _, _ = _setup_taskhub_keys(monkeypatch, tmp_path)
    opts = _make_default_options(
        signing_key_path, approvals_dir,
        reason_summary="contains spaces and >",
    )
    success, reason, _ = issue_approval_record(opts)
    assert success is False
    assert reason == "approval_issue_reason_summary_malformed"


def test_issue_drill_kind_subcommand_mismatch_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """drill_kind=age_rotate + allowed_subcommands=[migrate] で mismatch."""
    signing_key_path, approvals_dir, _, _ = _setup_taskhub_keys(monkeypatch, tmp_path)
    opts = _make_default_options(
        signing_key_path, approvals_dir,
        drill_kind="age_rotate",
        allowed_subcommands=("migrate",),
    )
    success, reason, _ = issue_approval_record(opts)
    assert success is False
    assert reason == "approval_issue_drill_kind_subcommand_mismatch"


def test_issue_backup_claim_required_when_backup_in_subcommands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """allowed_subcommands=[backup] で backup_claim 未指定 → backup_claim_required."""
    signing_key_path, approvals_dir, _, _ = _setup_taskhub_keys(monkeypatch, tmp_path)
    opts = _make_default_options(
        signing_key_path, approvals_dir,
        allowed_subcommands=("backup",),
        # backup_claim=None (default)
    )
    success, reason, _ = issue_approval_record(opts)
    assert success is False
    assert reason == "approval_issue_backup_claim_required"


def test_issue_restore_rollback_claim_required(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """R1 F-001 adopt: restore-rollback in subcommands で rrc 未指定 → required."""
    signing_key_path, approvals_dir, _, _ = _setup_taskhub_keys(monkeypatch, tmp_path)
    opts = _make_default_options(
        signing_key_path, approvals_dir,
        drill_kind="restore_only",
        allowed_subcommands=("restore-rollback",),
    )
    success, reason, _ = issue_approval_record(opts)
    assert success is False
    assert reason == "approval_issue_restore_rollback_claim_required"


def test_issue_signed_at_after_expires_at_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    signing_key_path, approvals_dir, _, _ = _setup_taskhub_keys(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    opts = ApprovalIssueOptions(
        approval_id="drill-2026-07-01-abc12345",
        decider="t-ohga",
        reason_summary="half-yearly-drill",
        signed_at=now + timedelta(hours=2),
        expires_at=now + timedelta(hours=1),  # expires_at < signed_at
        drill_kind="host_migration_mac_vps",
        allowed_subcommands=("migrate",),
        target_host="t-ohga-vps",
        signing_key_path=signing_key_path,
        output_dir=approvals_dir,
    )
    success, reason, _ = issue_approval_record(opts)
    assert success is False
    assert reason == "approval_issue_signed_at_expires_inversion"


def test_issue_ttl_max_48h_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """R1 F-009 adopt: TTL = DEFAULT_MAX_TTL (48h) は境界 OK."""
    signing_key_path, approvals_dir, _, _ = _setup_taskhub_keys(monkeypatch, tmp_path)
    opts = _make_default_options(signing_key_path, approvals_dir, ttl_hours=48)
    success, reason, _ = issue_approval_record(opts)
    assert success is True, (reason,)


def test_issue_ttl_exceeds_48h_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """R1 F-009 adopt: TTL = 49h で ttl_exceeded."""
    signing_key_path, approvals_dir, _, _ = _setup_taskhub_keys(monkeypatch, tmp_path)
    opts = _make_default_options(signing_key_path, approvals_dir, ttl_hours=49)
    success, reason, _ = issue_approval_record(opts)
    assert success is False
    assert reason == "approval_issue_ttl_exceeded"


def test_issue_approval_id_collision_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """ADV R2 F-001 adopt: 既存 file ありで O_EXCL 衝突 → collision (--force 廃止)."""
    signing_key_path, approvals_dir, _, _ = _setup_taskhub_keys(monkeypatch, tmp_path)
    opts = _make_default_options(signing_key_path, approvals_dir)
    success1, _, _ = issue_approval_record(opts)
    assert success1 is True
    # 2回目は collision
    opts2 = _make_default_options(signing_key_path, approvals_dir)
    success2, reason2, _ = issue_approval_record(opts2)
    assert success2 is False
    assert reason2 == "approval_issue_output_path_collision"


def test_issue_migrate_without_target_host_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """ADV PR F-5 adopt: migrate in allowed_subcommands で target_host 未指定 → required."""
    signing_key_path, approvals_dir, _, _ = _setup_taskhub_keys(monkeypatch, tmp_path)
    opts = _make_default_options(
        signing_key_path, approvals_dir,
        allowed_subcommands=("migrate",),
        target_host=None,
    )
    success, reason, _ = issue_approval_record(opts)
    assert success is False
    assert reason == "approval_issue_target_host_required"


def test_issue_atomic_no_force_flag_argparse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """ADV R2 F-001 adopt: --force flag が argparse choices に存在しない (廃止)."""
    import argparse

    from scripts.taskhub_approval_cli import register_subparser
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="subcommand", required=False)
    register_subparser(subparsers)
    # --force 不在 → argparse error (catch)
    with pytest.raises(SystemExit):
        parser.parse_args([
            "approval", "issue", "--force",
            "--approval-id", "drill-2026-07-01-abc12345",
            "--decider", "t-ohga", "--reason-summary", "test",
            "--drill-kind", "host_migration_mac_vps",
            "--allowed-subcommands", "migrate",
        ])
