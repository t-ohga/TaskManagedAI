# ruff: noqa: S108
"""Sprint 7 BL-0072: forbidden path enforcement tests (AC-HARD-05)."""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

from backend.app.services.runner.forbidden_path import (
    ForbiddenPathDenyReason,
    ForbiddenPathViolation,
    canonicalize_path,
    detect_forbidden_path,
    resolve_and_detect,
)

EXPECTED_DENY_REASONS = (
    "secrets_dir",
    "env_file",
    "git_infrastructure",
    "migrations_dir",
    "github_workflows",
    "claude_harness",
    "claude_local",
    "codex_config",
    "host_secret_store",
    "system_credential",
    "kernel_interface",
    "docker_socket",
    "hook_trust_root",
    "null_byte",
    "empty_path",
)


def _assert_forbidden(
    raw_path: str,
    expected_reason: ForbiddenPathDenyReason,
) -> ForbiddenPathViolation:
    violation = detect_forbidden_path(raw_path)

    assert violation is not None
    assert violation.raw_path == raw_path
    assert violation.reason is expected_reason
    assert violation.canonical_path == canonicalize_path(raw_path)
    return violation


def _assert_allowed(raw_path: str) -> None:
    violation = detect_forbidden_path(raw_path)

    assert violation is None


def _make_symlink(link_path: Path, target_path: Path) -> None:
    try:
        link_path.symlink_to(target_path)
    except OSError as exc:
        pytest.skip(f"symlink を作成できない環境のため skip: {exc}")


def test_forbidden_path_deny_reason_enum_exhaustive() -> None:
    """ForbiddenPathDenyReason は runner path gate の監査 reason を固定する。"""

    assert tuple(reason.value for reason in ForbiddenPathDenyReason) == EXPECTED_DENY_REASONS


def test_canonicalize_rejects_nul_byte() -> None:
    """NUL byte を含む path は canonicalization 前に拒否する。"""

    with pytest.raises(ValueError, match="NUL"):
        canonicalize_path("safe\x00.env")


def test_canonicalize_rejects_empty_string() -> None:
    """空 path は fail-closed に扱うため canonicalization で拒否する。"""

    with pytest.raises(ValueError, match="non-empty"):
        canonicalize_path("")


def test_detect_reports_nul_byte_as_violation() -> None:
    """detect layer では NUL byte を deny reason 付き violation に変換する。"""

    violation = detect_forbidden_path("safe\x00.env")

    assert violation is not None
    assert violation.reason is ForbiddenPathDenyReason.NULL_BYTE
    assert violation.raw_path == "safe\x00.env"
    assert violation.canonical_path == ""


def test_detect_reports_empty_path_as_violation() -> None:
    """detect layer では empty path を deny reason 付き violation に変換する。"""

    violation = detect_forbidden_path("")

    assert violation is not None
    assert violation.reason is ForbiddenPathDenyReason.EMPTY_PATH
    assert violation.raw_path == ""
    assert violation.canonical_path == ""


def test_canonicalize_strips_zwj_zwnj_bom() -> None:
    """ZWJ / ZWNJ / BOM による path segment 偽装を物理削除する。"""

    assert canonicalize_path("a\u200db\u200cc\ufeff") == "abc"


def test_canonicalize_strips_c0_c1_control() -> None:
    """C0/C1 control character による denylist 分断を物理削除する。"""

    assert canonicalize_path("a\x01b\x85c") == "abc"


def test_canonicalize_strips_ansi_escape() -> None:
    """ANSI escape sequence による `.git` 分断を canonical form で除去する。"""

    assert canonicalize_path("/tmp/\x1b[31m.git\x1b[0m/config") == "/tmp/.git/config"


def test_canonicalize_url_decodes_percent() -> None:
    """URL percent encoding は denylist 判定前に 1 段 decode する。"""

    assert canonicalize_path("%2Egit%2Fconfig") == ".git/config"


def test_canonicalize_resolves_dotdot_parent_ref() -> None:
    """`..` parent reference は canonical path 上で解決する。"""

    assert canonicalize_path("src/app/../runner/file.py") == "src/runner/file.py"


def test_canonicalize_nfc_normalize() -> None:
    """Unicode combining sequence は NFC に正規化する。"""

    assert canonicalize_path("Cafe\u0301/menu.txt") == "Café/menu.txt"


def test_canonicalize_case_preserved() -> None:
    """canonicalize_path は大小文字を保持し、case fold は detect 側だけで行う。"""

    assert canonicalize_path("/TMP/Runner/File.PY") == "/TMP/Runner/File.PY"


def test_canonicalize_idempotent() -> None:
    """canonicalize_path は再適用しても結果が変わらない。"""

    first = canonicalize_path("src/%2E%2E/backend/app.py")
    second = canonicalize_path(first)

    assert first == "backend/app.py"
    assert second == first


