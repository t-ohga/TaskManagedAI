from __future__ import annotations

import datetime as _datetime
import hashlib
import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from jsonschema import Draft7Validator, FormatChecker
from jsonschema.exceptions import SchemaError as JsonSchemaSchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

FixtureKind = Literal["public_regression", "private_holdout", "adversarial_new"]
RedactedFixtureKind = Literal["private_holdout", "adversarial_new"]
GateId = Literal["AC-HARD-01"]
MetricKey = Literal["policy_block_recall"]
ExpectedDecision = Literal["block", "allow"]

_ALLOWED_FIXTURE_KINDS: tuple[FixtureKind, ...] = (
    "public_regression",
    "private_holdout",
    "adversarial_new",
)
_ALLOWED_SPLIT_DIRS = {
    "public_regression": "public_regression",
    "private_holdout": "private_holdout",
    "adversarial_new": "adversarial_new",
}
_CANONICAL_EXPECTED_SCHEMA_FILENAME = "expected_schema.json"
_VALID_SPLIT_KINDS = frozenset({"public_regression", "private_holdout", "adversarial_new"})
_VALID_INDEX_ENTRY_KEYS = frozenset({"sha256", "split", "created_at"})
_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_REQUIRED_FIXTURE_KEYS_PUBLIC = frozenset(
    {
        "fixture_id",
        "dataset_version_id",
        "fixture_kind",
        "gate_id",
        "metric_key",
        "case_key",
        "input",
        "expected_decision",
        "expected_block",
        "expected_reason_code",
        "expected_agent_run_status",
        "pattern_hit_kind",
        "assertions",
        "anti_gaming",
        "metadata",
    }
)
_REQUIRED_FIXTURE_KEYS_REDACTED = frozenset(
    {
        "fixture_id",
        "dataset_version_id",
        "fixture_kind",
        "gate_id",
        "metric_key",
        "case_key",
        "input",
        "anti_gaming",
        "metadata",
    }
)
_PROHIBITED_REDACTED_KEYS = frozenset(
    {
        "expected_decision",
        "expected_block",
        "expected_reason_code",
        "expected_agent_run_status",
        "pattern_hit_kind",
        "assertions",
    }
)
_PROHIBITED_SECRET_METADATA_KEYS = frozenset(
    {
        "raw_secret",
        "raw_token",
        "api_key",
        "auth_token",
        "secret_value",
        "plaintext",
        "private_key",
        "sops_key",
        "age_key",
        "canary",
        "raw_value",
        "token",
        "value",
    }
)
_REQUIRED_ANTI_GAMING_RULES = frozenset(
    {
        "private_holdout_expectations_not_used_for_tuning",
        "monthly_refresh_append_only",
        "separate_fixture_and_policy_or_prompt_commits",
        "persist_fixture_id_and_dataset_version",
        "avoid_private_expectation_leakage",
        "adversarial_new_append_only",
    }
)


@dataclass(frozen=True)
class PublicFixture:
    """Complete public_regression fixture with readable expectations."""

    fixture_id: str
    dataset_version_id: str
    fixture_kind: Literal["public_regression"]
    gate_id: GateId
    metric_key: MetricKey
    case_key: str
    input: dict[str, Any]
    expected_decision: ExpectedDecision
    expected_block: bool
    expected_reason_code: str
    expected_agent_run_status: str
    pattern_hit_kind: str
    assertions: list[dict[str, Any]]
    anti_gaming: dict[str, bool]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class RedactedFixture:
    """Redacted private_holdout / adversarial_new fixture without expectations."""

    fixture_id: str
    dataset_version_id: str
    fixture_kind: RedactedFixtureKind
    gate_id: GateId
    metric_key: MetricKey
    case_key: str
    input: dict[str, Any]
    anti_gaming: dict[str, bool]
    metadata: dict[str, Any]


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"json file not found: {path}")

    text = path.read_text(encoding="utf-8")

    def _strict_object_pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: set[str] = set()
        for key, _ in pairs:
            if key in seen:
                raise ValueError(
                    f"duplicate JSON object key {key!r} in {path}; "
                    "AC-HARD-01 fixture must use canonical JSON without duplicate keys"
                )
            seen.add(key)
        return dict(pairs)

    def _strict_parse_constant(constant: str) -> Any:
        raise ValueError(
            f"non-canonical JSON constant {constant!r} in {path}; "
            "AC-HARD-01 fixture must not contain NaN / Infinity / -Infinity"
        )

    try:
        data = json.loads(
            text,
            object_pairs_hook=_strict_object_pairs_hook,
            parse_constant=_strict_parse_constant,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"json file {path} must contain a JSON object at the root")
    return data


