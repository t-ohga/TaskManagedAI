"""Sprint 7 BL-0072: forbidden path enforcement (AC-HARD-05 boundary).

ADR-00008 §denylist + §canonical path normalization を実装。
Sprint 6 batch 2 redaction.py の Cc/Cf carpet-bomb pattern を path 入力にも
適用 (Unicode bypass 防御)、Sprint 6 batch 1 launcher.py の path containment
+ symlink reject pattern を runner sandbox に拡張。

設計 (rules/ai-output-boundary.md §7 + ADR-00008):

- ``detect_forbidden_path(path)`` は path string を入力に取り、
  ``ForbiddenPathViolation | None`` を返す。
- canonical path normalization: ``..`` resolution / symlink follow /
  URL encoded percent-decode / Unicode default-ignorable strip / case-
  insensitive 比較 (macOS HFS+ 対応)。
- denylist は ADR-00008 §denylist の 13 種を実装。allowlist は caller
  (RunnerAdapter) が runtime に決定する (本 module は **denylist only** で
  fail-closed)。
"""

from __future__ import annotations

import os
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

# Codex SP6B2 R7-001 / R8-001 で確立した Cc/Cf carpet-bomb pattern を共有。
# `_strip_invisible` は path 入力の Unicode bypass (ZWJ / BOM / VSS 等) を消す。
_CONTROL_CHAR_RE = re.compile(
    "["
    "\x00-\x08\x0b\x0c\x0e-\x1f"
    "\x7f-"
    "͏"
    "​-‏"
    " -‮"
    "⁠-⁤"
    "⁦-⁩"
    "﻿"
    "︀-️"
    "\U000e0000-\U000e007f"
    "\U000e0100-\U000e01ef"
    "]"
)

# Sprint 6 batch 2 redaction.py と同じ ANSI strip pattern を path 入力にも
# 適用 (.git\x1b[0m/config のような bypass を防御)。
_ANSI_ESCAPE_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"
    r"|\x1b\[[^\n]*"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b\][^\n]*"
    r"|\x1b[@-Z\\-_]"
    r"|\x1b"
)


class ForbiddenPathDenyReason(StrEnum):
    SECRETS_DIR = "secrets_dir"
    ENV_FILE = "env_file"
    GIT_INFRASTRUCTURE = "git_infrastructure"
    MIGRATIONS_DIR = "migrations_dir"
    GITHUB_WORKFLOWS = "github_workflows"
    CLAUDE_HARNESS = "claude_harness"
    CLAUDE_LOCAL = "claude_local"
    CODEX_CONFIG = "codex_config"
    HOST_SECRET_STORE = "host_secret_store"  # noqa: S105 - enum value, not password
    SYSTEM_CREDENTIAL = "system_credential"
    KERNEL_INTERFACE = "kernel_interface"
    DOCKER_SOCKET = "docker_socket"
    HOOK_TRUST_ROOT = "hook_trust_root"  # ADR-00012 §Sprint 7 pre-protect
    NULL_BYTE = "null_byte"
    EMPTY_PATH = "empty_path"


@dataclass(frozen=True, slots=True)
class ForbiddenPathViolation:
    raw_path: str
    canonical_path: str
    reason: ForbiddenPathDenyReason


