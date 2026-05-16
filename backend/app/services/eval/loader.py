from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

import sqlalchemy as sa
from jsonschema import Draft7Validator, FormatChecker
from jsonschema.exceptions import SchemaError as JsonSchemaSchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.base import JsonDict
from backend.app.db.models.dataset_version import DatasetVersion, FixtureKind
from backend.app.db.models.eval_case import EvalCase

LOADER_FIXTURE_KIND_VALUES: Final[tuple[FixtureKind, ...]] = (
    "public_regression",
    "private_holdout",
    "adversarial_new",
)
LOADER_FIXTURE_KINDS: Final[frozenset[FixtureKind]] = frozenset(LOADER_FIXTURE_KIND_VALUES)

_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_EXPECTED_SCHEMA_FILENAME = "expected_schema.json"
_PUBLIC_EXPECTED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "expected_decision",
        "expected_failure",
        "expected_reason_code",
        "pattern_hit_kind",
        "assertions",
    }
)
_REQUIRED_FIXTURE_KEYS: Final[frozenset[str]] = frozenset(
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
_REQUIRED_PUBLIC_FIXTURE_KEYS: Final[frozenset[str]] = _REQUIRED_FIXTURE_KEYS | _PUBLIC_EXPECTED_KEYS
_REQUIRED_INDEX_ENTRY_KEYS: Final[frozenset[str]] = frozenset({"sha256", "split", "created_at"})
_REQUIRED_ANTI_GAMING_RULES: Final[frozenset[str]] = frozenset(
    {
        "private_holdout_expectations_not_used_for_tuning",
        "monthly_refresh_append_only",
        "separate_fixture_and_policy_or_prompt_commits",
        "persist_fixture_id_and_dataset_version",
        "avoid_private_expectation_leakage",
        "adversarial_new_append_only",
    }
)
_RAW_SECRET_KEY_NAMES: Final[frozenset[str]] = frozenset(
    {
        # F-PR28-R1-003 P2 adopt: `value` removed from key-name set — too generic and rejected
        # legitimate KPI threshold.value fields (eval/quality/citation_coverage/manifest.json).
        # Defense-in-depth still applies via _RAW_SECRET_VALUE_PATTERNS (sk-/ghp_/AKIA/etc.).
        "age_key",
        "age_private_key",
        "api_key",
        "auth_token",
        "bearer_token",
        "canary",
        "canary_value",
        "capability_token",
        "github_app_private_key",
        "github_installation_token",
        "private_key",
        "provider_key",
        "raw_canary",
        "raw_secret",
        "raw_token",
        "raw_value",
        "secret",
        "secret_value",
        "session_token",
        "sops_age_key",
        "sops_key",
        "tailscale_auth_key",
        "token",
    }
)
_RAW_SECRET_VALUE_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("github_pat", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{16,}\b")),
    ("github_fine_grained_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
)


class FixtureLoadError(ValueError):
    """Raised when a file-system eval fixture corpus violates loader invariants."""


class DatasetVersionSyncError(ValueError):
    """Raised when file-system fixtures cannot be safely synced to DB."""


class FixtureKindPayload(BaseModel):
    """Pydantic fixture_kind validator used as one source in enum drift tests."""

    model_config = ConfigDict(extra="forbid")

    fixture_kind: FixtureKind

    @field_validator("fixture_kind")
    @classmethod
    def validate_standard_fixture_kind(cls, value: FixtureKind) -> FixtureKind:
        if value not in LOADER_FIXTURE_KINDS:
            raise ValueError("fixture_kind is not a standard Eval Harness split")
        return value


@dataclass(frozen=True)
class Fixture:
    fixture_id: str
    dataset_version_id: str
    fixture_kind: FixtureKind
    gate_id: str
    metric_key: str
    case_key: str
    case_json: JsonDict
    expected_json: JsonDict
    metadata: JsonDict
    anti_gaming: JsonDict
    source_path: Path
    raw_json: JsonDict


@dataclass(frozen=True)
class LoadedCorpus:
    dataset_key: str
    version: str
    content_hash: str
    manifest: JsonDict
    expected_schema: JsonDict
    fixtures: tuple[Fixture, ...]


@dataclass(frozen=True)
class RawSecretHit:
    path: str
    reason_code: str


def _read_json_object(path: Path) -> JsonDict:
    if not path.is_file():
        raise FixtureLoadError(f"json file not found: {path}")

    text = path.read_text(encoding="utf-8")

    def _strict_object_pairs_hook(pairs: list[tuple[str, object]]) -> JsonDict:
        seen: set[str] = set()
        result: JsonDict = {}
        for key, value in pairs:
            if key in seen:
                raise FixtureLoadError(f"duplicate JSON object key {key!r} in {path}")
            seen.add(key)
            result[key] = value
        return result

    def _strict_parse_constant(constant: str) -> object:
        raise FixtureLoadError(f"non-canonical JSON constant {constant!r} in {path}")

    try:
        data = json.loads(
            text,
            object_pairs_hook=_strict_object_pairs_hook,
            parse_constant=_strict_parse_constant,
        )
    except json.JSONDecodeError as exc:
        raise FixtureLoadError(f"invalid JSON in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise FixtureLoadError(f"json file {path} must contain a JSON object at the root")

    return cast(JsonDict, data)


def _require_object(value: object, *, source_path: Path, key: str) -> JsonDict:
    if not isinstance(value, dict):
        raise FixtureLoadError(f"{source_path}: {key} must be a JSON object")
    return cast(JsonDict, value)


def _require_str(value: object, *, source_path: Path, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise FixtureLoadError(f"{source_path}: {key} must be a non-empty string")
    return value


def _coerce_fixture_kind(value: object, *, source_path: Path) -> FixtureKind:
    try:
        return FixtureKindPayload.model_validate({"fixture_kind": value}).fixture_kind
    except ValidationError as exc:
        raise FixtureLoadError(
            f"{source_path}: fixture_kind must be one of {sorted(LOADER_FIXTURE_KINDS)}"
        ) from exc


def _nfc_canonical_json(payload: object) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return unicodedata.normalize("NFC", canonical)


def _canonical_fixture_hash(raw_fixture: JsonDict) -> str:
    return hashlib.sha256(_nfc_canonical_json(raw_fixture).encode("utf-8")).hexdigest()


def _canonical_content_hash(fixtures: list[Fixture]) -> str:
    payload = [
        fixture.raw_json
        for fixture in sorted(
            fixtures,
            key=lambda item: (item.fixture_kind, item.case_key, item.fixture_id),
        )
    ]
    return hashlib.sha256(_nfc_canonical_json(payload).encode("utf-8")).hexdigest()


def _find_raw_secret_hits(value: object, *, path: str = "$") -> list[RawSecretHit]:
    hits: list[RawSecretHit] = []

    if isinstance(value, dict):
        for raw_key, child in value.items():
            if not isinstance(raw_key, str):
                hits.append(RawSecretHit(path=path, reason_code="non_string_key"))
                continue
            child_path = f"{path}.{raw_key}"
            normalized_key = raw_key.strip().lower()
            if normalized_key in _RAW_SECRET_KEY_NAMES:
                hits.append(RawSecretHit(path=child_path, reason_code=f"raw_secret_key:{normalized_key}"))
            hits.extend(_find_raw_secret_hits(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(_find_raw_secret_hits(child, path=f"{path}[{index}]"))
    elif isinstance(value, str):
        for reason_code, pattern in _RAW_SECRET_VALUE_PATTERNS:
            if pattern.search(value):
                hits.append(RawSecretHit(path=path, reason_code=f"raw_secret_value:{reason_code}"))
    elif isinstance(value, (bool, int, float, type(None))):
        pass
    else:
        hits.append(RawSecretHit(path=path, reason_code=f"unsupported_json_type:{type(value).__name__}"))

    return hits


def _scan_for_raw_secret(fixture_json: JsonDict) -> None:
    hits = _find_raw_secret_hits(fixture_json)
    if hits:
        first = hits[0]
        raise FixtureLoadError(
            f"raw secret pattern detected in fixture JSON at {first.path} "
            f"(reason_code={first.reason_code}; raw value redacted)"
        )


def _manifest_version(manifest: JsonDict) -> str:
    version = manifest.get("dataset_version_id", manifest.get("dataset_version"))
    if not isinstance(version, str) or not version:
        raise FixtureLoadError("manifest dataset_version must be a non-empty string")
    return version


def _resolve_split_dir(root: Path, manifest: JsonDict, fixture_kind: FixtureKind) -> Path:
    splits = _require_object(manifest.get("splits"), source_path=root / "manifest.json", key="splits")
    split = _require_object(splits.get(fixture_kind), source_path=root / "manifest.json", key=f"splits.{fixture_kind}")
    raw_path = _require_str(split.get("path"), source_path=root / "manifest.json", key=f"splits.{fixture_kind}.path")

    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise FixtureLoadError(f"manifest split path for {fixture_kind} must be relative")
    if any(part == ".." for part in candidate.parts):
        raise FixtureLoadError(f"manifest split path for {fixture_kind} must not contain '..'")
    if raw_path.rstrip("/") != fixture_kind:
        raise FixtureLoadError(f"manifest split path for {fixture_kind} must equal {fixture_kind!r}")

    root_resolved = root.resolve()
    split_resolved = (root / candidate).resolve()
    try:
        split_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise FixtureLoadError(f"manifest split path for {fixture_kind} resolves outside fixture root") from exc

    return split_resolved


def _resolve_expected_schema_path(root: Path, manifest: JsonDict) -> Path:
    raw_path = _require_str(manifest.get("expected_schema"), source_path=root / "manifest.json", key="expected_schema")
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise FixtureLoadError("manifest expected_schema must be relative")
    if any(part == ".." for part in candidate.parts):
        raise FixtureLoadError("manifest expected_schema must not contain '..'")
    if raw_path != _EXPECTED_SCHEMA_FILENAME:
        raise FixtureLoadError(f"manifest expected_schema must equal {_EXPECTED_SCHEMA_FILENAME!r}")

    root_resolved = root.resolve()
    schema_resolved = (root / candidate).resolve()
    try:
        schema_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise FixtureLoadError("manifest expected_schema resolves outside fixture root") from exc

    return schema_resolved


def _load_expected_schema(root: Path, manifest: JsonDict) -> JsonDict:
    schema = _read_json_object(_resolve_expected_schema_path(root, manifest))
    try:
        Draft7Validator.check_schema(schema)
    except JsonSchemaSchemaError as exc:
        raise FixtureLoadError(f"expected_schema is not a valid Draft 7 schema: {exc.message}") from exc

    if schema.get("type") != "object":
        raise FixtureLoadError("expected_schema type must be object")
    return schema


def _validate_public_fixture_schema(raw_fixture: JsonDict, schema: JsonDict, source_path: Path) -> None:
    validator = Draft7Validator(schema, format_checker=FormatChecker())
    errors: list[JsonSchemaValidationError] = sorted(
        validator.iter_errors(raw_fixture),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        details = "; ".join(
            f"path={list(error.absolute_path)} validator={error.validator}"
            for error in errors[:5]
        )
        raise FixtureLoadError(f"public fixture {source_path.name} fails expected_schema validation: {details}")


def _fixture_paths_for_split(split_dir: Path) -> list[Path]:
    if not split_dir.exists():
        return []
    if not split_dir.is_dir():
        raise FixtureLoadError(f"fixture split path must be a directory: {split_dir}")
    return sorted(split_dir.glob("*.json"))


def _assert_split_count(manifest: JsonDict, fixture_kind: FixtureKind, actual_count: int) -> None:
    splits = _require_object(manifest.get("splits"), source_path=Path("manifest.json"), key="splits")
    split = _require_object(splits.get(fixture_kind), source_path=Path("manifest.json"), key=f"splits.{fixture_kind}")
    expected_count = split.get("expected_count")
    if isinstance(expected_count, bool) or not isinstance(expected_count, int) or expected_count < 0:
        raise FixtureLoadError(f"manifest.splits.{fixture_kind}.expected_count must be a non-negative integer")
    if expected_count != actual_count:
        raise FixtureLoadError(f"split {fixture_kind}: expected {expected_count} fixtures, found {actual_count}")


def _assert_manifest_anti_gaming(manifest: JsonDict) -> None:
    anti_gaming_rules = _require_object(
        manifest.get("anti_gaming_rules"),
        source_path=Path("manifest.json"),
        key="anti_gaming_rules",
    )
    common = _require_object(
        anti_gaming_rules.get("common"),
        source_path=Path("manifest.json"),
        key="anti_gaming_rules.common",
    )
    for rule_name in sorted(_REQUIRED_ANTI_GAMING_RULES):
        if common.get(rule_name) is not True:
            raise FixtureLoadError(f"anti-gaming rule violation: {rule_name}")


def _assert_immutable_index_entry(
    manifest: JsonDict,
    *,
    raw_fixture: JsonDict,
    fixture_id: str,
    fixture_kind: FixtureKind,
    source_path: Path,
) -> None:
    index = _require_object(
        manifest.get("fixture_immutable_index"),
        source_path=Path("manifest.json"),
        key="fixture_immutable_index",
    )
    entry = _require_object(
        index.get(fixture_id),
        source_path=Path("manifest.json"),
        key=f"fixture_immutable_index.{fixture_id}",
    )

    missing_keys = sorted(_REQUIRED_INDEX_ENTRY_KEYS - set(entry))
    if missing_keys:
        raise FixtureLoadError(f"fixture_immutable_index entry for {fixture_id} missing keys {missing_keys}")

    split = entry.get("split")
    if split != fixture_kind:
        raise FixtureLoadError(f"{source_path}: immutable index split does not match fixture split")

    expected_sha = entry.get("sha256")
    if not isinstance(expected_sha, str) or not _SHA256_PATTERN.fullmatch(expected_sha):
        raise FixtureLoadError(f"fixture_immutable_index entry for {fixture_id} has invalid sha256")

    actual_sha = _canonical_fixture_hash(raw_fixture)
    if actual_sha != expected_sha:
        raise FixtureLoadError(
            f"{source_path}: fixture content sha256 mismatch "
            f"(expected={expected_sha[:8]}..., actual={actual_sha[:8]}...)"
        )


def _assert_index_split_consistency(
    manifest: JsonDict,
    *,
    fixture_kind: FixtureKind,
    actual_fixture_ids: set[str],
) -> None:
    index = _require_object(
        manifest.get("fixture_immutable_index"),
        source_path=Path("manifest.json"),
        key="fixture_immutable_index",
    )
    registered = {
        fixture_id
        for fixture_id, entry in index.items()
        if isinstance(fixture_id, str)
        and isinstance(entry, dict)
        and entry.get("split") == fixture_kind
    }
    missing_files = sorted(registered - actual_fixture_ids)
    if missing_files:
        raise FixtureLoadError(
            f"split {fixture_kind}: fixture_immutable_index contains entries with no fixture file: {missing_files}"
        )


def _case_json(raw_fixture: JsonDict) -> JsonDict:
    return {
        key: value
        for key, value in raw_fixture.items()
        if key not in _PUBLIC_EXPECTED_KEYS
    }


def _expected_json(raw_fixture: JsonDict, fixture_kind: FixtureKind) -> JsonDict:
    if fixture_kind == "public_regression":
        return {key: raw_fixture[key] for key in sorted(_PUBLIC_EXPECTED_KEYS) if key in raw_fixture}

    metadata = _require_object(raw_fixture.get("metadata"), source_path=Path("fixture.json"), key="metadata")
    expectation_ref = metadata.get("expectation_ref")
    expected: JsonDict = {"encrypted": True, "fixture_kind": fixture_kind}
    if isinstance(expectation_ref, str) and expectation_ref:
        expected["expectation_ref"] = expectation_ref
    return expected


def _fixture_from_raw(
    raw_fixture: JsonDict,
    *,
    fixture_kind: FixtureKind,
    source_path: Path,
    manifest_version: str,
    schema: JsonDict,
) -> Fixture:
    required = _REQUIRED_PUBLIC_FIXTURE_KEYS if fixture_kind == "public_regression" else _REQUIRED_FIXTURE_KEYS
    missing = sorted(required - set(raw_fixture))
    if missing:
        raise FixtureLoadError(f"{source_path}: missing required fixture keys: {missing}")

    declared_kind = _coerce_fixture_kind(raw_fixture.get("fixture_kind"), source_path=source_path)
    if declared_kind != fixture_kind:
        raise FixtureLoadError(f"{source_path}: fixture_kind does not match split directory {fixture_kind}")

    dataset_version_id = _require_str(
        raw_fixture.get("dataset_version_id"),
        source_path=source_path,
        key="dataset_version_id",
    )
    if dataset_version_id != manifest_version:
        raise FixtureLoadError(f"{source_path}: dataset_version_id does not match manifest dataset version")

    if fixture_kind == "public_regression":
        _validate_public_fixture_schema(raw_fixture, schema, source_path)
    else:
        # F-PR28-R1-005 P2 adopt: anti-gaming for redacted splits must reject
        # ALL expectation-style fields, not just the tenant_isolation-specific set.
        # Other corpora use expected_block / expected_agent_run_status /
        # expected_pattern_hit_kind / expected_aggregate etc.; whitelisting only
        # the tenant_isolation keys would silently store holdout expectations
        # in case_json, exposing them to policy/prompt authors.
        leaked_expectation_keys = sorted(
            key
            for key in raw_fixture
            if isinstance(key, str)
            and (key in _PUBLIC_EXPECTED_KEYS or key.startswith("expected_") or key == "assertions")
        )
        if leaked_expectation_keys:
            raise FixtureLoadError(
                f"{source_path}: redacted fixture contains prohibited expectation keys {leaked_expectation_keys}"
            )

    metadata = dict(_require_object(raw_fixture.get("metadata"), source_path=source_path, key="metadata"))
    metadata.setdefault("rls_ready", True)
    if fixture_kind != "public_regression":
        metadata.setdefault("encrypted", True)

    fixture = Fixture(
        fixture_id=_require_str(raw_fixture.get("fixture_id"), source_path=source_path, key="fixture_id"),
        dataset_version_id=dataset_version_id,
        fixture_kind=fixture_kind,
        gate_id=_require_str(raw_fixture.get("gate_id"), source_path=source_path, key="gate_id"),
        metric_key=_require_str(raw_fixture.get("metric_key"), source_path=source_path, key="metric_key"),
        case_key=_require_str(raw_fixture.get("case_key"), source_path=source_path, key="case_key"),
        case_json=_case_json(raw_fixture),
        expected_json=_expected_json(raw_fixture, fixture_kind),
        metadata=metadata,
        anti_gaming=_require_object(raw_fixture.get("anti_gaming"), source_path=source_path, key="anti_gaming"),
        source_path=source_path,
        raw_json=raw_fixture,
    )

    if fixture.anti_gaming.get("append_only_refresh") is not True:
        raise FixtureLoadError(f"{source_path}: anti_gaming.append_only_refresh must be true")
    if fixture.anti_gaming.get("separate_fixture_and_policy_commits") is not True:
        raise FixtureLoadError(f"{source_path}: anti_gaming.separate_fixture_and_policy_commits must be true")
    if fixture.anti_gaming.get("private_expectation_visible_to_policy_author") is not False:
        raise FixtureLoadError(f"{source_path}: private expectation visibility must be false")

    return fixture


def load_fixture_corpus(root: Path, *, dataset_key: str) -> LoadedCorpus:
    if not dataset_key or len(dataset_key) > 200:
        raise FixtureLoadError("dataset_key must be between 1 and 200 characters")

    manifest = _read_json_object(root / "manifest.json")
    _scan_for_raw_secret(manifest)
    _assert_manifest_anti_gaming(manifest)

    version = _manifest_version(manifest)
    schema = _load_expected_schema(root, manifest)
    fixtures: list[Fixture] = []

    for fixture_kind in LOADER_FIXTURE_KIND_VALUES:
        split_dir = _resolve_split_dir(root, manifest, fixture_kind)
        paths = _fixture_paths_for_split(split_dir)
        _assert_split_count(manifest, fixture_kind, len(paths))

        actual_fixture_ids: set[str] = set()
        for fixture_path in paths:
            raw_fixture = _read_json_object(fixture_path)
            _scan_for_raw_secret(raw_fixture)

            fixture = _fixture_from_raw(
                raw_fixture,
                fixture_kind=fixture_kind,
                source_path=fixture_path,
                manifest_version=version,
                schema=schema,
            )
            _assert_immutable_index_entry(
                manifest,
                raw_fixture=raw_fixture,
                fixture_id=fixture.fixture_id,
                fixture_kind=fixture_kind,
                source_path=fixture_path,
            )
            actual_fixture_ids.add(fixture.fixture_id)
            fixtures.append(fixture)

        _assert_index_split_consistency(
            manifest,
            fixture_kind=fixture_kind,
            actual_fixture_ids=actual_fixture_ids,
        )

    return LoadedCorpus(
        dataset_key=dataset_key,
        version=version,
        content_hash=_canonical_content_hash(fixtures),
        manifest=manifest,
        expected_schema=schema,
        fixtures=tuple(fixtures),
    )


async def sync_dataset_version_to_db(
    session: AsyncSession,
    *,
    tenant_id: int,
    dataset_key: str,
    version: str,
    fixture_kind: FixtureKind,
    content_hash: str,
    fixtures: list[Fixture],
) -> DatasetVersion:
    if tenant_id < 1:
        raise DatasetVersionSyncError("tenant_id must be a positive integer")
    if not dataset_key or len(dataset_key) > 200:
        raise DatasetVersionSyncError("dataset_key must be between 1 and 200 characters")
    if not version or len(version) > 100:
        raise DatasetVersionSyncError("version must be between 1 and 100 characters")
    if fixture_kind not in LOADER_FIXTURE_KINDS:
        raise DatasetVersionSyncError("fixture_kind must be a standard Eval Harness split")
    if not _SHA256_PATTERN.fullmatch(content_hash):
        raise DatasetVersionSyncError("content_hash must be a 64-character lowercase sha256 hex digest")
    if not fixtures:
        raise DatasetVersionSyncError("fixtures must not be empty")

    mismatched_kinds = [fixture.fixture_id for fixture in fixtures if fixture.fixture_kind != fixture_kind]
    if mismatched_kinds:
        raise DatasetVersionSyncError(
            f"fixture_kind mismatch for {len(mismatched_kinds)} fixtures; expected {fixture_kind}"
        )

    mismatched_versions = [fixture.fixture_id for fixture in fixtures if fixture.dataset_version_id != version]
    if mismatched_versions:
        raise DatasetVersionSyncError(
            f"dataset_version_id mismatch for {len(mismatched_versions)} fixtures; expected {version}"
        )

    calculated_hash = _canonical_content_hash(fixtures)
    if calculated_hash != content_hash:
        raise DatasetVersionSyncError(
            f"content_hash mismatch (expected={content_hash[:8]}..., actual={calculated_hash[:8]}...)"
        )

    existing = await session.scalar(
        sa.select(DatasetVersion).where(
            DatasetVersion.tenant_id == tenant_id,
            DatasetVersion.dataset_key == dataset_key,
            DatasetVersion.version == version,
        )
    )
    if existing is not None:
        raise DatasetVersionSyncError(
            "dataset version already exists for "
            f"tenant_id={tenant_id}, dataset_key={dataset_key!r}, version={version!r}"
        )

    dataset_version = DatasetVersion(
        tenant_id=tenant_id,
        dataset_key=dataset_key,
        version=version,
        fixture_kind=fixture_kind,
        content_hash=content_hash,
        metadata_={
            "rls_ready": True,
            "append_only_refresh": True,
            "fixture_count": len(fixtures),
        },
    )
    session.add(dataset_version)

    try:
        await session.flush()
    except IntegrityError as exc:
        raise DatasetVersionSyncError("dataset_versions insert failed") from exc

    for fixture in fixtures:
        metadata = dict(fixture.metadata)
        metadata.update(
            {
                "rls_ready": True,
                "fixture_id": fixture.fixture_id,
                "fixture_kind": fixture.fixture_kind,
                "source_dataset_version_id": fixture.dataset_version_id,
                "source_path": str(fixture.source_path),
            }
        )
        session.add(
            EvalCase(
                tenant_id=tenant_id,
                dataset_version_id=dataset_version.id,
                case_key=fixture.case_key,
                case_json=fixture.case_json,
                expected_json=fixture.expected_json,
                metadata_=metadata,
            )
        )

    try:
        await session.flush()
    except IntegrityError as exc:
        raise DatasetVersionSyncError("eval_cases insert failed") from exc

    return dataset_version


__all__ = [
    "DatasetVersionSyncError",
    "Fixture",
    "FixtureKindPayload",
    "FixtureLoadError",
    "LOADER_FIXTURE_KINDS",
    "LoadedCorpus",
    "load_fixture_corpus",
    "sync_dataset_version_to_db",
]
