"""Signed approval Ed25519 verification module (SP022-T02 Phase 1).

ADR-00021 §3-§7 / T03 SOP §7 (planned contract for T02) で明文化された
`taskhub` admin CLI の security boundary を実装。

Provides:
- ApprovalRecord schema (strict、allowlist 方式)
- detect_automation_context(): env matrix + TTY absence
- verify_signed_approval(approval_id, subcommand, target_host=None):
  RFC 8785 strict JCS canonical JSON + Ed25519 signature verify +
  expiration + max_ttl + clock_skew + allowed_subcommands +
  target_host + drill_kind ↔ subcommands 整合 + verify key fingerprint
- require_approval_for_destructive(subcommand, approval_id, from_automation,
  allow_unsigned_manual_skeleton, target_host):
  pre-execution gate (default deny、R1-F-002 adopt)
- emit_audit_event(reason_code, extras): stderr redacted audit-line scaffold
  (allowlist 方式、R1-F-010 adopt)

Security invariants (R3-F-001 adopt):
- env-based trust root override は production code から削除 (TASKHUB_HOME 等は無し)
- pytest fixture は `monkeypatch.setenv("HOME", str(tmp_path))` で HOME 全体 redirect
  + `monkeypatch.setattr` で repo-internal allowlist path を override
- fingerprint allowlist は hard fail invariant (file 不在 / 空 / comment-only も deny)
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# --- path accessors (R3-F-001 adopt: env override 削除、HOME 経由のみ) ---


def _taskhub_home() -> Path:
    """`Path.home() / .taskhub`。

    `Path.home()` は HOME env を respect (OS-standard user isolation)。
    pytest fixture は `monkeypatch.setenv("HOME", str(tmp_path))` で redirect。
    F-PR75-006 adopt: `Path.home()` の RuntimeError (resolvable home なし、container/service UID 等) を
    fail-closed sentinel path に変換、呼出側で existence check が deny 経路へ進む。
    """
    try:
        return Path.home() / ".taskhub"
    except RuntimeError:
        # Sentinel non-existent path; downstream existence checks fail → structured deny
        return Path("/__taskhub_home_unresolved__") / ".taskhub"


def _approval_dir() -> Path:
    return _taskhub_home() / "approvals"


def _verify_key_path() -> Path:
    return _taskhub_home() / "keys" / "approval-verify-key.pub"


def _verify_key_fingerprint_allowlist_path() -> Path:
    """repo-internal 固定 path (test は monkeypatch.setattr で override)."""
    return Path(__file__).resolve().parent.parent / ".taskhub" / "approval-verify-key-fingerprints.allowlist"


# --- constants ---

APPROVAL_ID_REGEX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REASON_SUMMARY_REGEX = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DATETIME_STRICT_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
BASE64_SIG_LEN = 88  # 64 bytes Ed25519 sig encoded as base64 with padding

DEFAULT_CLOCK_SKEW = timedelta(minutes=5)
DEFAULT_MAX_TTL = timedelta(hours=48)

AUTOMATION_ENV_VARS = (
    "SYSTEMD_INVOCATION_ID",
    "INVOCATION_ID",
    "JOURNAL_STREAM",
    "CRON_INVOCATION",
    "GITHUB_ACTIONS",
    "CI",
    "BUILD_ID",
    "BUILD_NUMBER",
    "RUN_ID",
    "KUBERNETES_SERVICE_HOST",
    "container",
    "BASH_EXECUTION_STRING",
)

DESTRUCTIVE_SUBCOMMANDS = frozenset(
    {"backup", "restore", "migrate", "freeze", "thaw", "age-rotate"},
)

DRILL_KIND_ALLOWED_SUBCOMMANDS: dict[str, frozenset[str]] = {
    "host_migration_mac_vps": frozenset({"backup", "migrate", "restore"}),
    "host_migration_linux_vps": frozenset({"backup", "migrate", "restore"}),
    "host_migration_vps_vps": frozenset({"backup", "migrate", "restore"}),
    "backup_only": frozenset({"backup"}),
    "restore_only": frozenset({"restore"}),
    "age_rotate": frozenset({"age-rotate"}),
    "freeze_only": frozenset({"freeze"}),
    "thaw_only": frozenset({"thaw"}),
}

# SP022-T02 Phase 2 / T08 batch 2: backup_claim (R2-F-001 adopt)
@dataclass(frozen=True)
class BackupApprovalClaim:
    """Backup-specific approval claim (SP022-T02 Phase 2 / T08 batch 2).

    R2-F-001 adopt: backup subcommand では output_path / include_sops_env /
    skip_service_stop / overwrite / age_public_key_fingerprint 全て approval payload に
    含め、CLI 引数との完全一致を verify。Phase 1 既存 record (backup_claim 不在) は
    backup では deny、他 subcommand では従来通り verify。
    """

    output_path: str  # absolute path string, normpath
    include_sops_env: bool
    skip_service_stop: bool
    overwrite: bool
    age_public_key_fingerprint: str  # SHA-256 hex of age public key bytes


ReasonCode = Literal[
    "taskhub_signed_approval_verified",
    "taskhub_signed_approval_skipped_non_destructive",
    "taskhub_signed_approval_unsigned_manual_skeleton_allowed",
    "taskhub_signed_approval_destructive_requires_approval",
    "taskhub_signed_approval_automation_detected_without_flag",
    "taskhub_signed_approval_from_automation_requires_approval_id",
    "taskhub_signed_approval_approval_id_malformed",
    "taskhub_signed_approval_record_not_found",
    "taskhub_signed_approval_record_malformed",
    "taskhub_signed_approval_record_id_mismatch",
    "taskhub_signed_approval_datetime_format_invalid",
    "taskhub_signed_approval_signed_at_future",
    "taskhub_signed_approval_expired",
    "taskhub_signed_approval_ttl_exceeded",
    "taskhub_signed_approval_reason_summary_malformed",
    "taskhub_signed_approval_subcommand_not_allowed",
    "taskhub_signed_approval_target_host_mismatch",
    "taskhub_signed_approval_drill_kind_subcommands_mismatch",
    "taskhub_signed_approval_signature_malformed",
    "taskhub_signed_approval_signature_invalid",
    "taskhub_signed_approval_verify_key_missing",
    "taskhub_signed_approval_verify_key_fingerprint_mismatch",
    "taskhub_signed_approval_verify_key_fingerprint_allowlist_missing",
    "taskhub_signed_approval_verify_key_fingerprint_allowlist_empty",
    "taskhub_signed_approval_verify_key_permission_unsafe",
    "taskhub_signed_approval_backup_claim_required",  # R2-F-001 adopt: backup subcommand で claim 不在
    "taskhub_signed_approval_backup_claim_mismatch",   # R2-F-001 adopt: claim と CLI 引数不一致
    "taskhub_signed_approval_backup_allow_unsigned_skeleton_rejected",  # R2-F-001 adopt: backup では escape を物理 deny
]

AUDIT_PAYLOAD_ALLOWLIST_KEYS: frozenset[str] = frozenset(
    {
        "reason_code",
        "subcommand",
        "approval_id",
        "decider",
        "drill_kind",
        "allowed_subcommands",
        "target_host",
        "expected_target_host",
        "actual_target_host",
        "from_automation",
        "allow_unsigned_manual_skeleton",
        "unsigned_manual_skeleton_used",
        "automation_env_hits",
        "tty_absent",
        "timestamp",
        "audit_marker",
        "verify_key_fingerprint",
    },
)


@dataclass(frozen=True)
class ApprovalRecord:
    """Approval record schema (strict)."""

    approval_id: str
    decider: str
    reason_summary: str
    signed_at_str: str  # 原文字列 (R1-F-001: canonical bytes 用)
    expires_at_str: str
    drill_kind: str
    allowed_subcommands: tuple[str, ...]
    target_host: str | None
    signature_b64: str  # raw base64 string (validate 済)


# --- detection helpers ---


def detect_automation_context() -> dict[str, object]:
    """env matrix hit + TTY absence (R1-F-003 adopt: 拡張 env list + TTY weak signal)."""
    env_hits = sorted(v for v in AUTOMATION_ENV_VARS if os.environ.get(v))
    try:
        tty_absent = not sys.stdin.isatty() and not sys.stdout.isatty()
    except (OSError, ValueError):
        tty_absent = True
    return {"env_hits": env_hits, "tty_absent": tty_absent}


# --- approval_id validation (R1-F-005 adopt: allowlist + path traversal) ---


def _validate_approval_id(approval_id: str) -> bool:
    if not APPROVAL_ID_REGEX.fullmatch(approval_id):
        return False
    expected_root = _approval_dir().resolve()
    expected_path = (_approval_dir() / f"{approval_id}.signed").resolve()
    try:
        expected_path.relative_to(expected_root)
    except ValueError:
        return False
    return True


# --- RFC 8785 canonical encoder (R1-F-001 adopt) ---


def _rfc8785_canonical_payload_bytes(record: ApprovalRecord) -> bytes:
    """RFC 8785 strict JCS canonical JSON (datetime 原文字列保持).

    Reference vector is tested in tests/scripts/test_taskhub_signed_approval.py.
    """
    payload: dict[str, object] = {
        "allowed_subcommands": list(record.allowed_subcommands),
        "approval_id": record.approval_id,
        "decider": record.decider,
        "drill_kind": record.drill_kind,
        "expires_at": record.expires_at_str,
        "reason_summary": record.reason_summary,
        "signed_at": record.signed_at_str,
        "target_host": record.target_host,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# --- record loader (R1-F-005 + R1-F-015 + R1-F-001 + R1-F-016 adopt) ---


def _load_approval_record(approval_id: str) -> tuple[ApprovalRecord | None, ReasonCode | None]:
    if not _validate_approval_id(approval_id):
        return None, "taskhub_signed_approval_approval_id_malformed"

    path = _approval_dir() / f"{approval_id}.signed"
    if not path.exists():
        return None, "taskhub_signed_approval_record_not_found"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, json.JSONDecodeError, OSError):
        return None, "taskhub_signed_approval_record_malformed"
    if not isinstance(data, dict):
        return None, "taskhub_signed_approval_record_malformed"

    # F-PR75-005 adopt: extra unsigned fields も reject (allowlist strict)
    # F-PR77-001 adopt: backup_claim は SP022-T02 Phase 2 で導入された signed extension
    # field、allowlist に含める (Phase 2 record で backup を通すため)
    required = {
        "approval_id",
        "decider",
        "reason_summary",
        "signed_at",
        "expires_at",
        "drill_kind",
        "allowed_subcommands",
        "signature",
    }
    allowed_keys = required | {"target_host", "backup_claim"}  # backup_claim 追加 (F-PR77-001)
    if not required.issubset(data.keys()):
        return None, "taskhub_signed_approval_record_malformed"
    extra_keys = set(data.keys()) - allowed_keys
    if extra_keys:
        # extra unsigned fields は record_malformed として deny (tampered metadata 防止)
        return None, "taskhub_signed_approval_record_malformed"

    # R1-F-015 adopt
    if data["approval_id"] != approval_id:
        return None, "taskhub_signed_approval_record_id_mismatch"

    # R1-F-001 adopt: datetime 文字列 strict
    if not isinstance(data["signed_at"], str) or not DATETIME_STRICT_REGEX.fullmatch(data["signed_at"]):
        return None, "taskhub_signed_approval_datetime_format_invalid"
    if not isinstance(data["expires_at"], str) or not DATETIME_STRICT_REGEX.fullmatch(data["expires_at"]):
        return None, "taskhub_signed_approval_datetime_format_invalid"

    # R1-F-010 adopt: reason_summary allowlist
    if not isinstance(data["reason_summary"], str) or not REASON_SUMMARY_REGEX.fullmatch(data["reason_summary"]):
        return None, "taskhub_signed_approval_reason_summary_malformed"

    # types for other fields
    if not isinstance(data["decider"], str) or not data["decider"]:
        return None, "taskhub_signed_approval_record_malformed"
    if not isinstance(data["drill_kind"], str) or not data["drill_kind"]:
        return None, "taskhub_signed_approval_record_malformed"
    if not isinstance(data["allowed_subcommands"], list) or not all(
        isinstance(s, str) and s for s in data["allowed_subcommands"]
    ):
        return None, "taskhub_signed_approval_record_malformed"
    target_host = data.get("target_host")
    if target_host is not None and (not isinstance(target_host, str)):
        return None, "taskhub_signed_approval_record_malformed"

    # R1-F-016 adopt: signature strict base64 + 64-byte
    sig_b64 = data["signature"]
    if not isinstance(sig_b64, str) or len(sig_b64) != BASE64_SIG_LEN:
        return None, "taskhub_signed_approval_signature_malformed"
    try:
        decoded = base64.b64decode(sig_b64, validate=True)
    except (ValueError, binascii.Error):
        return None, "taskhub_signed_approval_signature_malformed"
    if len(decoded) != 64:
        return None, "taskhub_signed_approval_signature_malformed"

    record = ApprovalRecord(
        approval_id=data["approval_id"],
        decider=data["decider"],
        reason_summary=data["reason_summary"],
        signed_at_str=data["signed_at"],
        expires_at_str=data["expires_at"],
        drill_kind=data["drill_kind"],
        allowed_subcommands=tuple(data["allowed_subcommands"]),
        target_host=target_host,
        signature_b64=sig_b64,
    )
    return record, None


# --- verify key loader (R1-F-009 + R3-F-001 adopt) ---


def _verify_key_permissions(key_path: Path) -> ReasonCode | None:
    try:
        st = key_path.stat()
    except OSError:
        return "taskhub_signed_approval_verify_key_missing"
    if st.st_uid != os.getuid():
        return "taskhub_signed_approval_verify_key_permission_unsafe"
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return "taskhub_signed_approval_verify_key_permission_unsafe"
    return None


def _load_verify_key_and_fingerprint() -> tuple[Ed25519PublicKey | None, str | None, ReasonCode | None]:
    """R1-F-009 + R3-F-001 + F-PR75-001 + F-PR75-002 adopt: fingerprint allowlist hard fail invariant.

    F-PR75-001 adopt: verify key file の `read_bytes()` を OSError catch、CLI crash 防止 + structured deny。
    F-PR75-002 adopt: allowlist file の `read_text()` を OSError catch、同様に structured deny。
    """
    verify_key_path = _verify_key_path()
    perm_error = _verify_key_permissions(verify_key_path)
    if perm_error:
        return None, None, perm_error
    try:
        raw = verify_key_path.read_bytes()
    except OSError:
        # F-PR75-001 adopt: existence/permission は通過したが read 失敗 (transient FS error 等)
        return None, None, "taskhub_signed_approval_verify_key_missing"
    key_bytes: bytes | None = None
    if len(raw) == 32:
        key_bytes = raw
    else:
        try:
            decoded = base64.b64decode(raw.strip(), validate=True)
        except (ValueError, binascii.Error):
            decoded = b""
        if len(decoded) == 32:
            key_bytes = decoded
    if key_bytes is None:
        return None, None, "taskhub_signed_approval_verify_key_missing"
    fingerprint = sha256(key_bytes).hexdigest()

    # R3-F-001 adopt: hard fail invariant
    allowlist_path = _verify_key_fingerprint_allowlist_path()
    if not allowlist_path.exists():
        return None, fingerprint, "taskhub_signed_approval_verify_key_fingerprint_allowlist_missing"
    try:
        allowlist_lines = allowlist_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        # F-PR75-002 adopt: file 存在するが read 不能 → effectively missing として hard fail
        return None, fingerprint, "taskhub_signed_approval_verify_key_fingerprint_allowlist_missing"
    allowlist = {
        line.strip()
        for line in allowlist_lines
        if line.strip() and not line.startswith("#")
    }
    if not allowlist:
        return None, fingerprint, "taskhub_signed_approval_verify_key_fingerprint_allowlist_empty"
    if fingerprint not in allowlist:
        return None, fingerprint, "taskhub_signed_approval_verify_key_fingerprint_mismatch"

    return Ed25519PublicKey.from_public_bytes(key_bytes), fingerprint, None


# --- main verification ---


def _extract_backup_claim_from_record(approval_id: str) -> BackupApprovalClaim | None:
    """Re-read approval record file and extract backup_claim sub-record (R2-F-001 adopt).

    既存 ApprovalRecord は backup_claim を含まないため、record file から直接 parse する。
    Phase 1 record (backup_claim key 不在) は None を返す → caller が backup_claim_required deny。
    """
    if not _validate_approval_id(approval_id):
        return None
    path = _approval_dir() / f"{approval_id}.signed"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    bc = data.get("backup_claim")
    if not isinstance(bc, dict):
        return None
    required = {"output_path", "include_sops_env", "skip_service_stop",
                "overwrite", "age_public_key_fingerprint"}
    if not required.issubset(bc.keys()):
        return None
    if not isinstance(bc["output_path"], str) or not bc["output_path"]:
        return None
    if not isinstance(bc["include_sops_env"], bool):
        return None
    if not isinstance(bc["skip_service_stop"], bool):
        return None
    if not isinstance(bc["overwrite"], bool):
        return None
    if not isinstance(bc["age_public_key_fingerprint"], str) or not bc["age_public_key_fingerprint"]:
        return None
    return BackupApprovalClaim(
        output_path=bc["output_path"],
        include_sops_env=bc["include_sops_env"],
        skip_service_stop=bc["skip_service_stop"],
        overwrite=bc["overwrite"],
        age_public_key_fingerprint=bc["age_public_key_fingerprint"],
    )


def _backup_claims_match(cli: BackupApprovalClaim, record: BackupApprovalClaim) -> bool:
    """R2-F-001 adopt: backup_claim 全 field 完全一致 verify。

    output_path は absolute path string で比較 (caller が normpath 済前提)。
    """
    return (
        cli.output_path == record.output_path
        and cli.include_sops_env == record.include_sops_env
        and cli.skip_service_stop == record.skip_service_stop
        and cli.overwrite == record.overwrite
        and cli.age_public_key_fingerprint == record.age_public_key_fingerprint
    )


def verify_signed_approval(
    approval_id: str,
    subcommand: str,
    target_host: str | None = None,
    *,
    clock_skew: timedelta = DEFAULT_CLOCK_SKEW,
    max_ttl: timedelta = DEFAULT_MAX_TTL,
    backup_claim: BackupApprovalClaim | None = None,  # R2-F-001 adopt
) -> tuple[bool, ReasonCode, dict[str, object]]:
    """Verify approval record (R1-F-001/005/007/014/015/016 + R2-F-003 + R2-F-001 全 adopt).

    R2-F-001 adopt: subcommand == "backup" の場合、record 内 backup_claim (sub-record) と
    引数 backup_claim を完全一致 verify。Phase 1 既存 record (backup_claim 不在) は backup で
    は deny。他 subcommand では backup_claim 引数を ignore (backwards compat)。
    """
    extras: dict[str, object] = {"approval_id": approval_id, "subcommand": subcommand}
    record, load_error = _load_approval_record(approval_id)
    if load_error or record is None:
        return False, load_error or "taskhub_signed_approval_record_malformed", extras
    extras["decider"] = record.decider
    extras["drill_kind"] = record.drill_kind

    now = datetime.now(timezone.utc)
    # F-PR75-003 adopt: regex pass しても strptime が ValueError (例: 2026-02-30 等の impossible
    # calendar date) を投げる可能性、structured deny に変換
    try:
        signed_at = datetime.strptime(record.signed_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        expires_at = datetime.strptime(record.expires_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return False, "taskhub_signed_approval_datetime_format_invalid", extras

    # R1-F-007 adopt: clock skew + max_ttl
    if signed_at > now + clock_skew:
        return False, "taskhub_signed_approval_signed_at_future", extras
    if expires_at <= now:
        return False, "taskhub_signed_approval_expired", extras
    if expires_at - signed_at > max_ttl:
        return False, "taskhub_signed_approval_ttl_exceeded", extras

    if subcommand not in record.allowed_subcommands:
        extras["allowed_subcommands"] = list(record.allowed_subcommands)
        return False, "taskhub_signed_approval_subcommand_not_allowed", extras

    # R1-F-014 adopt
    expected_subs = DRILL_KIND_ALLOWED_SUBCOMMANDS.get(record.drill_kind)
    if expected_subs is None or not set(record.allowed_subcommands).issubset(expected_subs):
        return False, "taskhub_signed_approval_drill_kind_subcommands_mismatch", extras

    # R2-F-003 adopt: migrate claim 厳密化
    # CLI --target と record.target_host 両方 non-empty + strip 後 exact match
    if target_host is not None:
        cli_target_stripped = target_host.strip()
        record_target_stripped = (record.target_host or "").strip()
        if not cli_target_stripped or not record_target_stripped:
            extras["expected_target_host"] = record.target_host
            extras["actual_target_host"] = target_host
            return False, "taskhub_signed_approval_target_host_mismatch", extras
        if cli_target_stripped != record_target_stripped:
            extras["expected_target_host"] = record.target_host
            extras["actual_target_host"] = target_host
            return False, "taskhub_signed_approval_target_host_mismatch", extras

    # R2-F-001 adopt: backup_claim verification for "backup" subcommand
    if subcommand == "backup":
        if backup_claim is None:
            return False, "taskhub_signed_approval_backup_claim_required", extras
        record_claim = _extract_backup_claim_from_record(approval_id)
        if record_claim is None:
            # Phase 1 既存 record (backup_claim 不在) は backup では deny
            return False, "taskhub_signed_approval_backup_claim_required", extras
        if not _backup_claims_match(backup_claim, record_claim):
            extras["expected_backup_claim_fingerprint"] = record_claim.age_public_key_fingerprint
            extras["actual_backup_claim_fingerprint"] = backup_claim.age_public_key_fingerprint
            return False, "taskhub_signed_approval_backup_claim_mismatch", extras

    verify_key, fingerprint, key_error = _load_verify_key_and_fingerprint()
    if key_error or verify_key is None:
        if fingerprint:
            extras["verify_key_fingerprint"] = fingerprint
        return False, key_error or "taskhub_signed_approval_verify_key_missing", extras
    extras["verify_key_fingerprint"] = fingerprint

    payload = _rfc8785_canonical_payload_bytes(record)
    try:
        signature_bytes = base64.b64decode(record.signature_b64, validate=True)
        verify_key.verify(signature_bytes, payload)
    except InvalidSignature:
        return False, "taskhub_signed_approval_signature_invalid", extras
    return True, "taskhub_signed_approval_verified", extras


# --- pre-execution gate (R1-F-002 + R1-F-017 + R3-F-001 adopt) ---


def require_approval_for_destructive(
    subcommand: str,
    approval_id: str | None,
    from_automation: bool,
    allow_unsigned_manual_skeleton: bool,
    target_host: str | None = None,
    backup_claim: BackupApprovalClaim | None = None,  # R2-F-001 adopt
) -> tuple[bool, ReasonCode, dict[str, object]]:
    """Pre-execution gate (default deny for destructive subcommands).

    R2-F-001 adopt: backup subcommand では `--allow-unsigned-manual-skeleton` を物理 deny、
    backup_claim 必須化 (Phase 1 既存 record backup_claim 不在は backup では deny)。
    """
    extras: dict[str, object] = {
        "subcommand": subcommand,
        "from_automation": from_automation,
        "allow_unsigned_manual_skeleton": allow_unsigned_manual_skeleton,
    }
    if subcommand not in DESTRUCTIVE_SUBCOMMANDS:
        # R1-F-017 adopt
        return True, "taskhub_signed_approval_skipped_non_destructive", extras

    # R2-F-001 adopt: backup subcommand では --allow-unsigned-manual-skeleton を物理 deny
    if subcommand == "backup" and allow_unsigned_manual_skeleton:
        return False, "taskhub_signed_approval_backup_allow_unsigned_skeleton_rejected", extras

    automation = detect_automation_context()
    extras["automation_env_hits"] = automation["env_hits"]
    extras["tty_absent"] = automation["tty_absent"]
    has_automation_env = bool(automation["env_hits"])

    if has_automation_env:
        if not from_automation:
            return False, "taskhub_signed_approval_automation_detected_without_flag", extras
        if not approval_id:
            return False, "taskhub_signed_approval_from_automation_requires_approval_id", extras
    elif not approval_id:
        if allow_unsigned_manual_skeleton:
            # backup subcommand は上で deny 済、ここに到達するのは他 destructive
            extras["unsigned_manual_skeleton_used"] = True
            return True, "taskhub_signed_approval_unsigned_manual_skeleton_allowed", extras
        return False, "taskhub_signed_approval_destructive_requires_approval", extras

    if approval_id is None:  # pragma: no cover (defensive)
        return False, "taskhub_signed_approval_destructive_requires_approval", extras

    allowed, reason, verify_extras = verify_signed_approval(
        approval_id, subcommand, target_host=target_host, backup_claim=backup_claim,
    )
    for k, v in verify_extras.items():
        extras.setdefault(k, v)
    return allowed, reason, extras


# --- audit-line scaffold (R1-F-010 + R1-F-004 adopt) ---


def emit_audit_event(reason_code: ReasonCode, extras: dict[str, object]) -> None:
    """allowlist-only redacted audit-line scaffold (stderr, Phase 1)."""
    payload: dict[str, object] = {
        "reason_code": reason_code,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "audit_marker": "taskhub_signed_approval_gate",
    }
    for k, v in extras.items():
        if k in AUDIT_PAYLOAD_ALLOWLIST_KEYS:
            payload[k] = v
    print(  # noqa: T201
        f"AUDIT taskhub_signed_approval_gate: {json.dumps(payload, sort_keys=True)}",
        file=sys.stderr,
    )
