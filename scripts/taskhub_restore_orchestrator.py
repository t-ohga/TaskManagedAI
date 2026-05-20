"""Taskhub restore real I/O orchestration (SP022-T02 Phase 3 / T08 batch 3).

24 rounds + 58 findings 100% adopt of codex-plan-review (CLAUDE.md §6.5.4 codex-plan-review
R1-R24 完遂). Refer `.claude/plans/sp022-t02p3-t08b3-restore-real-io.md` for design rationale.

Architectural invariants (R14-F-001 root cause fix):
- pg_restore / pg_dump / redis-cli / psql は **全て `docker compose exec` 経由** + container 内 unix socket
  (host TCP path 廃止、port-collision attack 完全排除)
- archive sha256 verify + age decrypt は **immutable stage に full copy** で同一 inode 隔離 (R19-F-001)
- BGSAVE 廃止、blocking `SAVE` を採用 (R17-F-001 race-free)
- pre-restore snapshot は `.tmp` suffix → atomic rename pattern (R20-F-001 partial file 防止)
- rollback exception 範囲拡張 (OSError / shutil.Error / SubprocessError / SubprocessTimeoutError /
  SubprocessNotFoundError、R6-F-001 + R7-F-001)
- runtime target binding consistency preflight (compose project/file/services/ports/volumes、R11-R23)
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

try:
    from scripts.taskhub_subprocess_runner import (
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
        SafeSubprocessConfig,
        SubprocessNotFoundError,
        SubprocessResult,
        SubprocessTimeoutError,
        run_safe_subprocess,
    )


# --- Python version gate (R7-F-001 + R8-F-008 adopt) ---


def _assert_python_version() -> None:
    """Python 3.12+ requirement gate (tarfile.extractall filter='data' は 3.12+ supported).

    pyproject.toml `requires-python = ">=3.12,<3.13"` 整合、graceful skip 禁止。
    """
    if sys.version_info < (3, 12):  # noqa: UP036 — intentional runtime defense check
        raise RuntimeError(
            f"taskhub_restore_orchestrator requires Python 3.12+, got {sys.version_info}",
        )


_assert_python_version()


# --- ReasonCode + WarningCode (R1-R23 全 reason 統合) ---

ReasonCode = Literal[
    "restore_input_path_invalid",
    "restore_input_archive_sha256_mismatch",
    "restore_input_archive_mutated_during_verification",
    "restore_age_identity_path_invalid",
    "restore_age_decrypt_failed",
    "restore_archive_size_exceeded",
    "restore_archive_allowlist_violation",
    "restore_meta_json_invalid",
    "restore_checksums_mismatch",
    "restore_postgres_major_version_mismatch",
    "restore_alembic_head_mismatch",
    "restore_service_stop_failed",
    "restore_service_start_failed",
    "restore_healthcheck_failed",
    "restore_pre_restore_pg_dump_failed",
    "restore_pre_restore_redis_save_failed",
    "restore_pg_restore_failed",
    "restore_redis_data_placement_failed",
    "restore_target_binding_unresolvable",
    "restore_target_binding_mismatch",
    "restore_target_data_dir_in_use_without_overwrite",
    "restore_output_path_invalid",
    "restore_rollback_attempted",
    "restore_rollback_failed",
    "restore_completed",
    # SP022-T02 Phase 4 (R1 F-004 + R2 F-004 + R5 F-001 + ADV R1 F-017 adopt): snapshot manifest
    "restore_rollback_snapshot_manifest_missing",
    "restore_rollback_snapshot_manifest_invalid_json",
    "restore_rollback_snapshot_manifest_target_mismatch",
    "restore_rollback_snapshot_component_hash_mismatch",
    "restore_rollback_snapshot_component_missing",
    "restore_rollback_snapshot_id_mismatch",
    "restore_rollback_snapshot_manifest_unsupported_version",
    "restore_rollback_snapshot_manifest_toctou_mismatch",
]

WarningCode = Literal[
    "restore_rollback_attempted",
    "restore_rollback_redis_skipped_no_pre_snapshot",
    "restore_rollback_db_skipped_no_pre_snapshot",
    "restore_meta_json_unknown_keys",
    # SP022-T02 Phase 4 (R2 F-004 adopt): partial snapshot component skip warnings
    "restore_rollback_snapshot_component_db_dump_not_present",
    "restore_rollback_snapshot_component_redis_dump_not_present",
]


class RestoreUsageError(Exception):
    """CLI usage / approval / preflight 起因の deny (exit_code=2 mapping)."""

    def __init__(self, reason_code: ReasonCode, *, detail: str | None = None) -> None:
        super().__init__(f"{reason_code}: {detail or ''}")
        self.reason_code = reason_code
        self.detail = detail

    def stderr_message(self) -> str:
        msg: str = self.reason_code
        if self.detail:
            msg = f"{msg}: {self.detail}"
        return msg


class RestoreRuntimeError(Exception):
    """runtime failure (tool / subprocess / I/O) 起因の deny (exit_code=1 mapping)."""

    def __init__(self, reason_code: ReasonCode, *, detail: str | None = None) -> None:
        super().__init__(f"{reason_code}: {detail or ''}")
        self.reason_code = reason_code
        self.detail = detail

    def stderr_message(self) -> str:
        msg: str = self.reason_code
        if self.detail:
            msg = f"{msg}: {self.detail}"
        return msg


# --- Constants (R11-F-001 DoS limits + R14-F-001 timeouts + R6-F-001 healthcheck) ---

# R11-F-001 fix: tar member size / count limits (DoS 防止)
TAR_MAX_TOTAL_SIZE_BYTES = 50 * 1024 ** 3   # 50 GiB
TAR_MAX_MEMBER_SIZE_BYTES = 10 * 1024 ** 3  # 10 GiB / 単一 member
TAR_MAX_MEMBER_COUNT = 100_000               # 10万 file 上限
SNIFF_MAX_READ_BYTES = 4096                  # 抽出前 sniff の最大 read

# Healthcheck timeouts (R6-F-001 fix: 現行 docker-compose.yml の interval=30s × retries=3 整合)
DATA_HEALTHCHECK_TIMEOUT_SEC = 120  # postgres / redis (依存なし、起動 30-60s)
APP_HEALTHCHECK_TIMEOUT_SEC = 180   # api / worker (DB 接続 + alembic check 含む)
HEALTHCHECK_POLL_INTERVAL_SEC = 5

# Subprocess timeouts (R14-F-001 adopt)
PG_RESTORE_TIMEOUT_SEC = 1800       # 30 min (大規模 DB 想定)
PG_DUMP_TIMEOUT_SEC = 1800
REDIS_SAVE_TIMEOUT_SEC = 900        # 15 min (blocking SAVE)
AGE_DECRYPT_TIMEOUT_SEC = 600

SUPPORTED_FORMAT_VERSIONS = frozenset({"1.0"})

# Archive allowlist (backup_orchestrator から import で再利用も可、ここでは re-declare)
_ARCHIVE_ALLOWLIST_PATTERNS = (
    "meta.json",
    "checksums.txt",
    "postgres",     # F-PR78-004 adopt: top-level dir entry (no trailing slash) も accept
    "postgres/",
    "redis",        # F-PR78-004 adopt: top-level dir entry
    "redis/",
    "artifacts",    # F-PR78-004 adopt: top-level dir entry
    "artifacts/",
    "env.encrypted",  # optional, include_sops_env
)

_ARCHIVE_DENY_FILENAME_PATTERNS = (
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
    "age-key", "age.key", "age-secret-key",
    "keys.txt", "private.key", "private-key",
)

_ARCHIVE_DENY_CONTENT_PREFIXES = (
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
    b"-----BEGIN EC PRIVATE KEY-----",
    b"-----BEGIN DSA PRIVATE KEY-----",
    b"-----BEGIN PGP PRIVATE KEY BLOCK-----",
    b"AGE-SECRET-KEY-1",
)


# --- RestoreOptions (R23 + R12 + R13 + R14 全 field 反映) ---


@dataclasses.dataclass(frozen=True)
class RestoreOptions:
    """Restore configuration (R14-F-001 + R8-F-001 + R12-F-001 + R23-F-001 反映).

    Note: skip_service_stop は CLI で物理 deny されるため field 不在。
    Note: pgpassfile_path は廃止 (R14-F-001、container exec + unix socket 経路).
    """
    input_path: Path  # absolute, normpath
    archive_sha256: str  # 64-char hex
    age_identity_file: Path  # 0o400/0o600 verify 済 absolute path
    target_pg_dsn_components: dict[str, str]  # {host, port, db, user}
    target_redis_endpoint: str  # host:port literal
    target_artifacts_dir: Path  # absolute normpath
    target_artifacts_container_path: str  # e.g., /app/data/artifacts
    target_compose_project_name: str
    target_compose_file_path: Path  # absolute
    expected_postgres_major_version: str  # e.g., "17"
    expected_alembic_head: str
    overwrite: bool

    @classmethod
    def for_rollback_mode(
        cls,
        *,
        pre_restore_dir: Path,
        target_pg_dsn_components: dict[str, str],
        target_redis_endpoint: str,
        target_artifacts_dir: Path,
        target_artifacts_container_path: str,
        target_compose_project_name: str,
        target_compose_file_path: Path,
        expected_postgres_major_version: str,
    ) -> RestoreOptions:
        """SP022-T02 Phase 4 (R1 F-005 + R2 F-005 adopt): rollback 用 minimal RestoreOptions.

        archive_sha256 / age_identity_file / expected_alembic_head は rollback では未使用
        (snapshot 内 data が正本)、sentinel value で埋める。CLI rollback 分岐は
        `rollback_from_pre_restore_snapshot()` を直接呼ぶため `run_restore()` には渡さない.
        """
        return cls(
            input_path=pre_restore_dir,
            archive_sha256="",
            age_identity_file=Path("/dev/null"),
            target_pg_dsn_components=target_pg_dsn_components,
            target_redis_endpoint=target_redis_endpoint,
            target_artifacts_dir=target_artifacts_dir,
            target_artifacts_container_path=target_artifacts_container_path,
            target_compose_project_name=target_compose_project_name,
            target_compose_file_path=target_compose_file_path,
            expected_postgres_major_version=expected_postgres_major_version,
            expected_alembic_head="",
            overwrite=True,
        )


@dataclasses.dataclass(frozen=True)
class RestoreResult:
    output_path: Path
    reason_code: ReasonCode
    warnings: tuple[WarningCode, ...]
    duration_sec: float
    meta: dict[str, Any]

    def summary(self) -> dict[str, Any]:
        return {
            "mode": "restore-real-io",
            "reason_code": self.reason_code,
            "warnings": list(self.warnings),
            "duration_sec": round(self.duration_sec, 2),
            "meta": self.meta,
        }


# --- helper: compose argv prefix (R8/R9 fix) ---


def _compose_argv_prefix(options: RestoreOptions) -> list[str]:
    """R8-F-001 + R9-F-001 fix: docker compose に -p <project> + -f <abs_path> 明示."""
    return [
        "docker", "compose",
        "-p", options.target_compose_project_name,
        "-f", str(options.target_compose_file_path),
    ]


# --- archive verification: same fd immutable stage (R16/R17/R18/R19 fix) ---


def verify_archive_sha256_and_decrypt_via_immutable_stage(
    input_path: Path,
    expected_sha256: str,
    age_identity_file: Path,
    out_tar_path: Path,
    stage_dir: Path,
) -> None:
    """R16/R17/R18/R19 adopt: input を別 inode の immutable stage に copy 経由で隔離、
    sha256 verify + age decrypt を stage 上で完結 (元 path の in-place overwrite/truncate と無関係).

    - hardlink ではなく cp --reflink=auto (CoW) で別 inode 確保 (R19-F-001 fix)
    - reflink 不可なら shutil.copy2 full byte copy (disk 2x)
    - stage を chmod 0o400 read-only
    - sha256 streaming read (R15-F-002: 全 memory load しない)
    - age decrypt も stdin pipe で stream
    """
    if input_path.is_symlink():
        raise RestoreUsageError(
            "restore_input_path_invalid",
            detail=f"input_path must not be symlink: {input_path}",
        )
    if not input_path.is_file():
        raise RestoreUsageError(
            "restore_input_path_invalid",
            detail=f"input_path not found or not regular file: {input_path}",
        )
    # Stage に CoW copy (or fallback full byte copy)
    stage_path = stage_dir / "input_archive_immutable.tar.age"
    try:
        subprocess.run(  # noqa: S603, S607 - `cp` system tool with literal args, shell=False
            ["cp", "--reflink=auto", str(input_path), str(stage_path)],  # noqa: S607
            check=True, capture_output=True, timeout=300,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        # macOS / busybox 等の `cp --reflink` 未対応環境 → shutil.copy2 で純粋 byte copy
        shutil.copy2(input_path, stage_path)
    # stage を read-only に
    os.chmod(stage_path, 0o400)

    # O_NOFOLLOW open + same fd で sha256 + decrypt (R16/R17/R18 fix)
    fd_num = os.open(stage_path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with os.fdopen(fd_num, "rb", closefd=False) as fd:
            # streaming sha256
            h = hashlib.sha256()
            while True:
                chunk = fd.read(64 * 1024)
                if not chunk:
                    break
                h.update(chunk)
            actual = h.hexdigest()
            if actual != expected_sha256:
                raise RestoreUsageError(
                    "restore_input_archive_sha256_mismatch",
                    detail=f"expected={expected_sha256[:16]}..., actual={actual[:16]}...",
                )
            # seek 0 + age decrypt stdin pipe
            fd.seek(0)
            argv = ["age", "-d", "-i", str(age_identity_file), "-o", str(out_tar_path)]
            try:
                result = run_safe_subprocess(
                    argv,
                    config=SafeSubprocessConfig(
                        timeout_sec=AGE_DECRYPT_TIMEOUT_SEC, stdin_file=fd,
                    ),
                )
            except SubprocessNotFoundError as e:
                raise RestoreRuntimeError(
                    "restore_age_decrypt_failed",
                    detail=f"age tool not found: {e.command_name}",
                ) from None
            except SubprocessTimeoutError as e:
                raise RestoreRuntimeError(
                    "restore_age_decrypt_failed",
                    detail=f"age decrypt timeout: {e.timeout_sec}s",
                ) from None
            if result.returncode != 0:
                raise RestoreRuntimeError(
                    "restore_age_decrypt_failed",
                    detail=f"exit={result.returncode}",
                )
    finally:
        os.close(fd_num)


# --- tar extraction (R11 + R20 fix) ---


def verify_tar_members_safe(tar: tarfile.TarFile) -> None:
    """R20-F-002 fix: extractall 前に symlink/hardlink/device/fifo を明示 reject.

    + R11-F-001: tar member count + total size + member size limits.
    """
    total_size = 0
    member_count = 0
    for member in tar.getmembers():
        member_count += 1
        if member_count > TAR_MAX_MEMBER_COUNT:
            raise RestoreRuntimeError(
                "restore_archive_size_exceeded",
                detail=f"tar member count > {TAR_MAX_MEMBER_COUNT}",
            )
        if member.issym() or member.islnk():
            raise RestoreRuntimeError(
                "restore_archive_allowlist_violation",
                detail=f"tar member is symlink/hardlink (rejected): {member.name}",
            )
        if member.ischr() or member.isblk() or member.isfifo():
            raise RestoreRuntimeError(
                "restore_archive_allowlist_violation",
                detail=f"tar member is device/fifo (rejected): {member.name}",
            )
        if not (member.isfile() or member.isdir()):
            raise RestoreRuntimeError(
                "restore_archive_allowlist_violation",
                detail=f"tar member unsupported type (rejected): {member.name} type={member.type!r}",
            )
        if member.size > TAR_MAX_MEMBER_SIZE_BYTES:
            raise RestoreRuntimeError(
                "restore_archive_size_exceeded",
                detail=f"tar member size > {TAR_MAX_MEMBER_SIZE_BYTES}: {member.name}",
            )
        total_size += member.size
        if total_size > TAR_MAX_TOTAL_SIZE_BYTES:
            raise RestoreRuntimeError(
                "restore_archive_size_exceeded",
                detail=f"tar total size > {TAR_MAX_TOTAL_SIZE_BYTES}",
            )


def check_archive_member_allowlist(name: str) -> tuple[bool, str | None]:
    """allowlist sniff: tar member name が allowlist prefix のいずれかで始まるか.

    F-PR78-004 adopt: top-level dir entry (e.g., "postgres", "redis", "artifacts" without
    trailing slash) も accept、backup_orchestrator が writeする tar header と整合.

    Returns: (allowed: bool, reason: str or None).
    """
    # Allowlist match: exact name (top-level dir entry) or starts with prefix (subpath)
    matched = False
    for p in _ARCHIVE_ALLOWLIST_PATTERNS:
        if name == p:
            matched = True
            break
        # prefix patterns ending in "/" allow subpaths under them
        if p.endswith("/") and name.startswith(p):
            matched = True
            break
        # Top-level dir name (no trailing slash) accepts itself as exact match only
    if not matched:
        return False, f"not in allowlist: {name}"
    # deny filename pattern (id_rsa 等)
    basename = Path(name).name.lower()
    if any(pat in basename for pat in _ARCHIVE_DENY_FILENAME_PATTERNS):
        return False, f"deny filename pattern: {name}"
    return True, None


def extract_with_limits(tar_path: Path, dest_dir: Path) -> None:
    """tar extraction with allowlist + DoS limits + member safety verify."""
    with tarfile.open(tar_path, "r") as tar:
        verify_tar_members_safe(tar)
        # allowlist sniff (R11-F-001 + R20-F-002)
        for member in tar.getmembers():
            allowed, reason = check_archive_member_allowlist(member.name)
            if not allowed:
                raise RestoreRuntimeError(
                    "restore_archive_allowlist_violation",
                    detail=reason or member.name,
                )
            # content sniff for private key prefix (extraction 前 reject)
            if member.isfile() and member.size > 0:
                f = tar.extractfile(member)
                if f is not None:
                    head = f.read(SNIFF_MAX_READ_BYTES)
                    for prefix in _ARCHIVE_DENY_CONTENT_PREFIXES:
                        if head.startswith(prefix):
                            raise RestoreRuntimeError(
                                "restore_archive_allowlist_violation",
                                detail=f"content sniff hit private key prefix in: {member.name}",
                            )
        # Python 3.12+ extractall filter='data' で path traversal / device / symlink double-defense
        tar.extractall(dest_dir, filter="data")


# --- meta.json schema verify (R12-F-001 + R20 fix) ---


_REQUIRED_META_KEYS = frozenset({
    "format_version", "host_name", "timestamp_utc",
    "postgres_version", "redis_version", "alembic_head",
})

_KNOWN_OPTIONAL_META_KEYS = frozenset({
    "tenant_id_set", "multi_agent_tables", "schema_extras",
})


def read_and_verify_meta_json(
    meta_path: Path, warnings: list[WarningCode],
) -> dict[str, Any]:
    """meta.json strict schema verify + version-aware forward compat (R12 + R20-F-002 fix)."""
    if not meta_path.is_file():
        raise RestoreRuntimeError(
            "restore_meta_json_invalid",
            detail=f"meta.json not found: {meta_path}",
        )
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise RestoreRuntimeError(
            "restore_meta_json_invalid",
            detail=f"meta.json parse failed: {e}",
        ) from None
    if not isinstance(meta, dict):
        raise RestoreRuntimeError(
            "restore_meta_json_invalid",
            detail="meta.json not a dict",
        )
    missing = _REQUIRED_META_KEYS - meta.keys()
    if missing:
        raise RestoreRuntimeError(
            "restore_meta_json_invalid",
            detail=f"missing_required={sorted(missing)}",
        )
    fmt_ver = meta.get("format_version")
    if fmt_ver not in SUPPORTED_FORMAT_VERSIONS:
        raise RestoreRuntimeError(
            "restore_meta_json_invalid",
            detail=f"unsupported_format_version={fmt_ver}",
        )
    # extra keys: KNOWN_OPTIONAL → accept、unknown → warning (forward compat)
    unknown_keys = set(meta.keys()) - _REQUIRED_META_KEYS - _KNOWN_OPTIONAL_META_KEYS
    if unknown_keys:
        warnings.append("restore_meta_json_unknown_keys")
    return meta


def verify_checksums(extracted_dir: Path) -> None:
    """checksums.txt と extracted 内 file の sha256 deterministic compare.

    F-PR78-R2-001 CRITICAL fix: checksums.txt path を strict verify (absolute path / `..` traversal
    reject、host file 読み取り attack 防止)。
    F-PR78-R2-006 fix: 抽出済 file 集合 vs checksums.txt declared 集合の exact match verify
    (undeclared payload による tampered archive 防止)。
    """
    checksums_path = extracted_dir / "checksums.txt"
    if not checksums_path.is_file():
        raise RestoreRuntimeError(
            "restore_checksums_mismatch",
            detail="checksums.txt missing",
        )
    extracted_root = extracted_dir.resolve()
    expected: dict[str, str] = {}
    for line in checksums_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        # format: "<sha256>  <relative_path>" (sha256sum compat)
        parts = line.split("  ", 1)
        if len(parts) != 2:
            raise RestoreRuntimeError(
                "restore_checksums_mismatch",
                detail=f"checksums.txt malformed line: {line[:80]}",
            )
        rel = parts[1]
        # F-PR78-R2-001 fix: absolute path / `..` traversal を文字列レベルで reject
        if rel.startswith("/") or rel.startswith("\\"):
            raise RestoreRuntimeError(
                "restore_checksums_mismatch",
                detail=f"checksums.txt has absolute path (rejected): {rel}",
            )
        if ".." in Path(rel).parts:
            raise RestoreRuntimeError(
                "restore_checksums_mismatch",
                detail=f"checksums.txt has `..` traversal (rejected): {rel}",
            )
        expected[rel] = parts[0]
    # compute actual sha256 of each extracted file
    for rel_path, expected_hash in expected.items():
        full = (extracted_dir / rel_path).resolve()
        # F-PR78-R2-001 fix: resolved path が extracted_root 配下であること verify
        if not (full == extracted_root or full.is_relative_to(extracted_root)):
            raise RestoreRuntimeError(
                "restore_checksums_mismatch",
                detail=f"checksums.txt path escapes extracted root: {rel_path}",
            )
        if not full.is_file():
            raise RestoreRuntimeError(
                "restore_checksums_mismatch",
                detail=f"expected file missing: {rel_path}",
            )
        h = hashlib.sha256()
        with full.open("rb") as f:
            while True:
                chunk = f.read(64 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        if h.hexdigest() != expected_hash:
            raise RestoreRuntimeError(
                "restore_checksums_mismatch",
                detail=f"sha256 mismatch: {rel_path}",
            )
    # F-PR78-R2-006 fix: extracted 内に checksums.txt 未宣言 file があれば reject
    # (tampered archive が undeclared payload を追加するのを防止)
    extracted_files: set[str] = set()
    for entry in extracted_dir.rglob("*"):
        if not entry.is_file():
            continue
        rel = entry.relative_to(extracted_dir).as_posix()
        if rel == "checksums.txt":
            continue  # self-exclude
        extracted_files.add(rel)
    declared_files = set(expected.keys())
    undeclared = extracted_files - declared_files
    if undeclared:
        raise RestoreRuntimeError(
            "restore_checksums_mismatch",
            detail=f"extracted files not declared in checksums.txt: {sorted(undeclared)[:5]}",
        )


def verify_postgres_major_version(meta: dict[str, Any], expected_major: str) -> None:
    """meta.json.postgres_version の major と claim.expected_postgres_major_version 一致 verify."""
    pg_ver = str(meta.get("postgres_version", ""))
    if not pg_ver:
        raise RestoreRuntimeError(
            "restore_postgres_major_version_mismatch",
            detail="meta.json postgres_version missing/empty",
        )
    major = pg_ver.split(".")[0]
    if major != expected_major:
        raise RestoreRuntimeError(
            "restore_postgres_major_version_mismatch",
            detail=f"meta_major={major}, claim_expected={expected_major}",
        )


# --- target binding consistency preflight (R11-R23 統合) ---


def _strip_protocol_suffix(port_str: str) -> str:
    """`5432/tcp` / `5432/udp` から protocol suffix を strip して port number のみ返す (F-PR78-R2-005)."""
    if "/" in port_str:
        return port_str.split("/", 1)[0]
    return port_str


def _parse_redis_endpoint(endpoint: str) -> tuple[str, str]:
    """`host:port` literal を parse、IPv4 / IPv6 (bracketed and unbracketed loopback) 両対応.

    F-PR78-R3-001 adopt: `partition(":")` は `::1:6379` で empty host + malformed port を生むため
    廃止。`rsplit(":", 1)` で host と port を分離 + bracketed (`[::1]:6379`) も unwrap。
    Returns: (host, port_str)
    """
    if endpoint.startswith("["):
        # bracketed: `[::1]:6379`
        bracket_end = endpoint.find("]")
        if bracket_end == -1 or not endpoint[bracket_end + 1:].startswith(":"):
            return endpoint, ""
        host = endpoint[1:bracket_end]
        port = endpoint[bracket_end + 2:]
        return host, port
    # rsplit で末尾の port を分離 (IPv6 unbracketed `::1:6379` も最後の `:` で split)
    if ":" not in endpoint:
        return endpoint, ""
    host, _, port = endpoint.rpartition(":")
    return host, port


def _parse_short_port_syntax(p: str) -> tuple[str | None, str | None, str | None]:
    """Compose short syntax port mapping を parse、(host_ip, host_port, container_port) を返す.

    F-PR78-R2-003 + R2-005 + R3-002 adopt: IPv6 bracketed (`[::1]:6001:6001`) +
    unbracketed IPv6 (`::1:6001:6001`) + protocol suffix (`5432:5432/tcp`) の全対応。
    """
    # IPv6 bracketed: [host_ip]:host_port:container_port
    if p.startswith("["):
        bracket_end = p.find("]")
        if bracket_end == -1:
            return None, None, None
        host_ip = p[1:bracket_end]
        rest = p[bracket_end + 1:]
        if not rest.startswith(":"):
            return None, None, None
        rest = rest[1:]
        parts = rest.split(":")
        if len(parts) != 2:
            return None, None, None
        host_port, cont_port = parts
        return host_ip, host_port, _strip_protocol_suffix(cont_port)
    # F-PR78-R3-002 fix: unbracketed IPv6 forms (`::1`, `fe80::N` 等 colon を含む host_ip)
    # 末尾 2 segment を host_port / container_port、その前を host_ip として parse
    parts = p.split(":")
    if len(parts) == 2:
        host_port, cont_port = parts
        return None, host_port, _strip_protocol_suffix(cont_port)
    if len(parts) == 3:
        host_ip, host_port, cont_port = parts
        return host_ip, host_port, _strip_protocol_suffix(cont_port)
    if len(parts) > 3:
        # IPv6 unbracketed: 末尾 2 が ports、それ以前が host_ip (再 join)
        host_port = parts[-2]
        cont_port = parts[-1]
        host_ip = ":".join(parts[:-2])
        # sanity: ports は numeric
        if not host_port.isdigit():
            return None, None, None
        cont_clean = _strip_protocol_suffix(cont_port)
        if not cont_clean.isdigit():
            return None, None, None
        return host_ip, host_port, cont_clean
    return None, None, None


def _extract_published_port(ports_spec: Any, container_port: int) -> str | None:  # noqa: ANN401 — JSON ports spec is genuinely Any
    """Compose ports 配列から published host port を抽出 (long/short/IPv6/protocol-suffix 両対応)."""
    if not isinstance(ports_spec, list):
        return None
    for p in ports_spec:
        if isinstance(p, str):
            _, host_port, cont_port = _parse_short_port_syntax(p)
            if cont_port == str(container_port) and host_port is not None:
                return host_port
        elif isinstance(p, dict):
            if str(p.get("target", "")) == str(container_port):
                published = p.get("published")
                if published is not None:
                    return str(published)
    return None


def _extract_host_ip(ports_spec: Any, container_port: int) -> str | None:  # noqa: ANN401
    """Compose ports 配列から host_ip を抽出 (None = 0.0.0.0 相当 = fail-closed deny の signal).

    F-PR78-R2-003 adopt: IPv6 bracketed syntax (e.g. `[::1]:5432:5432`) も parse。
    """
    if not isinstance(ports_spec, list):
        return None
    for p in ports_spec:
        if isinstance(p, str):
            host_ip, _, cont_port = _parse_short_port_syntax(p)
            if cont_port == str(container_port) and host_ip:
                return host_ip
            # 2-part syntax には host_ip なし → 続行
        elif isinstance(p, dict):
            if str(p.get("target", "")) == str(container_port):
                hip = p.get("host_ip")
                if hip:
                    return str(hip)
    return None


def _normalize_compose_env(env_spec: Any) -> dict[str, str]:  # noqa: ANN401
    """Compose environment を dict に normalize (dict or list-of-K=V 両対応)."""
    result: dict[str, str] = {}
    if isinstance(env_spec, dict):
        for k, v in env_spec.items():
            result[str(k)] = str(v) if v is not None else ""
    elif isinstance(env_spec, list):
        for item in env_spec:
            if isinstance(item, str) and "=" in item:
                k, v = item.split("=", 1)
                result[k] = v
    return result


def verify_target_binding_consistency(options: RestoreOptions) -> None:
    """R11-R23 統合: Compose deployment と claim target identity の一致 preflight (mutation 前)."""
    # docker compose config で resolved services を取得
    try:
        result = run_safe_subprocess(
            _compose_argv_prefix(options) + ["config", "--format", "json"],
            config=SafeSubprocessConfig(timeout_sec=30),
        )
    except SubprocessNotFoundError as e:
        raise RestoreRuntimeError(
            "restore_target_binding_unresolvable",
            detail=f"docker tool not found: {e.command_name}",
        ) from None
    except SubprocessTimeoutError as e:
        raise RestoreRuntimeError(
            "restore_target_binding_unresolvable",
            detail=f"compose config timeout: {e.timeout_sec}s",
        ) from None
    if result.returncode != 0:
        raise RestoreRuntimeError(
            "restore_target_binding_unresolvable",
            detail=f"compose config exit={result.returncode}",
        )
    try:
        compose_config = json.loads(result.stdout.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise RestoreRuntimeError(
            "restore_target_binding_unresolvable",
            detail=f"compose config json invalid: {e}",
        ) from None
    services = compose_config.get("services", {})
    if not isinstance(services, dict):
        raise RestoreRuntimeError(
            "restore_target_binding_unresolvable",
            detail="compose config services not a dict",
        )

    # postgres service required + DSN port + DB/USER env + host loopback bind
    pg_svc = services.get("postgres")
    if pg_svc is None:
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail="compose_postgres_service_absent",
        )
    pg_ports = pg_svc.get("ports", [])
    pg_published = _extract_published_port(pg_ports, container_port=5432)
    expected_pg_port = options.target_pg_dsn_components.get("port", "")
    if pg_published is None or str(pg_published) != str(expected_pg_port):
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=f"postgres_port_mismatch: compose={pg_published}, claim={expected_pg_port}",
        )

    # R13-F-001: postgres published host_ip must be explicit 127.0.0.1 or ::1
    pg_host_ip = _extract_host_ip(pg_ports, container_port=5432)
    if pg_host_ip not in ("127.0.0.1", "::1"):
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=(
                f"postgres_published_host_ip_not_explicit_loopback: {pg_host_ip} "
                "(docker-compose.yml must use '127.0.0.1:5432:5432' explicit binding)"
            ),
        )

    # R12-F-001 + R13-F-001: claim host も IP literal loopback 限定
    expected_pg_host = options.target_pg_dsn_components.get("host", "")
    if expected_pg_host not in ("127.0.0.1", "::1"):
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=f"postgres_host_not_ip_loopback: {expected_pg_host}",
        )

    # POSTGRES_DB / POSTGRES_USER env と claim DSN 一致 verify (R12)
    pg_env = _normalize_compose_env(pg_svc.get("environment", {}))
    expected_pg_db = options.target_pg_dsn_components.get("db", "")
    expected_pg_user = options.target_pg_dsn_components.get("user", "")
    if pg_env.get("POSTGRES_DB", "") != expected_pg_db:
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=f"postgres_db_mismatch: compose={pg_env.get('POSTGRES_DB')}, claim={expected_pg_db}",
        )
    if pg_env.get("POSTGRES_USER", "") != expected_pg_user:
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=f"postgres_user_mismatch: compose={pg_env.get('POSTGRES_USER')}, claim={expected_pg_user}",
        )

    # redis service binding verify (同 pattern)
    redis_svc = services.get("redis")
    if redis_svc is None:
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail="compose_redis_service_absent",
        )
    redis_ports = redis_svc.get("ports", [])
    redis_published = _extract_published_port(redis_ports, container_port=6379)
    # F-PR78-R3-001 fix: IPv6 endpoint (`::1:6379` or `[::1]:6379`) safe parse
    expected_redis_host, expected_redis_port_str = _parse_redis_endpoint(
        options.target_redis_endpoint,
    )
    if redis_published is None or str(redis_published) != expected_redis_port_str:
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=f"redis_port_mismatch: compose={redis_published}, claim={expected_redis_port_str}",
        )
    if expected_redis_host not in ("127.0.0.1", "::1"):
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=f"redis_host_not_ip_loopback: {expected_redis_host}",
        )
    redis_host_ip = _extract_host_ip(redis_ports, container_port=6379)
    if redis_host_ip not in ("127.0.0.1", "::1"):
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=(
                f"redis_published_host_ip_not_explicit_loopback: {redis_host_ip} "
                "(docker-compose.yml must use '127.0.0.1:6379:6379' explicit binding)"
            ),
        )

    # R21-F-001 + R22-F-001 + R23-F-001: artifacts_dir normalize + allowed roots + required services bind mount
    # F-PR78-002 adopt: default に repo_root/data/artifacts も含める (admin.py default の `<repo>/data/artifacts` 整合)
    expected_artifacts_dir = options.target_artifacts_dir.resolve()
    repo_root = Path(__file__).resolve().parent.parent
    default_allowed_roots = ":".join([
        "/var/lib/taskhub/artifacts",
        str(Path.home() / ".taskhub" / "artifacts"),
        str(repo_root / "data" / "artifacts"),  # F-PR78-002 fix: admin.py default 整合
    ])
    allowed_roots_raw = os.environ.get(
        "TASKHUB_RESTORE_ALLOWED_ARTIFACTS_ROOTS",
        default_allowed_roots,
    )
    allowed_roots = [Path(p).resolve() for p in allowed_roots_raw.split(":") if p]
    artifacts_under_allowed = any(
        expected_artifacts_dir == root or expected_artifacts_dir.is_relative_to(root)
        for root in allowed_roots
    )
    if not artifacts_under_allowed:
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=(
                f"artifacts_dir_not_in_allowed_roots: {expected_artifacts_dir} "
                f"not under any of {allowed_roots}"
            ),
        )

    # R23-F-001: REQUIRED_BIND_SERVICES = {api, worker} 両方一致必須 + container path 一致
    REQUIRED_BIND_SERVICES = frozenset({"api", "worker"})
    expected_container_path = options.target_artifacts_container_path
    found_in_services: set[str] = set()
    for svc_name in REQUIRED_BIND_SERVICES:
        svc_def = services.get(svc_name)
        if svc_def is None:
            raise RestoreRuntimeError(
                "restore_target_binding_mismatch",
                detail=f"required_service_missing_in_compose: {svc_name}",
            )
        for vol in svc_def.get("volumes", []):
            host_part: Path | None = None
            container_part = ""
            if isinstance(vol, str):
                parts = vol.split(":")
                if len(parts) >= 2:
                    try:
                        host_part = Path(parts[0]).resolve()
                    except (OSError, RuntimeError):
                        continue
                    container_part = parts[1]
            elif isinstance(vol, dict) and vol.get("type") == "bind":
                src = vol.get("source", "")
                if src:
                    try:
                        host_part = Path(src).resolve()
                    except (OSError, RuntimeError):
                        continue
                container_part = vol.get("target", "")
            if host_part is None:
                continue
            # F-PR78-003 adopt: parent dir match (is_relative_to) は false-positive を生む
            # (e.g., bind `./data:/app/data/artifacts` で claim `./data/artifacts` を accept してしまう)
            # 修正: host path **exact match** + container path exact match の両方必須
            host_match = host_part == expected_artifacts_dir
            container_match = container_part == expected_container_path
            if host_match and container_match:
                found_in_services.add(svc_name)
                break

    missing_svcs = REQUIRED_BIND_SERVICES - found_in_services
    if missing_svcs:
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=(
                f"artifacts_bind_mount_missing_in_services: {sorted(missing_svcs)}, "
                f"required_host={expected_artifacts_dir}, required_container={expected_container_path}"
            ),
        )


# --- docker compose service helpers (R9-F-001 全 helper を _compose_argv_prefix 経由統一) ---


def stop_app_services(options: RestoreOptions) -> None:
    """api / worker stop (postgres / redis は snapshot 取得のため alive 維持)."""
    try:
        result = run_safe_subprocess(
            _compose_argv_prefix(options) + ["stop", "--timeout=30", "api", "worker"],
            config=SafeSubprocessConfig(timeout_sec=120),
        )
    except (SubprocessNotFoundError, SubprocessTimeoutError) as e:
        raise RestoreRuntimeError(
            "restore_service_stop_failed",
            detail=f"app_stop_subprocess_failed: {type(e).__name__}",
        ) from None
    if result.returncode != 0:
        raise RestoreRuntimeError(
            "restore_service_stop_failed",
            detail=f"app_stop_exit={result.returncode}",
        )


def stop_redis_service_only(options: RestoreOptions) -> None:
    """redis のみ stop (postgres は alive 維持、R5-F-001 / R10-F-001)."""
    try:
        result = run_safe_subprocess(
            _compose_argv_prefix(options) + ["stop", "--timeout=30", "redis"],
            config=SafeSubprocessConfig(timeout_sec=120),
        )
    except (SubprocessNotFoundError, SubprocessTimeoutError) as e:
        raise RestoreRuntimeError(
            "restore_service_stop_failed",
            detail=f"redis_only_stop_subprocess_failed: {type(e).__name__}",
        ) from None
    if result.returncode != 0:
        raise RestoreRuntimeError(
            "restore_service_stop_failed",
            detail=f"redis_only_stop_exit={result.returncode}",
        )


def start_postgres_wait_healthy(options: RestoreOptions) -> None:
    """rollback Step 0b で postgres のみ確実 up (R5-F-001)."""
    try:
        result = run_safe_subprocess(
            _compose_argv_prefix(options) + ["up", "-d", "postgres"],
            config=SafeSubprocessConfig(timeout_sec=300),
        )
    except (SubprocessNotFoundError, SubprocessTimeoutError) as e:
        raise RestoreRuntimeError(
            "restore_service_start_failed",
            detail=f"postgres_only_start_subprocess_failed: {type(e).__name__}",
        ) from None
    if result.returncode != 0:
        raise RestoreRuntimeError(
            "restore_service_start_failed",
            detail=f"postgres_only_start_exit={result.returncode}",
        )
    _wait_services_healthy(options, ["postgres"], timeout_sec=DATA_HEALTHCHECK_TIMEOUT_SEC)


def start_redis_service_wait_healthy(options: RestoreOptions) -> None:
    """redis のみ up + healthcheck."""
    try:
        result = run_safe_subprocess(
            _compose_argv_prefix(options) + ["up", "-d", "redis"],
            config=SafeSubprocessConfig(timeout_sec=300),
        )
    except (SubprocessNotFoundError, SubprocessTimeoutError) as e:
        raise RestoreRuntimeError(
            "restore_service_start_failed",
            detail=f"redis_only_start_subprocess_failed: {type(e).__name__}",
        ) from None
    if result.returncode != 0:
        raise RestoreRuntimeError(
            "restore_service_start_failed",
            detail=f"redis_only_start_exit={result.returncode}",
        )
    _wait_services_healthy(options, ["redis"], timeout_sec=DATA_HEALTHCHECK_TIMEOUT_SEC)


def start_app_services_wait_healthy(options: RestoreOptions) -> None:
    """api / worker up + healthcheck (alembic verify PASS 後)."""
    try:
        result = run_safe_subprocess(
            _compose_argv_prefix(options) + ["up", "-d", "api", "worker"],
            config=SafeSubprocessConfig(timeout_sec=300),
        )
    except (SubprocessNotFoundError, SubprocessTimeoutError) as e:
        raise RestoreRuntimeError(
            "restore_service_start_failed",
            detail=f"app_start_subprocess_failed: {type(e).__name__}",
        ) from None
    if result.returncode != 0:
        raise RestoreRuntimeError(
            "restore_service_start_failed",
            detail=f"app_start_exit={result.returncode}",
        )
    _wait_services_healthy(options, ["api", "worker"], timeout_sec=APP_HEALTHCHECK_TIMEOUT_SEC)


def all_services_healthy(stdout: bytes, services: list[str]) -> bool:
    """docker compose ps --format json output から services 全 healthy 判定."""
    try:
        text = stdout.decode("utf-8")
    except UnicodeDecodeError:
        return False
    if not text.strip():
        return False
    # docker compose v2 では 1 service per line JSON (newline-delimited) or array
    # 両形式に対応
    parsed: list[dict[str, Any]] = []
    try:
        # try array first
        data = json.loads(text)
        if isinstance(data, list):
            parsed = [d for d in data if isinstance(d, dict)]
        elif isinstance(data, dict):
            parsed = [data]
    except json.JSONDecodeError:
        # try newline-delimited
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                if isinstance(d, dict):
                    parsed.append(d)
            except json.JSONDecodeError:
                continue
    found_healthy: set[str] = set()
    for entry in parsed:
        svc_name = entry.get("Service") or entry.get("service") or entry.get("Name") or ""
        # healthcheck: Health: "healthy" or State: "running" + Health absent
        health = (entry.get("Health") or entry.get("health") or "").lower()
        state = (entry.get("State") or entry.get("state") or "").lower()
        if svc_name in services:
            if health == "healthy":
                found_healthy.add(svc_name)
            elif state == "running" and not health:
                # no healthcheck defined → consider running as healthy
                found_healthy.add(svc_name)
    return set(services).issubset(found_healthy)


def _wait_services_healthy(
    options: RestoreOptions, services: list[str], *, timeout_sec: int,
) -> None:
    """docker compose ps --format json で services 全 healthy を timeout 内に確認."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            ps = run_safe_subprocess(
                _compose_argv_prefix(options) + ["ps", "--format", "json"] + services,
                config=SafeSubprocessConfig(timeout_sec=30),
            )
            if all_services_healthy(ps.stdout, services):
                return
        except (SubprocessNotFoundError, SubprocessTimeoutError):
            pass
        time.sleep(HEALTHCHECK_POLL_INTERVAL_SEC)
    raise RestoreRuntimeError(
        "restore_healthcheck_failed",
        detail=f"timeout={timeout_sec}s for {services}",
    )


