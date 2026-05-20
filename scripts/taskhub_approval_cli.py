"""SP022-T08 batch 4: `taskhub approval issue` Ed25519-signed approval record generation.

operator が CLI で approval record を発行、Ed25519 sign + claim 付与 + raw 32-byte seed
private key (`bytearray` buffer 経由) で sign + 即時 overwrite zeroize.

Security invariants (R1 F-008/F-009/F-011/F-017 + ADV R1 F-004/F-005/F-006/F-015/F-019 + ADV R2 F-001 adopt):

- private key path = ~/.taskhub/keys/approval-signing-key (raw 32-byte seed format)
- mode 0o600 + parent dir 0o700 + O_NOFOLLOW
- approval_id pattern は sa.APPROVAL_ID_REGEX
- reason_summary pattern は sa.REASON_SUMMARY_REGEX
- drill_kind choices は sa.DRILL_KIND_ALLOWED_SUBCOMMANDS keys から派生
- allowed_subcommands choices は sa.DESTRUCTIVE_SUBCOMMANDS
- TTL default 24h, max = sa.DEFAULT_MAX_TTL (48h)
- canonical payload は sa._rfc8785_canonical_payload_bytes 既存 layout
- output file は final path に O_CREAT|O_EXCL|O_NOFOLLOW 直接 create (--force 廃止、tmp+rename 排除)
- chmod 0o600 (旧 0o644 撤回)
- bytearray zeroize for raw seed
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import stat
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

# import shared types from existing module
try:
    from scripts.taskhub_signed_approval import (
        APPROVAL_ID_REGEX,
        DEFAULT_MAX_TTL,
        DESTRUCTIVE_SUBCOMMANDS,
        DRILL_KIND_ALLOWED_SUBCOMMANDS,
        REASON_SUMMARY_REGEX,
        ApprovalRecord,
        BackupApprovalClaim,
        RestoreApprovalClaim,
        RestoreRollbackApprovalClaim,
        _rfc8785_canonical_payload_bytes,
    )
except ModuleNotFoundError:  # pragma: no cover
    _REPO_ROOT = Path(__file__).resolve().parent.parent
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from scripts.taskhub_signed_approval import (  # noqa: E402
        APPROVAL_ID_REGEX,
        DEFAULT_MAX_TTL,
        DESTRUCTIVE_SUBCOMMANDS,
        DRILL_KIND_ALLOWED_SUBCOMMANDS,
        REASON_SUMMARY_REGEX,
        ApprovalRecord,
        BackupApprovalClaim,
        RestoreApprovalClaim,
        RestoreRollbackApprovalClaim,
        _rfc8785_canonical_payload_bytes,
    )

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ReasonCode = Literal[
    "approval_issue_ok",
    # signing key
    "approval_issue_signing_key_missing",
    "approval_issue_signing_key_permission",
    "approval_issue_signing_key_symlink",
    "approval_issue_signing_key_dir_permission",
    "approval_issue_signing_key_invalid_format",
    # approval_id / collision
    "approval_issue_approval_id_collision",
    "approval_issue_approval_id_malformed",
    # schema
    "approval_issue_reason_summary_malformed",
    "approval_issue_drill_kind_subcommand_mismatch",
    "approval_issue_target_host_required",
    # claim
    "approval_issue_backup_claim_required",
    "approval_issue_backup_claim_field_missing",
    "approval_issue_restore_claim_required",
    "approval_issue_restore_claim_field_missing",
    "approval_issue_restore_rollback_claim_required",
    "approval_issue_restore_rollback_claim_field_missing",
    # TTL
    "approval_issue_signed_at_expires_inversion",
    "approval_issue_ttl_exceeded",
    # output
    "approval_issue_output_path_collision",
    "approval_issue_output_path_invalid",
]

# constants
_TASKHUB_HOME_DEFAULT = Path.home() / ".taskhub"
_SIGNING_KEY_PATH_DEFAULT = _TASKHUB_HOME_DEFAULT / "keys" / "approval-signing-key"
_APPROVAL_DIR_DEFAULT = _TASKHUB_HOME_DEFAULT / "approvals"


@dataclass(frozen=True)
class ApprovalIssueOptions:
    approval_id: str
    decider: str
    reason_summary: str
    signed_at: datetime
    expires_at: datetime
    drill_kind: str
    allowed_subcommands: tuple[str, ...]
    target_host: str | None
    backup_claim: BackupApprovalClaim | None = None
    restore_claim: RestoreApprovalClaim | None = None
    restore_rollback_claim: RestoreRollbackApprovalClaim | None = None
    signing_key_path: Path = _SIGNING_KEY_PATH_DEFAULT
    output_dir: Path = _APPROVAL_DIR_DEFAULT


def _validate_and_load_signing_key(
    path: Path,
) -> tuple[Ed25519PrivateKey | None, ReasonCode | None]:
    """ADV R1 F-019 + ADV PR R2 F-003 adopt: O_NOFOLLOW + fstat で symlink/permission 検査と
    raw 32-byte seed 読取を **同一 FD 上で完結** (TOCTOU race 排除、検査済みとは別 inode を
    読み込む経路を物理排除).
    """
    # parent dir mode check (path 自体は O_NOFOLLOW open で symlink reject)
    parent = path.parent
    try:
        parent_st = parent.stat()
    except OSError:
        return None, "approval_issue_signing_key_dir_permission"
    parent_mode = stat.S_IMODE(parent_st.st_mode)
    if parent_mode != 0o700:
        return None, "approval_issue_signing_key_dir_permission"

    # O_NOFOLLOW: symlink を物理 reject (open 時点で ELOOP)
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None, "approval_issue_signing_key_missing"
    except OSError as e:
        # ELOOP (40) = symlink reject by O_NOFOLLOW
        import errno
        if e.errno == errno.ELOOP:
            return None, "approval_issue_signing_key_symlink"
        return None, "approval_issue_signing_key_missing"

    seed_buf = bytearray(32)
    try:
        # 同一 FD 上で fstat → mode check
        st = os.fstat(fd)
        mode = stat.S_IMODE(st.st_mode)
        if mode != 0o600:
            return None, "approval_issue_signing_key_permission"
        # 同一 FD 上で read (検証済 inode と同一)
        with os.fdopen(fd, "rb", closefd=True) as f:
            data = f.read()
            if len(data) != 32:
                return None, "approval_issue_signing_key_invalid_format"
            seed_buf = bytearray(data)
            del data
        try:
            priv = Ed25519PrivateKey.from_private_bytes(bytes(seed_buf))
            return priv, None
        finally:
            for i in range(len(seed_buf)):
                seed_buf[i] = 0
    except OSError:
        try:
            os.close(fd)
        except OSError:
            pass
        return None, "approval_issue_signing_key_missing"


# Backward-compat: 既存 test が _validate_signing_key と _load_signing_key_zeroize を直接呼び出す
# 可能性に備えた alias (両者を統合した新関数)
def _validate_signing_key(path: Path) -> tuple[bool, ReasonCode | None]:
    """Deprecated: ADV PR R2 F-003 で `_validate_and_load_signing_key` に統合済。
    互換性のため残置 (testing で個別呼出可能)。
    """
    priv, reason = _validate_and_load_signing_key(path)
    if reason is not None:
        return False, reason
    return True, None


def _load_signing_key_zeroize(path: Path) -> tuple[Ed25519PrivateKey | None, ReasonCode | None]:
    """Deprecated: ADV PR R2 F-003 で `_validate_and_load_signing_key` に統合済."""
    return _validate_and_load_signing_key(path)


def issue_approval_record(opts: ApprovalIssueOptions) -> tuple[bool, ReasonCode, Path | None]:
    """approval record を発行、(success, reason_code, output_path) を返す.

    R1 F-009/F-011/F-017 + ADV R1 F-004/F-005/F-015 + ADV R2 F-001 adopt.
    """
    # 1. approval_id format validate
    if not APPROVAL_ID_REGEX.fullmatch(opts.approval_id):
        return False, "approval_issue_approval_id_malformed", None

    # 2. reason_summary regex (R1 F-017 adopt)
    if not REASON_SUMMARY_REGEX.fullmatch(opts.reason_summary):
        return False, "approval_issue_reason_summary_malformed", None

    # 3. drill_kind / subcommand 整合
    if opts.drill_kind not in DRILL_KIND_ALLOWED_SUBCOMMANDS:
        return False, "approval_issue_drill_kind_subcommand_mismatch", None
    allowed_for_drill = DRILL_KIND_ALLOWED_SUBCOMMANDS[opts.drill_kind]
    if not set(opts.allowed_subcommands).issubset(allowed_for_drill):
        return False, "approval_issue_drill_kind_subcommand_mismatch", None
    for sub in opts.allowed_subcommands:
        if sub not in DESTRUCTIVE_SUBCOMMANDS:
            return False, "approval_issue_drill_kind_subcommand_mismatch", None

    # 3.5. target_host required for migrate (ADV PR F-5 adopt)
    # verify_signed_approval(target_host=...) は record.target_host を strict require、
    # migrate subcommand を allowed_subcommands に含めるなら target_host 必須。
    if "migrate" in opts.allowed_subcommands and not opts.target_host:
        return False, "approval_issue_target_host_required", None

    # 4. signed_at < expires_at
    if opts.signed_at >= opts.expires_at:
        return False, "approval_issue_signed_at_expires_inversion", None

    # 5. TTL ≤ DEFAULT_MAX_TTL (R1 F-009 adopt)
    ttl = opts.expires_at - opts.signed_at
    if ttl > DEFAULT_MAX_TTL:
        return False, "approval_issue_ttl_exceeded", None

    # 6. claim required check
    if "backup" in opts.allowed_subcommands and opts.backup_claim is None:
        return False, "approval_issue_backup_claim_required", None
    if "restore" in opts.allowed_subcommands and opts.restore_claim is None:
        return False, "approval_issue_restore_claim_required", None
    if "restore-rollback" in opts.allowed_subcommands and opts.restore_rollback_claim is None:
        return False, "approval_issue_restore_rollback_claim_required", None

    # 7. signing key validate + load (ADV PR R2 F-003 adopt: 同一 FD 上で TOCTOU 排除)
    priv, key_err = _validate_and_load_signing_key(opts.signing_key_path)
    if key_err or priv is None:
        return False, key_err or "approval_issue_signing_key_missing", None

    # 9. build ApprovalRecord (signature placeholder で後で update)
    signed_at_str = opts.signed_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    expires_at_str = opts.expires_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    record_for_signing = ApprovalRecord(
        approval_id=opts.approval_id,
        decider=opts.decider,
        reason_summary=opts.reason_summary,
        signed_at_str=signed_at_str,
        expires_at_str=expires_at_str,
        drill_kind=opts.drill_kind,
        allowed_subcommands=opts.allowed_subcommands,
        target_host=opts.target_host,
        signature_b64="A" * 88,  # placeholder
        backup_claim=opts.backup_claim,
        restore_claim=opts.restore_claim,
        restore_rollback_claim=opts.restore_rollback_claim,
    )

    # 10. canonical payload + sign
    canonical_bytes = _rfc8785_canonical_payload_bytes(record_for_signing)
    sig_bytes = priv.sign(canonical_bytes)
    signature_b64 = base64.b64encode(sig_bytes).decode("ascii")

    # 11. final record dict (ApprovalRecord -> JSON serializable)
    record_dict: dict[str, object] = {
        "approval_id": opts.approval_id,
        "decider": opts.decider,
        "reason_summary": opts.reason_summary,
        "signed_at": signed_at_str,
        "expires_at": expires_at_str,
        "drill_kind": opts.drill_kind,
        "allowed_subcommands": list(opts.allowed_subcommands),
        "target_host": opts.target_host,
        "signature": signature_b64,
    }
    if opts.backup_claim is not None:
        record_dict["backup_claim"] = {
            "age_public_key_fingerprint": opts.backup_claim.age_public_key_fingerprint,
            "include_sops_env": opts.backup_claim.include_sops_env,
            "output_path": opts.backup_claim.output_path,
            "overwrite": opts.backup_claim.overwrite,
            "skip_service_stop": opts.backup_claim.skip_service_stop,
        }
    if opts.restore_claim is not None:
        record_dict["restore_claim"] = {
            "age_public_key_fingerprint": opts.restore_claim.age_public_key_fingerprint,
            "archive_sha256": opts.restore_claim.archive_sha256,
            "expected_alembic_head": opts.restore_claim.expected_alembic_head,
            "expected_postgres_major_version": opts.restore_claim.expected_postgres_major_version,
            "input_path": opts.restore_claim.input_path,
            "skip_service_stop": opts.restore_claim.skip_service_stop,
            "target_artifacts_container_path": opts.restore_claim.target_artifacts_container_path,
            "target_artifacts_dir": opts.restore_claim.target_artifacts_dir,
            "target_compose_file_path": opts.restore_claim.target_compose_file_path,
            "target_compose_project_name": opts.restore_claim.target_compose_project_name,
            "target_pg_dsn_components": dict(sorted(opts.restore_claim.target_pg_dsn_components.items())),
            "target_redis_endpoint": opts.restore_claim.target_redis_endpoint,
        }
    if opts.restore_rollback_claim is not None:
        rrc = opts.restore_rollback_claim
        record_dict["restore_rollback_claim"] = {
            "expected_postgres_major_version": rrc.expected_postgres_major_version,
            "pre_restore_dir": rrc.pre_restore_dir,
            "pre_restore_ts": rrc.pre_restore_ts,
            "snapshot_manifest_sha256": rrc.snapshot_manifest_sha256,
            "target_artifacts_container_path": rrc.target_artifacts_container_path,
            "target_artifacts_dir": rrc.target_artifacts_dir,
            "target_compose_file_path": rrc.target_compose_file_path,
            "target_compose_project_name": rrc.target_compose_project_name,
            "target_pg_dsn_components": dict(sorted(rrc.target_pg_dsn_components.items())),
            "target_redis_endpoint": rrc.target_redis_endpoint,
        }

    # 12. atomic create with O_CREAT|O_EXCL|O_NOFOLLOW (ADV R1 F-005 + R2 F-001 adopt)
    output_dir = opts.output_dir
    output_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    final_path = output_dir / f"{opts.approval_id}.signed"
    fd = None
    try:
        fd = os.open(
            str(final_path),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
            0o600,
        )
        content = json.dumps(record_dict, indent=2, sort_keys=True).encode("utf-8")
        # ADV PR R2 F-006 adopt: os.write 戻り値 check + 短書き込み loop (途中切れた JSON で
        # verify 失敗の不整合を防止)
        offset = 0
        while offset < len(content):
            n = os.write(fd, content[offset:])
            if n <= 0:
                # 0 bytes 書込は EOF / 異常、loop break で OSError 経路へ
                raise OSError("short write: 0 bytes written")
            offset += n
        os.fsync(fd)
    except FileExistsError:
        return False, "approval_issue_output_path_collision", None
    except OSError:
        # cleanup
        try:
            final_path.unlink()
        except OSError:
            pass
        return False, "approval_issue_output_path_invalid", None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    # parent dir fsync (ADV R1 F-015 adopt)
    try:
        pfd = os.open(str(output_dir), os.O_RDONLY)
        try:
            os.fsync(pfd)
        finally:
            os.close(pfd)
    except OSError:
        pass

    return True, "approval_issue_ok", final_path


# --- CLI subcommand handler ---


def _build_backup_claim(args: argparse.Namespace) -> BackupApprovalClaim | None:
    if not all([
        args.backup_output_path, args.backup_age_public_key_fingerprint,
    ]):
        return None
    return BackupApprovalClaim(
        output_path=args.backup_output_path,
        include_sops_env=bool(args.backup_include_sops_env),
        skip_service_stop=bool(args.backup_skip_service_stop),
        overwrite=bool(args.backup_overwrite),
        age_public_key_fingerprint=args.backup_age_public_key_fingerprint,
    )


def _build_restore_claim(args: argparse.Namespace) -> RestoreApprovalClaim | None:
    fields = [
        args.restore_input_path, args.restore_archive_sha256,
        args.restore_age_public_key_fingerprint, args.restore_target_pg_host,
        args.restore_target_pg_port, args.restore_target_pg_db, args.restore_target_pg_user,
        args.restore_target_redis_endpoint, args.restore_target_artifacts_dir,
        args.restore_target_artifacts_container_path, args.restore_target_compose_project,
        args.restore_target_compose_file, args.restore_expected_pg_major,
        args.restore_expected_alembic_head,
    ]
    if not all(fields):
        return None
    return RestoreApprovalClaim(
        input_path=args.restore_input_path,
        archive_sha256=args.restore_archive_sha256,
        age_public_key_fingerprint=args.restore_age_public_key_fingerprint,
        target_pg_dsn_components={
            "host": args.restore_target_pg_host,
            "port": args.restore_target_pg_port,
            "db": args.restore_target_pg_db,
            "user": args.restore_target_pg_user,
        },
        target_redis_endpoint=args.restore_target_redis_endpoint,
        target_artifacts_dir=args.restore_target_artifacts_dir,
        target_artifacts_container_path=args.restore_target_artifacts_container_path,
        target_compose_project_name=args.restore_target_compose_project,
        target_compose_file_path=args.restore_target_compose_file,
        expected_postgres_major_version=args.restore_expected_pg_major,
        expected_alembic_head=args.restore_expected_alembic_head,
        skip_service_stop=bool(args.restore_skip_service_stop),
    )


def _build_restore_rollback_claim(
    args: argparse.Namespace,
) -> RestoreRollbackApprovalClaim | None:
    fields = [
        args.rollback_pre_restore_ts, args.rollback_pre_restore_dir,
        args.rollback_snapshot_manifest_sha256, args.rollback_target_pg_host,
        args.rollback_target_pg_port, args.rollback_target_pg_db, args.rollback_target_pg_user,
        args.rollback_target_redis_endpoint, args.rollback_target_artifacts_dir,
        args.rollback_target_artifacts_container_path, args.rollback_target_compose_project,
        args.rollback_target_compose_file, args.rollback_expected_pg_major,
    ]
    if not all(fields):
        return None
    return RestoreRollbackApprovalClaim(
        pre_restore_ts=args.rollback_pre_restore_ts,
        pre_restore_dir=args.rollback_pre_restore_dir,
        snapshot_manifest_sha256=args.rollback_snapshot_manifest_sha256,
        target_pg_dsn_components={
            "host": args.rollback_target_pg_host,
            "port": args.rollback_target_pg_port,
            "db": args.rollback_target_pg_db,
            "user": args.rollback_target_pg_user,
        },
        target_redis_endpoint=args.rollback_target_redis_endpoint,
        target_artifacts_dir=args.rollback_target_artifacts_dir,
        target_artifacts_container_path=args.rollback_target_artifacts_container_path,
        target_compose_project_name=args.rollback_target_compose_project,
        target_compose_file_path=args.rollback_target_compose_file,
        expected_postgres_major_version=args.rollback_expected_pg_major,
    )


def cmd_approval_issue(args: argparse.Namespace) -> int:
    """`taskhub approval issue` CLI subcommand handler."""
    signed_at = datetime.now(UTC)
    expires_at = signed_at + timedelta(hours=args.ttl_hours)

    backup_claim = _build_backup_claim(args)
    restore_claim = _build_restore_claim(args)
    restore_rollback_claim = _build_restore_rollback_claim(args)

    opts = ApprovalIssueOptions(
        approval_id=args.approval_id,
        decider=args.decider,
        reason_summary=args.reason_summary,
        signed_at=signed_at,
        expires_at=expires_at,
        drill_kind=args.drill_kind,
        allowed_subcommands=tuple(args.allowed_subcommands),
        target_host=args.target_host,
        backup_claim=backup_claim,
        restore_claim=restore_claim,
        restore_rollback_claim=restore_rollback_claim,
    )
    success, reason_code, output_path = issue_approval_record(opts)
    if not success:
        print(f"ERROR: approval issue failed [reason={reason_code}]", file=sys.stderr)  # noqa: T201
        return 2
    print(  # noqa: T201
        json.dumps({"reason_code": reason_code, "output_path": str(output_path)}, sort_keys=True)
    )
    return 0


def register_subparser(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """admin.py から呼び出される subparser 登録 helper."""
    sub_approval = subparsers.add_parser(
        "approval", help="approval record management (issue)",
    )
    approval_sub = sub_approval.add_subparsers(dest="approval_subcommand", required=True)

    issue_parser = approval_sub.add_parser(
        "issue", help="issue Ed25519-signed approval record (SP022-T08 batch 4)",
    )
    issue_parser.add_argument("--approval-id", required=True)
    issue_parser.add_argument("--decider", required=True)
    issue_parser.add_argument("--reason-summary", required=True)
    issue_parser.add_argument(
        "--drill-kind", required=True,
        choices=sorted(DRILL_KIND_ALLOWED_SUBCOMMANDS.keys()),
    )
    issue_parser.add_argument(
        "--allowed-subcommands", required=True, nargs="+",
        choices=sorted(DESTRUCTIVE_SUBCOMMANDS),
    )
    issue_parser.add_argument("--target-host", default=None)
    issue_parser.add_argument("--ttl-hours", type=int, default=24)
    # backup_claim
    issue_parser.add_argument("--backup-output-path", default=None)
    issue_parser.add_argument("--backup-age-public-key-fingerprint", default=None)
    issue_parser.add_argument("--backup-include-sops-env", action="store_true")
    issue_parser.add_argument("--backup-skip-service-stop", action="store_true")
    issue_parser.add_argument("--backup-overwrite", action="store_true")
    # restore_claim
    issue_parser.add_argument("--restore-input-path", default=None)
    issue_parser.add_argument("--restore-archive-sha256", default=None)
    issue_parser.add_argument("--restore-age-public-key-fingerprint", default=None)
    issue_parser.add_argument("--restore-target-pg-host", default=None)
    issue_parser.add_argument("--restore-target-pg-port", default=None)
    issue_parser.add_argument("--restore-target-pg-db", default=None)
    issue_parser.add_argument("--restore-target-pg-user", default=None)
    issue_parser.add_argument("--restore-target-redis-endpoint", default=None)
    issue_parser.add_argument("--restore-target-artifacts-dir", default=None)
    issue_parser.add_argument("--restore-target-artifacts-container-path", default=None)
    issue_parser.add_argument("--restore-target-compose-project", default=None)
    issue_parser.add_argument("--restore-target-compose-file", default=None)
    issue_parser.add_argument("--restore-expected-pg-major", default=None)
    issue_parser.add_argument("--restore-expected-alembic-head", default=None)
    issue_parser.add_argument("--restore-skip-service-stop", action="store_true")
    # restore_rollback_claim
    issue_parser.add_argument("--rollback-pre-restore-ts", default=None)
    issue_parser.add_argument("--rollback-pre-restore-dir", default=None)
    issue_parser.add_argument("--rollback-snapshot-manifest-sha256", default=None)
    issue_parser.add_argument("--rollback-target-pg-host", default=None)
    issue_parser.add_argument("--rollback-target-pg-port", default=None)
    issue_parser.add_argument("--rollback-target-pg-db", default=None)
    issue_parser.add_argument("--rollback-target-pg-user", default=None)
    issue_parser.add_argument("--rollback-target-redis-endpoint", default=None)
    issue_parser.add_argument("--rollback-target-artifacts-dir", default=None)
    issue_parser.add_argument("--rollback-target-artifacts-container-path", default=None)
    issue_parser.add_argument("--rollback-target-compose-project", default=None)
    issue_parser.add_argument("--rollback-target-compose-file", default=None)
    issue_parser.add_argument("--rollback-expected-pg-major", default=None)
    issue_parser.set_defaults(func=cmd_approval_issue)


__all__ = [
    "ApprovalIssueOptions",
    "ReasonCode",
    "cmd_approval_issue",
    "issue_approval_record",
    "register_subparser",
]
