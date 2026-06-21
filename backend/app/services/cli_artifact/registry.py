"""Sprint 6 BL-0065: CLI agent registry loader.

``config/cli_registry.toml`` から CLI agent allowlist を読み込み、launcher へ
immutable な ``CliAgentRegistry`` として provide する。

Server-owned-boundary §1 invariant:
- caller (API endpoint / service layer) は registry entry を直接 construct
  できない。launcher は ``load_cli_agent_registry()`` 経由でのみ取得。
- ``env_passthrough`` に登場しない ENV var は subprocess に渡らない
  (raw secret 漏出防止)。
- ``argv_template`` placeholder は固定 3 種 (``{prompt_file}`` /
  ``{output_file}`` / ``{stream_file}``)、それ以外は registry load 時に reject。
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from backend.app.domain.artifact.data_class import (
    DATA_CLASS_ORDINAL,
    PayloadDataClass,
)

_ALLOWED_PLACEHOLDERS: frozenset[str] = frozenset(
    {
        "{prompt_file}",
        "{output_file}",
        "{stream_file}",
    }
)

# SP-PHASE0 gate C (control 2): credential_home_env は POSIX ENV var 名規約。
_ENV_NAME_RE = re.compile(r"[A-Z_][A-Z0-9_]*")

# SP-PHASE0 S3 (ADR-00058): CLI サブスク credential 供給経路の分類 (additive metadata)。
# - "host_ambient": CLI が self-rotating OAuth を所有・refresh、host worker が ~/.claude / ~/.codex
#   を直読 (SecretBroker 非経由)。SecretRegistrationService が broker-managed 登録を reject する。
# - "broker_managed": static API key を in-process provider.call で broker 内部消費 (Phase 2)。
# None = credential 供給を持たない (read-only artifact 生成のみ)。
_ALLOWED_CREDENTIAL_SUPPLY_MODES: frozenset[str] = frozenset(
    {
        "host_ambient",
        "broker_managed",
    }
)

# subprocess を spawn する際に **絶対に渡してはいけない** ENV var.
# env_passthrough にあっても本 list の名前は drop する (defense-in-depth)。
_FORBIDDEN_ENV_NAMES: frozenset[str] = frozenset(
    {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "TAILSCALE_AUTHKEY",
        "SOPS_AGE_KEY",
        "SOPS_AGE_KEY_FILE",
        "AGE_PRIVATE_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "DATABASE_URL",
        "POSTGRES_PASSWORD",
        "REDIS_PASSWORD",
        "TASKMANAGEDAI_DATABASE_URL",
    }
)


@dataclass(frozen=True, slots=True)
class AgentRegistryEntry:
    name: str
    binary_path: str
    argv_template: tuple[str, ...]
    stdin_source: str
    env_passthrough: frozenset[str]
    timeout_seconds: int
    max_stdout_bytes: int
    max_stderr_bytes: int
    max_payload_data_class: PayloadDataClass
    cwd_allowlist: tuple[str, ...]
    # SP-PHASE0 S3 (ADR-00058): host_ambient | broker_managed | None (additive、未設定後方互換)。
    credential_supply_mode: str | None = None
    # SP-PHASE0 gate C (ADR-00058 §exit must_ship、control 2 per-agent 最小 HOME):
    # host_ambient agent の subprocess に供給する **per-agent 最小 HOME** と
    # **credential home env** (additive、未設定後方互換)。
    # - ``minimal_home_dir``: subprocess の ``HOME`` を本 dir へ override する。
    #   この dir 配下には agent 固有 credential 以外の secret を **同居させない**
    #   ことで、prompt-injected な ``cat ~/.ssh/id_rsa`` / ``cat ~/.aws/...`` の
    #   blast radius を最小化する (他 secret が HOME 配下に無い)。
    # - ``credential_home_env``: agent credential dir を指す ENV var 名 (codex は
    #   ``CODEX_HOME``)。launcher が ``credential_home_dir`` を本 var へ set する。
    # - ``credential_home_dir``: agent 自身の credential dir (codex の ``~/.codex``)
    #   絶対パス。agent 自身の credential 読取は許可、他 secret read は HOME 制限で阻止。
    # raw secret / token は本 field に書かない (dir path のみ)。
    minimal_home_dir: str | None = None
    credential_home_env: str | None = None
    credential_home_dir: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("agent name must be non-empty")
        if not self.binary_path:
            raise ValueError(f"agent {self.name!r}: binary_path must be non-empty")
        if not self.binary_path.startswith("/"):
            raise ValueError(
                f"agent {self.name!r}: binary_path must be an absolute path "
                f"(Codex SP6B1 R2 F-SP6B1-R2-004: PATH 汚染による別 binary 起動を "
                f"signature レベルで物理削除); got {self.binary_path!r}"
            )
        if not self.argv_template:
            raise ValueError(f"agent {self.name!r}: argv_template must be non-empty")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 3600:
            raise ValueError(
                f"agent {self.name!r}: timeout_seconds must be in (0, 3600] "
                f"(got {self.timeout_seconds})"
            )
        if self.max_stdout_bytes <= 0 or self.max_stdout_bytes > 16 * 1024 * 1024:
            raise ValueError(
                f"agent {self.name!r}: max_stdout_bytes must be in (0, 16 MiB] "
                f"(got {self.max_stdout_bytes})"
            )
        if self.max_stderr_bytes <= 0 or self.max_stderr_bytes > 8 * 1024 * 1024:
            raise ValueError(
                f"agent {self.name!r}: max_stderr_bytes must be in (0, 8 MiB] "
                f"(got {self.max_stderr_bytes})"
            )
        if self.max_payload_data_class not in DATA_CLASS_ORDINAL:
            raise ValueError(
                f"agent {self.name!r}: max_payload_data_class must be one of "
                f"{sorted(DATA_CLASS_ORDINAL.keys())} "
                f"(got {self.max_payload_data_class!r})"
            )
        if not self.cwd_allowlist:
            raise ValueError(
                f"agent {self.name!r}: cwd_allowlist must be non-empty "
                "(server-owned-boundary §1 path containment requirement)"
            )
        for raw in self.cwd_allowlist:
            if not raw.startswith("/"):
                raise ValueError(
                    f"agent {self.name!r}: cwd_allowlist entries must be "
                    f"absolute paths (got {raw!r})"
                )
        # argv_template に登場する placeholder は固定 set のみ許可
        for arg in self.argv_template:
            stripped = arg.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                if stripped not in _ALLOWED_PLACEHOLDERS:
                    raise ValueError(
                        f"agent {self.name!r}: argv_template has forbidden "
                        f"placeholder {stripped!r}; allowed: "
                        f"{sorted(_ALLOWED_PLACEHOLDERS)}"
                    )
        # stdin_source も placeholder 検査
        if self.stdin_source not in _ALLOWED_PLACEHOLDERS and self.stdin_source != "":
            raise ValueError(
                f"agent {self.name!r}: stdin_source must be empty or one of "
                f"{sorted(_ALLOWED_PLACEHOLDERS)} (got {self.stdin_source!r})"
            )
        # SP-PHASE0 S3: credential_supply_mode は allowlist enum (未設定 None は許容)。
        if (
            self.credential_supply_mode is not None
            and self.credential_supply_mode not in _ALLOWED_CREDENTIAL_SUPPLY_MODES
        ):
            raise ValueError(
                f"agent {self.name!r}: credential_supply_mode must be None or one of "
                f"{sorted(_ALLOWED_CREDENTIAL_SUPPLY_MODES)} "
                f"(got {self.credential_supply_mode!r})"
            )
        # SP-PHASE0 gate C (control 2): per-agent 最小 HOME / credential home の
        # path field は絶対パス必須 (path containment / symlink reject は launcher
        # が apply。env name は ENV 規約に沿う識別子)。raw secret 非含 (path のみ)。
        for field_name, value in (
            ("minimal_home_dir", self.minimal_home_dir),
            ("credential_home_dir", self.credential_home_dir),
        ):
            if value is not None and not value.startswith("/"):
                raise ValueError(
                    f"agent {self.name!r}: {field_name} must be an absolute path "
                    f"(got {value!r})"
                )
        if self.credential_home_env is not None and not _ENV_NAME_RE.fullmatch(
            self.credential_home_env
        ):
            raise ValueError(
                f"agent {self.name!r}: credential_home_env must be a valid ENV var "
                f"name [A-Z_][A-Z0-9_]* (got {self.credential_home_env!r})"
            )
        # credential_home_env と credential_home_dir はペアで指定する (片方だけは
        # 設定ミスとして reject、fail-closed)。
        if (self.credential_home_env is None) != (self.credential_home_dir is None):
            raise ValueError(
                f"agent {self.name!r}: credential_home_env と credential_home_dir は "
                "両方指定するか両方未設定のいずれか (片方のみは設定ミス)"
            )
        # credential home env が forbidden secret env 名と衝突しないこと
        # (defense-in-depth: CODEX_HOME 等の dir-pointer のみ許可、secret-bearing
        # var を credential home として偽装する経路を塞ぐ)。
        if (
            self.credential_home_env is not None
            and self.credential_home_env in _FORBIDDEN_ENV_NAMES
        ):
            raise ValueError(
                f"agent {self.name!r}: credential_home_env must not be a "
                f"secret-bearing ENV var ({self.credential_home_env!r})"
            )
        # ENV passthrough から forbidden secret を除外
        leaked = self.env_passthrough & _FORBIDDEN_ENV_NAMES
        if leaked:
            raise ValueError(
                f"agent {self.name!r}: env_passthrough contains forbidden "
                f"secret-bearing ENV vars: {sorted(leaked)}. "
                "SecretBroker 経由でのみ provider key を扱う invariant 違反 "
                "(rules/secretbroker-boundary.md §1)."
            )


@dataclass(frozen=True, slots=True)
class CliAgentRegistry:
    """Immutable view of registry agents keyed by name."""

    schema_version: str
    agents: Mapping[str, AgentRegistryEntry] = field(default_factory=dict)

    def get(self, name: str) -> AgentRegistryEntry:
        if name not in self.agents:
            raise KeyError(
                f"agent {name!r} not in registry; allowed: "
                f"{sorted(self.agents.keys())}"
            )
        return self.agents[name]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.agents.keys()))


def load_cli_agent_registry(path: Path | str) -> CliAgentRegistry:
    """Load registry from a TOML file. The file MUST be readable by the
    backend process; callers should not pass user-controlled paths."""

    registry_path = Path(path)
    if not registry_path.is_file():
        raise FileNotFoundError(
            f"CLI registry file not found: {registry_path}"
        )
    with registry_path.open("rb") as fp:
        raw = tomllib.load(fp)

    schema_version = str(raw.get("schema_version", ""))
    if not schema_version:
        raise ValueError("cli_registry.toml must declare schema_version")

    raw_agents = raw.get("agents", [])
    if not isinstance(raw_agents, list):
        raise ValueError("cli_registry.toml [[agents]] must be an array")

    entries: dict[str, AgentRegistryEntry] = {}
    for raw_agent in raw_agents:
        if not isinstance(raw_agent, dict):
            raise ValueError("each [[agents]] entry must be a TOML table")
        entry = AgentRegistryEntry(
            name=str(raw_agent["name"]),
            binary_path=str(raw_agent["binary_path"]),
            argv_template=tuple(str(a) for a in raw_agent["argv_template"]),
            stdin_source=str(raw_agent.get("stdin_source", "")),
            env_passthrough=frozenset(
                str(v) for v in raw_agent.get("env_passthrough", [])
            ),
            timeout_seconds=int(raw_agent["timeout_seconds"]),
            max_stdout_bytes=int(raw_agent["max_stdout_bytes"]),
            max_stderr_bytes=int(raw_agent["max_stderr_bytes"]),
            max_payload_data_class=str(  # type: ignore[arg-type]
                raw_agent["max_payload_data_class"]
            ),
            cwd_allowlist=tuple(
                str(p) for p in raw_agent.get("cwd_allowlist", [])
            ),
            credential_supply_mode=(
                str(raw_agent["credential_supply_mode"])
                if raw_agent.get("credential_supply_mode") is not None
                else None
            ),
            minimal_home_dir=(
                str(raw_agent["minimal_home_dir"])
                if raw_agent.get("minimal_home_dir") is not None
                else None
            ),
            credential_home_env=(
                str(raw_agent["credential_home_env"])
                if raw_agent.get("credential_home_env") is not None
                else None
            ),
            credential_home_dir=(
                str(raw_agent["credential_home_dir"])
                if raw_agent.get("credential_home_dir") is not None
                else None
            ),
        )
        if entry.name in entries:
            raise ValueError(
                f"cli_registry.toml has duplicate agent name {entry.name!r}"
            )
        entries[entry.name] = entry

    return CliAgentRegistry(
        schema_version=schema_version,
        agents=MappingProxyType(entries),
    )


__all__ = [
    "AgentRegistryEntry",
    "CliAgentRegistry",
    "load_cli_agent_registry",
]
