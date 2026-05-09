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
KpiId = Literal["AC-KPI-04"]
MetricKey = Literal["citation_coverage"]

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
        "kpi_id",
        "metric_key",
        "case_key",
        "input",
        "expected_aggregate",
        "threshold",
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
        "kpi_id",
        "metric_key",
        "case_key",
        "input",
        "anti_gaming",
        "metadata",
    }
)
_PROHIBITED_REDACTED_KEYS = frozenset(
    {
        "expected_aggregate",
        "expected_total_claims",
        "expected_claims_with_citation",
        "expected_coverage_ratio",
        "claims_with_citation",
        "coverage_ratio",
        "total_claims",
    }
)
_PROHIBITED_REDACTED_FIXTURE_KEYS = _PROHIBITED_REDACTED_KEYS | frozenset(
    {"threshold", "assertions"}
)
_MANIFEST_EXPECTATION_LEAK_ALLOWED_PATHS = frozenset({"$.threshold"})
_PROHIBITED_SECRET_METADATA_KEYS = frozenset(
    {
        "api_key",
        "api_token",
        "raw_secret",
        "secret",
        "secret_value",
        "private_key",
        "auth_token",
        "bearer_token",
        "capability_token",
        "capability_token_value",
        "provider_key",
        "github_installation_token",
        "github_app_private_key",
        "tailscale_auth_key",
        "sops_age_key",
        "age_private_key",
        "canary_value",
        "raw_canary",
    }
)
_RAW_SECRET_VALUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_api_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("anthropic_api_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("github_installation_token", re.compile(r"ghs_[A-Za-z0-9]{20,}")),
    ("github_oauth_token", re.compile(r"gho_[A-Za-z0-9]{20,}")),
    ("github_personal_token", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    ("tailscale_auth_key", re.compile(r"tskey-[a-z0-9]{16,}-[a-z0-9]{16,}")),
    ("age_private_key", re.compile(r"AGE-SECRET-KEY-1[A-Z0-9]{50,}")),
    ("pem_private_key", re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----")),
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
    """Complete public_regression fixture with readable expected aggregate."""

    fixture_id: str
    dataset_version_id: str
    fixture_kind: Literal["public_regression"]
    kpi_id: KpiId
    metric_key: MetricKey
    case_key: str
    input: dict[str, Any]
    expected_aggregate: dict[str, Any]
    threshold: dict[str, Any]
    assertions: list[dict[str, Any]]
    anti_gaming: dict[str, bool]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class RedactedFixture:
    """Redacted private_holdout / adversarial_new fixture without expectations."""

    fixture_id: str
    dataset_version_id: str
    fixture_kind: RedactedFixtureKind
    kpi_id: KpiId
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
                    "AC-KPI-04 fixture must use canonical JSON without duplicate keys"
                )
            seen.add(key)
        return dict(pairs)

    def _strict_parse_constant(constant: str) -> Any:
        raise ValueError(
            f"non-canonical JSON constant {constant!r} in {path}; "
            "AC-KPI-04 fixture must not contain NaN / Infinity / -Infinity"
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


def _coerce_kpi_id(value: object, *, source_path: Path) -> KpiId:
    if value != "AC-KPI-04":
        raise ValueError(f"{source_path}: kpi_id must be AC-KPI-04.")
    return "AC-KPI-04"


def _coerce_metric_key(value: object, *, source_path: Path) -> MetricKey:
    if value != "citation_coverage":
        raise ValueError(f"{source_path}: metric_key must be citation_coverage.")
    return "citation_coverage"


def _require_str(value: object, *, source_path: Path, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{source_path}: {key} must be a non-empty string.")
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
                    "fixture attributes must be JSON-compatible (dict keys must be strings)"
                )
            child_path = f"{path}.{key}"
            if key in prohibited:
                leaks.append(child_path)
            leaks.extend(_find_prohibited_keys_recursive(value, prohibited, child_path))
    elif isinstance(obj, (list, tuple)):
        for index, item in enumerate(obj):
            leaks.extend(_find_prohibited_keys_recursive(item, prohibited, f"{path}[{index}]"))
    elif isinstance(obj, (str, bool, int, float, type(None))):
        pass
    else:
        raise TypeError(
            f"unsupported value type {type(obj).__name__} at {path}; "
            "fixture attributes must be JSON-compatible "
            "(dict, list, tuple, str, int, float, bool, None)"
        )
    return leaks


def _find_raw_secret_value_patterns_recursive(obj: Any, path: str = "$") -> list[str]:
    leaks: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"unsupported dict key type {type(key).__name__} at {path}; "
                    "fixture attributes must be JSON-compatible (dict keys must be strings)"
                )
            leaks.extend(_find_raw_secret_value_patterns_recursive(value, f"{path}.{key}"))
    elif isinstance(obj, (list, tuple)):
        for index, item in enumerate(obj):
            leaks.extend(_find_raw_secret_value_patterns_recursive(item, f"{path}[{index}]"))
    elif isinstance(obj, str):
        for pattern_name, pattern in _RAW_SECRET_VALUE_PATTERNS:
            if pattern.search(obj):
                leaks.append(f"{path}:{pattern_name}")
    elif isinstance(obj, (bool, int, float, type(None))):
        pass
    else:
        raise TypeError(
            f"unsupported value type {type(obj).__name__} at {path}; "
            "fixture attributes must be JSON-compatible "
            "(dict, list, tuple, str, int, float, bool, None)"
        )
    return leaks


def _assert_no_raw_secret_leaks(
    obj: Any,
    source_path: Path,
    field_name: str,
) -> None:
    key_leaks = _find_prohibited_keys_recursive(obj, _PROHIBITED_SECRET_METADATA_KEYS)
    if key_leaks:
        raise ValueError(
            f"fixture {source_path.name} {field_name} contains raw secret keys at "
            f"{sorted(key_leaks)}; raw secret / raw canary keys are prohibited "
            f"(prohibited: {sorted(_PROHIBITED_SECRET_METADATA_KEYS)})"
        )

    value_leaks = _find_raw_secret_value_patterns_recursive(obj)
    if value_leaks:
        raise ValueError(
            f"fixture {source_path.name} {field_name} contains raw secret value patterns at "
            f"{sorted(value_leaks)}; raw values are never echoed in loader errors"
        )


def _assert_no_expectation_leak_in_manifest(manifest: dict[str, Any]) -> None:
    """Reject expectation fields in manifest while allowing standard top-level threshold."""

    expectation_leaks = [
        path
        for path in _find_prohibited_keys_recursive(
            manifest,
            _PROHIBITED_REDACTED_FIXTURE_KEYS,
        )
        if path not in _MANIFEST_EXPECTATION_LEAK_ALLOWED_PATHS
    ]
    if expectation_leaks:
        raise ValueError(
            f"manifest contains expectation leak keys at {sorted(expectation_leaks)}; "
            "manifest must not include redacted fixture expectation keys "
            f"(prohibited: {sorted(_PROHIBITED_REDACTED_FIXTURE_KEYS)})."
        )


def _assert_no_redacted_keys_in_redacted_fixture(
    data: dict[str, Any],
    source_path: Path,
) -> None:
    """RedactedFixture bodies must not expose expected values, including nested threshold."""

    top_level_leaks = sorted(_PROHIBITED_REDACTED_FIXTURE_KEYS.intersection(data))
    if top_level_leaks:
        raise ValueError(
            f"expectation leak in redacted fixture {source_path}: "
            f"prohibited top-level keys {top_level_leaks}"
        )

    nested_leaks = _find_prohibited_keys_recursive(data, _PROHIBITED_REDACTED_FIXTURE_KEYS)
    if nested_leaks:
        raise ValueError(
            f"expectation leak in redacted fixture {source_path}: "
            f"nested prohibited keys at {sorted(nested_leaks)}"
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


def _compute_expected_aggregate(sample_claims: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute citation coverage from claim rows."""

    if not isinstance(sample_claims, list):
        raise ValueError("sample_claims must be a list")

    total_claims = len(sample_claims)
    claims_with_citation = 0

    for index, claim in enumerate(sample_claims):
        if not isinstance(claim, dict):
            raise ValueError(f"sample_claims[{index}] must be a JSON object")
        citation_ids = claim.get("citation_ids", [])
        if not isinstance(citation_ids, list):
            raise ValueError(f"sample_claims[{index}].citation_ids must be a list")
        if any(isinstance(citation_id, str) and citation_id for citation_id in citation_ids):
            claims_with_citation += 1

    coverage_ratio = 0.0 if total_claims == 0 else claims_with_citation / total_claims
    return {
        "total_claims": total_claims,
        "claims_with_citation": claims_with_citation,
        "coverage_ratio": coverage_ratio,
    }


def _validate_claim_input(input_data: dict[str, Any], source_path: Path) -> None:
    evidence_set_hash = input_data.get("evidence_set_hash")
    if not isinstance(evidence_set_hash, str) or not _SHA256_PATTERN.fullmatch(evidence_set_hash):
        raise ValueError(f"{source_path}: input.evidence_set_hash must be 64-char lowercase hex")

    dataset_version = input_data.get("dataset_version")
    if not isinstance(dataset_version, str) or not dataset_version:
        raise ValueError(f"{source_path}: input.dataset_version must be a non-empty string")

    sample_claims = input_data.get("sample_claims")
    if not isinstance(sample_claims, list) or len(sample_claims) == 0:
        raise ValueError(f"{source_path}: input.sample_claims must be a non-empty array")

    seen_claim_ids: set[str] = set()
    for index, claim in enumerate(sample_claims):
        if not isinstance(claim, dict):
            raise ValueError(f"{source_path}: input.sample_claims[{index}] must be an object")
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id:
            raise ValueError(f"{source_path}: input.sample_claims[{index}].claim_id is required")
        if claim_id in seen_claim_ids:
            raise ValueError(f"{source_path}: duplicate claim_id {claim_id!r}")
        seen_claim_ids.add(claim_id)

        claim_text = claim.get("claim_text")
        if not isinstance(claim_text, str) or not claim_text:
            raise ValueError(f"{source_path}: input.sample_claims[{index}].claim_text is required")

        for key in ("evidence_ids", "citation_ids"):
            value = claim.get(key)
            if not isinstance(value, list):
                raise ValueError(f"{source_path}: input.sample_claims[{index}].{key} must be a list")
            if any(not isinstance(item, str) or not item for item in value):
                raise ValueError(
                    f"{source_path}: input.sample_claims[{index}].{key} must contain non-empty strings"
                )


def _validate_threshold(threshold: dict[str, Any], source_path: Path) -> None:
    if threshold.get("operator") != ">=":
        raise ValueError(f"{source_path}: threshold.operator must be >=")
    value = threshold.get("value")
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"{source_path}: threshold.value must be a number")
    if abs(float(value) - 0.9) > 1e-9:
        raise ValueError(f"{source_path}: threshold.value must be 0.9 for AC-KPI-04")


def _validate_aggregate_consistency(
    fixture: PublicFixture,
    source_path: Path,
) -> None:
    """Fail closed when expected_aggregate drifts from input.sample_claims."""

    sample_claims = fixture.input.get("sample_claims")
    if not isinstance(sample_claims, list):
        raise ValueError(f"{source_path}: input.sample_claims must be a list")

    computed = _compute_expected_aggregate(cast(list[dict[str, Any]], sample_claims))
    expected = fixture.expected_aggregate

    expected_total = expected.get("total_claims")
    if isinstance(expected_total, bool) or not isinstance(expected_total, int):
        raise ValueError(f"{source_path}: expected_aggregate.total_claims must be an integer")
    if computed["total_claims"] != expected_total:
        raise ValueError(
            f"expected_aggregate.total_claims mismatch in {source_path.name}: "
            f"computed {computed['total_claims']}, fixture {expected_total}"
        )

    expected_with_citation = expected.get("claims_with_citation")
    if isinstance(expected_with_citation, bool) or not isinstance(expected_with_citation, int):
        raise ValueError(
            f"{source_path}: expected_aggregate.claims_with_citation must be an integer"
        )
    if computed["claims_with_citation"] != expected_with_citation:
        raise ValueError(
            f"expected_aggregate.claims_with_citation mismatch in {source_path.name}: "
            f"computed {computed['claims_with_citation']}, fixture {expected_with_citation}"
        )

    expected_ratio = expected.get("coverage_ratio")
    if not isinstance(expected_ratio, int | float) or isinstance(expected_ratio, bool):
        raise ValueError(f"{source_path}: expected_aggregate.coverage_ratio must be a number")
    if abs(float(computed["coverage_ratio"]) - float(expected_ratio)) > 1e-3:
        raise ValueError(
            f"expected_aggregate.coverage_ratio mismatch in {source_path.name}: "
            f"computed {computed['coverage_ratio']}, fixture {expected_ratio} (diff > 1e-3)"
        )


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
        if isinstance(entry, dict) and entry.get("split") == kind
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

    unknown_keys = sorted(set(data) - _REQUIRED_FIXTURE_KEYS_PUBLIC)
    if unknown_keys:
        raise ValueError(
            f"public fixture {source_path.name} has unknown top-level keys "
            f"{unknown_keys}; allowed keys are {sorted(_REQUIRED_FIXTURE_KEYS_PUBLIC)}."
        )

    missing = sorted(_REQUIRED_FIXTURE_KEYS_PUBLIC.difference(data))
    if missing:
        raise ValueError(f"{source_path}: missing required fixture keys: {', '.join(missing)}.")

    _assert_no_raw_secret_leaks(data, source_path, "fixture")
    fixture_dataset_version_id = _validate_dataset_version(
        data,
        source_path=source_path,
        dataset_version_id=dataset_version_id,
    )
    input_data = _require_dict(data.get("input"), source_path=source_path, key="input")
    _validate_claim_input(input_data, source_path)
    expected_aggregate = _require_dict(
        data.get("expected_aggregate"),
        source_path=source_path,
        key="expected_aggregate",
    )
    threshold = _require_dict(data.get("threshold"), source_path=source_path, key="threshold")
    _validate_threshold(threshold, source_path)

    fixture = PublicFixture(
        fixture_id=_require_str(data.get("fixture_id"), source_path=source_path, key="fixture_id"),
        dataset_version_id=fixture_dataset_version_id,
        fixture_kind="public_regression",
        kpi_id=_coerce_kpi_id(data.get("kpi_id"), source_path=source_path),
        metric_key=_coerce_metric_key(data.get("metric_key"), source_path=source_path),
        case_key=_require_str(data.get("case_key"), source_path=source_path, key="case_key"),
        input=input_data,
        expected_aggregate=expected_aggregate,
        threshold=threshold,
        assertions=_require_assertions(data.get("assertions"), source_path=source_path),
        anti_gaming=_require_bool_dict(
            data.get("anti_gaming"),
            source_path=source_path,
            key="anti_gaming",
        ),
        metadata=_require_dict(data.get("metadata"), source_path=source_path, key="metadata"),
    )
    _validate_aggregate_consistency(fixture, source_path)
    return fixture


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

    _assert_no_redacted_keys_in_redacted_fixture(data, source_path)

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

    _assert_no_raw_secret_leaks(data, source_path, "fixture")
    fixture_dataset_version_id = _validate_dataset_version(
        data,
        source_path=source_path,
        dataset_version_id=dataset_version_id,
    )

    return RedactedFixture(
        fixture_id=_require_str(data.get("fixture_id"), source_path=source_path, key="fixture_id"),
        dataset_version_id=fixture_dataset_version_id,
        fixture_kind=cast(RedactedFixtureKind, fixture_kind),
        kpi_id=_coerce_kpi_id(data.get("kpi_id"), source_path=source_path),
        metric_key=_coerce_metric_key(data.get("metric_key"), source_path=source_path),
        case_key=_require_str(data.get("case_key"), source_path=source_path, key="case_key"),
        input=_require_dict(data.get("input"), source_path=source_path, key="input"),
        anti_gaming=_require_bool_dict(
            data.get("anti_gaming"),
            source_path=source_path,
            key="anti_gaming",
        ),
        metadata=_require_dict(data.get("metadata"), source_path=source_path, key="metadata"),
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
    """Load and validate AC-KPI-04 manifest.json."""

    manifest = dict(_read_json_object(manifest_path))
    if manifest.get("kpi_id") != "AC-KPI-04":
        raise ValueError("manifest kpi_id must be AC-KPI-04.")

    metric = manifest.get("metric", manifest.get("metric_key"))
    if metric != "citation_coverage":
        raise ValueError("manifest metric must be citation_coverage.")

    threshold = manifest.get("threshold")
    if not isinstance(threshold, dict):
        raise ValueError("manifest threshold must be a JSON object.")
    _validate_threshold(threshold, manifest_path)

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
    manifest["metric_key"] = "citation_coverage"
    manifest["dataset_version_id"] = dataset_version_id
    _validate_fixture_immutable_index(manifest)
    _assert_no_expectation_leak_in_manifest(manifest)
    _assert_no_raw_secret_leaks(manifest, manifest_path, "manifest")
    return manifest


def load_expected_schema(path: Path) -> dict[str, Any]:
    """Load expected_schema.json and validate it as Draft 7 JSON Schema."""

    if path.name != _CANONICAL_EXPECTED_SCHEMA_FILENAME:
        raise ValueError(
            f"expected_schema filename must be {_CANONICAL_EXPECTED_SCHEMA_FILENAME!r}; "
            f"got {path.name!r}"
        )

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
    base_path: Path = Path("eval/quality/citation_coverage"),
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
    """Enforce AC-KPI-04 fixture anti-gaming invariants."""

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

        if fixture.kpi_id != "AC-KPI-04":
            raise ValueError(f"{fixture.fixture_id}: kpi_id must be AC-KPI-04.")

        if fixture.metric_key != "citation_coverage":
            raise ValueError(f"{fixture.fixture_id}: metric_key must be citation_coverage.")

        payload: dict[str, Any] = {
            "input": fixture.input,
            "anti_gaming": fixture.anti_gaming,
            "metadata": fixture.metadata,
        }
        if isinstance(fixture, PublicFixture):
            payload["threshold"] = fixture.threshold
        _assert_no_raw_secret_leaks(payload, Path(fixture.fixture_id), "post-load attributes")

        if isinstance(fixture, RedactedFixture):
            leaks = _find_prohibited_keys_recursive(payload, _PROHIBITED_REDACTED_FIXTURE_KEYS)
            if leaks:
                raise ValueError(
                    f"redacted fixture {fixture.fixture_id} ({fixture.fixture_kind}) "
                    f"contains expectation leak in attributes: {sorted(leaks)}. "
                    "Anti-gaming invariant requires redacted fixture attributes to never "
                    "expose expected aggregate values, threshold, or assertions after construction."
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
    base_path: Path = Path("eval/quality/citation_coverage"),
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

