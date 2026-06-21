"""Sprint 6 BL-0065: registry loader negative + positive tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.services.cli_artifact.registry import (
    AgentRegistryEntry,
    load_cli_agent_registry,
)


def _write_registry(tmp_path: Path, body: str) -> Path:
    registry_path = tmp_path / "cli_registry.toml"
    registry_path.write_text(body, encoding="utf-8")
    return registry_path


# --- shipped registry --------------------------------------------------------


def test_shipped_registry_loads() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "cli_registry.toml"
    )
    registry = load_cli_agent_registry(path)
    # SP-PHASE0 S3 (ADR-00058): credential_supply_mode additive field で 1.0.0 -> 1.1.0。
    # SP-PHASE0 gate C: per-agent 最小 HOME / credential home env additive で 1.1.0 -> 1.2.0。
    assert registry.schema_version == "1.2.0"
    assert "codex" in registry.names()
    entry = registry.get("codex")
    # Codex SP6B1 R2 F-SP6B1-R2-004: binary_path MUST be absolute to defeat
    # PATH-injection-redirected execution.
    assert entry.binary_path.startswith("/"), entry.binary_path
    assert entry.timeout_seconds == 1800
    assert entry.max_payload_data_class == "internal"
    assert "OPENAI_API_KEY" not in entry.env_passthrough
    assert "PATH" in entry.env_passthrough
    # SP-PHASE0 S3 (ADR-00058): codex CLI サブスク credential は host-ambient 分類。
    # claude の launchable entry は Phase 2 (CLIAgentAdapter) で追加 (Codex PR #353 F2/F3/F4/F6 adopt、
    # Phase 0 では launch argv 不正のため launchable 登録を延期、分類は codex field + コメントで確定)。
    assert entry.credential_supply_mode == "host_ambient"
    assert "claude" not in registry.names()


# --- positive ---------------------------------------------------------------


def test_load_minimal_valid_registry(tmp_path: Path) -> None:
    body = """
schema_version = "1.0.0"

[[agents]]
name = "codex"
binary_path = "/bin/sh"
argv_template = ["exec", "-"]
stdin_source = "{prompt_file}"
env_passthrough = ["PATH"]
timeout_seconds = 600
max_stdout_bytes = 1024
max_stderr_bytes = 1024
max_payload_data_class = "internal"
cwd_allowlist = ["/tmp"]
"""
    path = _write_registry(tmp_path, body)
    registry = load_cli_agent_registry(path)
    assert set(registry.names()) == {"codex"}


# --- file errors ------------------------------------------------------------


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_cli_agent_registry(tmp_path / "missing.toml")


def test_missing_schema_version_raises(tmp_path: Path) -> None:
    body = "[[agents]]\nname = 'codex'\nbinary_path = 'codex'\n"
    path = _write_registry(tmp_path, body)
    with pytest.raises(ValueError, match="schema_version"):
        load_cli_agent_registry(path)


def test_duplicate_agent_name_raises(tmp_path: Path) -> None:
    body = """
schema_version = "1.0.0"

[[agents]]
name = "codex"
binary_path = "/bin/sh"
argv_template = ["x"]
stdin_source = ""
env_passthrough = []
timeout_seconds = 60
max_stdout_bytes = 1024
max_stderr_bytes = 1024
max_payload_data_class = "internal"
cwd_allowlist = ["/tmp"]

