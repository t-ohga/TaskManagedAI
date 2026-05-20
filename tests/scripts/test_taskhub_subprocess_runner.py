"""SP022-T02 Phase 2 / T08 batch 2 — taskhub_subprocess_runner unit tests.

R1-F-009 + R3-F-001 adopt: subprocess hardening contract verification。
"""

from __future__ import annotations

import os
import sys

import pytest

from scripts.taskhub_subprocess_runner import (
    SECRET_ENV_REJECT_PATTERNS,
    SafeSubprocessConfig,
    SubprocessNotFoundError,
    SubprocessTimeoutError,
    _filter_env,
    _sanitize_stderr,
    run_safe_subprocess,
)

# --- Pure helper tests ---


def test_filter_env_keeps_allowlist_only() -> None:
    parent = {"PATH": "/usr/bin", "HOME": "/tmp", "PGPASSWORD": "secret"}  # noqa: S108 — test fixture
    filtered = _filter_env(parent)
    assert "PATH" in filtered
    assert "HOME" in filtered
    assert "PGPASSWORD" not in filtered


def test_filter_env_rejects_secret_patterns_double_defense() -> None:
    """R3-F-001 adopt: 万が一 allowlist に追加されても secret reject pattern で二重防御."""
    parent = {"PATH": "/usr/bin", "MY_SECRET_TOKEN": "abc"}
    # explicitly add to allowlist
    filtered = _filter_env(parent, extra_allowlist=("MY_SECRET_TOKEN",))
    # reject pattern (*_TOKEN) should catch this
    assert "MY_SECRET_TOKEN" not in filtered


def test_filter_env_rejects_pgpassword() -> None:
    """R3-F-001 adopt: PGPASSWORD は absolute reject."""
    parent = {"PATH": "/usr/bin", "PGPASSWORD": "hunter2"}
    filtered = _filter_env(parent, extra_allowlist=("PGPASSWORD",))
    assert "PGPASSWORD" not in filtered


def test_filter_env_rejects_rediscli_auth() -> None:
    parent = {"PATH": "/usr/bin", "REDISCLI_AUTH": "secret"}
    filtered = _filter_env(parent, extra_allowlist=("REDISCLI_AUTH",))
    assert "REDISCLI_AUTH" not in filtered


def test_filter_env_allows_pgpassfile() -> None:
    """R3-F-001 adopt: PGPASSFILE は temp file 経路として allowlist 残存."""
    pgpass_str = "/tmp/.pgpass"  # noqa: S108 — test fixture, intentional /tmp literal for env value
    parent = {"PATH": "/usr/bin", "PGPASSFILE": pgpass_str}
    filtered = _filter_env(parent)
    assert filtered.get("PGPASSFILE") == pgpass_str


def test_sanitize_stderr_redacts_private_key() -> None:
    stderr = b"some text\n-----BEGIN OPENSSH PRIVATE KEY-----\nABCDEF\n-----END OPENSSH PRIVATE KEY-----\n"
    sanitized = _sanitize_stderr(stderr)
    assert "PRIVATE KEY" not in sanitized or "[REDACTED" in sanitized
    assert "ABCDEF" not in sanitized


def test_sanitize_stderr_redacts_age_secret() -> None:
    stderr = b"AGE-SECRET-KEY-12345ABCDEF\n"
    sanitized = _sanitize_stderr(stderr)
    assert "AGE-SECRET-KEY-12345" not in sanitized
    assert "[REDACTED:AGE_SECRET_KEY]" in sanitized


def test_sanitize_stderr_redacts_password_kv() -> None:
    stderr = b"connection failed: password=hunter2\n"
    sanitized = _sanitize_stderr(stderr)
    assert "hunter2" not in sanitized
    assert "[REDACTED]" in sanitized


def test_sanitize_stderr_non_utf8_safe() -> None:
    stderr = b"\xff\xfe\x00\x01"
    sanitized = _sanitize_stderr(stderr)
    # should not raise; returns redacted/replaced string
    assert isinstance(sanitized, str)


# --- run_safe_subprocess tests with fake tools ---


def test_run_safe_subprocess_simple_echo() -> None:
    """Verify basic execution + stdout capture."""
    result = run_safe_subprocess(
        [sys.executable, "-c", "print('hello world')"],
        config=SafeSubprocessConfig(timeout_sec=10),
    )
    assert result.returncode == 0
    assert b"hello world" in result.stdout


def test_run_safe_subprocess_not_found_raises() -> None:
    with pytest.raises(SubprocessNotFoundError) as exc_info:
        run_safe_subprocess(
            ["/nonexistent-command-12345"],
            config=SafeSubprocessConfig(timeout_sec=5),
        )
    assert exc_info.value.command_name == "/nonexistent-command-12345" or \
           exc_info.value.command_name == "nonexistent-command-12345"


def test_run_safe_subprocess_timeout_raises() -> None:
    with pytest.raises(SubprocessTimeoutError):
        run_safe_subprocess(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            config=SafeSubprocessConfig(timeout_sec=1),
        )


def test_run_safe_subprocess_empty_argv_raises() -> None:
    with pytest.raises(ValueError):
        run_safe_subprocess([])


def test_run_safe_subprocess_stdin_is_devnull() -> None:
    """R1-F-009 adopt: stdin=DEVNULL で interactive password prompt hang を防止."""
    # If stdin is DEVNULL, read from stdin gets EOF immediately
    result = run_safe_subprocess(
        [sys.executable, "-c", "import sys; data = sys.stdin.read(); print(f'stdin_empty={not data}')"],
        config=SafeSubprocessConfig(timeout_sec=5),
    )
    assert result.returncode == 0
    assert b"stdin_empty=True" in result.stdout


def test_run_safe_subprocess_secret_env_not_passed() -> None:
    """R3-F-001 adopt: secret-bearing env が child process に渡らないこと verify."""
    os.environ["TEST_SECRET_PASSWORD"] = "should_not_leak"
    try:
        result = run_safe_subprocess(
            [sys.executable, "-c", "import os; print(os.environ.get('TEST_SECRET_PASSWORD', 'absent'))"],
            config=SafeSubprocessConfig(timeout_sec=5),
        )
        assert result.returncode == 0
        assert b"absent" in result.stdout
    finally:
        del os.environ["TEST_SECRET_PASSWORD"]


def test_run_safe_subprocess_sanitized_flags_extracted() -> None:
    """argv logging policy: flags のみ抽出、value-like tokens は除外."""
    result = run_safe_subprocess(
        [sys.executable, "-c", "print('done')"],
        config=SafeSubprocessConfig(timeout_sec=5),
    )
    # argv: [python, "-c", "print('done')"] → "-c" のみ flag
    assert "-c" in result.sanitized_flags
    assert "print('done')" not in result.sanitized_flags  # value excluded


def test_secret_env_reject_patterns_cover_common_secrets() -> None:
    """SECRET_ENV_REJECT_PATTERNS が一般的な secret env を全て cover."""
    test_cases = [
        "PGPASSWORD", "REDISCLI_AUTH", "AWS_SECRET_ACCESS_KEY",
        "GITHUB_TOKEN", "MY_API_KEY", "SOMETHING_PASSWORD",
        "OTHER_SECRET",
    ]
    for env_name in test_cases:
        assert any(p.match(env_name) for p in SECRET_ENV_REJECT_PATTERNS), \
            f"{env_name} should match a secret reject pattern"
