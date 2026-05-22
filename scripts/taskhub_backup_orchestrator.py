"""taskhub backup real I/O orchestration (SP022-T02 Phase 2 / T08 batch 2).

ADR-00021 §3-§4 spec の実 backup orchestration を実装。Sprint 12 batch 7 で確立した
skeleton (`_cmd_backup`) を本 module の `run_backup` 呼出で置き換える。

R1 14 + R2 2 + R3 1 = 17 plan-review findings 全件 adopt 反映:
- F-001 CRITICAL: archive allowlist (filename + content sniff + symlink reject)
- F-002 CRITICAL: 0700 tmp dir + cleanup audit (silent ignore 廃止)
- F-005 HIGH: `.part` atomic rename for partial output 防止
- F-009 HIGH: safe subprocess runner (timeout / env allowlist / stderr sanitize)
- R2-F-002 HIGH: tempfile.mkdtemp + os.chmod (mode 引数 unsupported workaround)
- R3-F-001 CRITICAL: PGPASSWORD env reject、temp .pgpass file (0600) + PGPASSFILE env のみ

CRITICAL security invariants:
- age private key は本 module で touch しない (-r <public_key> のみ受け取る)
- raw secret は argv / stderr / audit に出さない
- tmp dir 0700 + 全 exception path で cleanup
- archive content sniff で private key pattern 物理 reject
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

# Dual import for direct-script + console_script (T02 Phase 1 pattern)
try:
    from scripts.taskhub_subprocess_runner import (
        AGE_ENCRYPT_TIMEOUT_SEC,
        PG_DUMP_TIMEOUT_SEC,
        REDIS_RDB_TIMEOUT_SEC,
        SafeSubprocessConfig,
        SubprocessNotFoundError,
        SubprocessResult,
        SubprocessTimeoutError,
        run_safe_subprocess,
    )
except ModuleNotFoundError:
    _REPO_ROOT = Path(__file__).resolve().parent.parent
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from scripts.taskhub_subprocess_runner import (  # noqa: E402
        AGE_ENCRYPT_TIMEOUT_SEC,
        PG_DUMP_TIMEOUT_SEC,
        REDIS_RDB_TIMEOUT_SEC,
        SafeSubprocessConfig,
        SubprocessNotFoundError,
        SubprocessResult,
        SubprocessTimeoutError,
        run_safe_subprocess,
    )

# F-008 adopt: meta.json acquisition source
_PG_VERSION_RE = re.compile(r"pg_dump\s+\(PostgreSQL\)\s+(\d+\.\d+(?:\.\d+)?)")
_REDIS_VERSION_RE = re.compile(r"redis_version:(\S+)")

# F-001 adopt: archive allowlist
_ARCHIVE_ALLOWLIST_PATTERNS = (
    "meta.json",
    "checksums.txt",
    "postgres/pg_dump.dump",
    "postgres/alembic_version.txt",
    "redis/dump.rdb",
    "redis/appendonly.aof",
    "env.encrypted",
    "artifacts/",  # prefix match for recursive contents
)

_ARCHIVE_DENY_FILENAME_PATTERNS = (
    re.compile(r"^id_rsa$"),
    re.compile(r"^id_ed25519$"),
    re.compile(r"^id_ecdsa$"),
    re.compile(r"^id_dsa$"),
    re.compile(r"^age-key.*"),
    re.compile(r".*age-identity.*"),
    re.compile(r"^keys\.txt$"),
    re.compile(r".*\.private\.pem$"),
    re.compile(r".*-private\.pem$"),
    re.compile(r".*\.key\.pem$"),
    re.compile(r".*\.gpg$"),
    re.compile(r".*\.pgp$"),
)

_ARCHIVE_DENY_CONTENT_PREFIXES = (
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN EC PRIVATE KEY-----",
    b"-----BEGIN DSA PRIVATE KEY-----",
    b"-----BEGIN PGP PRIVATE KEY BLOCK-----",
    b"AGE-SECRET-KEY-",
)

_CONTENT_SNIFF_SIZE = 4096  # first 4 KB
_BACKUP_PATH_ALLOWED_ROOT_LABEL = "repo_root / /etc / /var/lib"


ReasonCode = Literal[
    "backup_completed",
    "backup_output_path_invalid",
    "backup_output_already_exists",
    "backup_temp_dir_creation_failed",
    "backup_archive_allowlist_violation",
    "backup_meta_json_acquisition_failed",
    "backup_pg_dump_tool_not_found",
    "backup_pg_dump_failed",
    "backup_redis_rdb_tool_not_found",
    "backup_redis_rdb_failed",
    "backup_artifacts_tar_failed",
    "backup_age_tool_not_found",
    "backup_age_encrypt_failed",
    "backup_checksum_calculation_failed",
    "backup_tmp_cleanup_failed",
    "backup_approval_claim_mismatch",
    "backup_claim_mismatch",  # ADV2 R3 F-002 + R13 F-003 統一: caller-supplied env で署名済 approval すり替え
    "backup_unexpected_error",
    # SP022-T02 Phase 5 拡張 (ADV2 累計 19 件 + Phase 1 R8 で 1 件 = 20 件、R13 F-003 で 1 件削除統一 = 19 件)
    "backup_age_key_toctou_mismatch",  # ADV R1 F-003: TOCTOU re-verify reason
    "backup_age_recipient_invalid",  # ADV R3 F-001 + R1 F-006: age recipient regex 違反
    "backup_service_stop_failed",  # ADV R2 F-003: api/worker stop 失敗 (致命的)
    "backup_service_start_failed",  # ADV R2 F-003: api/worker restart 失敗 (致命的)
    "backup_claim_legacy_runtime_binding_unsupported",  # ADV R4 F-001 + R5 F-001: PR #77 legacy 5-field 常時 reject
    "backup_compose_file_unreadable",  # ADV R5 F-002: lock 内 compose file 再読込失敗
    "backup_compose_binding_not_initialized",  # ADV R7 F-001: _compose_argv_prefix bind 前呼出
    "backup_compose_verified_copy_tampered",  # ADV2 R1 F-005: verified compose copy sha256 mismatch
    "backup_compose_config_failed",  # ADV2 R1 F-003: docker compose config canonical hash 失敗
    "backup_redis_rdb_tmp_not_regular_file",  # ADV2 R1 F-008: tmp file が regular file ではない
    "backup_compose_env_file_unreadable",  # ADV2 R2 F-001 + R9 F-001: env_file 不存在 / 読込失敗
    "backup_payload_source_unreadable",  # ADV2 R2 F-002: sops_env sha256 計算用 file 読込失敗
    "backup_env_file_verified_copy_tampered",  # ADV2 R2 F-004: env_file verified copy snapshot mismatch
    "backup_payload_source_tampered",  # ADV2 R5 F-002: sops_env verified copy sha256/metadata mismatch
    "backup_artifacts_staging_tampered",  # ADV2 R5 F-002: artifacts_dir staging tree manifest mismatch
    "backup_artifacts_source_unsupported_file_type",  # ADV2 R6 F-003 + R11 F-002: symlink / FIFO / socket / device
    "backup_artifacts_file_too_large",  # ADV2 R6 F-003: per-file 256 MiB 超
    "backup_artifacts_tree_too_large",  # ADV2 R6 F-003: tree total 4 GiB 超
    "backup_artifacts_source_reserved_name",  # ADV2 R8 F-002: source tree に reserved name
]

WarningCode = Literal[
    "backup_sops_env_skipped",
    "backup_service_stop_skipped",
    "backup_artifacts_dir_empty",
]


# --- exception types ---


class BackupUsageError(Exception):
    """exit 2 (usage error / schema invalid / arg out of range)."""

    def __init__(self, reason_code: ReasonCode, *, detail: str = "") -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.detail = _sanitize_token(detail)

    def stderr_message(self) -> str:
        parts = [f"ERROR reason_code={self.reason_code}"]
        if self.detail:
            parts.append(f"detail={self.detail}")
        return " ".join(parts)


class BackupRuntimeError(Exception):
    """exit 1 (chain build / subprocess / cleanup failure)."""

    def __init__(self, reason_code: ReasonCode, *, detail: str = "") -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.detail = _sanitize_token(detail)

    def stderr_message(self) -> str:
        parts = [f"ERROR reason_code={self.reason_code}"]
        if self.detail:
            parts.append(f"detail={self.detail}")
        return " ".join(parts)


class BackupToolNotFoundError(BackupUsageError):
    """exit 2 (required CLI tool not installed)."""


def backup_path_allowed_roots(repo_root: Path) -> tuple[Path, ...]:
    """Return the source path allowlist roots used by backup binding resolution."""
    return (
        repo_root.expanduser().resolve(strict=False),
        Path("/etc"),
        Path("/var/lib"),
    )


def validate_backup_source_path_allowed(
    *,
    path: Path,
    repo_root: Path,
    field_name: str,
    reason_code: ReasonCode = "backup_output_path_invalid",
) -> None:
    """Validate backup source path against the shared repo_root/etc/var/lib allowlist."""
    allowed_roots = backup_path_allowed_roots(repo_root)
    if any(path.is_relative_to(root) for root in allowed_roots):
        return
    raise BackupUsageError(
        reason_code,
        detail=(
            f"{field_name} not in allowed root "
            f"({_BACKUP_PATH_ALLOWED_ROOT_LABEL}): {path}"
        ),
    )


def _sanitize_token(s: str, max_len: int = 200) -> str:
    """control chars strip + length truncate (raw payload leak 防止)."""
    sanitized = re.sub(r"[\x00-\x1f\x7f-\x9f]", "?", s)
    if len(sanitized) > max_len:
        sanitized = sanitized[:max_len] + "..."
    return sanitized


# --- BackupOptions ---


@dataclasses.dataclass(frozen=True)
class BackupOptions:
    output_path: Path
    host_name: str
    include_sops_env: bool
    skip_service_stop: bool
    overwrite: bool
    age_public_key_path: Path
    pg_host: str
    pg_port: int
    pg_user: str
    pg_db: str
    redis_host: str
    redis_port: int
    artifacts_dir: Path
    sops_env_path: Path
    # SP022-T02 Phase 5 ADV R1 F-002 adopt: pgpassfile は Phase 5 compose exec で不要、optional 化
    pgpassfile_path: Path | None = None
    pg_dump_timeout_sec: int = PG_DUMP_TIMEOUT_SEC
    redis_rdb_timeout_sec: int = REDIS_RDB_TIMEOUT_SEC
    age_encrypt_timeout_sec: int = AGE_ENCRYPT_TIMEOUT_SEC
    # SP022-T02 Phase 5 ADV R1 F-010 + R2 F-001 adopt: Compose binding (signed)
    target_compose_project_name: str = "taskmanagedai"
    target_compose_file_path: Path = Path("/dev/null")  # sentinel、from_environment で override
    # ADV2 R9 F-001 adopt: env_file path (server-owned 必須、`--env-file` で docker compose に明示)
    env_file_path: Path | None = None
    # ADV R3 F-001 adopt: lock 内 fingerprint verify 後に bind される確定 recipient
    verified_age_recipient: str | None = None
    # ADV R6 F-001 adopt: 署名済 compose file source の project directory
    verified_source_project_dir: Path | None = None
    # ADV R7 F-001 adopt: verified compose copy (docker compose `-f` execution input)
    verified_compose_execution_input: Path | None = None
    # ADV2 R2 F-004 + R3 F-002 adopt: verified copy metadata snapshot (dev/ino/uid/mode/sha256)
    verified_compose_metadata_snapshot: dict[str, int | str] | None = None
    # ADV2 R2 F-001 + R4 F-002 + R9 F-001 adopt: env_file binding
    verified_env_file_execution_input: Path | None = None
    verified_env_file_metadata_snapshot: dict[str, int | str] | None = None
    # ADV2 R5 F-002 + R6 F-001 adopt: payload source TOCTOU 防御 (sops_env + artifacts_dir)
    verified_sops_env_execution_input: Path | None = None
    verified_sops_env_metadata_snapshot: dict[str, int | str] | None = None
    verified_artifacts_staging_dir: Path | None = None
    verified_artifacts_manifest_sha256: str | None = None
    # ADV2 R6 F-002 adopt: source artifacts_dir realpath snapshot (immutable bind)
    artifacts_dir_realpath_snapshot: Path | None = None
    # ADV2 R8 F-002 adopt: source mode sidecar path (verified_temp_dir 直下、staging tree の外)
    verified_artifacts_source_mode_sidecar_path: Path | None = None

    @classmethod
    def from_environment(
        cls,
        *,
        output_path: Path,
        repo_root: Path,
        include_sops_env: bool = False,
        skip_service_stop: bool = False,
        overwrite: bool = False,
    ) -> BackupOptions:
        """F-007 adopt: defaults precedence (CLI > env > hardcoded)。

        docker-compose.yml parse は本 batch では implement せず、env override で十分
        cover (将来 batch で yaml parse を ADR で追加判断)。

        F-PR77-004 adopt: env port parse 失敗は `BackupUsageError` に正規化、stack trace
        による異常終了を防止。
        """
        def _int_env(var: str, default: int) -> int:
            raw = os.environ.get(var)
            if raw is None:
                return default
            try:
                value = int(raw)
            except ValueError:
                raise BackupUsageError(
                    "backup_output_path_invalid",  # generic usage error reuse for env parse
                    detail=f"env {var} not an integer: {_sanitize_token(raw, 30)}",
                ) from None
            if value < 1 or value > 65535:
                raise BackupUsageError(
                    "backup_output_path_invalid",
                    detail=f"env {var} out of range [1, 65535]: {value}",
                )
            return value

        # SP022-T02 Phase 5 ADV R1 F-006 adopt: docker-compose.yml default 整合 (taskhub → taskmanagedai)
        pg_user = os.environ.get("TASKHUB_BACKUP_PG_USER", "taskmanagedai")
        pg_db = os.environ.get("TASKHUB_BACKUP_PG_DB", "taskmanagedai")

        # SP022-T02 Phase 5 ADV R1 F-010 + R2 F-001 adopt: Compose binding 解決 + allowlist
        target_compose_project = os.environ.get(
            "TASKHUB_BACKUP_COMPOSE_PROJECT", "taskmanagedai",
        )
        if not re.fullmatch(r"^[a-z0-9][a-z0-9_-]*$", target_compose_project):
            raise BackupUsageError(
                "backup_output_path_invalid",
                detail=f"target_compose_project_name invalid: {target_compose_project!r}",
            )
        target_compose_file_raw = os.environ.get(
            "TASKHUB_BACKUP_COMPOSE_FILE",
            str(repo_root / "docker-compose.yml"),
        )
        target_compose_file = Path(target_compose_file_raw).expanduser().resolve(strict=False)
        repo_root_resolved = repo_root.expanduser().resolve(strict=False)
        validate_backup_source_path_allowed(
            path=target_compose_file,
            repo_root=repo_root_resolved,
            field_name="target_compose_file_path",
        )

        # ADV2 R9 F-001 adopt: env_file_path を server-owned 解決 + allowlist + 存在確認 (Phase 5 用)
        # PR #77 backward compat: env が unset で .env.local が存在しない場合は None (legacy host TCP path 維持)
        env_file_raw = os.environ.get("TASKHUB_BACKUP_ENV_FILE")
        env_file_path: Path | None
        if env_file_raw is not None:
            # 明示指定された場合のみ allowlist + 存在 strict 検証
            env_file_path = Path(env_file_raw).expanduser().resolve(strict=False)
            validate_backup_source_path_allowed(
                path=env_file_path,
                repo_root=repo_root_resolved,
                field_name="env_file_path",
            )
            if not env_file_path.is_file():
                raise BackupUsageError(
                    "backup_compose_env_file_unreadable",
                    detail=f"env_file_path not found: {env_file_path}",
                )
        else:
            # default `<repo>/.env.local` (Phase 5 で docker compose interpolation 用)
            # 存在しなければ None (legacy PR #77 host TCP 経路は env_file 不要)
            default_env_file = (repo_root / ".env.local").expanduser().resolve(strict=False)
            env_file_path = default_env_file if default_env_file.is_file() else None

        return cls(
            output_path=output_path,
            host_name=os.environ.get("TASKHUB_BACKUP_HOST", socket.gethostname()),
            include_sops_env=include_sops_env,
            skip_service_stop=skip_service_stop,
            overwrite=overwrite,
            age_public_key_path=Path(
                os.environ.get(
                    "TASKHUB_BACKUP_AGE_PUBLIC_KEY",
                    str(Path.home() / ".taskhub" / "keys" / "age.pub"),
                ),
            ),
            pg_host=os.environ.get("TASKHUB_BACKUP_PG_HOST", "127.0.0.1"),
            pg_port=_int_env("TASKHUB_BACKUP_PG_PORT", 5432),
            pg_user=pg_user,
            pg_db=pg_db,
            redis_host=os.environ.get("TASKHUB_BACKUP_REDIS_HOST", "127.0.0.1"),
            redis_port=_int_env("TASKHUB_BACKUP_REDIS_PORT", 6379),
            artifacts_dir=Path(
                os.environ.get(
                    "TASKHUB_BACKUP_ARTIFACTS_DIR",
                    str(repo_root / "data" / "artifacts"),
                ),
            ),
            sops_env_path=Path(
                os.environ.get(
                    "TASKHUB_BACKUP_SOPS_ENV_PATH",
                    str(repo_root / ".env.encrypted"),
                ),
            ),
            pgpassfile_path=(
                # Phase 5 では None default、legacy fallback (PR #77 host TCP) で
                # TASKHUB_BACKUP_PGPASSFILE 明示設定時は env から解決 (Codex PR #80 F-005 adopt)
                Path(os.environ["TASKHUB_BACKUP_PGPASSFILE"])
                if os.environ.get("TASKHUB_BACKUP_PGPASSFILE")
                else None
            ),
            target_compose_project_name=target_compose_project,
            target_compose_file_path=target_compose_file,
            env_file_path=env_file_path,
        )


@dataclasses.dataclass(frozen=True)
class BackupResult:
    output_path: Path
    output_sha256: str
    entry_count: int
    postgres_version: str
    redis_version: str
    alembic_head: str
    reason_code: ReasonCode
    warnings: tuple[WarningCode, ...]
    duration_sec: float

    def summary(self) -> dict[str, Any]:
        return {
            "mode": "backup-real-io",
            "output_path": str(self.output_path),
            "output_sha256": self.output_sha256,
            "entry_count": self.entry_count,
            "postgres_version": self.postgres_version,
            "redis_version": self.redis_version,
            "alembic_head": self.alembic_head,
            "reason_code": self.reason_code,
            "warnings": list(self.warnings),
            "duration_sec": self.duration_sec,
        }


# --- pure functions ---


def build_meta_json(
    *,
    host_name: str,
    timestamp_utc: datetime,
    postgres_version: str,
    redis_version: str,
    alembic_head: str,
    format_version: str = "1.0",
) -> dict[str, Any]:
    """meta.json builder (F-008 adopt + R2-F-005 PR #77 retro-fix: SP022-T02 Phase 3 restore 側との
    field 名整合化).

    field rename (R2-F-005 adopt):
    - `backup_format_version` → `format_version` (1.0 semver で前方互換管理)
    - `host` → `host_name`
    - `timestamp` → `timestamp_utc` (rfc3339 Z suffix で UTC 明示)
    """
    return {
        "format_version": format_version,
        "host_name": host_name,
        "timestamp_utc": timestamp_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "postgres_version": postgres_version,
        "redis_version": redis_version,
        "alembic_head": alembic_head,
    }


def build_checksums_text(file_paths: dict[str, Path]) -> str:
    """checksums.txt builder (F-012 adopt: sha256sum 互換 format / byte-lex sort / self-exclude)。

    Args:
        file_paths: {relative_posix_path: absolute_path} mapping、`checksums.txt` 自身は含めない

    Returns:
        `<sha256-hex>  <relative-posix-path>\n` lines、byte-lex sorted by relative path
    """
    lines: list[str] = []
    for relative in sorted(file_paths.keys()):
        if relative == "checksums.txt":
            continue
        abs_path = file_paths[relative]
        if abs_path.is_symlink():
            # F-001 adopt: symlink reject
            msg = f"symlink not permitted in archive: {relative}"
            raise BackupRuntimeError(
                "backup_archive_allowlist_violation",
                detail=msg,
            )
        hasher = hashlib.sha256()
        try:
            with abs_path.open("rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    hasher.update(chunk)
        except OSError as exc:
            raise BackupRuntimeError(
                "backup_checksum_calculation_failed",
                detail=f"path={relative} err={type(exc).__name__}",
            ) from None
        lines.append(f"{hasher.hexdigest()}  {relative}")
    return "\n".join(lines) + "\n" if lines else ""


def check_archive_allowed(
    relative_path: str, abs_path: Path,
) -> tuple[bool, str]:
    """F-001 adopt: archive 対象として許可される path かを判定。

    Returns:
        (allowed: bool, reason: str)。reason は reject 理由 (allowed=True なら "")
    """
    # symlink 全 reject
    if abs_path.is_symlink():
        return False, "symlink_rejected"

    # filename pattern (basename) check
    filename = abs_path.name
    for pattern in _ARCHIVE_DENY_FILENAME_PATTERNS:
        if pattern.match(filename):
            return False, f"filename_pattern_rejected:{filename}"

    # allowlist match check
    allowed = False
    for allow_pat in _ARCHIVE_ALLOWLIST_PATTERNS:
        if allow_pat.endswith("/"):
            # prefix match for recursive dir (e.g., "artifacts/")
            if relative_path.startswith(allow_pat):
                allowed = True
                break
        elif relative_path == allow_pat:
            allowed = True
            break
    if not allowed:
        return False, f"not_in_allowlist:{relative_path}"

    # content sniff (first 4KB) — only for files, not directories
    if abs_path.is_file():
        try:
            with abs_path.open("rb") as f:
                head = f.read(_CONTENT_SNIFF_SIZE)
        except OSError:
            return False, "content_sniff_io_error"
        for prefix in _ARCHIVE_DENY_CONTENT_PREFIXES:
            if head.startswith(prefix):
                return False, f"content_prefix_rejected:{prefix.decode('ascii', errors='replace')[:30]}"

    return True, ""


def resolve_backup_temp_layout(parent_dir: Path | None = None) -> Path:
    """0700 tmp dir 作成 (R2-F-002 + F-002 adopt)。

    `tempfile.mkdtemp` の mode 引数は無いため、`mkdtemp` 後に `os.chmod(0o700)` +
    permission verify で fail-closed。
    """
    try:
        tmp_dir_str = tempfile.mkdtemp(
            prefix="taskhub-backup-",
            dir=str(parent_dir) if parent_dir else None,
        )
    except OSError as exc:
        raise BackupUsageError(
            "backup_temp_dir_creation_failed",
            detail=f"mkdtemp_failed: {type(exc).__name__}",
        ) from None
    tmp_dir = Path(tmp_dir_str)
    try:
        os.chmod(tmp_dir, 0o700)
    except OSError as exc:
        # cleanup attempt + fail-closed
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise BackupUsageError(
            "backup_temp_dir_creation_failed",
            detail=f"chmod_failed: {type(exc).__name__}",
        ) from None
    actual_mode = stat.S_IMODE(tmp_dir.stat().st_mode)
    if actual_mode != 0o700:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise BackupUsageError(
            "backup_temp_dir_creation_failed",
            detail=f"mode_verify_failed: actual_mode=0o{actual_mode:o}",
        )
    return tmp_dir


# --- subprocess wrappers ---


def invoke_pg_dump(
    *,
    pg_host: str,
    pg_port: int,
    pg_user: str,
    pg_db: str,
    output_path: Path,
    pgpassfile: Path | None,
    timeout_sec: int,
) -> SubprocessResult:
    """pg_dump --format=custom invocation (F-011 adopt: .dump 拡張子)。

    R3-F-001 adopt: PostgreSQL credentials は PGPASSFILE (temp .pgpass file path) 経由のみ、
    PGPASSWORD env は使用しない。
    """
    argv = [
        "pg_dump",
        "--format=custom",
        "--no-acl",
        "--no-owner",
        "-h", pg_host,
        "-p", str(pg_port),
        "-U", pg_user,
        "-d", pg_db,
        "-f", str(output_path),
    ]
    config = SafeSubprocessConfig(
        timeout_sec=timeout_sec,
        extra_env_allowlist=("PGPASSFILE",) if pgpassfile else (),
    )
    # PGPASSFILE env injection (R3-F-001 adopt)
    if pgpassfile:
        os.environ["PGPASSFILE"] = str(pgpassfile)
    try:
        return _run_subprocess_with_tool_check(argv, config, "backup_pg_dump_tool_not_found")
    finally:
        # caller controls pgpass file lifetime; here we only set/unset env var
        if pgpassfile:
            os.environ.pop("PGPASSFILE", None)


def invoke_redis_rdb(
    *,
    redis_host: str,
    redis_port: int,
    output_path: Path,
    timeout_sec: int,
) -> SubprocessResult:
    """redis-cli --rdb invocation (F-006 adopt)."""
    argv = [
        "redis-cli",
        "-h", redis_host,
        "-p", str(redis_port),
        "--rdb", str(output_path),
    ]
    config = SafeSubprocessConfig(timeout_sec=timeout_sec)
    return _run_subprocess_with_tool_check(argv, config, "backup_redis_rdb_tool_not_found")


def invoke_age_encrypt(
    *,
    input_path: Path,
    output_path: Path,
    public_key_path: Path,
    timeout_sec: int,
    verified_recipient: str | None = None,  # ADV R3 F-001 CRITICAL adopt
) -> SubprocessResult:
    """age -r <public_key> -o <output> <input> invocation。

    F-001 adopt: argv に public key path のみ、private key は touch しない。
    ADV R3 F-001 CRITICAL adopt: verified_recipient が指定された場合は public_key_path を
    再読込せず、検証済 recipient string をそのまま使う (lock 内 fingerprint verify 後の
    TOCTOU race 排除)。
    """
    if verified_recipient is not None:
        pub_key_content = verified_recipient
    else:
        if not public_key_path.exists():
            raise BackupRuntimeError(
                "backup_age_encrypt_failed",
                detail=f"public_key_not_found: {public_key_path}",
            )
        try:
            pub_key_content = public_key_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise BackupRuntimeError(
                "backup_age_encrypt_failed",
                detail=f"public_key_read_failed: {type(exc).__name__}",
            ) from None
    argv = [
        "age",
        "-r", pub_key_content,
        "-o", str(output_path),
        str(input_path),
    ]
    config = SafeSubprocessConfig(timeout_sec=timeout_sec)
    return _run_subprocess_with_tool_check(argv, config, "backup_age_tool_not_found")


# --- SP022-T02 Phase 5: docker compose exec helpers ---


# ADV R3 F-001 + R1 F-006: age recipient 厳密 regex (age v1 仕様、bech32 base32)
_AGE_RECIPIENT_RE = re.compile(r"^age1[0-9a-z]{58}$")

# ADV2 R6 F-003: artifacts directory size limits
MAX_ARTIFACT_FILE_BYTES = 256 * 1024 * 1024  # 256 MiB per-file
MAX_ARTIFACT_TREE_BYTES = 4 * 1024 * 1024 * 1024  # 4 GiB tree total

# ADV2 R8 F-002: source mode sidecar reserved file name
_ARTIFACTS_SOURCE_MODE_SIDECAR_NAME = "_artifacts_source_mode.json"


def validate_age_recipient_bytes(age_pub_bytes: bytes) -> str:
    """ADV R3 F-001 + ADV2 R1 F-006 CRITICAL adopt: age public key bytes を厳密 validate.

    UnicodeDecodeError catch + 単一行制約 + 最大長 + age v1 bech32 regex。
    返値は strip 済の verified recipient string、validation 失敗時は BackupRuntimeError。
    """
    try:
        recipient = age_pub_bytes.decode("ascii").strip()
    except UnicodeDecodeError:
        raise BackupRuntimeError(
            "backup_age_recipient_invalid",
            detail="age public key content not ASCII",
        ) from None
    if "\n" in recipient or "\r" in recipient or len(recipient) > 200:
        raise BackupRuntimeError(
            "backup_age_recipient_invalid",
            detail=f"age recipient malformed (multi-line or oversized): prefix={recipient[:8]!r}",
        )
    if not _AGE_RECIPIENT_RE.match(recipient):
        raise BackupRuntimeError(
            "backup_age_recipient_invalid",
            detail=f"age recipient regex mismatch: prefix={recipient[:8]!r}",
        )
    return recipient


def _compose_argv_prefix(options: BackupOptions) -> list[str]:
    """docker compose に -p <project> + -f <verified copy> + --project-directory + --env-file 明示.

    SP022-T02 Phase 5 ADV R6 F-001 + R7 F-001 + R9 F-002 + R10 F-001 CRITICAL adopt:
    - `-f` には verified_compose_execution_input (lock 内 read した bytes の immutable copy)
    - `--project-directory` には verified_source_project_dir (signed source realpath の parent)
    - `--env-file` には verified_env_file_execution_input (env_file_path set 時必須)
    - 各 verified copy 直前に metadata snapshot 再検証 (R2 F-004 same-UID unlink/rename swap 検知)
    - cross-field invariant: env_file_path set ↔ verified_env_file_execution_input set ↔ snapshot set
    """
    if options.verified_compose_execution_input is None or options.verified_source_project_dir is None:
        raise BackupRuntimeError(
            "backup_compose_binding_not_initialized",
            detail=(
                "verified_compose_execution_input / verified_source_project_dir "
                "must be bound before _compose_argv_prefix"
            ),
        )
    # ADV2 R3 F-002 + R8 F-001: snapshot 必須 (未初期化は fail-closed)
    if options.verified_compose_metadata_snapshot is None:
        raise BackupRuntimeError(
            "backup_compose_binding_not_initialized",
            detail="verified_compose_metadata_snapshot must be bound alongside verified_compose_execution_input",
        )
    _verify_metadata_snapshot(
        options.verified_compose_execution_input,
        options.verified_compose_metadata_snapshot,
        tamper_reason="backup_compose_verified_copy_tampered",
    )
    # ADV2 R9 F-002 + R10 F-001: env_file cross-field invariant
    if options.env_file_path is not None and options.verified_env_file_execution_input is None:
        raise BackupRuntimeError(
            "backup_compose_binding_not_initialized",
            detail="options.env_file_path set but verified_env_file_execution_input not bound",
        )
    if options.env_file_path is None and options.verified_env_file_execution_input is not None:
        raise BackupRuntimeError(
            "backup_compose_binding_not_initialized",
            detail="verified_env_file_execution_input bound but options.env_file_path is None",
        )
    if options.verified_env_file_execution_input is not None:
        if options.verified_env_file_metadata_snapshot is None:
            raise BackupRuntimeError(
                "backup_compose_binding_not_initialized",
                detail="verified_env_file_metadata_snapshot must be bound alongside verified_env_file_execution_input",
            )
        _verify_metadata_snapshot(
            options.verified_env_file_execution_input,
            options.verified_env_file_metadata_snapshot,
            tamper_reason="backup_env_file_verified_copy_tampered",
        )
    argv = [
        "docker", "compose",
        "-p", options.target_compose_project_name,
        "-f", str(options.verified_compose_execution_input),
        "--project-directory", str(options.verified_source_project_dir),
    ]
    if options.verified_env_file_execution_input is not None:
        argv.extend(["--env-file", str(options.verified_env_file_execution_input)])
    return argv


def _verify_metadata_snapshot(
    target: Path,
    snapshot: dict[str, int | str] | None,
    *,
    tamper_reason: ReasonCode,
) -> None:
    """ADV2 R2 F-004 + R3 F-002 + R8 F-001 CRITICAL adopt: verified copy の同一性を dev/ino/uid/mode/sha256 で再検証.

    各 docker compose 呼出 / archive 直前で呼ぶ。snapshot=None は呼出側で先に check (defense-in-depth)。
    """
    if snapshot is None:
        raise BackupRuntimeError(
            "backup_compose_binding_not_initialized",
            detail=f"metadata snapshot missing for {target}",
        )
    st = os.lstat(str(target))
    current_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    if (
        st.st_dev != snapshot["dev"]
        or st.st_ino != snapshot["ino"]
        or st.st_uid != snapshot["uid"]
        or stat.S_IMODE(st.st_mode) != snapshot["mode"]
        or current_sha != snapshot["sha256"]
    ):
        raise BackupRuntimeError(
            tamper_reason,
            detail=f"verified copy metadata mismatch: {target} (dev/ino/uid/mode/sha256 swap detected)",
        )


def invoke_pg_dump_via_compose_exec(
    options: BackupOptions,
    *,
    output_path: Path,
    timeout_sec: int,
) -> SubprocessResult:
    """SP022-T02 Phase 5: pg_dump を docker compose exec + container 内 unix socket 経路で実行.

    ADV R1 F-001 CRITICAL adopt: host TCP + PGPASSFILE 撤回、container 内 trust auth + unix socket.
    output_path は host 側 file、stdin redirection で container 出力を receive。
    """
    argv = (
        _compose_argv_prefix(options)
        + ["exec", "-T", "postgres", "pg_dump"]
        + ["--format=custom", "--no-acl", "--no-owner"]
        + [f"--username={options.pg_user}", f"--dbname={options.pg_db}"]
        + ["-h", "/var/run/postgresql", "--no-password"]
    )
    # stdout file redirection で container pg_dump stdout → host output_path に書込
    with output_path.open("wb") as out_fp:
        config = SafeSubprocessConfig(
            timeout_sec=timeout_sec,
            stdout_file=out_fp,
        )
        return _run_subprocess_with_tool_check(argv, config, "backup_pg_dump_tool_not_found")


def verify_pg_hba_trust_auth_via_compose_exec(
    options: BackupOptions, *, timeout_sec: int,
) -> None:
    """ADV R1 F-007 CRITICAL adopt: pg_dump 呼出前に trust auth 前提を verify.

    `psql -c 'select 1'` を同 argv pattern で実行、trust auth が effective か確認。
    fail-closed (postgres image 仕様変更 / pg_hba mount override で trust ではない場合 reject)。
    """
    argv = (
        _compose_argv_prefix(options)
        + ["exec", "-T", "postgres", "psql"]
        + [f"--username={options.pg_user}", f"--dbname={options.pg_db}"]
        + ["-h", "/var/run/postgresql", "--no-password"]
        + ["-c", "select 1", "-t", "-A"]
    )
    config = SafeSubprocessConfig(timeout_sec=timeout_sec)
    result = _run_subprocess_with_tool_check(argv, config, "backup_pg_dump_tool_not_found")
    if result.returncode != 0:
        raise BackupRuntimeError(
            "backup_pg_dump_failed",
            detail=f"pg_hba_preflight_exit={result.returncode}",
        )


def invoke_redis_save_via_compose_exec(
    options: BackupOptions, *, timeout_sec: int,
) -> SubprocessResult:
    """SP022-T02 Phase 5 ADV R1 F-005 adopt: redis-cli SAVE を docker compose exec で実行.

    blocking SAVE (race-free)、その後 docker compose cp で dump.rdb を host に stream copy。
    """
    argv = (
        _compose_argv_prefix(options)
        + ["exec", "-T", "redis", "redis-cli", "SAVE"]
    )
    config = SafeSubprocessConfig(timeout_sec=timeout_sec)
    return _run_subprocess_with_tool_check(argv, config, "backup_redis_rdb_tool_not_found")


def invoke_redis_dump_copy_via_compose_cp(
    options: BackupOptions,
    *,
    output_path: Path,
    timeout_sec: int,
) -> SubprocessResult:
    """SP022-T02 Phase 5 ADV R1 F-005 + ADV2 R1 F-008 + R14 F-001 adopt: redis container 内 dump.rdb を copy.

    docker compose cp + private temp dir (0o700) + O_EXCL + lstat regular file check + atomic rename.
    R14 F-001: predictable name path での symlink swap 防御 (private dir に閉じる)。
    """
    # ADV2 R14 F-001: private dir に閉じる (predictable path での symlink swap 防御)
    private_tmp_dir = Path(tempfile.mkdtemp(dir=str(output_path.parent), prefix=".taskhub-redis-rdb-"))
    try:
        os.chmod(private_tmp_dir, 0o700)
    except OSError:
        pass
    tmp_path = private_tmp_dir / "dump.rdb.tmp"
    # ADV2 R1 F-008: O_EXCL + O_NOFOLLOW で atomic create
    tmp_fd = os.open(
        str(tmp_path),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    os.close(tmp_fd)
    try:
        st_before = os.lstat(str(tmp_path))
        if not stat.S_ISREG(st_before.st_mode):
            raise BackupRuntimeError(
                "backup_redis_rdb_tmp_not_regular_file",
                detail=f"tmp_path is not regular file: mode={oct(st_before.st_mode)}",
            )
        argv = (
            _compose_argv_prefix(options)
            + ["cp", "redis:/data/dump.rdb", str(tmp_path)]
        )
        config = SafeSubprocessConfig(timeout_sec=timeout_sec)
        result = _run_subprocess_with_tool_check(argv, config, "backup_redis_rdb_tool_not_found")
        if result.returncode != 0:
            shutil.rmtree(private_tmp_dir, ignore_errors=True)
            return result
        st_after = os.lstat(str(tmp_path))
        if not stat.S_ISREG(st_after.st_mode):
            raise BackupRuntimeError(
                "backup_redis_rdb_tmp_not_regular_file",
                detail="tmp_path mutated to non-regular file after docker compose cp",
            )
    except (OSError, BackupRuntimeError):
        shutil.rmtree(private_tmp_dir, ignore_errors=True)
        raise
    # fsync + atomic rename + parent fsync (ADV2 R1 F-008 durability)
    try:
        with tmp_path.open("rb+") as f:
            os.fsync(f.fileno())
    except OSError:
        pass
    os.replace(str(tmp_path), str(output_path))
    try:
        parent_fd = os.open(str(output_path.parent), os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except OSError:
        pass
    shutil.rmtree(private_tmp_dir, ignore_errors=True)
    return result


def stop_app_services_via_compose_exec(
    options: BackupOptions, *, timeout_sec: int = 60,
) -> None:
    """SP022-T02 Phase 5 ADV R1 F-001 + R2 F-003 CRITICAL adopt: backup 中の api/worker stop.

    ADR-00021 §11.2 consistency boundary 確立。stop 失敗は致命的 (BackupRuntimeError)。
    """
    argv = _compose_argv_prefix(options) + ["stop", "--timeout=30", "api", "worker"]
    config = SafeSubprocessConfig(timeout_sec=timeout_sec)
    result = _run_subprocess_with_tool_check(argv, config, "backup_service_stop_failed")
    if result.returncode != 0:
        raise BackupRuntimeError(
            "backup_service_stop_failed",
            detail=f"stop_app_services failed: exit={result.returncode}",
        )


def start_app_services_wait_healthy_via_compose_exec(
    options: BackupOptions, *, timeout_sec: int = 180,
) -> None:
    """SP022-T02 Phase 5 ADV R1 F-001 + R2 F-003 + R6 F-002 + ADV2 R1 F-010 + R2 F-005 adopt.

    backup 完了後の api/worker 再起動 + healthy polling。restart 失敗は致命的。
    Service field exact match (api / worker) + Health=healthy 待ち + timeout 内に healthy にならなければ fatal。
    """
    up_argv = _compose_argv_prefix(options) + ["up", "-d", "api", "worker"]
    up_result = _run_subprocess_with_tool_check(
        up_argv,
        SafeSubprocessConfig(timeout_sec=timeout_sec // 3),
        "backup_service_start_failed",
    )
    if up_result.returncode != 0:
        raise BackupRuntimeError(
            "backup_service_start_failed",
            detail=f"start_app_services up failed: exit={up_result.returncode}",
        )
    # healthcheck polling (ADV2 R1 F-010 + R2 F-005 adopt)
    import time as _time  # local import で test 時 monkeypatch しやすく
    deadline = _time.monotonic() + timeout_sec // 2
    while _time.monotonic() < deadline:
        ps_argv = _compose_argv_prefix(options) + [
            "ps", "--format", "json", "--status", "running", "api", "worker",
        ]
        ps_result = _run_subprocess_with_tool_check(
            ps_argv,
            SafeSubprocessConfig(timeout_sec=10),
            "backup_service_start_failed",
        )
        if ps_result.returncode == 0 and _parse_compose_ps_healthy(ps_result.stdout, {"api", "worker"}):
            return
        _time.sleep(2)
    raise BackupRuntimeError(
        "backup_service_start_failed",
        detail=f"api/worker not healthy within {timeout_sec // 2}s polling",
    )


def _parse_compose_ps_healthy(stdout: bytes, target_services: set[str]) -> bool:
    """docker compose ps --format json の output から target services が healthy か判定.

    ADV2 R2 F-005 CRITICAL adopt: Service field primary key (Name は container name で乖離する)。
    JSON-array / JSON-lines 両形式に対応 (compose v2 系 format fluctuation 配慮)。
    """
    text = stdout.decode("utf-8", errors="replace")
    entries: list[dict[str, Any]] = []
    # try JSON array first
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            entries = [e for e in parsed if isinstance(e, dict)]
        elif isinstance(parsed, dict):
            entries = [parsed]
    except json.JSONDecodeError:
        # JSON-lines fallback
        for line in text.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    entries.append(obj)
            except json.JSONDecodeError:
                continue
    healthy_services: set[str] = set()
    for entry in entries:
        service = entry.get("Service")
        health = entry.get("Health")
        if isinstance(service, str) and service in target_services:
            if isinstance(health, str) and health == "healthy":
                healthy_services.add(service)
    return target_services.issubset(healthy_services)


# --- ADV2 R6 F-003 + R7 F-002/F-003 + R8 F-001/F-002 + R11 F-002: artifacts_dir tree helpers ---


def _verified_copy_tree_no_follow(
    *,
    src: Path,
    dst: Path,
    root_lstat_anchor: os.stat_result,
    source_mode_sidecar_path: Path,
) -> None:
    """ADV2 R5 F-002 + R6 F-002/F-003 + R7 F-002 + R8 F-002 + R11 F-002 CRITICAL adopt.

    src tree を no-follow walk して dst に O_EXCL/O_NOFOLLOW で copy。
    - regular file / directory のみ accept、symlink / FIFO / socket / device は reject (R11 F-002)
    - reserved name `_artifacts_source_mode.json` は source-side で reject (R8 F-002)
    - source mode (lstat) を sidecar に書き出す (staging tree の外、R8 F-002)
    - per-file 256 MiB + tree 4 GiB limit (R6 F-003)
    - root lstat anchor 再検証 (root rename/symlink swap 検知、R7 F-002)
    """
    # root anchor 再検証
    current_root_st = os.lstat(str(src))
    if (
        current_root_st.st_dev != root_lstat_anchor.st_dev
        or current_root_st.st_ino != root_lstat_anchor.st_ino
    ):
        raise BackupRuntimeError(
            "backup_artifacts_staging_tampered",
            detail=f"artifacts root dev/ino changed after lock acquisition: {src}",
        )
    source_mode_entries: list[dict[str, Any]] = []
    total_bytes = 0

    def _walk(src_dir: Path, dst_dir: Path, rel_prefix: str) -> None:
        nonlocal total_bytes
        os.makedirs(dst_dir, mode=0o700, exist_ok=False)
        for entry in sorted(os.scandir(str(src_dir)), key=lambda e: e.name):
            if entry.name == _ARTIFACTS_SOURCE_MODE_SIDECAR_NAME:
                raise BackupRuntimeError(
                    "backup_artifacts_source_reserved_name",
                    detail=f"source tree contains reserved name: {rel_prefix}{entry.name}",
                )
            rel = f"{rel_prefix}{entry.name}"
            st = os.lstat(entry.path)
            mode = stat.S_IMODE(st.st_mode)
            if stat.S_ISDIR(st.st_mode):
                source_mode_entries.append({"path": rel, "type": "dir", "mode": mode})
                _walk(Path(entry.path), dst_dir / entry.name, rel + "/")
            elif stat.S_ISREG(st.st_mode):
                if st.st_size > MAX_ARTIFACT_FILE_BYTES:
                    raise BackupRuntimeError(
                        "backup_artifacts_file_too_large",
                        detail=f"per-file size {st.st_size} > {MAX_ARTIFACT_FILE_BYTES}: {rel}",
                    )
                total_bytes += st.st_size
                if total_bytes > MAX_ARTIFACT_TREE_BYTES:
                    raise BackupRuntimeError(
                        "backup_artifacts_tree_too_large",
                        detail=f"tree total {total_bytes} > {MAX_ARTIFACT_TREE_BYTES}",
                    )
                # O_RDONLY | O_NOFOLLOW で source 読込
                src_fd = os.open(entry.path, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    # O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW で dst 書込 (0o400)
                    dst_path = dst_dir / entry.name
                    dst_fd = os.open(
                        str(dst_path),
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o400,
                    )
                    try:
                        hasher = hashlib.sha256()
                        while True:
                            chunk = os.read(src_fd, 65536)
                            if not chunk:
                                break
                            # Codex PR #80 R3 F-011 P2 adopt: partial write 検出 + 完全書き込み保証
                            # os.write は I/O pressure / interrupt で partial 完了可、loop で残量書き込み
                            remaining = chunk
                            while remaining:
                                written = os.write(dst_fd, remaining)
                                if written <= 0:
                                    raise BackupRuntimeError(
                                        "backup_artifacts_staging_tampered",
                                        detail=(
                                            f"partial write or write returned {written} for {rel}, "
                                            "potential staged file corruption"
                                        ),
                                    )
                                remaining = remaining[written:]
                            hasher.update(chunk)
                        os.fsync(dst_fd)
                    finally:
                        os.close(dst_fd)
                    source_mode_entries.append({
                        "path": rel,
                        "type": "file",
                        "sha256": hasher.hexdigest(),
                        "mode": mode,
                        "size": st.st_size,
                    })
                finally:
                    os.close(src_fd)
            else:
                # symlink / FIFO / socket / device は reject (R11 F-002 で symlink 全面 reject)
                raise BackupRuntimeError(
                    "backup_artifacts_source_unsupported_file_type",
                    detail=f"unsupported entry type at {rel} (only regular file / directory allowed)",
                )

    _walk(src, dst, "")
    # source mode sidecar を staging tree の外 (verified_temp_dir 直下) に書出
    source_mode_sidecar_path.write_text(
        json.dumps({
            "manifest_version": 1,
            "files": source_mode_entries,
            "total_files": len(source_mode_entries),
            "total_bytes": total_bytes,
        }, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    try:
        os.chmod(source_mode_sidecar_path, 0o400)
    except OSError:
        pass


def _compute_artifacts_dir_manifest_sha256(
    dir_path: Path,
    *,
    mode_source: Literal["lstat", "source_lstat"],
    source_mode_sidecar_path: Path | None = None,
) -> str:
    """ADV2 R5 F-002 + R6 F-003 + R7 F-003 + R8 F-001/F-002 + R11 F-002 CRITICAL adopt.

    artifacts tree の manifest を canonical JCS canonical JSON → SHA-256 で計算。
    mode_source="lstat": source tree を直接 walk、各 entry の lstat mode を canonical entry に
    mode_source="source_lstat": staging tree を walk + sidecar から source mode を読込
    """
    if mode_source == "source_lstat":
        if source_mode_sidecar_path is None or not source_mode_sidecar_path.is_file():
            raise BackupRuntimeError(
                "backup_compose_binding_not_initialized",
                detail="source_mode_sidecar_path required for mode_source='source_lstat'",
            )
        # Codex PR #80 R3 F-010 P1 CRITICAL adopt: sidecar JSON だけを hash する旧経路を排除、
        # staged tree を walk して **各 file の実 sha256 を再計算** + sidecar 内 sha256 と比較
        # (same-UID tamper で staged content 変更 + sidecar untouched 攻撃を検知)。
        sidecar_text = source_mode_sidecar_path.read_text(encoding="utf-8")
        sidecar_data = json.loads(sidecar_text)
        sidecar_files = {f["path"]: f for f in sidecar_data.get("files", []) if isinstance(f, dict)}
        # staged tree walk + per-file sha256 再計算 + sidecar entry と一致 verify
        staged_entries: list[dict[str, Any]] = []
        staged_total_bytes = 0

        def _walk_staged(d: Path, prefix: str) -> None:
            nonlocal staged_total_bytes
            for entry in sorted(os.scandir(str(d)), key=lambda e: e.name):
                rel = f"{prefix}{entry.name}"
                st_entry = os.lstat(entry.path)
                if stat.S_ISDIR(st_entry.st_mode):
                    # sidecar entry verify
                    expected = sidecar_files.get(rel)
                    if expected is None or expected.get("type") != "dir":
                        raise BackupRuntimeError(
                            "backup_artifacts_staging_tampered",
                            detail=f"staged dir not in sidecar: {rel}",
                        )
                    staged_entries.append({"path": rel, "type": "dir", "mode": expected["mode"]})
                    _walk_staged(Path(entry.path), rel + "/")
                elif stat.S_ISREG(st_entry.st_mode):
                    expected = sidecar_files.get(rel)
                    if expected is None or expected.get("type") != "file":
                        raise BackupRuntimeError(
                            "backup_artifacts_staging_tampered",
                            detail=f"staged file not in sidecar: {rel}",
                        )
                    # staged file 実 sha256 を chunked 再計算
                    hasher = hashlib.sha256()
                    with open(entry.path, "rb") as fobj:  # noqa: PTH123 — chunked
                        while True:
                            chunk = fobj.read(65536)
                            if not chunk:
                                break
                            hasher.update(chunk)
                    actual_sha = hasher.hexdigest()
                    if actual_sha != expected.get("sha256"):
                        raise BackupRuntimeError(
                            "backup_artifacts_staging_tampered",
                            detail=(
                                f"staged file sha256 mismatch at {rel}: "
                                f"sidecar={expected.get('sha256', '')[:16]}, "
                                f"staged={actual_sha[:16]}"
                            ),
                        )
                    if st_entry.st_size != expected.get("size"):
                        raise BackupRuntimeError(
                            "backup_artifacts_staging_tampered",
                            detail=f"staged file size mismatch at {rel}",
                        )
                    staged_total_bytes += st_entry.st_size
                    staged_entries.append({
                        "path": rel, "type": "file",
                        "sha256": actual_sha,
                        "mode": expected["mode"],  # source lstat mode (sidecar から)
                        "size": expected["size"],
                    })
                else:
                    # symlink / device / FIFO / socket は staging tree に存在しないはず (copy 時 reject)
                    raise BackupRuntimeError(
                        "backup_artifacts_staging_tampered",
                        detail=f"staged tree unexpected entry type at {rel}",
                    )

        _walk_staged(dir_path, "")
        # sidecar 内 entry が staged tree に全て存在するか (delete 攻撃検知)
        staged_paths = {e["path"] for e in staged_entries}
        sidecar_paths = set(sidecar_files.keys())
        if staged_paths != sidecar_paths:
            missing = sidecar_paths - staged_paths
            extra = staged_paths - sidecar_paths
            raise BackupRuntimeError(
                "backup_artifacts_staging_tampered",
                detail=f"staged tree drift: missing={sorted(missing)[:3]} extra={sorted(extra)[:3]}",
            )
        manifest_dict = {
            "manifest_version": 1,
            "files": staged_entries,
            "total_files": len(staged_entries),
            "total_bytes": staged_total_bytes,
        }
        canonical = json.dumps(manifest_dict, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    # mode_source == "lstat" → source tree walk
    entries: list[dict[str, Any]] = []
    total_bytes = 0

    def _walk(d: Path, prefix: str) -> None:
        nonlocal total_bytes
        for entry in sorted(os.scandir(str(d)), key=lambda e: e.name):
            if entry.name == _ARTIFACTS_SOURCE_MODE_SIDECAR_NAME:
                raise BackupRuntimeError(
                    "backup_artifacts_source_reserved_name",
                    detail=f"source tree contains reserved name: {prefix}{entry.name}",
                )
            rel = f"{prefix}{entry.name}"
            st = os.lstat(entry.path)
            mode = stat.S_IMODE(st.st_mode)
            if stat.S_ISDIR(st.st_mode):
                entries.append({"path": rel, "type": "dir", "mode": mode})
                _walk(Path(entry.path), rel + "/")
            elif stat.S_ISREG(st.st_mode):
                if st.st_size > MAX_ARTIFACT_FILE_BYTES:
                    raise BackupRuntimeError(
                        "backup_artifacts_file_too_large",
                        detail=f"per-file size {st.st_size} > {MAX_ARTIFACT_FILE_BYTES}: {rel}",
                    )
                total_bytes += st.st_size
                if total_bytes > MAX_ARTIFACT_TREE_BYTES:
                    raise BackupRuntimeError(
                        "backup_artifacts_tree_too_large",
                        detail=f"tree total {total_bytes} > {MAX_ARTIFACT_TREE_BYTES}",
                    )
                # chunked hashing
                hasher = hashlib.sha256()
                with open(entry.path, "rb") as f:  # noqa: PTH123 — chunked streaming
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        hasher.update(chunk)
                entries.append({
                    "path": rel,
                    "type": "file",
                    "sha256": hasher.hexdigest(),
                    "mode": mode,
                    "size": st.st_size,
                })
            else:
                raise BackupRuntimeError(
                    "backup_artifacts_source_unsupported_file_type",
                    detail=f"unsupported entry type at {rel}",
                )

    _walk(dir_path, "")
    manifest_dict = {
        "manifest_version": 1,
        "files": entries,
        "total_files": len(entries),
        "total_bytes": total_bytes,
    }
    canonical = json.dumps(manifest_dict, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- ADV2 R3 F-002 + R5 F-001 + R7 F-001: fingerprint helpers ---


def compute_backup_runtime_binding_fingerprint(
    options: BackupOptions,
    *,
    compose_file_sha256: str,
    sops_env_sha256: str | None,
    compose_config_canonical_sha256: str,
    env_file_sha256: str | None,
    artifacts_dir_manifest_sha256: str,
) -> str:
    """ADV2 R3 F-002 + R5 F-001 + R6 F-001/F-002 + R7 F-001 CRITICAL adopt.

    BackupApprovalClaim 6 整合に Compose binding + payload source binding を含める fingerprint.
    private helper、外部から直接呼出禁止 (compute_full_backup_runtime_binding_fingerprint 経由のみ)。
    """
    realpath = options.target_compose_file_path.resolve(strict=True)
    context = {
        "target_compose_project_name": options.target_compose_project_name,
        "target_compose_file_realpath": str(realpath),
        "target_compose_file_sha256": compose_file_sha256,
        "target_compose_project_directory": str(realpath.parent),
        # ADV2 R6 F-002: immutable snapshot から (caller-controlled rename swap を排除)
        "artifacts_dir_realpath": str(
            options.artifacts_dir_realpath_snapshot
            if options.artifacts_dir_realpath_snapshot is not None
            else options.artifacts_dir.resolve(strict=True)
        ),
        "artifacts_dir_manifest_sha256": artifacts_dir_manifest_sha256,
        "sops_env_path_realpath": (
            str(options.sops_env_path.resolve(strict=True)) if options.include_sops_env else None
        ),
        "sops_env_sha256": sops_env_sha256 if options.include_sops_env else None,
        # ADV2 R5 F-001: env_file canonical 必須化
        "env_file_realpath": (
            str(options.env_file_path.resolve(strict=True)) if options.env_file_path is not None else None
        ),
        "env_file_sha256": env_file_sha256 if options.env_file_path is not None else None,
        "compose_config_canonical_sha256": compose_config_canonical_sha256,
        "pg_user": options.pg_user,
        "pg_db": options.pg_db,
        "postgres_service_name": "postgres",
        "redis_service_name": "redis",
    }
    canonical = json.dumps(context, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _redact_compose_env_values(yaml_text: str) -> str:
    """ADV2 R1 F-003 adopt: docker compose config 出力から secret env value を redact.

    `KEY: "secret"` style の value を `<redacted>` に置換、binding は key set + non-secret structure のみ。
    """
    # 簡易: environment 配下の `KEY: value` の value を <redacted> に置換 (heuristic、完全な YAML parser は使わない)
    redacted = re.sub(
        r'^(\s+)([A-Z_][A-Z0-9_]*):\s+(?:"[^"]*"|\'[^\']*\'|[^\s].*)$',
        r'\1\2: "<redacted>"',
        yaml_text,
        flags=re.MULTILINE,
    )
    return redacted


def compute_compose_config_canonical_sha256_for_issue(
    options: BackupOptions,
    *,
    source_compose_path: Path,
    source_env_file_path: Path | None,
    source_project_dir: Path,
    timeout_sec: int = 30,
) -> str:
    """ADV2 R1 F-003 + R2 F-003 CRITICAL adopt: approval issue 段階用 canonical hash.

    issue 段階では verified copy 未作成のため、source path を直接渡して docker compose config を実行。
    """
    argv = [
        "docker", "compose",
        "-p", options.target_compose_project_name,
        "-f", str(source_compose_path),
        "--project-directory", str(source_project_dir),
    ]
    if source_env_file_path is not None:
        argv.extend(["--env-file", str(source_env_file_path)])
    argv.extend(["config", "--resolve-image-digests"])
    config = SafeSubprocessConfig(timeout_sec=timeout_sec)
    result = _run_subprocess_with_tool_check(argv, config, "backup_compose_config_failed")
    if result.returncode != 0:
        raise BackupRuntimeError(
            "backup_compose_config_failed",
            detail=f"docker compose config failed (issue): exit={result.returncode}",
        )
    return hashlib.sha256(
        _redact_compose_env_values(result.stdout.decode("utf-8", errors="replace")).encode("utf-8")
    ).hexdigest()


def compute_compose_config_canonical_sha256_for_redeem(
    options: BackupOptions, *, timeout_sec: int = 30,
) -> str:
    """ADV2 R1 F-003 + R2 F-003 CRITICAL adopt: lock 内 redeem 用 canonical hash.

    redeem 段階では verified copy bind 済、_compose_argv_prefix 経由で docker compose config を実行。
    """
    argv = _compose_argv_prefix(options) + ["config", "--resolve-image-digests"]
    config = SafeSubprocessConfig(timeout_sec=timeout_sec)
    result = _run_subprocess_with_tool_check(argv, config, "backup_compose_config_failed")
    if result.returncode != 0:
        raise BackupRuntimeError(
            "backup_compose_config_failed",
            detail=f"docker compose config failed (redeem): exit={result.returncode}",
        )
    return hashlib.sha256(
        _redact_compose_env_values(result.stdout.decode("utf-8", errors="replace")).encode("utf-8")
    ).hexdigest()


def compute_full_backup_runtime_binding_fingerprint(
    options: BackupOptions,
    *,
    mode: Literal["issue", "redeem"],
    source_compose_path: Path | None = None,
    source_env_file_path: Path | None = None,
    source_project_dir: Path | None = None,
) -> str:
    """ADV2 R3 F-001 + R4 F-001/F-002 + R7 F-001 + R9 F-002 CRITICAL adopt: single full-helper.

    issue / redeem 両 mode で同 canonical algorithm を保証。private helper への直接呼出を排除し、
    本 helper のみを正本にする (broker / CLI / redeem 3 経路で同 algorithm 維持)。
    """
    if mode == "issue":
        if source_compose_path is None or source_project_dir is None:
            raise BackupRuntimeError(
                "backup_compose_binding_not_initialized",
                detail="issue mode requires source_compose_path + source_project_dir",
            )
        # ADV2 R9 F-002 cross-field invariant
        if options.env_file_path is not None and source_env_file_path is None:
            raise BackupRuntimeError(
                "backup_compose_binding_not_initialized",
                detail="options.env_file_path is set but source_env_file_path missing for issue fingerprint",
            )
        if options.env_file_path is None and source_env_file_path is not None:
            raise BackupRuntimeError(
                "backup_compose_binding_not_initialized",
                detail="source_env_file_path passed but options.env_file_path is None (invariant violation)",
            )
        compose_file_sha256 = hashlib.sha256(source_compose_path.read_bytes()).hexdigest()
        sops_env_sha256 = (
            hashlib.sha256(options.sops_env_path.read_bytes()).hexdigest()
            if options.include_sops_env else None
        )
        env_file_sha256 = (
            hashlib.sha256(source_env_file_path.read_bytes()).hexdigest()
            if source_env_file_path is not None else None
        )
        compose_config_canonical = compute_compose_config_canonical_sha256_for_issue(
            options,
            source_compose_path=source_compose_path,
            source_env_file_path=source_env_file_path,
            source_project_dir=source_project_dir,
        )
        artifacts_dir_manifest_sha256 = _compute_artifacts_dir_manifest_sha256(
            options.artifacts_dir, mode_source="lstat",
        )
    else:  # redeem
        if options.verified_compose_execution_input is None:
            raise BackupRuntimeError(
                "backup_compose_binding_not_initialized",
                detail="redeem mode requires verified_compose_execution_input bound",
            )
        compose_file_sha256 = hashlib.sha256(
            options.verified_compose_execution_input.read_bytes()
        ).hexdigest()
        # ADV2 R6 F-001: verified sops_env copy から計算 (source path 再読込禁止)
        if options.include_sops_env:
            if options.verified_sops_env_execution_input is None:
                raise BackupRuntimeError(
                    "backup_compose_binding_not_initialized",
                    detail="verified_sops_env_execution_input must be bound before redeem fingerprint",
                )
            _verify_metadata_snapshot(
                options.verified_sops_env_execution_input,
                options.verified_sops_env_metadata_snapshot,
                tamper_reason="backup_payload_source_tampered",
            )
            sops_env_sha256 = hashlib.sha256(
                options.verified_sops_env_execution_input.read_bytes()
            ).hexdigest()
        else:
            sops_env_sha256 = None
        # ADV2 R9 F-002 cross-field invariant (redeem)
        if options.env_file_path is not None:
            if (
                options.verified_env_file_execution_input is None
                or options.verified_env_file_metadata_snapshot is None
            ):
                raise BackupRuntimeError(
                    "backup_compose_binding_not_initialized",
                    detail=(
                        "options.env_file_path is set but verified_env_file_execution_input "
                        "/ metadata_snapshot not bound for redeem"
                    ),
                )
            env_file_sha256 = hashlib.sha256(
                options.verified_env_file_execution_input.read_bytes()
            ).hexdigest()
        else:
            if options.verified_env_file_execution_input is not None:
                raise BackupRuntimeError(
                    "backup_compose_binding_not_initialized",
                    detail="verified_env_file_execution_input bound but options.env_file_path is None",
                )
            env_file_sha256 = None
        compose_config_canonical = compute_compose_config_canonical_sha256_for_redeem(options)
        if options.verified_artifacts_staging_dir is None or options.verified_artifacts_manifest_sha256 is None:
            raise BackupRuntimeError(
                "backup_compose_binding_not_initialized",
                detail="verified_artifacts_staging_dir / manifest_sha256 must be bound before redeem fingerprint",
            )
        artifacts_dir_manifest_sha256 = _compute_artifacts_dir_manifest_sha256(
            options.verified_artifacts_staging_dir,
            mode_source="source_lstat",
            source_mode_sidecar_path=options.verified_artifacts_source_mode_sidecar_path,
        )
        if artifacts_dir_manifest_sha256 != options.verified_artifacts_manifest_sha256:
            raise BackupRuntimeError(
                "backup_artifacts_staging_tampered",
                detail=(
                    f"verified artifacts manifest mismatch in redeem: "
                    f"snapshot={options.verified_artifacts_manifest_sha256[:16]}, "
                    f"current={artifacts_dir_manifest_sha256[:16]}"
                ),
            )

    return compute_backup_runtime_binding_fingerprint(
        options,
        compose_file_sha256=compose_file_sha256,
        sops_env_sha256=sops_env_sha256,
        compose_config_canonical_sha256=compose_config_canonical,
        env_file_sha256=env_file_sha256,
        artifacts_dir_manifest_sha256=artifacts_dir_manifest_sha256,
    )


def _run_subprocess_with_tool_check(
    argv: list[str],
    config: SafeSubprocessConfig,
    not_found_reason: ReasonCode,
) -> SubprocessResult:
    try:
        return run_safe_subprocess(argv, config=config)
    except SubprocessNotFoundError:
        raise BackupToolNotFoundError(
            not_found_reason,
            detail=f"command={argv[0]}",
        ) from None
    except SubprocessTimeoutError as exc:
        raise BackupRuntimeError(
            "backup_unexpected_error",
            detail=f"timeout: {exc.command_name} ({exc.timeout_sec}s)",
        ) from None


# --- meta.json acquisition (F-008 adopt) ---


def acquire_postgres_version() -> str:
    """pg_dump --version 出力から version parse。"""
    try:
        result = run_safe_subprocess(
            ["pg_dump", "--version"],
            config=SafeSubprocessConfig(timeout_sec=10),
        )
    except SubprocessNotFoundError:
        raise BackupToolNotFoundError(
            "backup_pg_dump_tool_not_found",
            detail="pg_dump",
        ) from None
    if result.returncode != 0:
        raise BackupRuntimeError(
            "backup_meta_json_acquisition_failed",
            detail=f"pg_dump_version_exit={result.returncode}",
        )
    output = result.stdout.decode("utf-8", errors="replace")
    m = _PG_VERSION_RE.search(output)
    if not m:
        raise BackupRuntimeError(
            "backup_meta_json_acquisition_failed",
            detail="pg_version_parse_failed",
        )
    return m.group(1)


def acquire_redis_version(redis_host: str, redis_port: int) -> str:
    """redis-cli INFO server 出力から redis_version parse。"""
    try:
        result = run_safe_subprocess(
            ["redis-cli", "-h", redis_host, "-p", str(redis_port), "INFO", "server"],
            config=SafeSubprocessConfig(timeout_sec=10),
        )
    except SubprocessNotFoundError:
        raise BackupToolNotFoundError(
            "backup_redis_rdb_tool_not_found",
            detail="redis-cli",
        ) from None
    if result.returncode != 0:
        raise BackupRuntimeError(
            "backup_meta_json_acquisition_failed",
            detail=f"redis_info_exit={result.returncode}",
        )
    output = result.stdout.decode("utf-8", errors="replace")
    m = _REDIS_VERSION_RE.search(output)
    if not m:
        raise BackupRuntimeError(
            "backup_meta_json_acquisition_failed",
            detail="redis_version_parse_failed",
        )
    return m.group(1)


def acquire_alembic_head(repo_root: Path | None = None) -> str:
    """alembic current 出力から head revision parse。"""
    cwd = repo_root or Path.cwd()
    try:
        result = run_safe_subprocess(
            ["alembic", "current"],
            config=SafeSubprocessConfig(timeout_sec=30, cwd=cwd),
        )
    except SubprocessNotFoundError:
        raise BackupToolNotFoundError(
            "backup_meta_json_acquisition_failed",
            detail="alembic",
        ) from None
    if result.returncode != 0:
        raise BackupRuntimeError(
            "backup_meta_json_acquisition_failed",
            detail=f"alembic_current_exit={result.returncode}",
        )
    output = result.stdout.decode("utf-8", errors="replace").strip()
    # alembic current 出力 format: "<revision> (head)" or just "<revision>"
    first_token = output.split()[0] if output else ""
    if not first_token:
        raise BackupRuntimeError(
            "backup_meta_json_acquisition_failed",
            detail="alembic_current_empty",
        )
    return first_token


# --- orchestration ---


def _copy_artifacts_with_allowlist(
    artifacts_dir: Path, dest_dir: Path,
) -> int:
    """artifacts_dir 配下を walk、allowlist 経由で copy。

    F-001 adopt: 各 file を check_archive_allowed で verify、reject 時は raise。

    Returns:
        Number of files copied.
    """
    if not artifacts_dir.exists():
        return 0
    count = 0
    for src in artifacts_dir.rglob("*"):
        if src.is_dir():
            continue
        relative_from_artifacts = src.relative_to(artifacts_dir).as_posix()
        # archive-internal relative path: "artifacts/<relative_from_artifacts>"
        archive_relative = f"artifacts/{relative_from_artifacts}"
        allowed, reason = check_archive_allowed(archive_relative, src)
        if not allowed:
            raise BackupRuntimeError(
                "backup_archive_allowlist_violation",
                detail=f"path={archive_relative} reason={reason}",
            )
        dest = dest_dir / relative_from_artifacts
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        count += 1
    return count


def _create_tar_archive(source_dir: Path, output_path: Path) -> int:
    """Python stdlib tarfile で deterministic tar (F-001 + F-012 adopt: symlink dereference false)。

    Returns:
        Number of entries in the archive.
    """
    entry_count = 0
    try:
        with tarfile.open(output_path, "w", dereference=False) as tar:
            # deterministic order: sort by archive name
            entries: list[tuple[str, Path]] = []
            for src in source_dir.rglob("*"):
                if src.is_symlink():
                    raise BackupRuntimeError(
                        "backup_archive_allowlist_violation",
                        detail=f"symlink_in_tmp:{src.name}",
                    )
                arcname = src.relative_to(source_dir).as_posix()
                entries.append((arcname, src))
            entries.sort()
            for arcname, src in entries:
                tar.add(str(src), arcname=arcname, recursive=False)
                entry_count += 1
    except OSError as exc:
        raise BackupRuntimeError(
            "backup_artifacts_tar_failed",
            detail=f"tar_io_error: {type(exc).__name__}",
        ) from None
    return entry_count


def run_backup(
    options: BackupOptions,
    *,
    phase_5_mode: bool = False,
    record_backup_claim: object = None,  # ADV2 R11 F-001 + R13 F-001: Phase 5 必須 (BackupApprovalClaim or None)
    verified_temp_dir: Path | None = None,  # ADV2 R11 F-001: Phase 5 必須
) -> BackupResult:
    """backup orchestration entry point。

    SP022-T02 Phase 5 で `phase_5_mode=True` を渡すと docker compose exec 経路を使う:
    - host TCP + PGPASSFILE → docker compose exec + container 内 unix socket + trust auth
    - host tar copy → verified staging tree (post-stop window 内、no-follow walk)
    - host redis-cli --rdb → redis-cli SAVE + docker compose cp + private tmp dir

    ADV2 R11 F-001 + R13 F-001 CRITICAL adopt: phase_5_mode=True 時は record_backup_claim と
    verified_temp_dir が必須、入口で legacy claim (fingerprint=None) を reject (defense-in-depth)。

    PR #77 backward compat: phase_5_mode=False (default) は既存 host TCP / PGPASSFILE 経路維持。
    """
    import time
    start = time.monotonic()

    # F-005 + F-PR77-002 adopt: output_path validation + .part suffix policy
    # `.tar.age` 拡張子チェーン (suffix chain `[".tar", ".age"]`) を厳密 verify
    suffixes = options.output_path.suffixes
    if not (len(suffixes) >= 2 and suffixes[-2:] == [".tar", ".age"]):
        raise BackupUsageError(
            "backup_output_path_invalid",
            detail="must end with .tar.age",
        )
    if not options.output_path.parent.exists():
        raise BackupUsageError(
            "backup_output_path_invalid",
            detail=f"parent_not_exist: {options.output_path.parent}",
        )
    if options.output_path.exists() and not options.overwrite:
        raise BackupUsageError(
            "backup_output_already_exists",
            detail="use --overwrite to replace",
        )

    if phase_5_mode:
        # ADV2 R13 F-001 + R14 F-002 CRITICAL adopt: Phase 5 必須引数 + legacy reject
        if record_backup_claim is None or verified_temp_dir is None:
            raise BackupRuntimeError(
                "backup_compose_binding_not_initialized",
                detail="phase_5_mode requires record_backup_claim and verified_temp_dir",
            )
        if getattr(record_backup_claim, "backup_runtime_binding_fingerprint", None) is None:
            raise BackupRuntimeError(
                "backup_claim_legacy_runtime_binding_unsupported",
                detail=(
                    "run_backup received legacy 5-field BackupApprovalClaim (fingerprint=None). "
                    "Phase 5 requires 6-field record. Re-issue via taskhub approval issue."
                ),
            )
    else:
        # F-PR77-003 adopt: PR #77 経路では PGPASSFILE は **必須**、~/.pgpass 暗黙 fallback 禁止
        if options.pgpassfile_path is None:
            raise BackupUsageError(
                "backup_output_path_invalid",
                detail=(
                    "pgpassfile_path required (set TASKHUB_BACKUP_PGPASSFILE env or pass "
                    "explicitly); ~/.pgpass implicit fallback is denied"
                ),
            )
        pgpass = options.pgpassfile_path
        if pgpass.is_symlink():
            raise BackupUsageError(
                "backup_output_path_invalid",
                detail=f"pgpassfile must not be symlink: {pgpass}",
            )
        if not pgpass.is_file():
            raise BackupUsageError(
                "backup_output_path_invalid",
                detail=f"pgpassfile not found or not regular file: {pgpass}",
            )
        pgpass_mode = stat.S_IMODE(pgpass.stat().st_mode)
        if pgpass_mode not in (0o600, 0o400):
            raise BackupUsageError(
                "backup_output_path_invalid",
                detail=f"pgpassfile permission must be 0600 or 0400 (got 0o{pgpass_mode:o})",
            )

    tmp_dir = resolve_backup_temp_layout()
    warnings_list: list[WarningCode] = []
    part_path = options.output_path.with_name(options.output_path.name + ".part")
    primary_exc: Exception | None = None
    stopped_or_attempted = False

    try:
        # ADV2 R1 F-004 + R11 F-001 CRITICAL adopt: stop も try 内に移動 + stopped_or_attempted flag
        # Phase 5 service stop は consistency boundary 確立のため artifacts staging より **前** に実行
        if phase_5_mode and not options.skip_service_stop:
            stopped_or_attempted = True
            stop_app_services_via_compose_exec(options)
        elif options.skip_service_stop:
            warnings_list.append("backup_service_stop_skipped")

        # ADV2 R11 F-001 + R12 F-001 + R6 F-002 + R8 F-002 CRITICAL adopt: artifacts staging を post-stop で実行
        # (api/worker 稼働中の artifacts snapshot を排除、DB/Redis stop 状態と時間整合確保)
        if phase_5_mode:
            # verified_temp_dir は run_backup signature で必須 (上記入口 check 済)、type narrow
            if verified_temp_dir is None:  # defense-in-depth
                raise BackupRuntimeError(
                    "backup_compose_binding_not_initialized",
                    detail="verified_temp_dir lost between entry check and post-stop block",
                )
            artifacts_dir_realpath_snapshot = options.artifacts_dir.resolve(strict=True)
            verified_artifacts_staging_dir = verified_temp_dir / "artifacts"
            verified_artifacts_source_mode_sidecar_path = (
                verified_temp_dir / "artifacts_source_mode.json"
            )
            _verified_copy_tree_no_follow(
                src=artifacts_dir_realpath_snapshot,
                dst=verified_artifacts_staging_dir,
                root_lstat_anchor=os.lstat(str(artifacts_dir_realpath_snapshot)),
                source_mode_sidecar_path=verified_artifacts_source_mode_sidecar_path,
            )
            verified_artifacts_manifest_sha256 = _compute_artifacts_dir_manifest_sha256(
                verified_artifacts_staging_dir,
                mode_source="source_lstat",
                source_mode_sidecar_path=verified_artifacts_source_mode_sidecar_path,
            )
            # ADV2 R12 F-001: options を post-stop で update (`backup_options` 残存禁止、archive 経路で options 統一)
            options = dataclasses.replace(
                options,
                artifacts_dir_realpath_snapshot=artifacts_dir_realpath_snapshot,
                verified_artifacts_staging_dir=verified_artifacts_staging_dir,
                verified_artifacts_manifest_sha256=verified_artifacts_manifest_sha256,
                verified_artifacts_source_mode_sidecar_path=verified_artifacts_source_mode_sidecar_path,
            )
            # ADV2 R11 F-001 CRITICAL adopt: post-stop で fingerprint verify (artifacts manifest 含む)
            expected_fp = compute_full_backup_runtime_binding_fingerprint(options, mode="redeem")
            claim_fp = getattr(record_backup_claim, "backup_runtime_binding_fingerprint", None)
            if claim_fp != expected_fp:
                raise BackupRuntimeError(
                    "backup_claim_mismatch",
                    detail=(
                        f"backup_runtime_binding_fingerprint post-stop mismatch "
                        f"(claim={(claim_fp or '')[:16]}, "
                        f"computed={expected_fp[:16]})"
                    ),
                )

        # acquire meta.json data (F-008 adopt)
        postgres_version = acquire_postgres_version()
        redis_version = acquire_redis_version(options.redis_host, options.redis_port)
        try:
            repo_root = Path(__file__).resolve().parent.parent
            alembic_head = acquire_alembic_head(repo_root)
        except BackupToolNotFoundError:
            alembic_head = "unknown"

        # postgres/ subdir
        pg_dir = tmp_dir / "postgres"
        pg_dir.mkdir()
        pg_dump_output = pg_dir / "pg_dump.dump"
        if phase_5_mode:
            verify_pg_hba_trust_auth_via_compose_exec(options, timeout_sec=30)
            result = invoke_pg_dump_via_compose_exec(
                options,
                output_path=pg_dump_output,
                timeout_sec=options.pg_dump_timeout_sec,
            )
        else:
            result = invoke_pg_dump(
                pg_host=options.pg_host,
                pg_port=options.pg_port,
                pg_user=options.pg_user,
                pg_db=options.pg_db,
                output_path=pg_dump_output,
                pgpassfile=options.pgpassfile_path,
                timeout_sec=options.pg_dump_timeout_sec,
            )
        if result.returncode != 0:
            raise BackupRuntimeError(
                "backup_pg_dump_failed",
                detail=f"exit={result.returncode}",
            )
        (pg_dir / "alembic_version.txt").write_text(alembic_head + "\n", encoding="utf-8")

        # redis/ subdir
        redis_dir = tmp_dir / "redis"
        redis_dir.mkdir()
        redis_rdb_output = redis_dir / "dump.rdb"
        if phase_5_mode:
            save_result = invoke_redis_save_via_compose_exec(
                options, timeout_sec=options.redis_rdb_timeout_sec,
            )
            if save_result.returncode != 0:
                raise BackupRuntimeError(
                    "backup_redis_rdb_failed",
                    detail=f"redis_save_exit={save_result.returncode}",
                )
            result = invoke_redis_dump_copy_via_compose_cp(
                options,
                output_path=redis_rdb_output,
                timeout_sec=options.redis_rdb_timeout_sec,
            )
        else:
            result = invoke_redis_rdb(
                redis_host=options.redis_host,
                redis_port=options.redis_port,
                output_path=redis_rdb_output,
                timeout_sec=options.redis_rdb_timeout_sec,
            )
        if result.returncode != 0:
            raise BackupRuntimeError(
                "backup_redis_rdb_failed",
                detail=f"exit={result.returncode}",
            )

        # artifacts/ subdir with allowlist enforcement (F-001 adopt)
        # Phase 5 では verified staging から copy (caller-controlled source は一切読まない)
        artifacts_dest = tmp_dir / "artifacts"
        artifacts_dest.mkdir()
        if phase_5_mode:
            # archive 直前 manifest re-verify (ADV2 R7 F-001 CRITICAL adopt)
            # type narrow: phase_5_mode で post-stop block を通った時点で staging fields は bound 済
            if (
                options.verified_artifacts_staging_dir is None
                or options.verified_artifacts_manifest_sha256 is None
            ):
                raise BackupRuntimeError(
                    "backup_compose_binding_not_initialized",
                    detail="verified_artifacts_staging_dir / manifest_sha256 unbound at archive stage",
                )
            current_manifest_sha = _compute_artifacts_dir_manifest_sha256(
                options.verified_artifacts_staging_dir,
                mode_source="source_lstat",
                source_mode_sidecar_path=options.verified_artifacts_source_mode_sidecar_path,
            )
            if current_manifest_sha != options.verified_artifacts_manifest_sha256:
                raise BackupRuntimeError(
                    "backup_artifacts_staging_tampered",
                    detail=(
                        f"verified_artifacts_staging_dir manifest mismatch: "
                        f"expected={options.verified_artifacts_manifest_sha256[:16]}, "
                        f"got={current_manifest_sha[:16]}"
                    ),
                )
            artifact_count = _copy_artifacts_with_allowlist(
                options.verified_artifacts_staging_dir, artifacts_dest,
            )
        else:
            artifact_count = _copy_artifacts_with_allowlist(
                options.artifacts_dir, artifacts_dest,
            )
        if artifact_count == 0:
            warnings_list.append("backup_artifacts_dir_empty")

        # optional env.encrypted
        # Codex PR #80 R3 F-012 P1 CRITICAL adopt: phase_5_mode で verified_sops_env_execution_input
        # (lock 内に read した bytes の immutable copy) から archive、caller-controlled source は読まない
        # (post-lock attack で source 改変 / 削除 → backup が tampered/missing content を含む経路を物理閉鎖)
        if options.include_sops_env:
            if phase_5_mode:
                if options.verified_sops_env_execution_input is None:
                    raise BackupRuntimeError(
                        "backup_compose_binding_not_initialized",
                        detail="phase_5_mode + include_sops_env requires verified_sops_env_execution_input",
                    )
                # metadata snapshot 再検証 (R5 F-002 same-UID swap 検知) 後に verified copy から archive
                _verify_metadata_snapshot(
                    options.verified_sops_env_execution_input,
                    options.verified_sops_env_metadata_snapshot,
                    tamper_reason="backup_payload_source_tampered",
                )
                shutil.copy2(options.verified_sops_env_execution_input, tmp_dir / "env.encrypted")
            elif options.sops_env_path.exists():
                # legacy PR #77 mode (phase_5_mode=False) は従来通り source 直接 copy
                shutil.copy2(options.sops_env_path, tmp_dir / "env.encrypted")
            else:
                warnings_list.append("backup_sops_env_skipped")

        # meta.json + checksums.txt (F-008 + F-012 adopt)
        meta = build_meta_json(
            host_name=options.host_name,
            timestamp_utc=datetime.now(UTC),
            postgres_version=postgres_version,
            redis_version=redis_version,
            alembic_head=alembic_head,
        )
        (tmp_dir / "meta.json").write_text(
            json.dumps(meta, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

        # collect all files for checksums (F-012 adopt: file-only, exclude checksums.txt itself)
        file_paths: dict[str, Path] = {}
        for src in tmp_dir.rglob("*"):
            if src.is_dir():
                continue
            relative = src.relative_to(tmp_dir).as_posix()
            file_paths[relative] = src
        checksums_text = build_checksums_text(file_paths)
        (tmp_dir / "checksums.txt").write_text(checksums_text, encoding="utf-8")

        # tar (F-001 adopt: symlink dereference false)
        tar_tmp_path = tmp_dir.parent / f"{tmp_dir.name}.tar"
        entry_count = _create_tar_archive(tmp_dir, tar_tmp_path)

        try:
            # age encrypt to .part file (F-005 adopt: atomic rename)
            # ADV R3 F-001 CRITICAL adopt: phase_5_mode で verified_recipient を渡す (path 再読込抑止)
            result = invoke_age_encrypt(
                input_path=tar_tmp_path,
                output_path=part_path,
                public_key_path=options.age_public_key_path,
                timeout_sec=options.age_encrypt_timeout_sec,
                verified_recipient=options.verified_age_recipient if phase_5_mode else None,
            )
            if result.returncode != 0:
                raise BackupRuntimeError(
                    "backup_age_encrypt_failed",
                    detail=f"exit={result.returncode}",
                )
        finally:
            tar_tmp_path.unlink(missing_ok=True)

        # atomic rename .part -> final
        os.replace(str(part_path), str(options.output_path))

        # compute output sha256 for result
        output_hasher = hashlib.sha256()
        with options.output_path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                output_hasher.update(chunk)

        duration = time.monotonic() - start
        return BackupResult(
            output_path=options.output_path,
            output_sha256=output_hasher.hexdigest(),
            entry_count=entry_count,
            postgres_version=postgres_version,
            redis_version=redis_version,
            alembic_head=alembic_head,
            reason_code="backup_completed",
            warnings=tuple(warnings_list),
            duration_sec=duration,
        )

    except (BackupUsageError, BackupRuntimeError, BackupToolNotFoundError) as exc:
        # ADV2 R1 F-007 MEDIUM adopt: primary failure reason を保持
        primary_exc = exc
        part_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        # F-002 adopt: unexpected exception でも cleanup
        primary_exc = exc
        part_path.unlink(missing_ok=True)
        raise BackupRuntimeError(
            "backup_unexpected_error",
            detail=f"unexpected: {type(exc).__name__}",
        ) from None
    finally:
        # ADV R1 F-001 + R2 F-003 + R6 F-002 + ADV2 R1 F-007 + R4 F-002 + Codex PR #80 F-004/F-007/F-008 adopt:
        # cleanup を **先** に実行してから restart 試行する順序 (secret-bearing plaintext staging を
        # restart failure 経路で残さない)。
        # Codex PR #80 R2 F-007/F-008 adopt: cleanup failure signal を primary/restart exception と
        # 組み合わせて **必ず stderr/audit に記録** (silent suppress 排除)。
        # F-002: cleanup OSError は audit + raise (silent ignore 廃止)
        cleanup_failure_exc: BackupRuntimeError | None
        try:
            shutil.rmtree(tmp_dir, ignore_errors=False)
        except OSError as exc:
            # secret-bearing tmp が残った場合 → CRITICAL audit + raise (ただし restart 試行は維持)
            cleanup_failure_exc = BackupRuntimeError(
                "backup_tmp_cleanup_failed",
                detail=f"cleanup_oserror: {type(exc).__name__} path={tmp_dir.name}",
            )
        else:
            cleanup_failure_exc = None

        # Codex PR #80 R2 F-007 adopt: cleanup failure は primary_exc 有無に関わらず必ず stderr に記録
        # (secret-bearing data 削除失敗 signal を silent suppress しない、incident response 強化)
        if cleanup_failure_exc is not None:
            sys.stderr.write(
                f"[backup_tmp_cleanup_failed] {cleanup_failure_exc!s} "
                f"(plaintext staging dir may remain: {tmp_dir.name})\n",
            )

        # phase_5_mode で stop が試行された場合は restart を必ず試行 (cleanup 後)
        # restart 失敗は致命的 (warning 流用禁止、consistency boundary 維持)
        if phase_5_mode and stopped_or_attempted:
            try:
                start_app_services_wait_healthy_via_compose_exec(options)
            except BackupRuntimeError as restart_exc:
                # Codex PR #80 R2 F-008 adopt: dual-failure (cleanup + restart) 経路で
                # cleanup_failure_exc を stderr に記録した後に restart raise
                # (cleanup signal を drop しない、operator が両方 incident response 可能)
                if cleanup_failure_exc is not None:
                    sys.stderr.write(
                        f"[backup_tmp_cleanup_failed + backup_service_start_failed dual incident] "
                        f"cleanup_detail={cleanup_failure_exc!s}\n",
                    )
                # primary failure があれば primary 優先 raise + restart failure detail を stderr に記録
                if primary_exc is not None:
                    sys.stderr.write(
                        f"[backup_service_start_failed during recovery] {restart_exc!s}\n"
                        f"[primary_reason] {primary_exc!s}\n",
                    )
                    # primary_exc を propagate (現在 except block で raise 中、上書きせず終了)
                else:
                    # backup 成功 + restart 失敗のみ → restart_exc を propagate
                    raise
        # cleanup 失敗があれば最後に raise (restart が成功した場合のみ)
        if cleanup_failure_exc is not None and primary_exc is None:
            raise cleanup_failure_exc from None


__all__ = [
    "BackupOptions",
    "BackupResult",
    "BackupRuntimeError",
    "BackupToolNotFoundError",
    "BackupUsageError",
    "ReasonCode",
    "WarningCode",
    "_ARCHIVE_DENY_CONTENT_PREFIXES",
    "_ARCHIVE_DENY_FILENAME_PATTERNS",
    "acquire_alembic_head",
    "acquire_postgres_version",
    "acquire_redis_version",
    "build_checksums_text",
    "build_meta_json",
    "check_archive_allowed",
    "invoke_age_encrypt",
    "invoke_pg_dump",
    "invoke_redis_rdb",
    "resolve_backup_temp_layout",
    "run_backup",
]