def _manifest_dataset_version_id(manifest: dict[str, Any]) -> str:
    dataset_version_id = manifest.get("dataset_version_id", manifest.get("dataset_version"))
    if not isinstance(dataset_version_id, str) or not dataset_version_id:
        raise ValueError("manifest dataset_version must be a non-empty string.")
    return dataset_version_id


def _coerce_fixture_kind(value: object, *, source_path: Path) -> FixtureKind:
    if value not in _ALLOWED_FIXTURE_KINDS:
        raise ValueError(f"{source_path}: fixture_kind must be one of {_ALLOWED_FIXTURE_KINDS}.")
    return cast(FixtureKind, value)


def _coerce_gate_id(value: object, *, source_path: Path) -> GateId:
    if value != "AC-HARD-01":
        raise ValueError(f"{source_path}: gate_id must be AC-HARD-01.")
    return "AC-HARD-01"


def _coerce_metric_key(value: object, *, source_path: Path) -> MetricKey:
    if value != "policy_block_recall":
        raise ValueError(f"{source_path}: metric_key must be policy_block_recall.")
    return "policy_block_recall"


def _coerce_expected_decision(value: object, *, source_path: Path) -> ExpectedDecision:
    if value not in {"block", "allow"}:
        raise ValueError(f"{source_path}: expected_decision must be block or allow.")
    return cast(ExpectedDecision, value)


def _require_str(value: object, *, source_path: Path, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{source_path}: {key} must be a non-empty string.")
    return value


def _require_bool(value: object, *, source_path: Path, key: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{source_path}: {key} must be a boolean.")
    return value


def _require_dict(value: object, *, source_path: Path, key: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{source_path}: {key} must be a JSON object.")
    return cast(dict[str, Any], value)


def _require_bool_dict(value: object, *, source_path: Path, key: str) -> dict[str, bool]:
    raw = _require_dict(value, source_path=source_path, key=key)
    result: dict[str, bool] = {}
    for item_key, item_value in raw.items():
        if not isinstance(item_key, str):
            raise ValueError(f"{source_path}: {key} keys must be strings.")
        if not isinstance(item_value, bool):
            raise ValueError(f"{source_path}: {key}.{item_key} must be a boolean.")
        result[item_key] = item_value
    return result


def _require_assertions(value: object, *, source_path: Path) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) == 0:
        raise ValueError(f"{source_path}: assertions must be a non-empty array.")

    assertions: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"{source_path}: assertions[{index}] must be a JSON object.")
        assertions.append(cast(dict[str, Any], item))
    return assertions


def _validate_dataset_version(
    data: dict[str, Any],
    *,
    source_path: Path,
    dataset_version_id: str | None,
) -> str:
    fixture_dataset_version_id = _require_str(
        data.get("dataset_version_id"),
        source_path=source_path,
        key="dataset_version_id",
    )
    if dataset_version_id is not None and fixture_dataset_version_id != dataset_version_id:
        raise ValueError(
            f"{source_path}: dataset_version_id mismatch: "
            f"{fixture_dataset_version_id} != {dataset_version_id}."
        )
    return fixture_dataset_version_id


def _find_prohibited_keys_recursive(
    obj: Any,
    prohibited: frozenset[str],
    path: str = "$",
) -> list[str]:
    leaks: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"unsupported dict key type {type(key).__name__} at {path}; "
                    "redacted fixture attributes must be JSON-compatible "
                    "(dict keys must be strings)"
                )
            child_path = f"{path}.{key}"
            if key in prohibited:
                leaks.append(child_path)
            leaks.extend(_find_prohibited_keys_recursive(value, prohibited, child_path))
    elif isinstance(obj, (list, tuple)):
        for index, item in enumerate(obj):
            child_path = f"{path}[{index}]"
            leaks.extend(_find_prohibited_keys_recursive(item, prohibited, child_path))
    elif isinstance(obj, (str, bool, int, float, type(None))):
        pass
    else:
        raise TypeError(
            f"unsupported value type {type(obj).__name__} at {path}; "
            "redacted fixture attributes must be JSON-compatible "
            "(dict, list, tuple, str, int, float, bool, None)"
        )
    return leaks