# ADR-00008 §denylist の 13 種 + ADR-00012 §pre-protect (hook trust root)
_FORBIDDEN_FRAGMENTS: tuple[tuple[str, ForbiddenPathDenyReason], ...] = (
    ("/.git/", ForbiddenPathDenyReason.GIT_INFRASTRUCTURE),
    ("/.env", ForbiddenPathDenyReason.ENV_FILE),
    ("/secrets/", ForbiddenPathDenyReason.SECRETS_DIR),
    ("/migrations/", ForbiddenPathDenyReason.MIGRATIONS_DIR),
    ("/.github/workflows/", ForbiddenPathDenyReason.GITHUB_WORKFLOWS),
    ("/.claude/local/", ForbiddenPathDenyReason.CLAUDE_LOCAL),
    ("/.codex/", ForbiddenPathDenyReason.CODEX_CONFIG),
    ("/.claude/settings.json", ForbiddenPathDenyReason.CLAUDE_HARNESS),
    ("/.claude/settings.local.json", ForbiddenPathDenyReason.CLAUDE_HARNESS),
    ("/.claude/CLAUDE.md", ForbiddenPathDenyReason.CLAUDE_HARNESS),
    ("/.claude/hooks/", ForbiddenPathDenyReason.CLAUDE_HARNESS),
    ("/.claude/agents/", ForbiddenPathDenyReason.CLAUDE_HARNESS),
    ("/.claude/skills/", ForbiddenPathDenyReason.CLAUDE_HARNESS),
    ("/.claude/rules/", ForbiddenPathDenyReason.CLAUDE_HARNESS),
    ("/.claude/reference/", ForbiddenPathDenyReason.CLAUDE_HARNESS),
    ("/.claude/commands/", ForbiddenPathDenyReason.CLAUDE_HARNESS),
    ("/.ssh/", ForbiddenPathDenyReason.HOST_SECRET_STORE),
    ("/.aws/", ForbiddenPathDenyReason.HOST_SECRET_STORE),
    ("/.kube/", ForbiddenPathDenyReason.HOST_SECRET_STORE),
    ("/.claude-trusted/", ForbiddenPathDenyReason.HOOK_TRUST_ROOT),
    ("/.claude-trusted-state/", ForbiddenPathDenyReason.HOOK_TRUST_ROOT),
)

# Absolute path prefixes (system-level forbidden、container 内でも host fs
# mount を防ぐ defense-in-depth)。
_FORBIDDEN_PREFIXES: tuple[tuple[str, ForbiddenPathDenyReason], ...] = (
    ("/etc/passwd", ForbiddenPathDenyReason.SYSTEM_CREDENTIAL),
    ("/etc/shadow", ForbiddenPathDenyReason.SYSTEM_CREDENTIAL),
    ("/etc/sudoers", ForbiddenPathDenyReason.SYSTEM_CREDENTIAL),
    ("/proc/", ForbiddenPathDenyReason.KERNEL_INTERFACE),
    ("/sys/", ForbiddenPathDenyReason.KERNEL_INTERFACE),
    ("/var/run/docker.sock", ForbiddenPathDenyReason.DOCKER_SOCKET),
    ("/run/docker.sock", ForbiddenPathDenyReason.DOCKER_SOCKET),
)


def canonicalize_path(raw: str) -> str:
    """Path string を canonical form に正規化する。

    手順 (順序重要):
    1. NUL byte / 空文字を reject 用 sentinel `""` を return しない (raise)。
    2. Unicode Cc/Cf default-ignorable strip (Sprint 6 batch 2 と同じ pattern)。
    3. ANSI escape strip (実 redaction.py を import する循環を避け、本 module
       で簡略 re で実装)。
    4. URL percent-decode を **1 回だけ** 適用 (多段 encode は decode 後の
       string に再適用するため caller が iterate するか別途処理)。
    5. unicode NFC normalize (Mac HFS+ 互換 + confusable 軽減)。
    6. ``..`` parent ref を ``os.path.normpath`` で resolution (relative も含む)。
    7. case-insensitive 比較のため最終結果を lowercase 化した shadow も返したい
       が、本関数は **canonical 単一値** を返す。比較側 (detect_forbidden_path)
       が `.lower()` で case-insensitive 比較する。
    """

    if "\x00" in raw:
        raise ValueError("path must not contain NUL byte")
    if not raw:
        raise ValueError("path must be non-empty")
    # ANSI escape strip (Sprint 6 redaction.py と同じ pattern)
    cleaned = _ANSI_ESCAPE_RE.sub("", raw)
    # bare ESC residual も削除 (defense-in-depth)
    cleaned = cleaned.replace("\x1b", "")
    # Unicode Cc/Cf strip
    cleaned = _CONTROL_CHAR_RE.sub("", cleaned)
    cleaned = "".join(
        c
        for c in cleaned
        if c in {"\t", "\n", "\r"}
        or unicodedata.category(c) not in {"Cc", "Cf"}
    )
    # URL percent-decode (Codex SP7 R1 F-007 adopt: 多段 encode 対応、
    # 最大 5 回 unquote until stable で `%252Fgit%252Fconfig` のような
    # double-encoded を fully decode)。
    for _ in range(5):
        decoded = urllib.parse.unquote(cleaned)
        if decoded == cleaned:
            break
        cleaned = decoded
    # NFC normalize
    cleaned = unicodedata.normalize("NFC", cleaned)
    # Path normalization (.. resolve、relative も含む)
    normalized = os.path.normpath(cleaned)
    # POSIX ``//`` prefix preservation を collapse (e.g. `//var/run` → `/var/run`)
    if normalized.startswith("//") and not normalized.startswith("///"):
        normalized = normalized[1:]
    return normalized