[[agents]]
name = "codex"
binary_path = "/bin/sh"
argv_template = ["x"]
stdin_source = ""
env_passthrough = []
timeout_seconds = 60
max_stdout_bytes = 1024
max_stderr_bytes = 1024
max_payload_data_class = "internal"
cwd_allowlist = ["/tmp"]
"""
    path = _write_registry(tmp_path, body)
    with pytest.raises(ValueError, match="duplicate"):
        load_cli_agent_registry(path)


# --- field validations ------------------------------------------------------


def _base_kwargs() -> dict[str, object]:
    return {
        "name": "codex",
        "binary_path": "/opt/homebrew/bin/codex",
        "argv_template": ("exec",),
        "stdin_source": "",
        "env_passthrough": frozenset({"PATH"}),
        "timeout_seconds": 600,
        "max_stdout_bytes": 1024,
        "max_stderr_bytes": 1024,
        "max_payload_data_class": "internal",
        "cwd_allowlist": ("/tmp",),  # noqa: S108 - test fixture only
    }


def test_entry_rejects_empty_name() -> None:
    kw = _base_kwargs()
    kw["name"] = ""
    with pytest.raises(ValueError, match="non-empty"):
        AgentRegistryEntry(**kw)  # type: ignore[arg-type]


def test_entry_rejects_empty_argv() -> None:
    kw = _base_kwargs()
    kw["argv_template"] = ()
    with pytest.raises(ValueError, match="argv_template"):
        AgentRegistryEntry(**kw)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [0, -1, 3601, 10_000])
def test_entry_rejects_invalid_timeout(bad: int) -> None:
    kw = _base_kwargs()
    kw["timeout_seconds"] = bad
    with pytest.raises(ValueError, match="timeout_seconds"):
        AgentRegistryEntry(**kw)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_field", ["max_stdout_bytes", "max_stderr_bytes"])
def test_entry_rejects_invalid_byte_caps(bad_field: str) -> None:
    kw = _base_kwargs()
    kw[bad_field] = 0
    with pytest.raises(ValueError, match=bad_field):
        AgentRegistryEntry(**kw)  # type: ignore[arg-type]


def test_entry_rejects_unknown_payload_data_class() -> None:
    kw = _base_kwargs()
    kw["max_payload_data_class"] = "top_secret"
    with pytest.raises(ValueError, match="max_payload_data_class"):
        AgentRegistryEntry(**kw)  # type: ignore[arg-type]


def test_entry_rejects_forbidden_placeholder_in_argv() -> None:
    kw = _base_kwargs()
    kw["argv_template"] = ("exec", "{secret_value}")
    with pytest.raises(ValueError, match="forbidden"):
        AgentRegistryEntry(**kw)  # type: ignore[arg-type]


def test_entry_rejects_forbidden_placeholder_in_stdin() -> None:
    kw = _base_kwargs()
    kw["stdin_source"] = "{secret_file}"
    with pytest.raises(ValueError, match="stdin_source"):
        AgentRegistryEntry(**kw)  # type: ignore[arg-type]


def test_entry_accepts_allowed_placeholders() -> None:
    kw = _base_kwargs()
    kw["argv_template"] = (
        "exec",
        "--output",
        "{output_file}",
        "--stream",
        "{stream_file}",
    )
    kw["stdin_source"] = "{prompt_file}"
    entry = AgentRegistryEntry(**kw)  # type: ignore[arg-type]
    assert "{output_file}" in entry.argv_template


@pytest.mark.parametrize(
    "secret_var",
    [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GITHUB_TOKEN",
        "DATABASE_URL",
        "SOPS_AGE_KEY",
        "AWS_SECRET_ACCESS_KEY",
    ],
)
def test_entry_rejects_secret_env_passthrough(secret_var: str) -> None:
    kw = _base_kwargs()
    kw["env_passthrough"] = frozenset({"PATH", secret_var})
    with pytest.raises(ValueError, match="forbidden"):
        AgentRegistryEntry(**kw)  # type: ignore[arg-type]


# --- frozen / hashable invariants -------------------------------------------


def test_entry_is_frozen() -> None:
    entry = AgentRegistryEntry(**_base_kwargs())  # type: ignore[arg-type]
    with pytest.raises(AttributeError):
        entry.name = "other"  # type: ignore[misc]


def test_registry_get_unknown_raises() -> None:
    registry_path = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "cli_registry.toml"
    )
    registry = load_cli_agent_registry(registry_path)
    with pytest.raises(KeyError, match="not in registry"):
        registry.get("nonexistent")


def test_entry_rejects_empty_cwd_allowlist() -> None:
    kw = _base_kwargs()
    kw["cwd_allowlist"] = ()
    with pytest.raises(ValueError, match="cwd_allowlist"):
        AgentRegistryEntry(**kw)  # type: ignore[arg-type]


def test_entry_rejects_relative_cwd_allowlist() -> None:
    kw = _base_kwargs()
    kw["cwd_allowlist"] = ("relative/path",)
    with pytest.raises(ValueError, match="absolute"):
        AgentRegistryEntry(**kw)  # type: ignore[arg-type]


def test_shipped_registry_has_cwd_allowlist() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "cli_registry.toml"
    )
    registry = load_cli_agent_registry(path)
    entry = registry.get("codex")
    assert entry.cwd_allowlist
    for raw in entry.cwd_allowlist:
        assert raw.startswith("/")


def test_entry_rejects_relative_binary_path() -> None:
    """Codex SP6B1 R2 F-SP6B1-R2-004: PATH 解決経路を物理削除する。
    AgentRegistryEntry は binary_path が absolute path でなければ reject。"""

    kw = _base_kwargs()
    kw["binary_path"] = "codex"
    with pytest.raises(ValueError, match="absolute path"):
        AgentRegistryEntry(**kw)  # type: ignore[arg-type]


def test_entry_rejects_empty_binary_path() -> None:
    kw = _base_kwargs()
    kw["binary_path"] = ""
    with pytest.raises(ValueError, match="binary_path must be non-empty"):
        AgentRegistryEntry(**kw)  # type: ignore[arg-type]


# --- SP-PHASE0 gate C: per-agent minimal HOME / credential home fields -------


def test_entry_accepts_minimal_home_and_credential_home() -> None:
    """control 2: 最小 HOME + credential home env のペア指定を受け付ける。"""

    kw = _base_kwargs()
    kw["credential_supply_mode"] = "host_ambient"
    kw["minimal_home_dir"] = "/run/cli-home/codex"
    kw["credential_home_env"] = "CODEX_HOME"
    kw["credential_home_dir"] = "/run/codex-cred"
    entry = AgentRegistryEntry(**kw)  # type: ignore[arg-type]
    assert entry.minimal_home_dir == "/run/cli-home/codex"
    assert entry.credential_home_env == "CODEX_HOME"
    assert entry.credential_home_dir == "/run/codex-cred"


def test_entry_defaults_minimal_home_fields_to_none() -> None:
    """後方互換: 未設定なら None (既存挙動 = parent HOME passthrough)。"""

    entry = AgentRegistryEntry(**_base_kwargs())  # type: ignore[arg-type]
    assert entry.minimal_home_dir is None
    assert entry.credential_home_env is None
    assert entry.credential_home_dir is None


@pytest.mark.parametrize("bad_field", ["minimal_home_dir", "credential_home_dir"])
def test_entry_rejects_relative_home_dir(bad_field: str) -> None:
    kw = _base_kwargs()
    if bad_field == "credential_home_dir":
        kw["credential_home_env"] = "CODEX_HOME"
    kw[bad_field] = "relative/home"
    with pytest.raises(ValueError, match="absolute path"):
        AgentRegistryEntry(**kw)  # type: ignore[arg-type]


def test_entry_rejects_invalid_credential_home_env_name() -> None:
    kw = _base_kwargs()
    kw["credential_home_env"] = "codex home"  # lowercase + space, invalid
    kw["credential_home_dir"] = "/run/codex-cred"
    with pytest.raises(ValueError, match="ENV var name"):
        AgentRegistryEntry(**kw)  # type: ignore[arg-type]


def test_entry_rejects_credential_home_env_without_dir() -> None:
    kw = _base_kwargs()
    kw["credential_home_env"] = "CODEX_HOME"
    # credential_home_dir 未設定 (片方のみ) は設定ミスとして reject
    with pytest.raises(ValueError, match="両方"):
        AgentRegistryEntry(**kw)  # type: ignore[arg-type]


def test_entry_rejects_credential_home_dir_without_env() -> None:
    kw = _base_kwargs()
    kw["credential_home_dir"] = "/run/codex-cred"
    with pytest.raises(ValueError, match="両方"):
        AgentRegistryEntry(**kw)  # type: ignore[arg-type]


def test_entry_rejects_secret_bearing_credential_home_env() -> None:
    """credential_home_env は dir-pointer のみ。secret-bearing var 偽装を reject。"""

    kw = _base_kwargs()
    kw["credential_home_env"] = "OPENAI_API_KEY"
    kw["credential_home_dir"] = "/run/codex-cred"
    with pytest.raises(ValueError, match="secret-bearing"):
        AgentRegistryEntry(**kw)  # type: ignore[arg-type]


def test_load_registry_with_minimal_home_fields(tmp_path: Path) -> None:
    body = """
schema_version = "1.2.0"

[[agents]]
name = "codex"
binary_path = "/bin/sh"
argv_template = ["exec", "-"]
stdin_source = "{prompt_file}"
env_passthrough = ["PATH", "HOME"]
timeout_seconds = 600
max_stdout_bytes = 1024
max_stderr_bytes = 1024
max_payload_data_class = "internal"
cwd_allowlist = ["/tmp"]
credential_supply_mode = "host_ambient"
minimal_home_dir = "/run/cli-home/codex"
credential_home_env = "CODEX_HOME"
credential_home_dir = "/run/codex-cred"
"""
    path = _write_registry(tmp_path, body)
    registry = load_cli_agent_registry(path)
    entry = registry.get("codex")
    assert entry.minimal_home_dir == "/run/cli-home/codex"
    assert entry.credential_home_env == "CODEX_HOME"
    assert entry.credential_home_dir == "/run/codex-cred"


def test_entry_accepts_absolute_binary_path() -> None:
    kw = _base_kwargs()
    kw["binary_path"] = "/bin/sh"
    entry = AgentRegistryEntry(**kw)  # type: ignore[arg-type]
    assert entry.binary_path == "/bin/sh"