def _assert_no_raw_secret_keys(
    obj: Any,
    source_path: Path,
    field_name: str,
) -> None:
    leaks = _find_prohibited_keys_recursive(obj, _PROHIBITED_SECRET_METADATA_KEYS)
    if leaks:
        raise ValueError(
            f"fixture {source_path.name} {field_name} contains raw secret keys at "
            f"{sorted(leaks)}; allowed: anti-gaming requires raw secret keys to be "
            "absent from fixture metadata/input "
            f"(prohibited: {sorted(_PROHIBITED_SECRET_METADATA_KEYS)})"
        )


def _canonical_fixture_hash(data: dict[str, Any]) -> str:
    canonical = json.dumps(
        data,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    nfc = unicodedata.normalize("NFC", canonical)
    return hashlib.sha256(nfc.encode("utf-8")).hexdigest()


def _validate_fixture_immutable_index(manifest: dict[str, Any]) -> None:
    index = manifest.get("fixture_immutable_index", {})
    if not isinstance(index, dict):
        raise ValueError("manifest.fixture_immutable_index must be an object")

    for fixture_id, entry in index.items():
        if not isinstance(fixture_id, str) or not fixture_id:
            raise ValueError(
                "manifest.fixture_immutable_index key must be a non-empty string: "
                f"got {type(fixture_id).__name__}"
            )
        if not isinstance(entry, dict):
            raise ValueError(
                f"manifest.fixture_immutable_index[{fixture_id}] must be an object, "
                f"got {type(entry).__name__}"
            )

        entry_keys = set(entry.keys())
        unknown_keys = sorted(entry_keys - _VALID_INDEX_ENTRY_KEYS)
        if unknown_keys:
            raise ValueError(
                f"manifest.fixture_immutable_index[{fixture_id}] has unknown keys "
                f"{unknown_keys}; allowed keys are {sorted(_VALID_INDEX_ENTRY_KEYS)}"
            )
        missing_keys = sorted(_VALID_INDEX_ENTRY_KEYS - entry_keys)
        if missing_keys:
            raise ValueError(
                f"manifest.fixture_immutable_index[{fixture_id}] is missing required keys "
                f"{missing_keys}"
            )

        split = entry.get("split")
        if not isinstance(split, str):
            raise ValueError(
                f"manifest.fixture_immutable_index[{fixture_id}].split must be a string, "
                f"got {type(split).__name__}"
            )
        if split not in _VALID_SPLIT_KINDS:
            raise ValueError(
                f"manifest.fixture_immutable_index[{fixture_id}].split must be one of "
                f"{sorted(_VALID_SPLIT_KINDS)}, got {split!r}"
            )

        sha256 = entry.get("sha256")
        if not isinstance(sha256, str) or not _SHA256_PATTERN.fullmatch(sha256):
            raise ValueError(
                f"manifest.fixture_immutable_index[{fixture_id}].sha256 must be a "
                "64-char lowercase hex string"
            )

        created_at = entry.get("created_at")
        if not isinstance(created_at, str):
            raise ValueError(
                f"manifest.fixture_immutable_index[{fixture_id}].created_at must be a string, "
                f"got {type(created_at).__name__}"
            )
        if not _DATE_PATTERN.fullmatch(created_at):
            raise ValueError(
                f"manifest.fixture_immutable_index[{fixture_id}].created_at must match "
                "YYYY-MM-DD with ASCII digits"
            )
        try:
            _datetime.date.fromisoformat(created_at)
        except ValueError as exc:
            raise ValueError(
                f"manifest.fixture_immutable_index[{fixture_id}].created_at "
                "is not a valid calendar date"
            ) from exc


def _assert_fixture_matches_immutable_index(
    fixture_id: str,
    data: dict[str, Any],
    manifest: dict[str, Any],
    expected_split: str,
) -> None:
    index = manifest.get("fixture_immutable_index", {})
    if not isinstance(index, dict):
        raise ValueError("manifest.fixture_immutable_index must be an object")

    entry = index.get(fixture_id)
    if entry is None:
        raise ValueError(
            f"fixture {fixture_id} is not registered in manifest.fixture_immutable_index "
            "(append-only requires manifest registration before fixture file is added)"
        )
    if not isinstance(entry, dict):
        raise ValueError(f"manifest.fixture_immutable_index[{fixture_id}] must be an object")

    if entry.get("split") != expected_split:
        raise ValueError(
            f"fixture {fixture_id} split mismatch: manifest={entry.get('split')}, "
            f"actual={expected_split}"
        )

    expected_sha = entry.get("sha256")
    if not isinstance(expected_sha, str) or not _SHA256_PATTERN.fullmatch(expected_sha):
        raise ValueError(
            f"manifest.fixture_immutable_index[{fixture_id}].sha256 must be "
            "64-char lowercase hex"
        )

    actual_sha = _canonical_fixture_hash(data)
    if actual_sha != expected_sha:
        raise ValueError(
            f"fixture {fixture_id} content has been modified after registration "
            f"(sha256 mismatch: expected {expected_sha[:8]}..., actual {actual_sha[:8]}...)"
        )


def _assert_immutable_index_split_consistency(
    manifest: dict[str, Any],
    kind: str,
    actual_fixture_ids: set[str],
) -> None:
    index = manifest.get("fixture_immutable_index", {})
    registered_for_kind = {
        fixture_id
        for fixture_id, entry in index.items()
        if entry["split"] == kind
    }

    missing_in_split = sorted(registered_for_kind - actual_fixture_ids)
    if missing_in_split:
        raise ValueError(
            f"split {kind}: fixture_immutable_index has entries with no fixture file: "
            f"{missing_in_split}. Append-only invariant requires fixture files match "
            "manifest registrations exactly (deletion forbidden)."
        )

    splits = manifest.get("splits", {})
    expected_count = splits.get(kind, {}).get("expected_count")
    if isinstance(expected_count, int) and not isinstance(expected_count, bool):
        if len(registered_for_kind) != expected_count:
            raise ValueError(
                f"split {kind}: fixture_immutable_index entry count "
                f"{len(registered_for_kind)} does not match "
                f"manifest.splits.{kind}.expected_count {expected_count}"
            )


def _validate_fixture_against_schema(
    data: dict[str, Any],
    schema: dict[str, Any],
    source_path: Path,
) -> None:
    validator = Draft7Validator(schema, format_checker=FormatChecker())
    errors: list[JsonSchemaValidationError] = sorted(
        validator.iter_errors(data),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        details = "; ".join(
            f"path={list(error.absolute_path)} validator={error.validator} "
            f"schema_path={list(error.schema_path)[-3:]}"
            for error in errors[:5]
        )
        raise ValueError(
            f"public fixture {source_path.name} fails expected_schema validation: {details}"
        )


def _assert_split_count_matches_manifest(
    manifest: dict[str, Any],
    kind: str,
    actual_count: int,
) -> None:
    splits = manifest.get("splits")
    if not isinstance(splits, dict):
        raise ValueError("manifest.splits must be an object")

    split = splits.get(kind)
    if not isinstance(split, dict):
        raise ValueError(f"manifest.splits.{kind} must be an object")

    expected_count = split.get("expected_count")
    if isinstance(expected_count, bool) or not isinstance(expected_count, int) or expected_count < 0:
        raise ValueError(
            f"manifest.splits.{kind}.expected_count must be a non-negative integer"
        )

    if expected_count != actual_count:
        raise ValueError(f"split {kind}: expected {expected_count} fixtures, found {actual_count}")


def _resolve_split_dir(base_path: Path, kind: str, manifest: dict[str, Any]) -> Path:
    expected_dir = _ALLOWED_SPLIT_DIRS.get(kind)
    if expected_dir is None:
        raise ValueError(f"unknown split kind {kind!r}")

    splits = manifest.get("splits")
    if not isinstance(splits, dict):
        raise ValueError("manifest.splits must be an object")

    split_entry = splits.get(kind)
    if not isinstance(split_entry, dict):
        raise ValueError(f"manifest.splits.{kind} must be an object")

    raw_path = split_entry.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError(f"manifest.splits.{kind}.path must be a non-empty string")

    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise ValueError(
            f"manifest.splits.{kind}.path must be relative; "
            f"got absolute path {raw_path!r}"
        )

    if any(part == ".." for part in candidate.parts):
        raise ValueError(
            f"manifest.splits.{kind}.path must not contain '..'; got {raw_path!r}"
        )

    normalized = raw_path.rstrip("/")
    if normalized != expected_dir:
        raise ValueError(
            f"manifest.splits.{kind}.path must equal {expected_dir!r}; "
            f"got {normalized!r}"
        )

    base_resolved = base_path.resolve()
    split_resolved = (base_path / candidate).resolve()
    try:
        split_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise ValueError(
            f"manifest.splits.{kind}.path resolves outside base_path: "
            f"{split_resolved} not under {base_resolved}"
        ) from exc

    return split_resolved


def _resolve_expected_schema_path(base_path: Path, manifest: dict[str, Any]) -> Path:
    raw_path = manifest.get("expected_schema")
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("manifest.expected_schema must be a non-empty string")

    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise ValueError(
            f"manifest.expected_schema must be relative; got absolute path {raw_path!r}"
        )

    if any(part == ".." for part in candidate.parts):
        raise ValueError(
            f"manifest.expected_schema must not contain '..'; got {raw_path!r}"
        )

    if raw_path != _CANONICAL_EXPECTED_SCHEMA_FILENAME:
        raise ValueError(
            f"manifest.expected_schema must equal {_CANONICAL_EXPECTED_SCHEMA_FILENAME!r}; "
            f"got {raw_path!r}"
        )

    base_resolved = base_path.resolve()
    schema_resolved = (base_path / candidate).resolve()
    try:
        schema_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise ValueError(
            f"manifest.expected_schema resolves outside base_path: "
            f"{schema_resolved} not under {base_resolved}"
        ) from exc

    return schema_resolved


def _fixture_paths_for_split(split_path: Path) -> list[Path]:
    if not split_path.exists():
        return []
    if not split_path.is_dir():
        raise ValueError(f"fixture split path must be a directory: {split_path}")
    return sorted(split_path.glob("*.json"))


def _public_fixture_from_data(
    data: dict[str, Any],
    *,
    source_path: Path,
    dataset_version_id: str | None,
) -> PublicFixture:
    fixture_kind = _coerce_fixture_kind(data.get("fixture_kind"), source_path=source_path)
    if fixture_kind != "public_regression":
        raise ValueError(
            f"{source_path}: fixture_kind {fixture_kind} does not match split public_regression."
        )

    missing = sorted(_REQUIRED_FIXTURE_KEYS_PUBLIC.difference(data))
    if missing:
        raise ValueError(f"{source_path}: missing required fixture keys: {', '.join(missing)}.")

    fixture_dataset_version_id = _validate_dataset_version(
        data,
        source_path=source_path,
        dataset_version_id=dataset_version_id,
    )
    metadata = _require_dict(data.get("metadata"), source_path=source_path, key="metadata")
    input_data = _require_dict(data.get("input"), source_path=source_path, key="input")
    _assert_no_raw_secret_keys(metadata, source_path, "metadata")
    _assert_no_raw_secret_keys(input_data, source_path, "input")

    return PublicFixture(
        fixture_id=_require_str(data.get("fixture_id"), source_path=source_path, key="fixture_id"),
        dataset_version_id=fixture_dataset_version_id,
        fixture_kind="public_regression",
        gate_id=_coerce_gate_id(data.get("gate_id"), source_path=source_path),
        metric_key=_coerce_metric_key(data.get("metric_key"), source_path=source_path),
        case_key=_require_str(data.get("case_key"), source_path=source_path, key="case_key"),
        input=input_data,
        expected_decision=_coerce_expected_decision(
            data.get("expected_decision"),
            source_path=source_path,
        ),
        expected_block=_require_bool(
            data.get("expected_block"),
            source_path=source_path,
            key="expected_block",
        ),
        expected_reason_code=_require_str(
            data.get("expected_reason_code"),
            source_path=source_path,
            key="expected_reason_code",
        ),
        expected_agent_run_status=_require_str(
            data.get("expected_agent_run_status"),
            source_path=source_path,
            key="expected_agent_run_status",
        ),
        pattern_hit_kind=_require_str(
            data.get("pattern_hit_kind"),
            source_path=source_path,
            key="pattern_hit_kind",
        ),
        assertions=_require_assertions(data.get("assertions"), source_path=source_path),
        anti_gaming=_require_bool_dict(
            data.get("anti_gaming"),
            source_path=source_path,
            key="anti_gaming",
        ),
        metadata=metadata,
    )


def _redacted_fixture_from_data(
    data: dict[str, Any],
    *,
    source_path: Path,
    expected_fixture_kind: RedactedFixtureKind,
    dataset_version_id: str | None,
) -> RedactedFixture:
    fixture_kind = _coerce_fixture_kind(data.get("fixture_kind"), source_path=source_path)
    if fixture_kind != expected_fixture_kind:
        raise ValueError(
            f"{source_path}: fixture_kind {fixture_kind} does not match split "
            f"{expected_fixture_kind}."
        )

    top_level_leaks = sorted(_PROHIBITED_REDACTED_KEYS.intersection(data))
    if top_level_leaks:
        raise ValueError(
            f"expectation leak in redacted fixture {source_path}: "
            f"prohibited top-level keys {top_level_leaks}"
        )

    nested_leaks = _find_prohibited_keys_recursive(data, _PROHIBITED_REDACTED_KEYS)
    if nested_leaks:
        raise ValueError(
            f"expectation leak in redacted fixture {source_path}: "
            f"nested prohibited keys at {sorted(nested_leaks)}"
        )

    unknown_keys = sorted(set(data) - _REQUIRED_FIXTURE_KEYS_REDACTED)
    if unknown_keys:
        raise ValueError(
            f"redacted fixture {source_path.name} has unknown top-level keys "
            f"{unknown_keys}; allowed keys are {sorted(_REQUIRED_FIXTURE_KEYS_REDACTED)}. "
            "Anti-gaming invariant requires redacted fixtures to use only the allowed schema."
        )

    missing = sorted(_REQUIRED_FIXTURE_KEYS_REDACTED.difference(data))
    if missing:
        raise ValueError(f"{source_path}: missing required fixture keys: {', '.join(missing)}.")

    fixture_dataset_version_id = _validate_dataset_version(
        data,
        source_path=source_path,
        dataset_version_id=dataset_version_id,
    )
    metadata = _require_dict(data.get("metadata"), source_path=source_path, key="metadata")
    input_data = _require_dict(data.get("input"), source_path=source_path, key="input")
    _assert_no_raw_secret_keys(metadata, source_path, "metadata")
    _assert_no_raw_secret_keys(input_data, source_path, "input")

    return RedactedFixture(
        fixture_id=_require_str(data.get("fixture_id"), source_path=source_path, key="fixture_id"),
        dataset_version_id=fixture_dataset_version_id,
        fixture_kind=cast(RedactedFixtureKind, fixture_kind),
        gate_id=_coerce_gate_id(data.get("gate_id"), source_path=source_path),
        metric_key=_coerce_metric_key(data.get("metric_key"), source_path=source_path),
        case_key=_require_str(data.get("case_key"), source_path=source_path, key="case_key"),
        input=input_data,
        anti_gaming=_require_bool_dict(
            data.get("anti_gaming"),
            source_path=source_path,
            key="anti_gaming",
        ),
        metadata=metadata,
    )


def _load_public_split(
    split_path: Path,
    *,
    dataset_version_id: str | None,
    manifest: dict[str, Any],
    schema: dict[str, Any],
) -> list[PublicFixture]:
    fixture_paths = _fixture_paths_for_split(split_path)
    _assert_split_count_matches_manifest(manifest, "public_regression", len(fixture_paths))

    fixtures: list[PublicFixture] = []
    actual_fixture_ids: set[str] = set()
    for fixture_path in fixture_paths:
        data = _read_json_object(fixture_path)
        fixture = _public_fixture_from_data(
            data,
            source_path=fixture_path,
            dataset_version_id=dataset_version_id,
        )
        _validate_fixture_against_schema(data, schema, fixture_path)
        _assert_fixture_matches_immutable_index(
            fixture.fixture_id,
            data,
            manifest,
            "public_regression",
        )
        actual_fixture_ids.add(fixture.fixture_id)
        fixtures.append(fixture)

    _assert_immutable_index_split_consistency(
        manifest,
        "public_regression",
        actual_fixture_ids,
    )
    return fixtures


def _load_redacted_split(
    split_path: Path,
    *,
    fixture_kind: RedactedFixtureKind,
    dataset_version_id: str | None,
    manifest: dict[str, Any],
) -> list[RedactedFixture]:
    fixture_paths = _fixture_paths_for_split(split_path)
    _assert_split_count_matches_manifest(manifest, fixture_kind, len(fixture_paths))

    fixtures: list[RedactedFixture] = []
    actual_fixture_ids: set[str] = set()
    for fixture_path in fixture_paths:
        data = _read_json_object(fixture_path)
        fixture = _redacted_fixture_from_data(
            data,
            source_path=fixture_path,
            expected_fixture_kind=fixture_kind,
            dataset_version_id=dataset_version_id,
        )
        _assert_fixture_matches_immutable_index(
            fixture.fixture_id,
            data,
            manifest,
            fixture_kind,
        )
        actual_fixture_ids.add(fixture.fixture_id)
        fixtures.append(fixture)

    _assert_immutable_index_split_consistency(
        manifest,
        fixture_kind,
        actual_fixture_ids,
    )
    return fixtures


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    """Load and validate AC-HARD-01 manifest.json."""

    manifest = dict(_read_json_object(manifest_path))
    hard_gate_id = manifest.get("hard_gate_id", manifest.get("gate_id"))
    if hard_gate_id != "AC-HARD-01":
        raise ValueError("manifest hard_gate_id must be AC-HARD-01.")

    metric = manifest.get("metric", manifest.get("metric_key"))
    if metric != "policy_block_recall":
        raise ValueError("manifest metric must be policy_block_recall.")

    splits = manifest.get("splits")
    if not isinstance(splits, dict):
        raise ValueError("manifest splits must be a JSON object.")

    missing_splits = [kind for kind in _ALLOWED_FIXTURE_KINDS if kind not in splits]
    if missing_splits:
        raise ValueError(f"manifest splits missing: {', '.join(missing_splits)}.")

    anti_gaming_rules = manifest.get("anti_gaming_rules")
    if not isinstance(anti_gaming_rules, dict):
        raise ValueError("manifest anti_gaming_rules must be a JSON object.")

    common_rules = anti_gaming_rules.get("common")
    if not isinstance(common_rules, dict):
        raise ValueError("manifest anti_gaming_rules.common must be a JSON object.")

    dataset_version_id = _manifest_dataset_version_id(manifest)
    manifest["gate_id"] = "AC-HARD-01"
    manifest["metric_key"] = "policy_block_recall"
    manifest["dataset_version_id"] = dataset_version_id
    _validate_fixture_immutable_index(manifest)

    expectation_leaks = _find_prohibited_keys_recursive(manifest, _PROHIBITED_REDACTED_KEYS)
    if expectation_leaks:
        raise ValueError(
            f"manifest contains expectation leak keys at {sorted(expectation_leaks)}; "
            "manifest must not include redacted expectation keys "
            f"(prohibited: {sorted(_PROHIBITED_REDACTED_KEYS)}). "
            "Anti-gaming requires private_holdout/adversarial_new expectations to be "
            "absent from manifest."
        )

    secret_leaks = _find_prohibited_keys_recursive(manifest, _PROHIBITED_SECRET_METADATA_KEYS)
    if secret_leaks:
        raise ValueError(
            f"manifest contains raw secret keys at {sorted(secret_leaks)}; "
            "manifest must not include raw secret-related keys "
            f"(prohibited: {sorted(_PROHIBITED_SECRET_METADATA_KEYS)}). "
            "DB and loader denylist must be in sync."
        )

    return manifest


def load_expected_schema(path: Path) -> dict[str, Any]:
    """Load expected_schema.json and validate it as Draft 7 JSON Schema."""

    schema = _read_json_object(path)
    try:
        Draft7Validator.check_schema(schema)
    except JsonSchemaSchemaError as exc:
        raise ValueError(
            f"expected_schema is not a valid Draft 7 schema: {path}: {exc.message}"
        ) from exc

    if schema.get("type") != "object":
        raise ValueError("expected_schema type must be object.")

    required = schema.get("required")
    if not isinstance(required, list) or not set(_REQUIRED_FIXTURE_KEYS_PUBLIC).issubset(required):
        raise ValueError("expected_schema required keys do not cover PublicFixture.")

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("expected_schema properties must be a JSON object.")

    return schema


def load_public_regression_fixtures(
    base_path: Path = Path("eval/security/policy_block"),
) -> list[PublicFixture]:
    """Load public_regression/*.json files into PublicFixture."""

    manifest = load_manifest(base_path / "manifest.json")
    dataset_version_id = _manifest_dataset_version_id(manifest)

    schema_path = _resolve_expected_schema_path(base_path, manifest)
    schema = load_expected_schema(schema_path)

    fixtures = _load_public_split(
        _resolve_split_dir(base_path, "public_regression", manifest),
        dataset_version_id=dataset_version_id,
        manifest=manifest,
        schema=schema,
    )
    assert_anti_gaming_invariants(manifest, fixtures)
    return fixtures


def load_redacted_fixtures(
    base_path: Path,
    kind: RedactedFixtureKind,
) -> list[RedactedFixture]:
    """Load private_holdout / adversarial_new fixtures without reading expectations."""

    manifest = load_manifest(base_path / "manifest.json")
    dataset_version_id = _manifest_dataset_version_id(manifest)
    fixtures = _load_redacted_split(
        _resolve_split_dir(base_path, kind, manifest),
        fixture_kind=kind,
        dataset_version_id=dataset_version_id,
        manifest=manifest,
    )
    assert_anti_gaming_invariants(manifest, fixtures)
    return fixtures


def assert_anti_gaming_invariants(
    manifest: dict[str, Any],
    fixtures: Sequence[PublicFixture | RedactedFixture],
) -> None:
    """Enforce AC-HARD-01 fixture anti-gaming invariants."""

    dataset_version_id = _manifest_dataset_version_id(manifest)
    common_rules = _require_dict(
        _require_dict(
            manifest.get("anti_gaming_rules"),
            source_path=Path("manifest.json"),
            key="anti_gaming_rules",
        ).get("common"),
        source_path=Path("manifest.json"),
        key="anti_gaming_rules.common",
    )

    for rule_name in sorted(_REQUIRED_ANTI_GAMING_RULES):
        if common_rules.get(rule_name) is not True:
            raise ValueError(f"anti-gaming rule violation: {rule_name}")

    for fixture in fixtures:
        if isinstance(fixture, PublicFixture):
            if fixture.fixture_kind != "public_regression":
                raise ValueError(
                    f"PublicFixture {fixture.fixture_id} has spoofed fixture_kind "
                    f"{fixture.fixture_kind!r}; PublicFixture must always have "
                    "fixture_kind='public_regression'"
                )
        elif isinstance(fixture, RedactedFixture):
            if fixture.fixture_kind not in {"private_holdout", "adversarial_new"}:
                raise ValueError(
                    f"RedactedFixture {fixture.fixture_id} has spoofed fixture_kind "
                    f"{fixture.fixture_kind!r}; RedactedFixture must have "
                    "fixture_kind in {'private_holdout', 'adversarial_new'}"
                )
        else:
            raise TypeError(
                f"unsupported fixture type {type(fixture).__name__}; "
                "expected PublicFixture or RedactedFixture"
            )

    for fixture in fixtures:
        if fixture.dataset_version_id != dataset_version_id:
            raise ValueError(
                f"{fixture.fixture_id}: dataset_version_id mismatch: "
                f"{fixture.dataset_version_id} != {dataset_version_id}."
            )

        if fixture.gate_id != "AC-HARD-01":
            raise ValueError(f"{fixture.fixture_id}: gate_id must be AC-HARD-01.")

        if fixture.metric_key != "policy_block_recall":
            raise ValueError(f"{fixture.fixture_id}: metric_key must be policy_block_recall.")

        for field_name, field_value in (("metadata", fixture.metadata), ("input", fixture.input)):
            secret_leaks = _find_prohibited_keys_recursive(
                field_value,
                _PROHIBITED_SECRET_METADATA_KEYS,
            )
            if secret_leaks:
                raise ValueError(
                    f"fixture {fixture.fixture_id} {field_name} contains raw secret keys at "
                    f"{sorted(secret_leaks)}; anti-gaming requires raw secret keys to be "
                    "absent from fixture attributes (post-load check)"
                )

        if isinstance(fixture, RedactedFixture):
            payload = {
                "input": fixture.input,
                "anti_gaming": fixture.anti_gaming,
                "metadata": fixture.metadata,
            }
            leaks = _find_prohibited_keys_recursive(payload, _PROHIBITED_REDACTED_KEYS)
            if leaks:
                raise ValueError(
                    f"redacted fixture {fixture.fixture_id} ({fixture.fixture_kind}) "
                    f"contains expectation leak in attributes: {sorted(leaks)}. "
                    "Anti-gaming invariant requires redacted fixture attributes to "
                    "never expose expected_decision/expected_block/expected_reason_code/"
                    "expected_agent_run_status/pattern_hit_kind/assertions even after construction."
                )

        if fixture.anti_gaming.get("private_expectation_visible_to_policy_author") is not False:
            raise ValueError(
                f"{fixture.fixture_id}: private expectation visibility must be false."
            )

        if fixture.anti_gaming.get("append_only_refresh") is not True:
            raise ValueError(f"{fixture.fixture_id}: append_only_refresh must be true.")

        if fixture.anti_gaming.get("separate_fixture_and_policy_commits") is not True:
            raise ValueError(
                f"{fixture.fixture_id}: separate_fixture_and_policy_commits must be true."
            )


def discover_fixtures(
    base_path: Path = Path("eval/security/policy_block"),
) -> dict[str, list[PublicFixture | RedactedFixture]]:
    """Discover public, private, and adversarial fixture splits."""

    public: list[PublicFixture | RedactedFixture] = list(
        load_public_regression_fixtures(base_path)
    )
    private: list[PublicFixture | RedactedFixture] = list(
        load_redacted_fixtures(base_path, kind="private_holdout")
    )
    adversarial: list[PublicFixture | RedactedFixture] = list(
        load_redacted_fixtures(base_path, kind="adversarial_new")
    )
    return {
        "public_regression": public,
        "private_holdout": private,
        "adversarial_new": adversarial,
    }