# --- subprocess wrappers via compose exec (R14-F-001) ---


def invoke_pg_restore_via_compose_exec(
    options: RestoreOptions, dump_file: Path, *, timeout_sec: int,
) -> SubprocessResult:
    """pg_restore via docker compose exec + container 内 unix socket (R14-F-001).

    stdin に dump_file を fd 直接 pipe (R15-F-002: memory load しない).
    """
    argv = (
        _compose_argv_prefix(options)
        + ["exec", "-T", "postgres", "pg_restore"]
        + [f"--username={options.target_pg_dsn_components['user']}"]
        + [f"--dbname={options.target_pg_dsn_components['db']}"]
        + ["--clean", "--if-exists", "--single-transaction",
           "--no-owner", "--no-privileges", "--exit-on-error",
           "--no-password",
           "-h", "/var/run/postgresql"]
    )
    with dump_file.open("rb") as f:
        return run_safe_subprocess(
            argv,
            config=SafeSubprocessConfig(timeout_sec=timeout_sec, stdin_file=f),
        )


def invoke_pg_dump_via_compose_exec(
    options: RestoreOptions, output_path: Path, *, timeout_sec: int,
) -> SubprocessResult:
    """pre-restore snapshot 用 pg_dump via compose exec (R15-F-001)."""
    argv = (
        _compose_argv_prefix(options)
        + ["exec", "-T", "postgres", "pg_dump"]
        + [f"--username={options.target_pg_dsn_components['user']}"]
        + [f"--dbname={options.target_pg_dsn_components['db']}"]
        + ["--format=custom", "--no-owner", "--no-privileges",
           "--no-password",
           "-h", "/var/run/postgresql"]
    )
    with output_path.open("wb") as f:
        return run_safe_subprocess(
            argv,
            config=SafeSubprocessConfig(timeout_sec=timeout_sec, stdout_file=f),
        )