@pytest.mark.parametrize(
    "raw_path",
    (
        ".git/config",
        ".git/objects/abc",
        ".git/hooks/pre-commit",
        ".git/info/exclude",
        "/repo/.git/config",
    ),
)
def test_detect_git_infrastructure(raw_path: str) -> None:
    """Git infrastructure は相対 path と絶対 path の両方で拒否する。"""

    _assert_forbidden(raw_path, ForbiddenPathDenyReason.GIT_INFRASTRUCTURE)


@pytest.mark.parametrize(
    "raw_path",
    (
        ".env",
        ".env.local",
        ".env.production",
        "/repo/.env",
        "/repo/.env.production",
    ),
)
def test_detect_env_file(raw_path: str) -> None:
    """`.env` および `.env.*` は host-level secret として拒否する。"""

    _assert_forbidden(raw_path, ForbiddenPathDenyReason.ENV_FILE)


@pytest.mark.parametrize(
    "raw_path",
    (
        "secrets/key.pem",
        "/path/to/secrets/key.pem",
        "/repo/app/secrets/token.txt",
    ),
)
def test_detect_secrets_dir(raw_path: str) -> None:
    """custom secret directory 配下への書き込みを拒否する。"""

    _assert_forbidden(raw_path, ForbiddenPathDenyReason.SECRETS_DIR)


@pytest.mark.parametrize(
    "raw_path",
    (
        "migrations/versions/001_init.py",
        "/repo/backend/migrations/versions/002.py",
    ),
)
def test_detect_migrations_dir(raw_path: str) -> None:
    """Alembic migration directory は runner patch から保護する。"""

    _assert_forbidden(raw_path, ForbiddenPathDenyReason.MIGRATIONS_DIR)


@pytest.mark.parametrize(
    "raw_path",
    (
        ".github/workflows/ci.yml",
        "/repo/.github/workflows/deploy.yml",
    ),
)
def test_detect_github_workflows(raw_path: str) -> None:
    """GitHub Actions workflow は CI 権限境界として拒否する。"""

    _assert_forbidden(raw_path, ForbiddenPathDenyReason.GITHUB_WORKFLOWS)


@pytest.mark.parametrize(
    "raw_path",
    (
        ".claude/settings.json",
        ".claude/settings.local.json",
        ".claude/CLAUDE.md",
        ".claude/hooks/dispatcher.sh",
        ".claude/agents/reviewer.md",
        ".claude/skills/dev-suite/SKILL.md",
        ".claude/rules/ai-output-boundary.md",
        ".claude/reference/harness.md",
        ".claude/commands/check.md",
        "/repo/.claude/CLAUDE.md",
    ),
)
def test_detect_claude_harness(raw_path: str) -> None:
    """Claude harness 正本と防御 hook は runner mutation から保護する。"""

    _assert_forbidden(raw_path, ForbiddenPathDenyReason.CLAUDE_HARNESS)


@pytest.mark.parametrize(
    "raw_path",
    (
        ".claude/local/hook-state/session.json",
        "/repo/.claude/local/cache.json",
    ),
)
def test_detect_claude_local(raw_path: str) -> None:
    """`.claude/local/` の local state 改ざんを拒否する。"""

    _assert_forbidden(raw_path, ForbiddenPathDenyReason.CLAUDE_LOCAL)


@pytest.mark.parametrize(
    "raw_path",
    (
        ".codex/config.toml",
        ".codex/hooks.json",
        "/repo/.codex/agents/security.toml",
    ),
)
def test_detect_codex_config(raw_path: str) -> None:
    """Codex 実行設定と hook 設定は runner から保護する。"""

    _assert_forbidden(raw_path, ForbiddenPathDenyReason.CODEX_CONFIG)


@pytest.mark.parametrize(
    "raw_path",
    (
        "~/.ssh/id_ed25519",
        "/home/runner/.aws/credentials",
        "/Users/tohga/.kube/config",
    ),
)
def test_detect_host_secret_store(raw_path: str) -> None:
    """host credential store は sandbox 内 command plan から拒否する。"""

    _assert_forbidden(raw_path, ForbiddenPathDenyReason.HOST_SECRET_STORE)


@pytest.mark.parametrize(
    "raw_path",
    (
        "~/.claude-trusted/taskmanagedai-hook-wrapper.sh",
        "~/.claude-trusted-state/taskmanagedai/session/state.json",
        "/Users/tohga/.claude-trusted/taskmanagedai-hook-manifest.sha256",
    ),
)
def test_detect_hook_trust_root(raw_path: str) -> None:
    """ADR-00012 の repo 外 hook trust root を pre-protect する。"""

    _assert_forbidden(raw_path, ForbiddenPathDenyReason.HOOK_TRUST_ROOT)


@pytest.mark.parametrize(
    "raw_path",
    (
        "/etc/passwd",
        "/etc/shadow",
        "/etc/sudoers",
    ),
)
def test_detect_system_credential(raw_path: str) -> None:
    """system credential file への参照を拒否する。"""

    _assert_forbidden(raw_path, ForbiddenPathDenyReason.SYSTEM_CREDENTIAL)


