"""Policy Pack loader.

Sprint 5.5 で導入される ``config/policy_pack.toml`` を読み込む薄い service。
``PolicyPack.policy_version`` は人間可読 semver の version 文字列、
``PolicyPack.policy_pack_lock`` は ContextSnapshot 10 列目 (DD-03 §10) として
DB に書き込まれる、TOML content の SHA-256 hex digest 64 文字。両者は
**別 column** であり混同しない。

ADR-00009 Sprint 5.5 update §Sprint 5.5 update / Sprint Pack SP-005-5 §設計判断。
Missing required section / key は **fail-closed** で ValueError を raise
(silent default fallback はしない、SP55-B1-F-003 fix)。
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_POLICY_PACK_PATH: Path = _REPO_ROOT / "config" / "policy_pack.toml"

_SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class PolicyPack:
    """Immutable Policy Pack snapshot.

    ``policy_version`` is a human-readable semver-like string (e.g.
    ``"v1.0.0-p0-sp5-5"``).
    ``policy_pack_lock`` is the SHA-256 hex digest (64 chars) of the TOML
    bytes used to load this pack and is the value recorded into the
    ContextSnapshot ``policy_pack_lock`` column (DD-03 §10 カラム、ORM
    CHECK ``policy_pack_lock ~ '^[0-9a-f]{64}$'``).
    """

    policy_version: str
    policy_pack_lock: str
    repair_retry_max_attempts: int
    trust_level_promotion_to_trusted_instruction_requires_human_approval: bool


def _require_section(raw: dict[str, object], name: str) -> dict[str, object]:
    if name not in raw:
        raise ValueError(f"policy_pack missing required section [{name}]")
    value = raw[name]
    if not isinstance(value, dict):
        raise ValueError(f"policy_pack [{name}] must be a TOML table")
    return value


def _require_key(section: dict[str, object], section_name: str, key: str) -> object:
    if key not in section:
        raise ValueError(
            f"policy_pack [{section_name}] missing required key {key!r}"
        )
    return section[key]


def _coerce_repair_retry_max_attempts(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(
            "policy_pack.output_validator.repair_retry_max_attempts must be int"
        )
    if value < 1:
        raise ValueError(
            "policy_pack.output_validator.repair_retry_max_attempts must be >= 1"
        )
    return value


def _coerce_trusted_instruction_approval(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError(
            "policy_pack.input_trust."
            "trust_level_promotion_to_trusted_instruction_requires_human_approval "
            "must be bool"
        )
    return value


def _coerce_policy_version(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("policy_pack.meta.policy_version must be non-empty string")
    return value


def _compute_policy_pack_lock(content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()
    if not _SHA256_HEX_PATTERN.match(digest):
        raise ValueError("policy_pack_lock digest failed sha256 hex validation")
    return digest


def load_policy_pack(path: Path | None = None) -> PolicyPack:
    """Load a ``PolicyPack`` from the given TOML file (default repo path).

    Raises ``FileNotFoundError`` for missing files and ``ValueError`` for
    malformed contents OR missing required sections / keys (fail-closed,
    no silent defaults — SP55-B1-F-003 fix).
    """

    target = path if path is not None else DEFAULT_POLICY_PACK_PATH
    if not target.exists():
        raise FileNotFoundError(f"policy_pack TOML not found: {target}")

    content = target.read_bytes()
    raw = tomllib.loads(content.decode("utf-8"))

    meta = _require_section(raw, "meta")
    output_validator = _require_section(raw, "output_validator")
    input_trust = _require_section(raw, "input_trust")

    policy_version = _coerce_policy_version(
        _require_key(meta, "meta", "policy_version")
    )
    repair_retry_max_attempts = _coerce_repair_retry_max_attempts(
        _require_key(output_validator, "output_validator", "repair_retry_max_attempts")
    )
    trusted_instruction_approval = _coerce_trusted_instruction_approval(
        _require_key(
            input_trust,
            "input_trust",
            "trust_level_promotion_to_trusted_instruction_requires_human_approval",
        )
    )

    policy_pack_lock = _compute_policy_pack_lock(content)

    return PolicyPack(
        policy_version=policy_version,
        policy_pack_lock=policy_pack_lock,
        repair_retry_max_attempts=repair_retry_max_attempts,
        trust_level_promotion_to_trusted_instruction_requires_human_approval=(
            trusted_instruction_approval
        ),
    )


@lru_cache(maxsize=1)
def _cached_default_policy_pack() -> PolicyPack:
    return load_policy_pack()


def get_policy_pack() -> PolicyPack:
    """Return the default-path ``PolicyPack``, cached for the process."""

    return _cached_default_policy_pack()


def reset_policy_pack_cache() -> None:
    """Clear the process-level cache. Intended for tests only."""

    _cached_default_policy_pack.cache_clear()


__all__ = [
    "DEFAULT_POLICY_PACK_PATH",
    "PolicyPack",
    "get_policy_pack",
    "load_policy_pack",
    "reset_policy_pack_cache",
]
