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
from datetime import datetime, timezone
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
    "backup_unexpected_error",
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
    # F-PR77-003 adopt: pgpassfile は **必須**、`~/.pgpass` 暗黙 fallback を fail-closed
    # で禁止 (caller が明示 path を指定するか env で渡す)
    pgpassfile_path: Path | None
    pg_dump_timeout_sec: int = PG_DUMP_TIMEOUT_SEC
    redis_rdb_timeout_sec: int = REDIS_RDB_TIMEOUT_SEC
    age_encrypt_timeout_sec: int = AGE_ENCRYPT_TIMEOUT_SEC

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
            pg_user=os.environ.get("TASKHUB_BACKUP_PG_USER", "taskhub"),
            pg_db=os.environ.get("TASKHUB_BACKUP_PG_DB", "taskhub"),
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
                Path(os.environ["TASKHUB_BACKUP_PGPASSFILE"])
                if os.environ.get("TASKHUB_BACKUP_PGPASSFILE")
                else None
            ),
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
    backup_format_version: str = "1",
) -> dict[str, Any]:
    """meta.json builder (F-008 adopt: 取得済 source から組み立て)。"""
    return {
        "backup_format_version": backup_format_version,
        "host": host_name,
        "timestamp": timestamp_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
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
        "--single-transaction",
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
) -> SubprocessResult:
    """age -r <public_key> -o <output> <input> invocation。

    F-001 adopt: argv に public key path のみ、private key は touch しない。
    """
    if not public_key_path.exists():
        raise BackupRuntimeError(
            "backup_age_encrypt_failed",
            detail=f"public_key_not_found: {public_key_path}",
        )
    # Read public key content (age expects key string, not file path for -r)
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


def run_backup(options: BackupOptions) -> BackupResult:
    """backup orchestration entry point。

    R1-R3 17 findings 全件 adopt 反映。CRITICAL invariants:
    - age private key は touch しない
    - tmp dir 0700 + 全 exception path cleanup
    - archive allowlist で private key pattern 物理 reject
    - PGPASSWORD env 使用禁止 (temp .pgpass + PGPASSFILE のみ)
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

    # F-PR77-003 adopt: PGPASSFILE は **必須**、`~/.pgpass` libpq 暗黙 fallback を fail-closed で禁止
    # - file 存在 + permission 0600 + 通常 file を verify (symlink reject、HIGH severity)
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

    try:
        # service stop policy (F-003 adopt: app stop は本 batch では実装しない)
        if options.skip_service_stop:
            warnings_list.append("backup_service_stop_skipped")

        # acquire meta.json data (F-008 adopt)
        postgres_version = acquire_postgres_version()
        redis_version = acquire_redis_version(options.redis_host, options.redis_port)
        # Try to get alembic head from project (best-effort)
        try:
            repo_root = Path(__file__).resolve().parent.parent
            alembic_head = acquire_alembic_head(repo_root)
        except BackupToolNotFoundError:
            alembic_head = "unknown"

        # postgres/ subdir
        pg_dir = tmp_dir / "postgres"
        pg_dir.mkdir()
        pg_dump_output = pg_dir / "pg_dump.dump"
        result = invoke_pg_dump(
            pg_host=options.pg_host,
            pg_port=options.pg_port,
            pg_user=options.pg_user,
            pg_db=options.pg_db,
            output_path=pg_dump_output,
            # F-PR77-003 adopt: 検証済 PGPASSFILE を明示渡し (None fallback 禁止)
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
        artifacts_dest = tmp_dir / "artifacts"
        artifacts_dest.mkdir()
        artifact_count = _copy_artifacts_with_allowlist(
            options.artifacts_dir, artifacts_dest,
        )
        if artifact_count == 0:
            warnings_list.append("backup_artifacts_dir_empty")

        # optional env.encrypted
        if options.include_sops_env:
            if options.sops_env_path.exists():
                shutil.copy2(options.sops_env_path, tmp_dir / "env.encrypted")
            else:
                warnings_list.append("backup_sops_env_skipped")

        # meta.json + checksums.txt (F-008 + F-012 adopt)
        meta = build_meta_json(
            host_name=options.host_name,
            timestamp_utc=datetime.now(timezone.utc),
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
            result = invoke_age_encrypt(
                input_path=tar_tmp_path,
                output_path=part_path,
                public_key_path=options.age_public_key_path,
                timeout_sec=options.age_encrypt_timeout_sec,
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

    except (BackupUsageError, BackupRuntimeError, BackupToolNotFoundError):
        # cleanup part file if exists
        part_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        # F-002 adopt: unexpected exception でも cleanup
        part_path.unlink(missing_ok=True)
        raise BackupRuntimeError(
            "backup_unexpected_error",
            detail=f"unexpected: {type(exc).__name__}",
        ) from None
    finally:
        # F-002 adopt: cleanup OSError は audit + raise (silent ignore 廃止)
        try:
            shutil.rmtree(tmp_dir, ignore_errors=False)
        except OSError as exc:
            # secret-bearing tmp が残った場合 → CRITICAL audit + raise
            raise BackupRuntimeError(
                "backup_tmp_cleanup_failed",
                detail=f"cleanup_oserror: {type(exc).__name__} path={tmp_dir.name}",
            ) from None


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
