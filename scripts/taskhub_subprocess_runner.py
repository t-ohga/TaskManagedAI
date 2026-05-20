"""Common subprocess runner for taskhub admin CLI (SP022-T02 Phase 2 / T08 batch 2).

R1-F-009 + R3-F-001 adopt: shell=False / stdin=DEVNULL / timeout / env allowlist /
stderr sanitization / argv logging policy。

Security invariants (raw secret leakage 0):
- subprocess.run shell=False 固定 (shell injection 防止)
- stdin=subprocess.DEVNULL (interactive password prompt hang 防止)
- timeout 必須 (caller が明示指定)
- env は **explicit allowlist** で filter (secret-bearing env は明示 reject、PGPASSWORD /
  REDISCLI_AUTH / *_TOKEN / *_KEY / *_PASSWORD / AWS_SECRET_* 等)
- stderr capture + sanitization で secret pattern を redact
- argv 全体は audit に含めない、`command_name` + `arg_count` + `sanitized_flags` のみ
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# R3-F-001 adopt: explicit allowlist for child env vars。
# secret-bearing env は **絶対** allowlist に含めない。PostgreSQL credentials は
# temp .pgpass file + PGPASSFILE env のみ経路として許可。
DEFAULT_ENV_ALLOWLIST = frozenset({
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "USER",
    "LOGNAME",
    "TMPDIR",
    "PGPASSFILE",  # R3-F-001 adopt: temp .pgpass file path 経由のみ
})

# R3-F-001 adopt: secret-bearing env を pass しないよう明示 reject pattern。
# 万が一 allowlist に追加された場合の二重 防御。
SECRET_ENV_REJECT_PATTERNS = (
    re.compile(r"^PGPASSWORD$"),
    re.compile(r"^REDISCLI_AUTH$"),
    re.compile(r"^AWS_SECRET_.*$"),
    re.compile(r".*_TOKEN$", re.IGNORECASE),
    re.compile(r".*_KEY$", re.IGNORECASE),
    re.compile(r".*_PASSWORD$", re.IGNORECASE),
    re.compile(r".*_SECRET$", re.IGNORECASE),
    re.compile(r"^GITHUB_TOKEN$"),
)

# R1-F-009 + R1-F-005 adopt: stderr sanitization patterns。secret-like content を redact。
STDERR_REDACT_PATTERNS = (
    (re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----[^-]+-----END [A-Z ]+PRIVATE KEY-----"),
     "[REDACTED:PRIVATE_KEY]"),
    (re.compile(r"AGE-SECRET-KEY-[A-Z0-9]+"),
     "[REDACTED:AGE_SECRET_KEY]"),
    (re.compile(r"password\s*=\s*\S+", re.IGNORECASE),
     "password=[REDACTED]"),
    (re.compile(r"PGPASSWORD\s*=\s*\S+"),
     "PGPASSWORD=[REDACTED]"),
)

# Default timeouts (seconds)
DEFAULT_TIMEOUT_SEC = 60
PG_DUMP_TIMEOUT_SEC = 1800
REDIS_RDB_TIMEOUT_SEC = 300
AGE_ENCRYPT_TIMEOUT_SEC = 600


@dataclass(frozen=True)
class SubprocessResult:
    """Result of safe_subprocess.run, with sanitized output."""

    command_name: str  # argv[0] basename
    arg_count: int     # len(argv)
    returncode: int
    stdout: bytes      # binary stdout (e.g., pg_dump custom format dump)
    stderr_sanitized: str  # secret pattern redacted
    duration_sec: float
    sanitized_flags: tuple[str, ...]  # argv flags safe to log (e.g., "-h", "--format=custom")


@dataclass(frozen=True)
class SafeSubprocessConfig:
    """Configuration for run_safe_subprocess."""

    timeout_sec: int = DEFAULT_TIMEOUT_SEC
    cwd: Path | None = None
    extra_env_allowlist: tuple[str, ...] = field(default_factory=tuple)
    capture_stdout: bool = True
    capture_stderr: bool = True


class SubprocessTimeoutError(Exception):
    """timeout 超過。"""

    def __init__(self, command_name: str, timeout_sec: int) -> None:
        super().__init__(f"subprocess {command_name} exceeded timeout {timeout_sec}s")
        self.command_name = command_name
        self.timeout_sec = timeout_sec


class SubprocessNotFoundError(Exception):
    """command not found (FileNotFoundError)。"""

    def __init__(self, command_name: str) -> None:
        super().__init__(f"subprocess command not found: {command_name}")
        self.command_name = command_name


def _filter_env(parent_env: dict[str, str], *, extra_allowlist: tuple[str, ...] = ()) -> dict[str, str]:
    """Filter parent env to allowlist only, with secret reject double-defense.

    R3-F-001 adopt: allowlist + reject pattern の二重防御で secret-bearing env を child に
    渡さない。
    """
    allowlist: set[str] = set(DEFAULT_ENV_ALLOWLIST) | set(extra_allowlist)
    filtered: dict[str, str] = {}
    for k, v in parent_env.items():
        if k not in allowlist:
            continue
        # R3-F-001 adopt: 二重防御 reject (allowlist に誤って追加されても reject)
        if any(p.match(k) for p in SECRET_ENV_REJECT_PATTERNS):
            continue
        filtered[k] = v
    return filtered


def _sanitize_stderr(stderr_bytes: bytes) -> str:
    """Sanitize stderr by redacting secret patterns (R1-F-009 + R1-F-005 adopt)."""
    try:
        text = stderr_bytes.decode("utf-8", errors="replace")
    except (UnicodeDecodeError, AttributeError):
        return "[REDACTED:NON_UTF8_STDERR]"
    for pattern, replacement in STDERR_REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _extract_sanitized_flags(argv: list[str]) -> tuple[str, ...]:
    """Return argv flags safe to log (begins with `-`, no value-like tokens).

    例: `["pg_dump", "-h", "localhost", "-p", "5432", "--format=custom", "-f", "/tmp/x"]`
    → `("-h", "-p", "--format=custom", "-f")` (`localhost` / `5432` / path は除外)
    """
    return tuple(arg for arg in argv if arg.startswith("-"))


def run_safe_subprocess(
    argv: list[str],
    *,
    config: SafeSubprocessConfig | None = None,
) -> SubprocessResult:
    """Run subprocess with hardened defaults.

    R1-F-009 adopt:
    - shell=False
    - stdin=subprocess.DEVNULL (no interactive prompt hang)
    - timeout=config.timeout_sec
    - env=allowlist-filtered (no secret env)
    - capture_output with sanitized stderr
    - argv logging policy (sanitized_flags only, no raw values)

    Raises:
        SubprocessNotFoundError: argv[0] command not found
        SubprocessTimeoutError: timeout exceeded
    """
    import time
    if not argv:
        msg = "argv must not be empty"
        raise ValueError(msg)
    cfg = config or SafeSubprocessConfig()
    command_name = Path(argv[0]).name
    env = _filter_env(dict(os.environ), extra_allowlist=cfg.extra_env_allowlist)
    start = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S603
            argv,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if cfg.capture_stdout else subprocess.DEVNULL,
            stderr=subprocess.PIPE if cfg.capture_stderr else subprocess.DEVNULL,
            timeout=cfg.timeout_sec,
            check=False,
            cwd=str(cfg.cwd) if cfg.cwd else None,
            env=env,
        )
    except FileNotFoundError:
        raise SubprocessNotFoundError(command_name) from None
    except subprocess.TimeoutExpired:
        raise SubprocessTimeoutError(command_name, cfg.timeout_sec) from None
    duration = time.monotonic() - start
    return SubprocessResult(
        command_name=command_name,
        arg_count=len(argv),
        returncode=proc.returncode,
        stdout=proc.stdout or b"",
        stderr_sanitized=_sanitize_stderr(proc.stderr or b""),
        duration_sec=duration,
        sanitized_flags=_extract_sanitized_flags(argv),
    )


__all__ = [
    "AGE_ENCRYPT_TIMEOUT_SEC",
    "DEFAULT_ENV_ALLOWLIST",
    "DEFAULT_TIMEOUT_SEC",
    "PG_DUMP_TIMEOUT_SEC",
    "REDIS_RDB_TIMEOUT_SEC",
    "SECRET_ENV_REJECT_PATTERNS",
    "STDERR_REDACT_PATTERNS",
    "SafeSubprocessConfig",
    "SubprocessNotFoundError",
    "SubprocessResult",
    "SubprocessTimeoutError",
    "_filter_env",
    "_sanitize_stderr",
    "run_safe_subprocess",
]