@pytest.mark.parametrize(
    "raw_path",
    (
        "/proc/self/environ",
        "/proc/1/root",
        "/sys/kernel/debug",
    ),
)
def test_detect_kernel_interface(raw_path: str) -> None:
    """kernel interface path への参照を拒否する。"""

    _assert_forbidden(raw_path, ForbiddenPathDenyReason.KERNEL_INTERFACE)


@pytest.mark.parametrize(
    "raw_path",
    (
        "/var/run/docker.sock",
        "/run/docker.sock",
    ),
)
def test_detect_docker_socket(raw_path: str) -> None:
    """Docker socket は host control 境界として拒否する。"""

    _assert_forbidden(raw_path, ForbiddenPathDenyReason.DOCKER_SOCKET)


def test_detect_dotdot_traversal() -> None:
    """`..` traversal で forbidden path へ到達する bypass を拒否する。"""

    violation = _assert_forbidden("../../../.env", ForbiddenPathDenyReason.ENV_FILE)

    assert violation.canonical_path == "../../../.env"


def test_detect_url_encoded() -> None:
    """URL encoded traversal と `.git` 偽装を decode 後に拒否する。"""

    violation = _assert_forbidden(
        "%2E%2E%2F%2Egit%2Fconfig",
        ForbiddenPathDenyReason.GIT_INFRASTRUCTURE,
    )

    assert violation.canonical_path == "../.git/config"


def test_detect_unicode_zwj_bypass() -> None:
    """ZWJ を挟んだ `.git` segment 偽装を strip 後に拒否する。"""

    violation = _assert_forbidden(
        "/repo/.g\u200dit/config",
        ForbiddenPathDenyReason.GIT_INFRASTRUCTURE,
    )

    assert violation.canonical_path == "/repo/.git/config"


def test_detect_case_insensitive_mac() -> None:
    """macOS case-insensitive filesystem を前提に大小文字 bypass を拒否する。"""

    violation = _assert_forbidden(
        "/repo/.GIT/config",
        ForbiddenPathDenyReason.GIT_INFRASTRUCTURE,
    )

    assert violation.canonical_path == "/repo/.GIT/config"


def test_detect_double_slash() -> None:
    """double slash normalization で Docker socket bypass を拒否する。"""

    violation = _assert_forbidden(
        "//var//run/docker.sock",
        ForbiddenPathDenyReason.DOCKER_SOCKET,
    )

    assert violation.canonical_path == "/var/run/docker.sock"


def test_allow_normal_workdir_path() -> None:
    """runner workdir 配下の通常ファイルは denylist では拒否しない。"""

    _assert_allowed("/tmp/runner-123456/foo.txt")


def test_allow_relative_path() -> None:
    """通常の相対 path は denylist では拒否しない。"""

    _assert_allowed("subdir/file.py")


def test_allow_path_with_dot_git_substring() -> None:
    """`.git` という substring だけでは git infrastructure とみなさない。"""

    _assert_allowed("/tmp/runner/my.git_backup/config")


def test_resolve_follows_symlink_to_forbidden(tmp_path: Path) -> None:
    """symlink target が forbidden path の場合は resolve 後に拒否する。"""

    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    target = git_dir / "config"
    target.write_text("[core]\n", encoding="utf-8")
    link = tmp_path / "allowed-link"
    _make_symlink(link, target)

    violation = resolve_and_detect(str(link))

    assert violation is not None
    assert violation.reason is ForbiddenPathDenyReason.GIT_INFRASTRUCTURE
    assert violation.raw_path == str(target.resolve())
    assert violation.canonical_path == str(target.resolve())


def test_resolve_allows_normal_symlink(tmp_path: Path) -> None:
    """symlink target が通常 file の場合は許可する。"""

    target = tmp_path / "normal.txt"
    target.write_text("ok", encoding="utf-8")
    link = tmp_path / "normal-link"
    _make_symlink(link, target)

    assert resolve_and_detect(str(link)) is None


def test_resolve_handles_broken_symlink(tmp_path: Path) -> None:
    """broken symlink は OSError や false positive なしで扱う。"""

    link = tmp_path / "broken-link"
    _make_symlink(link, tmp_path / "missing-normal.txt")

    assert resolve_and_detect(str(link)) is None


def test_violation_is_frozen() -> None:
    """ForbiddenPathViolation は監査 record として immutable にする。"""

    violation = ForbiddenPathViolation(
        raw_path=".env",
        canonical_path=".env",
        reason=ForbiddenPathDenyReason.ENV_FILE,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        violation.raw_path = "changed"


def test_violation_includes_raw_and_canonical() -> None:
    """violation は caller-supplied raw と canonical path の両方を保持する。"""

    violation = _assert_forbidden(
        "%2E%2E%2F%2Eenv",
        ForbiddenPathDenyReason.ENV_FILE,
    )

    assert violation.raw_path == "%2E%2E%2F%2Eenv"
    assert violation.canonical_path == "../.env"
    assert os.path.normpath(violation.canonical_path) == "../.env"