def detect_forbidden_path(raw: str) -> ForbiddenPathViolation | None:
    """forbidden path を検出。matched 時は violation、なければ None。

    canonical path + lowercase 比較で fragment / prefix を判定。symlink
    follow は本 module では行わない (runner caller が
    ``Path.resolve(strict=False)`` で行う前提)。
    """

    try:
        canonical = canonicalize_path(raw)
    except ValueError as exc:
        msg = str(exc).lower()
        if "nul" in msg:
            reason = ForbiddenPathDenyReason.NULL_BYTE
        else:
            reason = ForbiddenPathDenyReason.EMPTY_PATH
        return ForbiddenPathViolation(
            raw_path=raw,
            canonical_path="",
            reason=reason,
        )

    canonical_lower = canonical.lower()
    # Collapse leading consecutive slashes (POSIX ``os.path.normpath`` keeps
    # ``//`` at the head). Required to detect ``//var//run/docker.sock`` →
    # ``/var/run/docker.sock``.
    canonical_lower = re.sub(r"^/+", "/", canonical_lower)
    # Synthetic leading slash for relative paths so fragment matchers that
    # start with ``/`` (e.g. ``/.claude/CLAUDE.md``) also catch relative
    # inputs like ``.claude/CLAUDE.md``.
    probe = canonical_lower if canonical_lower.startswith("/") else "/" + canonical_lower

    # Fragment match (case-insensitive、fragment 側も .lower() で正規化)
    for fragment, reason in _FORBIDDEN_FRAGMENTS:
        if fragment.lower() in probe:
            return ForbiddenPathViolation(
                raw_path=raw,
                canonical_path=canonical,
                reason=reason,
            )

    # Prefix match (case-insensitive、absolute path のみ)。Codex SP7 R1 F-008
    # adopt: prefix.rstrip("/") も exact match 対象に含め、root path 自体
    # (`/proc` / `/sys`) も deny。
    for prefix, reason in _FORBIDDEN_PREFIXES:
        prefix_lower = prefix.lower()
        stripped = prefix_lower.rstrip("/")
        if (
            probe == prefix_lower
            or probe == stripped
            or probe.startswith(stripped + "/")
        ):
            return ForbiddenPathViolation(
                raw_path=raw,
                canonical_path=canonical,
                reason=reason,
            )

    return None


def resolve_and_detect(raw: str) -> ForbiddenPathViolation | None:
    """``Path.resolve()`` で symlink follow 後の forbidden path も検出。

    symlink → forbidden target の場合に source path 自体は forbidden では
    ないが、resolved target が forbidden の経路を fail-closed reject。
    """

    primary = detect_forbidden_path(raw)
    if primary is not None:
        return primary
    try:
        resolved = str(Path(raw).resolve(strict=False))
    except OSError:
        return None
    return detect_forbidden_path(resolved)


__all__ = [
    "ForbiddenPathDenyReason",
    "ForbiddenPathViolation",
    "canonicalize_path",
    "detect_forbidden_path",
    "resolve_and_detect",
]