def invoke_redis_save_sync_via_compose_exec(
    options: RestoreOptions, *, timeout_sec: int,
) -> SubprocessResult:
    """redis-cli SAVE (blocking) via compose exec (R17-F-001 + R18-F-004)."""
    argv = _compose_argv_prefix(options) + ["exec", "-T", "redis", "redis-cli", "SAVE"]
    return run_safe_subprocess(argv, config=SafeSubprocessConfig(timeout_sec=timeout_sec))


def acquire_redis_data_host_path(options: RestoreOptions) -> Path:
    """docker inspect で redis container の /data mount source を実取得 (R17-F-004 + R18-F-001)."""
    try:
        ps_result = run_safe_subprocess(
            _compose_argv_prefix(options) + ["ps", "--all", "-q", "redis"],
            config=SafeSubprocessConfig(timeout_sec=30),
        )
    except (SubprocessNotFoundError, SubprocessTimeoutError) as e:
        raise RestoreRuntimeError(
            "restore_redis_data_placement_failed",
            detail=f"compose_ps_redis_subprocess_failed: {type(e).__name__}",
        ) from None
    if ps_result.returncode != 0 or not ps_result.stdout.strip():
        raise RestoreRuntimeError(
            "restore_redis_data_placement_failed",
            detail=f"compose_ps_redis_failed: exit={ps_result.returncode}",
        )
    container_id = ps_result.stdout.decode("utf-8").strip().split("\n")[0]
    try:
        inspect = run_safe_subprocess(
            ["docker", "inspect", "--format", "{{json .Mounts}}", container_id],
            config=SafeSubprocessConfig(timeout_sec=30),
        )
    except (SubprocessNotFoundError, SubprocessTimeoutError) as e:
        raise RestoreRuntimeError(
            "restore_redis_data_placement_failed",
            detail=f"docker_inspect_subprocess_failed: {type(e).__name__}",
        ) from None
    if inspect.returncode != 0:
        raise RestoreRuntimeError(
            "restore_redis_data_placement_failed",
            detail=f"docker_inspect_failed: exit={inspect.returncode}",
        )
    try:
        mounts = json.loads(inspect.stdout.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise RestoreRuntimeError(
            "restore_redis_data_placement_failed",
            detail=f"docker_inspect_json_invalid: {e}",
        ) from None
    if not isinstance(mounts, list):
        raise RestoreRuntimeError(
            "restore_redis_data_placement_failed",
            detail="docker_inspect_mounts_not_array",
        )
    data_mount = next((m for m in mounts if isinstance(m, dict) and m.get("Destination") == "/data"), None)
    if data_mount is None:
        raise RestoreRuntimeError(
            "restore_redis_data_placement_failed",
            detail="redis_container_no_data_mount",
        )
    source = data_mount.get("Source")
    if not isinstance(source, str) or not source:
        raise RestoreRuntimeError(
            "restore_redis_data_placement_failed",
            detail=f"data_mount_source_invalid: {source}",
        )
    return Path(source)


def verify_alembic_head_in_db(options: RestoreOptions) -> str:
    """restore 後 DB の alembic_version table から head 取得、claim と一致 verify (R15-F-001)."""
    argv = (
        _compose_argv_prefix(options)
        + ["exec", "-T", "postgres", "psql"]
        + [f"--username={options.target_pg_dsn_components['user']}"]
        + [f"--dbname={options.target_pg_dsn_components['db']}"]
        + ["-h", "/var/run/postgresql", "--no-password",
           "-c", "select version_num from alembic_version", "-t", "-A"]
    )
    try:
        result = run_safe_subprocess(argv, config=SafeSubprocessConfig(timeout_sec=30))
    except (SubprocessNotFoundError, SubprocessTimeoutError) as e:
        raise RestoreRuntimeError(
            "restore_alembic_head_mismatch",
            detail=f"psql_subprocess_failed: {type(e).__name__}",
        ) from None
    if result.returncode != 0:
        raise RestoreRuntimeError(
            "restore_alembic_head_mismatch",
            detail=f"psql_failed: exit={result.returncode}",
        )
    head = result.stdout.decode("utf-8").strip()
    if head != options.expected_alembic_head:
        raise RestoreRuntimeError(
            "restore_alembic_head_mismatch",
            detail=f"db={head}, expected={options.expected_alembic_head}",
        )
    return head


# --- tmp dir + pre-restore snapshot helpers (R10 + R18 + R20) ---


def resolve_restore_temp_layout() -> Path:
    """tempfile.mkdtemp + os.chmod(0o700) + permission verify (R3 F-PR77-003 pattern)."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="taskhub-restore-"))
    os.chmod(tmp_dir, 0o700)
    mode = stat.S_IMODE(tmp_dir.stat().st_mode)
    if mode != 0o700:
        raise RestoreRuntimeError(
            "restore_output_path_invalid",
            detail=f"tmp dir permission != 0o700: {mode:o}",
        )
    return tmp_dir


def create_pre_restore_snapshot(
    options: RestoreOptions,
    ts: str,
    register_dir: Callable[[Path], None],
    warnings: list[WarningCode],
) -> Path:
    """3 component snapshot を pre-restore dir に保管.

    R18-F-002 fix: artifacts move 完了直後 register_dir() callback で outer に登録
    (後続失敗でも rollback 起動可能).
    R20-F-001 fix: snapshot file は `.tmp` suffix → atomic rename (partial file 防止).
    F-PR78-R2-004 fix: timestamp collision (rapid retry 同秒) で mkdir 失敗 → register_dir skip
    で rollback 不能を防ぐため、collision 時は ts に増分 suffix 付加.
    F-PR78-R2-002 fix: target_artifacts_dir 不在 (clean target first-time recovery) で
    FileNotFoundError → empty artifacts component として処理.
    """
    # F-PR78-R2-004 fix: timestamp collision で `<ts>.N` 形式で retry
    pre_restore_dir: Path | None = None
    for attempt in range(10):
        suffix = f"-{attempt}" if attempt > 0 else ""
        candidate = options.target_artifacts_dir.parent / f"_pre-restore-{ts}{suffix}"
        try:
            candidate.mkdir(mode=0o700)
            pre_restore_dir = candidate
            break
        except FileExistsError:
            continue
    if pre_restore_dir is None:
        raise RestoreRuntimeError(
            "restore_pre_restore_pg_dump_failed",
            detail=f"_pre-restore-{ts}-* directory collision after 10 attempts",
        )

    # 1. artifacts: dir move (atomic rename) or empty stub for clean target
    # F-PR78-R2-002 fix: target_artifacts_dir 不在は first-time recovery 経路として扱い
    if options.target_artifacts_dir.exists():
        shutil.move(str(options.target_artifacts_dir), str(pre_restore_dir / "artifacts"))
    else:
        # 空 artifacts snapshot (rollback 時の clean state 戻し用)
        (pre_restore_dir / "artifacts").mkdir(mode=0o700)
    # R18-F-002 fix: outer に登録
    register_dir(pre_restore_dir)

    # 2. DB: pg_dump via compose exec (R15-F-001)
    db_snapshot_tmp = pre_restore_dir / "pre_restore_pg_dump.dump.tmp"
    db_snapshot_path = pre_restore_dir / "pre_restore_pg_dump.dump"
    try:
        result = invoke_pg_dump_via_compose_exec(
            options, output_path=db_snapshot_tmp, timeout_sec=PG_DUMP_TIMEOUT_SEC,
        )
    except (SubprocessNotFoundError, SubprocessTimeoutError) as e:
        if db_snapshot_tmp.exists():
            db_snapshot_tmp.unlink()
        raise RestoreRuntimeError(
            "restore_pre_restore_pg_dump_failed",
            detail=f"pg_dump_subprocess_failed: {type(e).__name__}",
        ) from None
    if result.returncode != 0:
        if db_snapshot_tmp.exists():
            db_snapshot_tmp.unlink()
        raise RestoreRuntimeError(
            "restore_pre_restore_pg_dump_failed",
            detail=f"exit={result.returncode}",
        )
    os.rename(db_snapshot_tmp, db_snapshot_path)

    # 3. Redis: blocking SAVE (R17-F-001) → named volume host source で dump.rdb copy
    try:
        save_result = invoke_redis_save_sync_via_compose_exec(
            options, timeout_sec=REDIS_SAVE_TIMEOUT_SEC,
        )
    except (SubprocessNotFoundError, SubprocessTimeoutError) as e:
        raise RestoreRuntimeError(
            "restore_pre_restore_redis_save_failed",
            detail=f"redis_save_subprocess_failed: {type(e).__name__}",
        ) from None
    if save_result.returncode != 0:
        raise RestoreRuntimeError(
            "restore_pre_restore_redis_save_failed",
            detail=f"redis_save_exit={save_result.returncode}",
        )
    redis_host_path = acquire_redis_data_host_path(options)
    redis_snapshot_tmp = pre_restore_dir / "pre_restore_dump.rdb.tmp"
    redis_snapshot_path = pre_restore_dir / "pre_restore_dump.rdb"
    src_rdb = redis_host_path / "dump.rdb"
    if not src_rdb.is_file():
        raise RestoreRuntimeError(
            "restore_pre_restore_redis_save_failed",
            detail=f"dump.rdb not found at {src_rdb}",
        )
    try:
        shutil.copy2(src_rdb, redis_snapshot_tmp)
    except OSError as e:
        if redis_snapshot_tmp.exists():
            redis_snapshot_tmp.unlink()
        raise RestoreRuntimeError(
            "restore_pre_restore_redis_save_failed",
            detail=f"redis_dump_copy_failed: {e}",
        ) from None
    os.rename(redis_snapshot_tmp, redis_snapshot_path)

    # SP022-T02 Phase 4 (R1 F-004 + R2 F-004 + R2 F-006 + ADV R1 F-017 adopt):
    # snapshot_manifest.json を atomic write (.tmp → rename)、全 component の hash 揃った後に最後
    _write_snapshot_manifest(
        pre_restore_dir, options, ts,
        db_dump_path=db_snapshot_path,
        redis_dump_path=redis_snapshot_path,
        artifacts_dir=pre_restore_dir / "artifacts",
    )

    return pre_restore_dir


def _file_sha256(path: Path) -> str:
    """streaming sha256 for files (1 MiB chunks)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _artifacts_merkle_sha256(artifacts_dir: Path) -> str:
    """artifacts dir 全 file の concatenated relative-path + content sha256 を再帰計算.

    SP022-T02 Phase 4 (R1 F-004 adopt): simple Merkle (relative_path + sha256) sequential hash.
    """
    h = hashlib.sha256()
    if not artifacts_dir.is_dir():
        return h.hexdigest()
    # sort で deterministic
    entries: list[Path] = []
    for entry in sorted(artifacts_dir.rglob("*")):
        if entry.is_file():
            entries.append(entry)
    for entry in entries:
        rel = entry.relative_to(artifacts_dir).as_posix()
        h.update(rel.encode("utf-8") + b"\n")
        h.update(_file_sha256(entry).encode("utf-8") + b"\n")
    return h.hexdigest()


def read_alembic_head_via_compose_exec(options: RestoreOptions) -> str | None:
    """SP022-T02 Phase 4 (R2 F-006 adopt): snapshot 作成時に alembic head を docker compose exec
    + container 内 unix socket 経由で取得 (host TCP 経由禁止). Returns None if unavailable.
    """
    argv = (
        _compose_argv_prefix(options)
        + ["exec", "-T", "postgres", "psql"]
        + [f"--username={options.target_pg_dsn_components['user']}"]
        + [f"--dbname={options.target_pg_dsn_components['db']}"]
        + ["-h", "/var/run/postgresql", "--no-password",
           "-c", "select version_num from alembic_version", "-t", "-A"]
    )
    try:
        result = run_safe_subprocess(argv, config=SafeSubprocessConfig(timeout_sec=30))
    except (SubprocessNotFoundError, SubprocessTimeoutError):
        return None
    if result.returncode != 0:
        return None
    head = result.stdout.decode("utf-8").strip()
    return head if head else None


def _write_snapshot_manifest(
    pre_restore_dir: Path,
    options: RestoreOptions,
    ts: str,
    *,
    db_dump_path: Path,
    redis_dump_path: Path,
    artifacts_dir: Path,
) -> None:
    """SP022-T02 Phase 4 (R1 F-004 + R2 F-004 + R2 F-006 + ADV R1 F-017 adopt):
    snapshot_manifest.json を atomic write (.tmp → rename).

    component schema = `{present: bool, sha256: string|null, skipped_reason: string|null}`
    に従い、partial snapshot semantics を保持。
    """
    components: dict[str, dict[str, object]] = {}
    # db component
    if db_dump_path.is_file():
        components["pre_restore_pg_dump.dump"] = {
            "present": True,
            "sha256": _file_sha256(db_dump_path),
            "skipped_reason": None,
        }
    else:
        components["pre_restore_pg_dump.dump"] = {
            "present": False,
            "sha256": None,
            "skipped_reason": "db_dump_not_present_at_snapshot",
        }
    # redis component
    if redis_dump_path.is_file():
        components["pre_restore_dump.rdb"] = {
            "present": True,
            "sha256": _file_sha256(redis_dump_path),
            "skipped_reason": None,
        }
    else:
        components["pre_restore_dump.rdb"] = {
            "present": False,
            "sha256": None,
            "skipped_reason": "redis_dump_not_present_at_snapshot",
        }
    # artifacts component (dir merkle)
    if artifacts_dir.is_dir():
        components["artifacts"] = {
            "present": True,
            "sha256": _artifacts_merkle_sha256(artifacts_dir),
            "skipped_reason": None,
        }
    else:
        components["artifacts"] = {
            "present": False,
            "sha256": None,
            "skipped_reason": "artifacts_dir_not_present_at_snapshot",
        }

    snapshot_id = pre_restore_dir.name.replace("_pre-restore-", "", 1)
    manifest: dict[str, object] = {
        "manifest_version": 1,
        "snapshot_id": snapshot_id,
        "created_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target_compose_project_name": options.target_compose_project_name,
        "target_compose_file_path": str(options.target_compose_file_path),
        "target_pg_dsn_components": dict(sorted(options.target_pg_dsn_components.items())),
        "target_redis_endpoint": options.target_redis_endpoint,
        "target_artifacts_dir": str(options.target_artifacts_dir),
        "target_artifacts_container_path": options.target_artifacts_container_path,
        "postgres_major_version": options.expected_postgres_major_version,
        "alembic_head_at_snapshot": read_alembic_head_via_compose_exec(options),
        "components": components,
    }
    manifest_tmp = pre_restore_dir / "snapshot_manifest.json.tmp"
    manifest_path = pre_restore_dir / "snapshot_manifest.json"
    manifest_tmp.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    os.rename(manifest_tmp, manifest_path)


def verify_snapshot_manifest_binding(
    manifest: dict[str, object],
    options: RestoreOptions,
    rrc: object,  # RestoreRollbackApprovalClaim (avoid circular import)
) -> None:
    """SP022-T02 Phase 4 (R1 F-004 + ADV R1 F-017 adopt): manifest と RestoreOptions / rrc claim
    の binding 一致 verify. raise RestoreUsageError on mismatch.
    """
    # ADV R1 F-017 adopt: manifest_version 必須 + v1 のみ
    if manifest.get("manifest_version") != 1:
        raise RestoreUsageError(
            "restore_rollback_snapshot_manifest_unsupported_version",
            detail=f"manifest_version={manifest.get('manifest_version')!r}, expected=1",
        )
    # target binding fields 1:1
    pairs: list[tuple[str, object, object]] = [
        ("target_compose_project_name", manifest.get("target_compose_project_name"),
         options.target_compose_project_name),
        ("target_compose_file_path", manifest.get("target_compose_file_path"),
         str(options.target_compose_file_path)),
        ("target_redis_endpoint", manifest.get("target_redis_endpoint"),
         options.target_redis_endpoint),
        ("target_artifacts_dir", manifest.get("target_artifacts_dir"),
         str(options.target_artifacts_dir)),
        ("target_artifacts_container_path", manifest.get("target_artifacts_container_path"),
         options.target_artifacts_container_path),
        ("postgres_major_version", manifest.get("postgres_major_version"),
         options.expected_postgres_major_version),
    ]
    for name, actual, expected in pairs:
        if actual != expected:
            raise RestoreUsageError(
                "restore_rollback_snapshot_manifest_target_mismatch",
                detail=f"{name}: manifest={actual!r}, options={expected!r}",
            )
    # DSN components: sorted dict compare
    manifest_dsn = manifest.get("target_pg_dsn_components")
    if not isinstance(manifest_dsn, dict):
        raise RestoreUsageError(
            "restore_rollback_snapshot_manifest_target_mismatch",
            detail="target_pg_dsn_components not dict",
        )
    if dict(sorted(manifest_dsn.items())) != dict(sorted(options.target_pg_dsn_components.items())):
        raise RestoreUsageError(
            "restore_rollback_snapshot_manifest_target_mismatch",
            detail="target_pg_dsn_components mismatch",
        )


def verify_snapshot_component_hashes(
    pre_restore_dir: Path,
    manifest: dict[str, object],
    warnings: list[WarningCode],
) -> None:
    """SP022-T02 Phase 4 (R1 F-004 + R2 F-004 adopt): manifest 内 components 表に従い、
    present=true は file sha256 一致 verify、present=false は warnings に skipped_reason 追加.

    raise RestoreRuntimeError on (present=true で hash mismatch or file missing).
    """
    components = manifest.get("components")
    if not isinstance(components, dict):
        raise RestoreRuntimeError(
            "restore_rollback_snapshot_manifest_invalid_json",
            detail="components field missing or not dict",
        )
    for fname, spec in components.items():
        if not isinstance(spec, dict):
            raise RestoreRuntimeError(
                "restore_rollback_snapshot_manifest_invalid_json",
                detail=f"components.{fname} not dict",
            )
        present = spec.get("present")
        expected_sha256 = spec.get("sha256")
        skipped_reason = spec.get("skipped_reason")
        if present is True:
            # 必須 file
            target_path = pre_restore_dir / fname
            if fname == "artifacts":
                if not target_path.is_dir():
                    raise RestoreRuntimeError(
                        "restore_rollback_snapshot_component_missing",
                        detail=f"artifacts dir not found: {target_path}",
                    )
                actual_sha256 = _artifacts_merkle_sha256(target_path)
            else:
                if not target_path.is_file():
                    raise RestoreRuntimeError(
                        "restore_rollback_snapshot_component_missing",
                        detail=f"component file not found: {target_path}",
                    )
                actual_sha256 = _file_sha256(target_path)
            if actual_sha256 != expected_sha256:
                raise RestoreRuntimeError(
                    "restore_rollback_snapshot_component_hash_mismatch",
                    detail=f"{fname}: expected={expected_sha256!r}, actual={actual_sha256!r}",
                )
        elif present is False:
            # partial snapshot: skipped_reason を warning に
            if fname == "pre_restore_pg_dump.dump":
                warnings.append("restore_rollback_snapshot_component_db_dump_not_present")
            elif fname == "pre_restore_dump.rdb":
                warnings.append("restore_rollback_snapshot_component_redis_dump_not_present")
            _ = skipped_reason  # observed only
        else:
            raise RestoreRuntimeError(
                "restore_rollback_snapshot_manifest_invalid_json",
                detail=f"components.{fname}.present must be bool, got {present!r}",
            )


def place_redis_dump_rdb_via_named_volume(
    options: RestoreOptions, new_dump_rdb: Path, pre_restore_dir: Path,
) -> None:
    """Redis stopped 後、named volume host source に dump.rdb 配置 + AOF 退避 (R3 + R17-F-003)."""
    redis_host_path = acquire_redis_data_host_path(options)
    # 新 AOF (失敗 restore 中に Redis が生成した可能性) を退避 (R17-F-003)
    aof_dir = redis_host_path / "appendonlydir"
    if aof_dir.exists():
        shutil.move(str(aof_dir), str(pre_restore_dir / "redis_aof_backup"))
    shutil.copy2(new_dump_rdb, redis_host_path / "dump.rdb")


def place_artifacts(extracted_artifacts: Path, target_dir: Path) -> None:
    """extracted/artifacts → target_dir に再配置."""
    if target_dir.exists():
        # snapshot で move 済の前提、ここに来るのは異常時
        shutil.rmtree(target_dir, ignore_errors=False)
    shutil.copytree(extracted_artifacts, target_dir)


def rollback_from_pre_restore_snapshot(
    pre_restore_dir: Path, options: RestoreOptions, warnings: list[WarningCode],
) -> None:
    """3 component (artifacts + DB + Redis) snapshot から復旧.

    R4-F-001 + R5-F-001 + R17-F-003 + R19-F-002 + R20-F-001 統合 order:
    0a. app services を確実 stop (partial-up race 防止、R4-F-001)
    0b. postgres のみ up + healthy (Redis 失敗で DB rollback 不能を防止、R5-F-001)
    1. artifacts move back (R17-F-003 clean slate)
    2. DB pg_restore via compose exec (snapshot 存在 verify、R19-F-002)
    3. Redis dump.rdb 復旧 + AOF 復旧 (snapshot 存在 verify、R19-F-002)
    4. data services + app services start
    """
    # 0a. app stop (partial-up race 防止)
    stop_app_services(options)
    # 0b. postgres alive 保証
    start_postgres_wait_healthy(options)

    # 1. artifacts: 新削除 → snapshot 戻し
    if options.target_artifacts_dir.exists():
        shutil.rmtree(options.target_artifacts_dir, ignore_errors=False)
    artifacts_backup = pre_restore_dir / "artifacts"
    if artifacts_backup.exists():
        shutil.move(str(artifacts_backup), str(options.target_artifacts_dir))

    # 2. DB rollback: snapshot 存在 verify (R19-F-002)
    pre_db_dump = pre_restore_dir / "pre_restore_pg_dump.dump"
    if not pre_db_dump.exists():
        warnings.append("restore_rollback_db_skipped_no_pre_snapshot")
        start_app_services_wait_healthy(options)
        return
    try:
        db_result = invoke_pg_restore_via_compose_exec(
            options, dump_file=pre_db_dump, timeout_sec=PG_RESTORE_TIMEOUT_SEC,
        )
    except (SubprocessNotFoundError, SubprocessTimeoutError) as e:
        raise RestoreRuntimeError(
            "restore_rollback_failed",
            detail=f"db_rollback_subprocess_failed: {type(e).__name__}",
        ) from None
    if db_result.returncode != 0:
        raise RestoreRuntimeError(
            "restore_rollback_failed",
            detail=f"pg_restore_rollback_exit={db_result.returncode}",
        )

    # 3. Redis rollback: snapshot 存在 verify (R17-F-003 + R19-F-002)
    pre_redis_dump = pre_restore_dir / "pre_restore_dump.rdb"
    pre_aof_backup = pre_restore_dir / "redis_aof_backup"
    if not pre_redis_dump.exists():
        warnings.append("restore_rollback_redis_skipped_no_pre_snapshot")
    else:
        stop_redis_service_only(options)
        redis_host_path = acquire_redis_data_host_path(options)
        # 新 dump.rdb / appendonlydir 削除 (R17-F-003 clean slate)
        new_dump_rdb = redis_host_path / "dump.rdb"
        if new_dump_rdb.exists():
            new_dump_rdb.unlink()
        new_aof_dir = redis_host_path / "appendonlydir"
        if new_aof_dir.exists():
            shutil.rmtree(new_aof_dir, ignore_errors=False)
        shutil.copy2(pre_redis_dump, redis_host_path / "dump.rdb")
        if pre_aof_backup.exists():
            shutil.move(str(pre_aof_backup), str(redis_host_path / "appendonlydir"))
        try:
            start_redis_service_wait_healthy(options)
        except RestoreRuntimeError as e:
            raise RestoreRuntimeError(
                "restore_rollback_failed",
                detail=(
                    f"redis_rollback_start_failed: {e.detail}. "
                    "DB + artifacts rolled back, Redis manual recovery required: "
                    f"(a) docker volume inspect for host path, "
                    f"(b) pre-restore snapshot at {pre_restore_dir}/pre_restore_dump.rdb, "
                    "(c) docker compose up redis then redis-cli LASTSAVE verify"
                ),
            ) from e

    # 4. app start + healthcheck
    start_app_services_wait_healthy(options)


# --- main entry point: run_restore ---


def run_restore(options: RestoreOptions) -> RestoreResult:
    """restore orchestration entry point.

    R1-R24 全 58 findings 100% adopt 反映 (CRITICAL=0 達成 plan-review READY).
    """
    start = time.monotonic()

    # output_path-like checks (input_path side)
    if not options.input_path.is_absolute():
        raise RestoreUsageError(
            "restore_input_path_invalid",
            detail=f"input_path must be absolute: {options.input_path}",
        )
    suffixes = options.input_path.suffixes
    if not (len(suffixes) >= 2 and suffixes[-2:] == [".tar", ".age"]):
        raise RestoreUsageError(
            "restore_input_path_invalid",
            detail="must end with .tar.age",
        )

    # age identity file checks (R3 + R18-F-003 pattern)
    if options.age_identity_file.is_symlink():
        raise RestoreUsageError(
            "restore_age_identity_path_invalid",
            detail=f"age_identity_file must not be symlink: {options.age_identity_file}",
        )
    if not options.age_identity_file.is_file():
        raise RestoreUsageError(
            "restore_age_identity_path_invalid",
            detail=f"age_identity_file not found or not regular file: {options.age_identity_file}",
        )
    age_mode = stat.S_IMODE(options.age_identity_file.stat().st_mode)
    if age_mode not in (0o600, 0o400):
        raise RestoreUsageError(
            "restore_age_identity_path_invalid",
            detail=f"age_identity_file permission must be 0600 or 0400 (got 0o{age_mode:o})",
        )

    # target dir overwrite check (R9-F-001)
    if options.target_artifacts_dir.exists() and any(options.target_artifacts_dir.iterdir()):
        if not options.overwrite:
            raise RestoreUsageError(
                "restore_target_data_dir_in_use_without_overwrite",
                detail=f"target artifacts dir exists and non-empty: {options.target_artifacts_dir}",
            )

    tmp_dir = resolve_restore_temp_layout()
    warnings: list[WarningCode] = []
    pre_restore_dir: Path | None = None
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    meta: dict[str, Any] = {}

    try:
        # === Step 1: archive verification (immutable stage, sha256 + age decrypt) ===
        decrypted_tar = tmp_dir / "decrypted.tar"
        stage_dir = tmp_dir / "immutable_stage"
        stage_dir.mkdir(mode=0o700)
        verify_archive_sha256_and_decrypt_via_immutable_stage(
            options.input_path, options.archive_sha256, options.age_identity_file,
            decrypted_tar, stage_dir,
        )

        # === Step 1a: tar extraction with safety + DoS limits ===
        extracted_dir = tmp_dir / "extracted"
        extracted_dir.mkdir(mode=0o700)
        extract_with_limits(decrypted_tar, extracted_dir)

        # === Step 1b: checksums + meta + postgres version verify ===
        verify_checksums(extracted_dir)
        meta = read_and_verify_meta_json(extracted_dir / "meta.json", warnings)
        verify_postgres_major_version(meta, options.expected_postgres_major_version)

        # === Step 1.5: target binding consistency preflight (R11-R23) ===
        verify_target_binding_consistency(options)

        # === Step 1.6: pre-restore snapshot parent verify (F-PR78-R3-003 fix) ===
        # mkdir(mode=0o700, parents=False) failure を service stop 後でなく **service stop 前** に検出
        # (rollback 不能 outage 防止)
        snapshot_parent = options.target_artifacts_dir.parent
        if not snapshot_parent.is_dir():
            raise RestoreUsageError(
                "restore_output_path_invalid",
                detail=f"pre-restore snapshot parent dir does not exist: {snapshot_parent}",
            )

        # === Step 2: app service stop ===
        stop_app_services(options)

        # === Step 3: pre-restore snapshot ===
        def _register(p: Path) -> None:
            nonlocal pre_restore_dir
            pre_restore_dir = p
        create_pre_restore_snapshot(options, ts, _register, warnings)

        # === Step 4: artifacts placement ===
        place_artifacts(extracted_dir / "artifacts", options.target_artifacts_dir)

        # === Step 5: pg_restore via compose exec ===
        try:
            pg_result = invoke_pg_restore_via_compose_exec(
                options, dump_file=extracted_dir / "postgres" / "pg_dump.dump",
                timeout_sec=PG_RESTORE_TIMEOUT_SEC,
            )
        except (SubprocessNotFoundError, SubprocessTimeoutError) as e:
            raise RestoreRuntimeError(
                "restore_pg_restore_failed",
                detail=f"pg_restore_subprocess_failed: {type(e).__name__}",
            ) from None
        if pg_result.returncode != 0:
            raise RestoreRuntimeError(
                "restore_pg_restore_failed",
                detail=f"exit={pg_result.returncode}",
            )

        # === Step 6: Redis-only stop (R10-F-001 postgres alive) ===
        stop_redis_service_only(options)

        # === Step 7: Redis dump.rdb 置換 + AOF temp 退避 ===
        if pre_restore_dir is None:
            raise RestoreRuntimeError(
                "restore_redis_data_placement_failed",
                detail="pre_restore_dir not registered before Redis placement",
            )
        place_redis_dump_rdb_via_named_volume(
            options, extracted_dir / "redis" / "dump.rdb", pre_restore_dir,
        )

        # === Step 8: redis only up + healthcheck ===
        start_redis_service_wait_healthy(options)

        # === Step 9: alembic verify (R2-F-004 fix: app start 前) ===
        verify_alembic_head_in_db(options)

        # === Step 10: app service up + healthcheck ===
        start_app_services_wait_healthy(options)

    except (
        RestoreRuntimeError,
        RestoreUsageError,
        OSError,
        shutil.Error,
        subprocess.SubprocessError,
        SubprocessTimeoutError,
        SubprocessNotFoundError,
    ) as exc:
        # R6-F-001 + R7-F-001 fix: rollback catch を OSError/shutil.Error/SubprocessError まで広げる
        original_error_type = type(exc).__name__
        original_error_detail = str(exc)[:200]
        if pre_restore_dir is not None:
            try:
                rollback_from_pre_restore_snapshot(pre_restore_dir, options, warnings)
                warnings.append("restore_rollback_attempted")
            except (
                RestoreRuntimeError, OSError, shutil.Error,
                subprocess.SubprocessError, SubprocessTimeoutError, SubprocessNotFoundError,
            ) as rollback_exc:
                raise RestoreRuntimeError(
                    "restore_rollback_failed",
                    detail=(
                        f"original={original_error_type}({original_error_detail}), "
                        f"rollback_also_failed={type(rollback_exc).__name__}({str(rollback_exc)[:200]})"
                    ),
                ) from rollback_exc
        if isinstance(exc, (RestoreRuntimeError, RestoreUsageError)):
            raise
        raise RestoreRuntimeError(
            "restore_rollback_attempted",
            detail=f"non_restore_error_caught_and_rolled_back: {original_error_type}({original_error_detail})",
        ) from exc
    finally:
        # tmp_dir は機密性高 (復号済 tar)、必ず削除
        shutil.rmtree(tmp_dir, ignore_errors=True)
        # pre_restore_dir は SOP retention で保持 (6 month、ADR-00021 §321)
        # ここでは削除しない

    duration = time.monotonic() - start
    return RestoreResult(
        output_path=options.input_path,
        reason_code="restore_completed",
        warnings=tuple(warnings),
        duration_sec=duration,
        meta=meta,
    )


__all__ = [
    "AGE_DECRYPT_TIMEOUT_SEC",
    "APP_HEALTHCHECK_TIMEOUT_SEC",
    "DATA_HEALTHCHECK_TIMEOUT_SEC",
    "HEALTHCHECK_POLL_INTERVAL_SEC",
    "PG_DUMP_TIMEOUT_SEC",
    "PG_RESTORE_TIMEOUT_SEC",
    "REDIS_SAVE_TIMEOUT_SEC",
    "SUPPORTED_FORMAT_VERSIONS",
    "TAR_MAX_MEMBER_COUNT",
    "TAR_MAX_MEMBER_SIZE_BYTES",
    "TAR_MAX_TOTAL_SIZE_BYTES",
    "RestoreOptions",
    "RestoreResult",
    "RestoreRuntimeError",
    "RestoreUsageError",
    "acquire_redis_data_host_path",
    "all_services_healthy",
    "check_archive_member_allowlist",
    "create_pre_restore_snapshot",
    "extract_with_limits",
    "invoke_pg_dump_via_compose_exec",
    "invoke_pg_restore_via_compose_exec",
    "invoke_redis_save_sync_via_compose_exec",
    "place_artifacts",
    "place_redis_dump_rdb_via_named_volume",
    "read_and_verify_meta_json",
    "resolve_restore_temp_layout",
    "read_alembic_head_via_compose_exec",
    "rollback_from_pre_restore_snapshot",
    "run_restore",
    "verify_snapshot_component_hashes",
    "verify_snapshot_manifest_binding",
    "verify_target_binding_consistency",
    "start_app_services_wait_healthy",
    "start_postgres_wait_healthy",
    "start_redis_service_wait_healthy",
    "stop_app_services",
    "stop_redis_service_only",
    "verify_alembic_head_in_db",
    "verify_archive_sha256_and_decrypt_via_immutable_stage",
    "verify_checksums",
    "verify_postgres_major_version",
    "verify_tar_members_safe",
    "verify_target_binding_consistency",
]
