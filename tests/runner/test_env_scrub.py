"""Sprint 7 BL-0076: env_scrub module tests."""

from __future__ import annotations

import pytest

from backend.app.services.runner.env_scrub import (
    is_forbidden_env_name,
    scrub_env,
)

# Sample of hardcode forbidden names (full set is 50+)
HARDCODE_FORBIDDEN: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "TAILSCALE_AUTHKEY",
    "SOPS_AGE_KEY",
    "AGE_PRIVATE_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "DATABASE_URL",
    "PYTHONPATH",
    "LD_PRELOAD",
    "DYLD_INSERT_LIBRARIES",
    "SSH_AUTH_SOCK",
    "GIT_CONFIG_GLOBAL",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "SUPABASE_SERVICE_ROLE_KEY",
)

# Pattern-based forbidden names (caller-supplied unknown but secret-like)
PATTERN_FORBIDDEN: tuple[str, ...] = (
    "ACME_CUSTOM_TOKEN",
    "VENDOR_API_KEY",
    "INTERNAL_SECRET",
    "DB_PASSWORD",
    "MY_CREDENTIALS",
    "PROD_PRIVATE_KEY",
    "service_token",  # case-insensitive
    "SERVICE_AUTHKEY",
    "BEARER_TOKEN",
    "X_BEARER",
)


@pytest.mark.parametrize("name", HARDCODE_FORBIDDEN)
def test_hardcode_forbidden_detected(name: str) -> None:
    assert is_forbidden_env_name(name) is True


@pytest.mark.parametrize("name", PATTERN_FORBIDDEN)
def test_pattern_forbidden_detected(name: str) -> None:
    assert is_forbidden_env_name(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "TERM",
        "CI",
        "PYTHONUNBUFFERED",
        "MY_CUSTOM_VAR",
    ],
)
def test_safe_env_not_flagged(name: str) -> None:
    assert is_forbidden_env_name(name) is False


def test_scrub_env_excludes_forbidden_names() -> None:
    """Forbidden names must be excluded from scrubbed env."""
    allowlist = frozenset({"OPENAI_API_KEY", "HOME", "PATH"})
    base_env = {
        "OPENAI_API_KEY": "sk-secret-value",
        "HOME": "/home/user",
        "PATH": "/usr/bin:/bin",
    }
    result = scrub_env(allowlist, base_env)
    assert "OPENAI_API_KEY" not in result.env
    assert "HOME" in result.env
    assert "PATH" in result.env
    assert "OPENAI_API_KEY" in result.scrubbed_keys


def test_scrub_env_pattern_match() -> None:
    """Pattern-based forbidden names (caller-supplied unknown TOKEN/KEY) must be scrubbed."""
    allowlist = frozenset({"VENDOR_ACME_TOKEN", "HOME", "ACME_API_KEY"})
    base_env = {
        "VENDOR_ACME_TOKEN": "evil",
        "HOME": "/home/user",
        "ACME_API_KEY": "evil",
    }
    result = scrub_env(allowlist, base_env)
    assert "VENDOR_ACME_TOKEN" not in result.env
    assert "ACME_API_KEY" not in result.env
    assert "HOME" in result.env
    assert "VENDOR_ACME_TOKEN" in result.scrubbed_keys
    assert "ACME_API_KEY" in result.scrubbed_keys


def test_scrub_env_missing_keys_reported() -> None:
    """Keys in allowlist but not in base_env must be reported."""
    allowlist = frozenset({"HOME", "NOT_IN_ENV"})
    base_env = {"HOME": "/home/user"}
    result = scrub_env(allowlist, base_env)
    assert "HOME" in result.env
    assert "NOT_IN_ENV" not in result.env
    assert "NOT_IN_ENV" in result.allowlist_missed_keys


def test_scrub_env_injects_path_default() -> None:
    """PATH must be injected if not in allowlist."""
    result = scrub_env(frozenset(), base_env={})
    assert result.env["PATH"] == "/usr/bin:/bin"


def test_scrub_env_inject_path_disabled() -> None:
    """inject_path=False suppresses PATH injection."""
    result = scrub_env(frozenset(), base_env={}, inject_path=False)
    assert "PATH" not in result.env


def test_scrub_env_audit_no_raw_value() -> None:
    """scrubbed_keys must not contain raw values (audit invariant)."""
    allowlist = frozenset({"OPENAI_API_KEY"})
    base_env = {"OPENAI_API_KEY": "sk-CONFIDENTIAL"}
    result = scrub_env(allowlist, base_env)
    # Audit invariant: scrubbed_keys is the *name only*
    assert "OPENAI_API_KEY" in result.scrubbed_keys
    for key in result.scrubbed_keys:
        assert "CONFIDENTIAL" not in key
        assert "sk-" not in key


def test_scrub_env_uses_os_environ_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """When base_env=None, ``os.environ`` is used."""
    monkeypatch.setenv("CUSTOM_VAR_FOR_TEST", "custom-value")
    result = scrub_env(frozenset({"CUSTOM_VAR_FOR_TEST"}))
    assert result.env.get("CUSTOM_VAR_FOR_TEST") == "custom-value"


def test_env_scrub_result_frozen() -> None:
    """EnvScrubResult must be frozen (dataclass invariant)."""
    import dataclasses

    result = scrub_env(frozenset(), base_env={})
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.env = {}  # type: ignore[misc]
