"""Sprint 7 BL-0081: AC-HARD-06 dangerous_command_block fixture loader.

Anti-Gaming Rules (.claude/rules/testing.md §10):
- public_regression: PR review 時の regression check (可視)
- private_holdout: 期待値漏えい禁止 (Sprint 11 で external vault に保存)
- adversarial_new: 月次 append-only (Sprint 11 で 3+ 件追加予定)

本 loader は public_regression / private_holdout / adversarial_new の 3 split を
JSON Schema (expected_schema.json) で validate して load する。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft7Validator

FixtureKind = Literal["public_regression", "private_holdout", "adversarial_new"]

_BASE = Path(__file__).parent
_SCHEMA_PATH = _BASE / "expected_schema.json"
_MANIFEST_PATH = _BASE / "manifest.json"
_VALID_SPLIT_KINDS: frozenset[str] = frozenset(
    {"public_regression", "private_holdout", "adversarial_new"}
)


@dataclass(frozen=True)
class DangerousCommandFixture:
    """parsed fixture instance."""

    fixture_id: str
    dataset_version_id: str
    fixture_kind: FixtureKind
    case_key: str
    gateway: str
    payload_data_class: str
    test_cases: tuple[dict[str, Any], ...]
    expected_decision: str
    expected_block: bool
    expected_runtime_blocked: str
    expected_blocked_reason: str
    expected_agent_run_status: str
    pattern_hit_kind: str
    metadata: dict[str, Any]


def _load_schema() -> Draft7Validator:
    with _SCHEMA_PATH.open(encoding="utf-8") as f:
        schema = json.load(f)
    return Draft7Validator(schema)


def load_manifest() -> dict[str, Any]:
    with _MANIFEST_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _parse_fixture(data: dict[str, Any]) -> DangerousCommandFixture:
    return DangerousCommandFixture(
        fixture_id=data["fixture_id"],
        dataset_version_id=data["dataset_version_id"],
        fixture_kind=data["fixture_kind"],
        case_key=data["case_key"],
        gateway=data["input"]["gateway"],
        payload_data_class=data["input"]["payload_data_class"],
        test_cases=tuple(data["input"]["test_cases"]),
        expected_decision=data["expected_decision"],
        expected_block=data["expected_block"],
        expected_runtime_blocked=data["expected_runtime_blocked"],
        expected_blocked_reason=data["expected_blocked_reason"],
        expected_agent_run_status=data["expected_agent_run_status"],
        pattern_hit_kind=data["pattern_hit_kind"],
        metadata=data.get("metadata", {}),
    )


def load_fixtures(split: FixtureKind) -> Iterator[DangerousCommandFixture]:
    """指定 split から fixture を全件 yield する。

    Codex SP7 audit F-SP7-007 adopt: manifest.expected_count と実 fixture 数を
    照合し、mismatch なら ValueError で reject (anti-gaming)。
    """
    if split not in _VALID_SPLIT_KINDS:
        raise ValueError(f"split must be one of {_VALID_SPLIT_KINDS}, got {split}")

    validator = _load_schema()
    dir_path = _BASE / split
    if not dir_path.is_dir():
        return

    # Codex SP7 audit F-SP7-007 adopt: manifest count 整合 verify
    manifest = load_manifest()
    expected_count = (
        manifest.get("splits", {}).get(split, {}).get("expected_count", 0)
    )
    fixture_files = [
        f for f in sorted(dir_path.glob("*.json")) if f.name != ".gitkeep"
    ]
    if len(fixture_files) != expected_count:
        raise ValueError(
            f"fixture count mismatch in {dir_path}: expected={expected_count} "
            f"(from manifest.splits.{split}.expected_count), actual={len(fixture_files)}. "
            f"Anti-Gaming: update manifest or add/remove fixtures to align "
            f"(Codex SP7 audit F-SP7-007 adopt)"
        )

    for f in fixture_files:
        with f.open(encoding="utf-8") as fp:
            data = json.load(fp)
        validator.validate(data)
        if data["fixture_kind"] != split:
            raise ValueError(
                f"fixture_kind {data['fixture_kind']!r} mismatches split dir "
                f"{split!r} in {f}"
            )
        yield _parse_fixture(data)


def load_public_regression_fixtures() -> tuple[DangerousCommandFixture, ...]:
    return tuple(load_fixtures("public_regression"))


__all__ = [
    "DangerousCommandFixture",
    "FixtureKind",
    "load_fixtures",
    "load_manifest",
    "load_public_regression_fixtures",
]
