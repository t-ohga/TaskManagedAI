from __future__ import annotations

import copy
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

import eval.security.tenant_isolation.loader as tenant_loader
from eval.security.tenant_isolation.loader import (
    _PROHIBITED_REDACTED_KEYS,
    _PROHIBITED_SECRET_METADATA_KEYS,
    PublicFixture,
    RedactedFixture,
    _canonical_fixture_hash,
    _find_prohibited_keys_recursive,
    _read_json_object,
    _resolve_expected_schema_path,
    _resolve_split_dir,
    assert_anti_gaming_invariants,
    discover_fixtures,
    load_expected_schema,
    load_manifest,
    load_public_regression_fixtures,
    load_redacted_fixtures,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = _REPO_ROOT / "eval/security/tenant_isolation"
_MIGRATION_PATH = _REPO_ROOT / "migrations" / "versions" / "0004_secret_refs_capability_tokens.py"
_REQUIRED_COMMON_RULES = (
    "private_holdout_expectations_not_used_for_tuning",
    "monthly_refresh_append_only",
    "separate_fixture_and_policy_or_prompt_commits",
    "persist_fixture_id_and_dataset_version",
    "avoid_private_expectation_leakage",
    "adversarial_new_append_only",
)


def _extract_db_secret_metadata_keys_from_migration() -> frozenset[str]:
    """Extract prohibited metadata keys from the secret_refs migration source.

    The migration stores jsonpath as Python string literals, so this test
    intentionally parses source text and matches escaped
    `@.key == \"<key_name>\"` fragments.
    """
    if not _MIGRATION_PATH.is_file():
        raise FileNotFoundError(f"migration not found: {_MIGRATION_PATH}")

    source = _MIGRATION_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"PROHIBITED_METADATA_KEYS_JSONPATH\s*=\s*\((.*?)\n\)",
        source,
        re.DOTALL,
    )
    if match is None:
        raise AssertionError(
            f"PROHIBITED_METADATA_KEYS_JSONPATH constant not found in {_MIGRATION_PATH}"
        )

    jsonpath_block = match.group(1)
    at_key_count = len(re.findall(r'@\.key\s*==\s*', jsonpath_block))
    keys = re.findall(r'@\.key\s*==\s*\\"([^"\\]+)\\"', jsonpath_block)

    if at_key_count != len(keys):
        raise AssertionError(
            f"key extraction mismatch: found {at_key_count} `@.key ==` patterns "
            f"but extracted only {len(keys)} key names. Migration format may have "
            f"changed (e.g., key contains characters not matched by `[^\"\\\\]+`). "
            f"Block: {jsonpath_block[:200]}"
        )

    if not keys:
        raise AssertionError(
            "No @.key patterns found in PROHIBITED_METADATA_KEYS_JSONPATH; "
            f"format may have changed. Block: {jsonpath_block[:200]}"
        )

    return frozenset(keys)


def _sample_public_fixture() -> dict[str, Any]:
    return json.loads((BASE_PATH / "public_regression/sample.json").read_text(encoding="utf-8"))


def _redacted_fixture(kind: str) -> dict[str, Any]:
    return {
        "fixture_id": f"AC-HARD-03_v2026.05.01-skeleton_{kind}_redacted_case",
        "dataset_version_id": "v2026.05.01-skeleton",
        "fixture_kind": kind,
        "gate_id": "AC-HARD-03",
        "metric_key": "tenant_isolation_negative_pass",
        "case_key": f"{kind}_redacted_case",
        "input": {
            "operation": "DELETE",
            "actor_role": "app_role",
            "tenant_context": {
                "current_tenant_id": 1,
                "target_tenant_id": 2,
                "current_project_id": 10,
                "target_project_id": 20,
            },
            "sql_fixture": {
                "statement_kind": "cross_tenant_delete",
                "redacted_sql": "DELETE FROM tickets WHERE tenant_id = :target_tenant_id",
            },
            "payload_data_class": "internal",
        },
        "anti_gaming": {
            "private_expectation_visible_to_policy_author": False,
            "append_only_refresh": True,
            "separate_fixture_and_policy_commits": True,
        },
        "metadata": {
            "policy_version": "policy-fixture-v0",
            "prompt_pack_version": "prompt-pack-fixture-v0",
            "provider_compliance_matrix_version": "provider-matrix-fixture-v0",
            "payload_data_class": "internal",
            "allowed_data_class": "internal",
            "created_at": "2026-05-01",
            "notes": "Synthetic redacted fixture without expected values.",
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _manifest_with_split_path(kind: str, path: str) -> dict[str, Any]:
    manifest = json.loads((BASE_PATH / "manifest.json").read_text(encoding="utf-8"))
    manifest["splits"][kind]["path"] = path
    return manifest


def _manifest_with_expected_schema(path: str) -> dict[str, Any]:
    manifest = json.loads((BASE_PATH / "manifest.json").read_text(encoding="utf-8"))
    manifest["expected_schema"] = path
    return manifest


def _immutable_index(
    fixtures: list[tuple[str, dict[str, Any]]],
) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for split, fixture in fixtures:
        metadata = fixture.get("metadata")
        created_at = "2026-05-01"
        if isinstance(metadata, dict) and isinstance(metadata.get("created_at"), str):
            created_at = metadata["created_at"]

        fixture_id = fixture["fixture_id"]
        assert isinstance(fixture_id, str)
        index[fixture_id] = {
            "sha256": _canonical_fixture_hash(fixture),
            "split": split,
            "created_at": created_at,
        }
    return index


def _write_manifest(
    base_path: Path,
    *,
    public_expected_count: int = 1,
    private_expected_count: int = 0,
    adversarial_expected_count: int = 0,
    immutable_index: dict[str, Any] | None = None,
) -> None:
    manifest = json.loads((BASE_PATH / "manifest.json").read_text(encoding="utf-8"))
    manifest["splits"]["public_regression"]["expected_count"] = public_expected_count
    manifest["splits"]["private_holdout"]["expected_count"] = private_expected_count
    manifest["splits"]["adversarial_new"]["expected_count"] = adversarial_expected_count
    if immutable_index is not None:
        manifest["fixture_immutable_index"] = immutable_index
    _write_json(base_path / "manifest.json", manifest)


def _sample_public_immutable_index_entry() -> tuple[str, dict[str, Any]]:
    index = _immutable_index([("public_regression", _sample_public_fixture())])
    fixture_id, entry = next(iter(index.items()))
    return fixture_id, dict(entry)


def _load_manifest_with_immutable_index(
    tmp_path: Path,
    immutable_index: dict[str, Any],
) -> dict[str, Any]:
    base_path = tmp_path / "tenant_isolation"
    _write_manifest(base_path, immutable_index=immutable_index)
    return load_manifest(base_path / "manifest.json")


def _write_expected_schema(base_path: Path) -> None:
    schema = json.loads((BASE_PATH / "expected_schema.json").read_text(encoding="utf-8"))
    _write_json(base_path / "expected_schema.json", schema)


def _write_public_sample(base_path: Path) -> None:
    _write_json(base_path / "public_regression/sample.json", _sample_public_fixture())


def _write_public_case(base_path: Path, fixture: dict[str, Any]) -> None:
    _write_manifest(base_path, public_expected_count=1)
    _write_expected_schema(base_path)
    _write_json(base_path / "public_regression/sample.json", fixture)


def _write_redacted_case(
    base_path: Path,
    kind: str,
    fixture: dict[str, Any],
    *,
    immutable_index: dict[str, Any] | None = None,
) -> None:
    _write_manifest(
        base_path,
        private_expected_count=1 if kind == "private_holdout" else 0,
        adversarial_expected_count=1 if kind == "adversarial_new" else 0,
        immutable_index=immutable_index,
    )
    _write_json(base_path / f"{kind}/redacted.json", fixture)


def _write_three_split_fixture_tree(base_path: Path) -> None:
    public = _sample_public_fixture()
    private = _redacted_fixture("private_holdout")
    adversarial = _redacted_fixture("adversarial_new")
    _write_manifest(
        base_path,
        public_expected_count=1,
        private_expected_count=1,
        adversarial_expected_count=1,
        immutable_index=_immutable_index(
            [
                ("public_regression", public),
                ("private_holdout", private),
                ("adversarial_new", adversarial),
            ]
        ),
    )
    _write_expected_schema(base_path)
    _write_json(base_path / "public_regression/sample.json", public)
    _write_json(base_path / "private_holdout/redacted.json", private)
    _write_json(base_path / "adversarial_new/redacted.json", adversarial)


def _direct_redacted_fixture(
    *,
    dataset_version_id: str,
    fixture_kind: Any = "private_holdout",
    input_payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> RedactedFixture:
    return RedactedFixture(
        fixture_id="AC-HARD-03_v2026.05.01-skeleton_private_holdout_direct_case",
        dataset_version_id=dataset_version_id,
        fixture_kind=cast(Any, fixture_kind),
        gate_id="AC-HARD-03",
        metric_key="tenant_isolation_negative_pass",
        case_key="private_holdout_direct_case",
        input=input_payload
        if input_payload is not None
        else {
            "operation": "SELECT",
            "actor_role": "app_role",
            "tenant_context": {
                "current_tenant_id": 1,
                "target_tenant_id": 2,
                "current_project_id": 10,
                "target_project_id": 20,
            },
            "payload_data_class": "internal",
        },
        anti_gaming={
            "private_expectation_visible_to_policy_author": False,
            "append_only_refresh": True,
            "separate_fixture_and_policy_commits": True,
        },
        metadata=metadata
        if metadata is not None
        else {
            "rls_ready": True,
            "created_at": "2026-05-01",
            "notes": "Directly constructed redacted fixture without expectations.",
        },
    )


def _direct_public_fixture(
    *,
    dataset_version_id: str,
    fixture_kind: Any = "public_regression",
) -> PublicFixture:
    raw = _sample_public_fixture()
    return PublicFixture(
        fixture_id=raw["fixture_id"],
        dataset_version_id=dataset_version_id,
        fixture_kind=cast(Any, fixture_kind),
        gate_id="AC-HARD-03",
        metric_key="tenant_isolation_negative_pass",
        case_key=raw["case_key"],
        input=raw["input"],
        expected_decision="block",
        expected_failure="tenant_boundary_violation",
        expected_reason_code="tenant_boundary_violation",
        pattern_hit_kind="tenant_boundary",
        assertions=raw["assertions"],
        anti_gaming=raw["anti_gaming"],
        metadata=raw["metadata"],
    )


def test_read_json_object_rejects_duplicate_key_in_metadata(tmp_path: Path) -> None:
    """F-027 (R24): JSON object 内の duplicate key を fail-closed reject。"""
    fake_fixture = tmp_path / "fake_fixture.json"
    fake_fixture.write_text(
        '{"fixture_id": "x", "metadata": {"raw_secret": "leak", "raw_secret": "ok"}}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JSON object key 'raw_secret'"):
        _read_json_object(fake_fixture)


def test_read_json_object_rejects_duplicate_top_level_key(tmp_path: Path) -> None:
    """F-027 (R24): top-level duplicate key を fail-closed reject。"""
    fake_fixture = tmp_path / "fake_fixture.json"
    fake_fixture.write_text(
        '{"fixture_id": "a", "fixture_id": "b", "metadata": {}}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JSON object key 'fixture_id'"):
        _read_json_object(fake_fixture)


def test_read_json_object_rejects_duplicate_expected_decision_in_redacted(
    tmp_path: Path,
) -> None:
    """F-027 (R24): redacted fixture の duplicate expectation leak を reject。"""
    base_path = tmp_path / "tenant_isolation"
    _write_manifest(base_path, private_expected_count=1)
    redacted_path = base_path / "private_holdout/redacted.json"
    redacted_path.parent.mkdir(parents=True, exist_ok=True)
    redacted_path.write_text(
        """{
  "fixture_id": "AC-HARD-03_v2026.05.01-skeleton_private_holdout_duplicate_expected_decision",
  "dataset_version_id": "v2026.05.01-skeleton",
  "fixture_kind": "private_holdout",
  "gate_id": "AC-HARD-03",
  "metric_key": "tenant_isolation_negative_pass",
  "case_key": "private_holdout_duplicate_expected_decision",
  "input": {"operation": "SELECT"},
  "expected_decision": "block",
  "expected_decision": "allow",
  "anti_gaming": {
    "private_expectation_visible_to_policy_author": false,
    "append_only_refresh": true,
    "separate_fixture_and_policy_commits": true
  },
  "metadata": {"created_at": "2026-05-01"}
}""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JSON object key 'expected_decision'"):
        load_redacted_fixtures(base_path, kind="private_holdout")


def test_read_json_object_rejects_nan_value(tmp_path: Path) -> None:
    """F-027 (R24): NaN literal を fail-closed reject。"""
    fake_fixture = tmp_path / "nan_fixture.json"
    fake_fixture.write_text('{"foo": NaN}', encoding="utf-8")

    with pytest.raises(ValueError, match="non-canonical JSON constant 'NaN'"):
        _read_json_object(fake_fixture)


def test_read_json_object_rejects_infinity_value(tmp_path: Path) -> None:
    """F-027 (R24): Infinity literal を fail-closed reject。"""
    fake_fixture = tmp_path / "infinity_fixture.json"
    fake_fixture.write_text('{"foo": Infinity}', encoding="utf-8")

    with pytest.raises(ValueError, match="non-canonical JSON constant 'Infinity'"):
        _read_json_object(fake_fixture)


def test_canonical_fixture_hash_rejects_nan_value() -> None:
    """F-027 (R24): hash 計算時も NaN を non-canonical JSON として reject。"""
    with pytest.raises(ValueError, match="Out of range float values are not JSON compliant"):
        _canonical_fixture_hash({"foo": float("nan")})


def test_existing_sample_passes_strict_json_parse() -> None:
    """F-027 (R24): 既存 sample は strict parser でも通過する。"""
    data = _read_json_object(BASE_PATH / "public_regression/sample.json")

    assert data["fixture_id"] == "AC-HARD-03_v2026.05.01-skeleton_cross_tenant_select_app_role"
    assert data["metadata"]["created_at"] == "2026-05-01"


def test_load_manifest_normalizes_ac_hard_03_gate_id() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")

    assert manifest["gate_id"] == "AC-HARD-03"
    assert manifest["metric_key"] == "tenant_isolation_negative_pass"
    assert manifest["dataset_version_id"] == "v2026.05.01-skeleton"


def test_load_manifest_rejects_top_level_expected_decision(tmp_path: Path) -> None:
    manifest = json.loads((BASE_PATH / "manifest.json").read_text(encoding="utf-8"))
    manifest["expected_decision"] = "block"
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="contains expectation leak keys") as exc_info:
        load_manifest(manifest_path)

    message = str(exc_info.value)
    assert "$.expected_decision" in message
    assert "block" not in message


def test_load_manifest_rejects_split_level_expected_reason_code(tmp_path: Path) -> None:
    manifest = json.loads((BASE_PATH / "manifest.json").read_text(encoding="utf-8"))
    manifest["splits"]["private_holdout"]["expected_reason_code"] = "tenant_boundary"
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="contains expectation leak keys") as exc_info:
        load_manifest(manifest_path)

    message = str(exc_info.value)
    assert "$.splits.private_holdout.expected_reason_code" in message
    assert "tenant_boundary" not in message


def test_load_manifest_rejects_nested_expected_failure(tmp_path: Path) -> None:
    manifest = json.loads((BASE_PATH / "manifest.json").read_text(encoding="utf-8"))
    manifest["agent_routing"]["expected_failure"] = "tenant_boundary_violation"
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="contains expectation leak keys") as exc_info:
        load_manifest(manifest_path)

    message = str(exc_info.value)
    assert "$.agent_routing.expected_failure" in message
    assert "tenant_boundary_violation" not in message


def test_load_manifest_rejects_top_level_raw_secret(tmp_path: Path) -> None:
    manifest = json.loads((BASE_PATH / "manifest.json").read_text(encoding="utf-8"))
    manifest["raw_secret"] = "leak"
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        load_manifest(manifest_path)

    message = str(exc_info.value)
    assert "$.raw_secret" in message
    assert "leak" not in message


def test_load_manifest_rejects_nested_api_key(tmp_path: Path) -> None:
    manifest = json.loads((BASE_PATH / "manifest.json").read_text(encoding="utf-8"))
    manifest["splits"]["adversarial_new"]["api_key"] = "leak"
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        load_manifest(manifest_path)

    message = str(exc_info.value)
    assert "$.splits.adversarial_new.api_key" in message
    assert "leak" not in message


def test_load_existing_manifest_passes_strict_leak_check() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")

    assert manifest["gate_id"] == "AC-HARD-03"
    assert _find_prohibited_keys_recursive(manifest, _PROHIBITED_REDACTED_KEYS) == []
    assert _find_prohibited_keys_recursive(manifest, _PROHIBITED_SECRET_METADATA_KEYS) == []


def test_load_expected_schema_returns_jsonschema_object() -> None:
    schema = load_expected_schema(BASE_PATH / "expected_schema.json")

    assert schema["type"] == "object"
    assert schema["properties"]["gate_id"]["const"] == "AC-HARD-03"
    assert "fixture_id" in schema["required"]
    assert "dataset_version_id" in schema["required"]


def test_resolve_split_dir_rejects_absolute_path(tmp_path: Path) -> None:
    manifest = _manifest_with_split_path("public_regression", "/etc/passwd")

    with pytest.raises(ValueError, match="must be relative"):
        _resolve_split_dir(tmp_path, "public_regression", manifest)


def test_resolve_split_dir_rejects_parent_traversal(tmp_path: Path) -> None:
    manifest = _manifest_with_split_path("public_regression", "../other_dir")

    with pytest.raises(ValueError, match=re.escape("must not contain '..'")):
        _resolve_split_dir(tmp_path, "public_regression", manifest)


def test_resolve_split_dir_rejects_unknown_split_dir_name(tmp_path: Path) -> None:
    manifest = _manifest_with_split_path("public_regression", "alternative_dir")

    with pytest.raises(ValueError, match=re.escape("must equal 'public_regression'")):
        _resolve_split_dir(tmp_path, "public_regression", manifest)


def test_resolve_split_dir_accepts_canonical_path(tmp_path: Path) -> None:
    manifest = _manifest_with_split_path("public_regression", "public_regression")

    split_dir = _resolve_split_dir(tmp_path, "public_regression", manifest)

    assert split_dir == (tmp_path / "public_regression").resolve()


def test_resolve_expected_schema_path_rejects_absolute_path(tmp_path: Path) -> None:
    manifest = _manifest_with_expected_schema("/etc/passwd")

    with pytest.raises(ValueError, match="must be relative"):
        _resolve_expected_schema_path(tmp_path, manifest)


def test_resolve_expected_schema_path_rejects_parent_traversal(tmp_path: Path) -> None:
    manifest = _manifest_with_expected_schema("../alternate_schema.json")

    with pytest.raises(ValueError, match=re.escape("must not contain '..'")):
        _resolve_expected_schema_path(tmp_path, manifest)


def test_resolve_expected_schema_path_rejects_alternate_filename(tmp_path: Path) -> None:
    manifest = _manifest_with_expected_schema("permissive_schema.json")

    with pytest.raises(ValueError, match=re.escape("must equal 'expected_schema.json'")):
        _resolve_expected_schema_path(tmp_path, manifest)


def test_resolve_expected_schema_path_rejects_trailing_slash(tmp_path: Path) -> None:
    manifest = _manifest_with_expected_schema("expected_schema.json/")

    with pytest.raises(
        ValueError,
        match=re.escape("must equal 'expected_schema.json'"),
    ) as exc_info:
        _resolve_expected_schema_path(tmp_path, manifest)

    assert "expected_schema.json/" in str(exc_info.value)


def test_resolve_expected_schema_path_rejects_double_trailing_slash(tmp_path: Path) -> None:
    manifest = _manifest_with_expected_schema("expected_schema.json//")

    with pytest.raises(
        ValueError,
        match=re.escape("must equal 'expected_schema.json'"),
    ) as exc_info:
        _resolve_expected_schema_path(tmp_path, manifest)

    assert "expected_schema.json//" in str(exc_info.value)


def test_resolve_expected_schema_path_accepts_canonical_filename(tmp_path: Path) -> None:
    manifest = _manifest_with_expected_schema("expected_schema.json")

    schema_path = _resolve_expected_schema_path(tmp_path, manifest)

    assert schema_path == (tmp_path / "expected_schema.json").resolve()
    assert schema_path.relative_to(tmp_path.resolve()) == Path("expected_schema.json")


@pytest.mark.parametrize("bad_split", [None, 0, []])
def test_load_manifest_rejects_malformed_split_field(
    tmp_path: Path,
    bad_split: Any,
) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry["split"] = bad_split

    with pytest.raises(ValueError, match="split must be a string") as exc_info:
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})

    assert f"got {type(bad_split).__name__}" in str(exc_info.value)


def test_load_manifest_rejects_unknown_split_value(tmp_path: Path) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry["split"] = "deprecated"

    with pytest.raises(ValueError, match="split must be one of") as exc_info:
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})

    message = str(exc_info.value)
    assert "deprecated" in message
    assert "adversarial_new" in message
    assert "private_holdout" in message
    assert "public_regression" in message


@pytest.mark.parametrize("bad_entry", ["string", 123, [1, 2]])
def test_load_manifest_rejects_non_object_entry(
    tmp_path: Path,
    bad_entry: Any,
) -> None:
    fixture_id, _entry = _sample_public_immutable_index_entry()

    with pytest.raises(ValueError, match="must be an object") as exc_info:
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: bad_entry})

    assert f"got {type(bad_entry).__name__}" in str(exc_info.value)


def test_load_manifest_rejects_non_hex_sha256(tmp_path: Path) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry["sha256"] = "ABC"

    with pytest.raises(ValueError, match="64-char lowercase hex string"):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


def test_load_manifest_rejects_empty_fixture_id(tmp_path: Path) -> None:
    _fixture_id, entry = _sample_public_immutable_index_entry()

    with pytest.raises(ValueError, match="key must be a non-empty string"):
        _load_manifest_with_immutable_index(tmp_path, {"": entry})


def test_load_manifest_rejects_unknown_index_entry_key(tmp_path: Path) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry["expected_decision"] = "block"

    with pytest.raises(
        ValueError,
        match=re.escape("has unknown keys ['expected_decision']"),
    ) as exc_info:
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})

    message = str(exc_info.value)
    assert "expected_decision" in message
    assert "created_at" in message
    assert "sha256" in message
    assert "split" in message


def test_load_manifest_rejects_index_entry_with_redacted_leak_key(tmp_path: Path) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry["assertions"] = [{"name": "x"}]

    with pytest.raises(
        ValueError,
        match=re.escape("has unknown keys ['assertions']"),
    ):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


def test_load_manifest_rejects_index_entry_with_extra_metadata_key(tmp_path: Path) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry["notes"] = "metadata belongs in fixture files, not immutable index entries"

    with pytest.raises(
        ValueError,
        match=re.escape("has unknown keys ['notes']"),
    ):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


def test_load_manifest_rejects_index_entry_missing_required_key(tmp_path: Path) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry.pop("created_at")

    with pytest.raises(
        ValueError,
        match=re.escape("missing required keys ['created_at']"),
    ):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


@pytest.mark.parametrize(
    ("bad_created_at", "expected_message"),
    [
        ("2026/05/01", "created_at must match YYYY-MM-DD"),
        ("abc", "created_at must match YYYY-MM-DD"),
        (20260501, "created_at must be a string"),
    ],
)
def test_load_manifest_rejects_invalid_date_format(
    tmp_path: Path,
    bad_created_at: Any,
    expected_message: str,
) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry["created_at"] = bad_created_at

    with pytest.raises(ValueError, match=re.escape(expected_message)):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


def test_load_manifest_rejects_fullwidth_digits_in_created_at(tmp_path: Path) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry["created_at"] = "２０２６-０５-０１"

    with pytest.raises(
        ValueError,
        match=re.escape("created_at must match YYYY-MM-DD with ASCII digits"),
    ):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


def test_load_manifest_rejects_arabic_indic_digits_in_created_at(tmp_path: Path) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry["created_at"] = "٢٠٢٦-٠٥-٠١"

    with pytest.raises(
        ValueError,
        match=re.escape("created_at must match YYYY-MM-DD with ASCII digits"),
    ):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


def test_load_manifest_rejects_invalid_calendar_month(tmp_path: Path) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry["created_at"] = "2026-99-99"

    with pytest.raises(
        ValueError,
        match=re.escape("created_at is not a valid calendar date"),
    ):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


def test_load_manifest_rejects_invalid_calendar_day(tmp_path: Path) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry["created_at"] = "2026-02-30"

    with pytest.raises(
        ValueError,
        match=re.escape("created_at is not a valid calendar date"),
    ):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


def test_load_public_regression_fixtures_rejects_invalid_metadata_created_at_format(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "tenant_isolation"
    fixture = _sample_public_fixture()
    fixture["metadata"]["created_at"] = "05/01/2026"
    _write_public_case(base_path, fixture)

    expected = "path=['metadata', 'created_at'] validator=format"
    with pytest.raises(ValueError, match=re.escape(expected)) as exc_info:
        load_public_regression_fixtures(base_path)

    assert "05/01/2026" not in str(exc_info.value)


def test_load_public_regression_fixtures_reads_expected_values() -> None:
    fixtures = load_public_regression_fixtures(BASE_PATH)

    # Sprint 10 batch 5 R1 fix (BL-0029c + Codex F-PR27-R1-002 P2 adopt) added 13 cross-tenant
    # fixtures for research_tasks / claims / evidence_items /
    # evidence_sources / research_to_ticket / citation_coverage, plus
    # the original Sprint 2 skeleton. Total = 14 (manifest expected_count = 14).
    assert len(fixtures) == 14

    by_id = {f.fixture_id: f for f in fixtures}
    legacy = by_id[
        "AC-HARD-03_v2026.05.01-skeleton_cross_tenant_select_app_role"
    ]
    assert isinstance(legacy, PublicFixture)
    assert legacy.fixture_kind == "public_regression"
    assert legacy.gate_id == "AC-HARD-03"
    assert legacy.metric_key == "tenant_isolation_negative_pass"
    assert legacy.expected_decision == "block"
    assert legacy.expected_failure == "tenant_boundary_violation"
    assert legacy.expected_reason_code == "tenant_boundary_violation"
    assert legacy.pattern_hit_kind == "tenant_boundary"
    assert legacy.assertions[0]["name"] == "app_role_cannot_read_other_tenant"

    # All Sprint 10 batch 5 fixtures share the same gate / metric / decision
    # invariants (anti-gaming: append-only refresh, same dataset_version).
    for fixture in fixtures:
        assert fixture.gate_id == "AC-HARD-03"
        assert fixture.metric_key == "tenant_isolation_negative_pass"
        assert fixture.expected_decision == "block"
        assert fixture.expected_failure == "tenant_boundary_violation"
        assert fixture.expected_reason_code == "tenant_boundary_violation"
        assert fixture.pattern_hit_kind == "tenant_boundary"


def test_prohibited_secret_metadata_keys_match_secret_refs_db_check() -> None:
    """Verify loader denylist stays in sync with secret_refs DB CHECK.

    F-025 (R20): parse the migration source so DB/loader drift is detectable.
    """
    db_keys = _extract_db_secret_metadata_keys_from_migration()

    assert db_keys == _PROHIBITED_SECRET_METADATA_KEYS, (
        f"loader denylist {sorted(_PROHIBITED_SECRET_METADATA_KEYS)} drifts from "
        f"migration DB CHECK keys {sorted(db_keys)}; sync required between "
        "migrations/versions/0004_secret_refs_capability_tokens.py "
        "PROHIBITED_METADATA_KEYS_JSONPATH and loader.py "
        "_PROHIBITED_SECRET_METADATA_KEYS"
    )


def test_extract_db_secret_metadata_keys_handles_diverse_key_chars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-026 (R22): extract non lower_snake migration keys without drift gaps."""
    fake_migration = tmp_path / "fake_migration.py"
    fake_migration.write_text(
        'PROHIBITED_METADATA_KEYS_JSONPATH = (\n'
        '    "? (@.key == \\"raw_secret\\" || @.key == \\"oauth2_token\\" "\n'
        '    "|| @.key == \\"github-token\\" || @.key == \\"RawToken\\")"\n'
        ')\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "tests.eval.test_tenant_isolation_loader._MIGRATION_PATH",
        fake_migration,
    )

    keys = _extract_db_secret_metadata_keys_from_migration()

    assert keys == frozenset({"raw_secret", "oauth2_token", "github-token", "RawToken"})


def test_extract_db_secret_metadata_keys_raises_on_key_count_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-026 (R22): fail closed if @.key comparisons outnumber extracted keys."""
    fake_migration = tmp_path / "fake_migration.py"
    fake_migration.write_text(
        'PROHIBITED_METADATA_KEYS_JSONPATH = (\n'
        '    "? (@.key == \\"raw_secret\\" || @.key == \\"x\\\\y\\")"\n'
        ')\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "tests.eval.test_tenant_isolation_loader._MIGRATION_PATH",
        fake_migration,
    )

    with pytest.raises(AssertionError, match="key extraction mismatch"):
        _extract_db_secret_metadata_keys_from_migration()


def test_existing_sample_passes_raw_secret_check() -> None:
    fixtures = load_public_regression_fixtures(BASE_PATH)

    # Sprint 10 batch 5 expanded the fixture set from 1 to 14. Verify
    # that EVERY fixture (legacy + new) passes the raw-secret canary
    # check on metadata and input (anti-gaming + raw secret 非含 invariant).
    assert len(fixtures) == 14
    for fixture in fixtures:
        assert _find_prohibited_keys_recursive(
            fixture.metadata,
            _PROHIBITED_SECRET_METADATA_KEYS,
        ) == []
        assert _find_prohibited_keys_recursive(
            fixture.input,
            _PROHIBITED_SECRET_METADATA_KEYS,
        ) == []
    # Spot-check the legacy Sprint 2 fixture metadata.
    by_id = {f.fixture_id: f for f in fixtures}
    legacy = by_id[
        "AC-HARD-03_v2026.05.01-skeleton_cross_tenant_select_app_role"
    ]
    assert legacy.metadata["created_at"] == "2026-05-01"


def test_load_public_regression_fixtures_rejects_raw_secret_in_metadata(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "tenant_isolation"
    fixture = _sample_public_fixture()
    fixture["metadata"]["raw_secret"] = "leaked"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        load_public_regression_fixtures(base_path)

    message = str(exc_info.value)
    assert "metadata" in message
    assert "$.raw_secret" in message
    assert "leaked" not in message


def test_load_public_regression_fixtures_rejects_nested_api_key_in_metadata(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "tenant_isolation"
    fixture = _sample_public_fixture()
    fixture["metadata"]["wrapper"] = {"api_key": "leak"}
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        load_public_regression_fixtures(base_path)

    message = str(exc_info.value)
    assert "metadata" in message
    assert "$.wrapper.api_key" in message
    assert "leak" not in message


def test_load_public_regression_fixtures_rejects_raw_token_in_input(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "tenant_isolation"
    fixture = _sample_public_fixture()
    fixture["input"]["raw_token"] = "leak"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        load_public_regression_fixtures(base_path)

    message = str(exc_info.value)
    assert "input" in message
    assert "$.raw_token" in message
    assert "leak" not in message
    assert "additionalProperties" not in message


def test_load_redacted_fixtures_rejects_private_key_in_metadata(tmp_path: Path) -> None:
    base_path = tmp_path / "tenant_isolation"
    leaked = _redacted_fixture("private_holdout")
    leaked["metadata"]["private_key"] = "leak"
    _write_redacted_case(base_path, "private_holdout", leaked)

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        load_redacted_fixtures(base_path, kind="private_holdout")

    message = str(exc_info.value)
    assert "metadata" in message
    assert "$.private_key" in message
    assert "leak" not in message


def test_load_redacted_fixtures_rejects_age_key_in_input(tmp_path: Path) -> None:
    base_path = tmp_path / "tenant_isolation"
    leaked = _redacted_fixture("adversarial_new")
    leaked["input"]["age_key"] = "leak"
    _write_redacted_case(base_path, "adversarial_new", leaked)

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        load_redacted_fixtures(base_path, kind="adversarial_new")

    message = str(exc_info.value)
    assert "input" in message
    assert "$.age_key" in message
    assert "leak" not in message


def test_assert_anti_gaming_invariants_rejects_constructed_fixture_with_raw_secret_in_metadata(
) -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_redacted_fixture(
        dataset_version_id=manifest["dataset_version_id"],
        metadata={"rls_ready": True, "raw_secret": "leak"},
    )

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        assert_anti_gaming_invariants(manifest, [fixture])

    message = str(exc_info.value)
    assert fixture.fixture_id in message
    assert "metadata" in message
    assert "$.raw_secret" in message
    assert "post-load check" in message
    assert "leak" not in message


def test_assert_anti_gaming_invariants_rejects_constructed_public_fixture_with_canary_in_input(
) -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = replace(
        _direct_public_fixture(dataset_version_id=manifest["dataset_version_id"]),
        input={"operation": "SELECT", "canary": "synthetic-canary"},
    )

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        assert_anti_gaming_invariants(manifest, [fixture])

    message = str(exc_info.value)
    assert fixture.fixture_id in message
    assert "input" in message
    assert "$.canary" in message
    assert "post-load check" in message
    assert "synthetic-canary" not in message


def test_load_public_regression_fixtures_rejects_raw_secret_in_metadata_tuple_nested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_path = tmp_path / "tenant_isolation"
    fixture = _sample_public_fixture()
    fixture["metadata"]["wrapper"] = ({"raw_secret": "tuple-secret-value"},)
    _write_public_case(base_path, fixture)
    original_read_json_object = tenant_loader._read_json_object

    def fake_read_json_object(path: Path) -> dict[str, Any]:
        if path == base_path / "public_regression/sample.json":
            return fixture
        return original_read_json_object(path)

    monkeypatch.setattr(tenant_loader, "_read_json_object", fake_read_json_object)

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        load_public_regression_fixtures(base_path)

    message = str(exc_info.value)
    assert "metadata" in message
    assert "$.wrapper[0].raw_secret" in message
    assert "tuple-secret-value" not in message


def test_load_redacted_fixtures_rejects_expected_decision_leak(tmp_path: Path) -> None:
    base_path = tmp_path / "tenant_isolation"
    leaked = _redacted_fixture("private_holdout")
    leaked["expected_decision"] = "block"
    _write_redacted_case(base_path, "private_holdout", leaked)

    with pytest.raises(ValueError, match="expectation leak") as exc_info:
        load_redacted_fixtures(base_path, kind="private_holdout")

    message = str(exc_info.value)
    assert "prohibited top-level keys ['expected_decision']" in message
    assert "unknown top-level keys" not in message


def test_load_redacted_fixtures_rejects_unknown_top_level_key(tmp_path: Path) -> None:
    base_path = tmp_path / "tenant_isolation"
    leaked = _redacted_fixture("private_holdout")
    leaked["oracle_decision"] = "block"
    _write_redacted_case(base_path, "private_holdout", leaked)

    with pytest.raises(ValueError, match="has unknown top-level keys") as exc_info:
        load_redacted_fixtures(base_path, kind="private_holdout")

    message = str(exc_info.value)
    assert "oracle_decision" in message
    assert "allowed keys" in message
    assert "Anti-gaming invariant" in message


def test_load_redacted_fixtures_rejects_arbitrary_extra_field(tmp_path: Path) -> None:
    base_path = tmp_path / "tenant_isolation"
    leaked = _redacted_fixture("private_holdout")
    leaked["private_oracle"] = {"decision": "block"}
    _write_redacted_case(base_path, "private_holdout", leaked)

    with pytest.raises(ValueError, match="has unknown top-level keys") as exc_info:
        load_redacted_fixtures(base_path, kind="private_holdout")

    message = str(exc_info.value)
    assert "private_oracle" in message
    assert "allowed keys" in message


def test_load_redacted_fixtures_for_adversarial_new_rejects_unknown_key(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "tenant_isolation"
    leaked = _redacted_fixture("adversarial_new")
    leaked["oracle_decision"] = "block"
    _write_redacted_case(base_path, "adversarial_new", leaked)

    with pytest.raises(ValueError, match="has unknown top-level keys") as exc_info:
        load_redacted_fixtures(base_path, kind="adversarial_new")

    message = str(exc_info.value)
    assert "oracle_decision" in message
    assert "allowed keys" in message


def test_load_redacted_fixtures_rejects_nested_metadata_expected_decision(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "tenant_isolation"
    leaked = _redacted_fixture("private_holdout")
    leaked["metadata"]["expected_decision"] = "block"
    _write_redacted_case(base_path, "private_holdout", leaked)

    expected = "nested prohibited keys at ['$.metadata.expected_decision']"
    with pytest.raises(ValueError, match=re.escape(expected)):
        load_redacted_fixtures(base_path, kind="private_holdout")


def test_load_redacted_fixtures_rejects_nested_input_expected_reason_code(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "tenant_isolation"
    leaked = _redacted_fixture("private_holdout")
    leaked["input"]["expected_reason_code"] = "tenant_boundary_violation"
    _write_redacted_case(base_path, "private_holdout", leaked)

    expected = "nested prohibited keys at ['$.input.expected_reason_code']"
    with pytest.raises(ValueError, match=re.escape(expected)):
        load_redacted_fixtures(base_path, kind="private_holdout")


def test_load_redacted_fixtures_rejects_deeply_nested_assertions(tmp_path: Path) -> None:
    base_path = tmp_path / "tenant_isolation"
    leaked = _redacted_fixture("private_holdout")
    leaked["metadata"]["something"] = {"assertions": [{"name": "leak"}]}
    _write_redacted_case(base_path, "private_holdout", leaked)

    expected = "nested prohibited keys at ['$.metadata.something.assertions']"
    with pytest.raises(ValueError, match=re.escape(expected)):
        load_redacted_fixtures(base_path, kind="private_holdout")


def test_load_redacted_fixtures_rejects_nested_pattern_hit_kind(tmp_path: Path) -> None:
    base_path = tmp_path / "tenant_isolation"
    leaked = _redacted_fixture("private_holdout")
    leaked["input"]["context"] = {"pattern_hit_kind": "tenant_boundary"}
    _write_redacted_case(base_path, "private_holdout", leaked)

    expected = "nested prohibited keys at ['$.input.context.pattern_hit_kind']"
    with pytest.raises(ValueError, match=re.escape(expected)):
        load_redacted_fixtures(base_path, kind="private_holdout")


def test_load_redacted_fixtures_accepts_redacted_only(tmp_path: Path) -> None:
    base_path = tmp_path / "tenant_isolation"
    redacted = _redacted_fixture("private_holdout")
    _write_redacted_case(
        base_path,
        "private_holdout",
        redacted,
        immutable_index=_immutable_index([("private_holdout", redacted)]),
    )

    fixtures = load_redacted_fixtures(base_path, kind="private_holdout")

    assert len(fixtures) == 1
    assert isinstance(fixtures[0], RedactedFixture)
    assert fixtures[0].fixture_kind == "private_holdout"
    assert fixtures[0].case_key == "private_holdout_redacted_case"
    assert not hasattr(fixtures[0], "expected_decision")
    assert not hasattr(fixtures[0], "assertions")


def test_load_redacted_fixtures_for_adversarial_new(tmp_path: Path) -> None:
    base_path = tmp_path / "tenant_isolation"
    redacted = _redacted_fixture("adversarial_new")
    _write_redacted_case(
        base_path,
        "adversarial_new",
        redacted,
        immutable_index=_immutable_index([("adversarial_new", redacted)]),
    )

    fixtures = load_redacted_fixtures(base_path, kind="adversarial_new")

    assert len(fixtures) == 1
    assert isinstance(fixtures[0], RedactedFixture)
    assert fixtures[0].fixture_kind == "adversarial_new"
    assert fixtures[0].input["operation"] == "DELETE"
    assert not hasattr(fixtures[0], "expected_reason_code")


def test_load_public_regression_fixtures_rejects_expected_decision_allow(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "tenant_isolation"
    fixture = _sample_public_fixture()
    fixture["expected_decision"] = "allow"
    _write_public_case(base_path, fixture)

    with pytest.raises(
        ValueError,
        match=r"fails expected_schema validation: path=.*validator=const",
    ):
        load_public_regression_fixtures(base_path)


def test_load_public_regression_fixtures_rejects_assertion_missing_expected_field(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "tenant_isolation"
    fixture = _sample_public_fixture()
    fixture["assertions"][0].pop("expected")
    _write_public_case(base_path, fixture)

    with pytest.raises(
        ValueError,
        match=r"fails expected_schema validation: path=.*validator=required",
    ):
        load_public_regression_fixtures(base_path)


def test_load_public_regression_fixtures_rejects_input_extra_key(tmp_path: Path) -> None:
    base_path = tmp_path / "tenant_isolation"
    fixture = _sample_public_fixture()
    fixture["input"]["extra_key"] = "schema should reject this"
    _write_public_case(base_path, fixture)

    with pytest.raises(
        ValueError,
        match=r"fails expected_schema validation: path=.*validator=additionalProperties",
    ):
        load_public_regression_fixtures(base_path)


def test_load_public_regression_fixtures_rejects_top_level_extra_key(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "tenant_isolation"
    fixture = _sample_public_fixture()
    fixture["extra_key"] = "schema should reject this"
    _write_public_case(base_path, fixture)

    with pytest.raises(
        ValueError,
        match=r"fails expected_schema validation: path=.*validator=additionalProperties",
    ):
        load_public_regression_fixtures(base_path)


def test_validate_fixture_error_does_not_leak_raw_value(tmp_path: Path) -> None:
    base_path = tmp_path / "tenant_isolation"
    fixture = _sample_public_fixture()
    fixture["input"]["operation"] = "SELECT credit_card FROM payments"
    _write_public_case(base_path, fixture)

    with pytest.raises(
        ValueError,
        match=r"fails expected_schema validation: path=.*validator=enum",
    ) as exc_info:
        load_public_regression_fixtures(base_path)

    message = str(exc_info.value)
    assert "credit_card" not in message
    assert "SELECT credit_card FROM payments" not in message
    assert "validator=enum" in message


def test_load_public_regression_fixtures_rejects_extra_file(tmp_path: Path) -> None:
    base_path = tmp_path / "tenant_isolation"
    _write_manifest(base_path, public_expected_count=1)
    _write_expected_schema(base_path)
    _write_public_sample(base_path)

    extra = _sample_public_fixture()
    extra["fixture_id"] = "AC-HARD-03_v2026.05.01-skeleton_extra_cross_tenant_select"
    extra["case_key"] = "extra_cross_tenant_select"
    _write_json(base_path / "public_regression/extra.json", extra)

    with pytest.raises(ValueError, match="expected 1 fixtures, found 2"):
        load_public_regression_fixtures(base_path)


def test_load_public_regression_fixtures_rejects_missing_file(tmp_path: Path) -> None:
    base_path = tmp_path / "tenant_isolation"
    _write_manifest(base_path, public_expected_count=1)
    _write_expected_schema(base_path)

    with pytest.raises(ValueError, match="expected 1 fixtures, found 0"):
        load_public_regression_fixtures(base_path)


def test_load_public_regression_fixtures_rejects_missing_registered_index_entry(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "tenant_isolation"
    orphan_fixture_id = "AC-HARD-03_v2026.05.01-skeleton_deleted_public_case"
    _write_manifest(
        base_path,
        public_expected_count=0,
        immutable_index={
            orphan_fixture_id: {
                "sha256": "0" * 64,
                "split": "public_regression",
                "created_at": "2026-05-01",
            },
        },
    )
    _write_expected_schema(base_path)

    with pytest.raises(
        ValueError,
        match="fixture_immutable_index has entries with no fixture file",
    ) as exc_info:
        load_public_regression_fixtures(base_path)

    assert orphan_fixture_id in str(exc_info.value)


def test_load_redacted_fixtures_rejects_immutable_index_entry_count_mismatch(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "tenant_isolation"
    redacted = _redacted_fixture("private_holdout")
    _write_manifest(
        base_path,
        private_expected_count=2,
        immutable_index=_immutable_index([("private_holdout", redacted)]),
    )
    _write_json(base_path / "private_holdout/redacted-a.json", redacted)
    _write_json(base_path / "private_holdout/redacted-b.json", redacted)

    with pytest.raises(
        ValueError,
        match=(
            r"fixture_immutable_index entry count 1 does not match "
            r"manifest\.splits\.private_holdout\.expected_count 2"
        ),
    ):
        load_redacted_fixtures(base_path, kind="private_holdout")


def test_load_redacted_fixtures_rejects_count_mismatch_for_private_holdout(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "tenant_isolation"
    _write_manifest(base_path, private_expected_count=0)
    _write_json(base_path / "private_holdout/redacted.json", _redacted_fixture("private_holdout"))

    with pytest.raises(ValueError, match="expected 0 fixtures, found 1"):
        load_redacted_fixtures(base_path, kind="private_holdout")


def test_load_redacted_fixtures_rejects_count_mismatch_for_adversarial_new(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "tenant_isolation"
    _write_manifest(base_path, adversarial_expected_count=0)
    _write_json(base_path / "adversarial_new/redacted.json", _redacted_fixture("adversarial_new"))

    with pytest.raises(ValueError, match="expected 0 fixtures, found 1"):
        load_redacted_fixtures(base_path, kind="adversarial_new")


def test_load_public_regression_fixtures_rejects_unregistered_fixture(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "tenant_isolation"
    fixture = _sample_public_fixture()
    fixture["fixture_id"] = "AC-HARD-03_v2026.05.01-skeleton_unregistered_case"
    fixture["case_key"] = "unregistered_case"
    _write_manifest(base_path, public_expected_count=1)
    _write_expected_schema(base_path)
    _write_json(base_path / "public_regression/new.json", fixture)

    with pytest.raises(
        ValueError,
        match="not registered in manifest.fixture_immutable_index",
    ):
        load_public_regression_fixtures(base_path)


def test_load_public_regression_fixtures_rejects_modified_fixture_content(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "tenant_isolation"
    fixture = _sample_public_fixture()
    fixture["case_key"] = "modified_cross_tenant_select_app_role"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="content has been modified"):
        load_public_regression_fixtures(base_path)


def test_load_public_regression_fixtures_accepts_unmodified_registered_fixture() -> None:
    fixtures = load_public_regression_fixtures(BASE_PATH)
    manifest = load_manifest(BASE_PATH / "manifest.json")

    # Sprint 10 batch 5: fixture count is now 14 (added 13 cross-tenant
    # including claims / evidence_items mutator coverage).
    # F-PR27-R2-004 P2 adopt: keep a PINNED sha256 assertion for the
    # original Sprint 2 legacy fixture so a future change that edits
    # the fixture and updates manifest in the same commit cannot
    # silently pass review. The pinned hash anchors the legacy
    # fixture's anti-gaming immutability claim.
    assert len(fixtures) == 14
    immutable_index = manifest["fixture_immutable_index"]
    legacy_fid = (
        "AC-HARD-03_v2026.05.01-skeleton_cross_tenant_select_app_role"
    )
    legacy_entry = immutable_index[legacy_fid]
    assert legacy_entry["split"] == "public_regression"
    assert legacy_entry["sha256"] == (
        "e019c3e5a45dae6b0eb5fccbf96aae139a4c7d784947d72d7706048bde39ccd4"
    ), (
        "Legacy AC-HARD-03 skeleton fixture sha256 must match Sprint 2 "
        "anti-gaming registration; any change requires an explicit "
        "ADR + Sprint Pack documenting the refresh rationale."
    )
    for fixture in fixtures:
        registered = immutable_index[fixture.fixture_id]
        assert registered["split"] == "public_regression"
        assert isinstance(registered["sha256"], str)
        assert len(registered["sha256"]) == 64  # sha256 hex


def test_load_redacted_fixtures_skips_immutable_index_for_empty_split() -> None:
    private = load_redacted_fixtures(BASE_PATH, kind="private_holdout")
    adversarial = load_redacted_fixtures(BASE_PATH, kind="adversarial_new")

    assert private == []
    assert adversarial == []


def test_discover_fixtures_returns_three_splits_with_correct_types(tmp_path: Path) -> None:
    base_path = tmp_path / "tenant_isolation"
    _write_three_split_fixture_tree(base_path)

    discovered = discover_fixtures(base_path)

    assert set(discovered) == {"public_regression", "private_holdout", "adversarial_new"}
    assert len(discovered["public_regression"]) == 1
    assert len(discovered["private_holdout"]) == 1
    assert len(discovered["adversarial_new"]) == 1
    assert isinstance(discovered["public_regression"][0], PublicFixture)
    assert isinstance(discovered["private_holdout"][0], RedactedFixture)
    assert isinstance(discovered["adversarial_new"][0], RedactedFixture)


def test_discover_fixtures_adversarial_new_returns_redacted_only(tmp_path: Path) -> None:
    base_path = tmp_path / "tenant_isolation"
    _write_three_split_fixture_tree(base_path)

    discovered = discover_fixtures(base_path)
    adversarial_fixture = discovered["adversarial_new"][0]

    assert isinstance(adversarial_fixture, RedactedFixture)
    assert adversarial_fixture.fixture_kind == "adversarial_new"
    assert not hasattr(adversarial_fixture, "expected_decision")
    assert not hasattr(adversarial_fixture, "pattern_hit_kind")


def test_assert_anti_gaming_invariants_accepts_manifest_common_rules() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixtures = load_public_regression_fixtures(BASE_PATH)

    for rule_name in _REQUIRED_COMMON_RULES:
        assert manifest["anti_gaming_rules"]["common"][rule_name] is True

    assert_anti_gaming_invariants(manifest, fixtures)


@pytest.mark.parametrize("rule_name", _REQUIRED_COMMON_RULES)
def test_assert_anti_gaming_invariants_rejects_missing_rule(rule_name: str) -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    mutated_manifest = copy.deepcopy(manifest)
    mutated_manifest["anti_gaming_rules"]["common"].pop(rule_name)
    fixtures = load_public_regression_fixtures(BASE_PATH)

    with pytest.raises(ValueError, match=f"anti-gaming rule violation: {rule_name}"):
        assert_anti_gaming_invariants(mutated_manifest, fixtures)


@pytest.mark.parametrize("rule_name", _REQUIRED_COMMON_RULES)
def test_assert_anti_gaming_invariants_rejects_false_rule(rule_name: str) -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    mutated_manifest = copy.deepcopy(manifest)
    mutated_manifest["anti_gaming_rules"]["common"][rule_name] = False
    fixtures = load_public_regression_fixtures(BASE_PATH)

    with pytest.raises(ValueError, match=f"anti-gaming rule violation: {rule_name}"):
        assert_anti_gaming_invariants(mutated_manifest, fixtures)


def test_assert_anti_gaming_invariants_rejects_dataset_version_drift() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixtures = load_public_regression_fixtures(BASE_PATH)
    drifted_fixture = replace(fixtures[0], dataset_version_id="v2099.01.01-drift")

    with pytest.raises(ValueError, match="dataset_version_id mismatch"):
        assert_anti_gaming_invariants(manifest, [drifted_fixture])


def test_assert_anti_gaming_invariants_rejects_public_fixture_spoofed_as_private(
) -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_public_fixture(
        dataset_version_id=manifest["dataset_version_id"],
        fixture_kind="private_holdout",
    )

    with pytest.raises(ValueError, match="PublicFixture .* spoofed fixture_kind") as exc_info:
        assert_anti_gaming_invariants(manifest, [fixture])

    message = str(exc_info.value)
    assert fixture.fixture_id in message
    assert "private_holdout" in message
    assert "public_regression" in message


def test_assert_anti_gaming_invariants_rejects_redacted_fixture_spoofed_as_public(
) -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_redacted_fixture(
        dataset_version_id=manifest["dataset_version_id"],
        fixture_kind="public_regression",
    )

    with pytest.raises(ValueError, match="RedactedFixture .* spoofed fixture_kind") as exc_info:
        assert_anti_gaming_invariants(manifest, [fixture])

    message = str(exc_info.value)
    assert fixture.fixture_id in message
    assert "public_regression" in message
    assert "private_holdout" in message
    assert "adversarial_new" in message


def test_assert_anti_gaming_invariants_rejects_unsupported_fixture_type() -> None:
    class FakeFixture:
        pass

    manifest = load_manifest(BASE_PATH / "manifest.json")

    with pytest.raises(TypeError, match="unsupported fixture type FakeFixture") as exc_info:
        assert_anti_gaming_invariants(manifest, cast(Any, [FakeFixture()]))

    message = str(exc_info.value)
    assert "expected PublicFixture or RedactedFixture" in message


def test_assert_anti_gaming_invariants_rejects_replaced_redacted_fixture_with_expectation_leak(
) -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_redacted_fixture(dataset_version_id=manifest["dataset_version_id"])
    replaced_fixture = replace(
        fixture,
        metadata={"rls_ready": True, "expected_decision": "block"},
    )

    with pytest.raises(
        ValueError,
        match="contains expectation leak in attributes",
    ) as exc_info:
        assert_anti_gaming_invariants(manifest, [replaced_fixture])

    message = str(exc_info.value)
    assert replaced_fixture.fixture_id in message
    assert "$.metadata.expected_decision" in message


def test_assert_anti_gaming_invariants_rejects_directly_constructed_redacted_with_input_leak(
) -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_redacted_fixture(
        dataset_version_id=manifest["dataset_version_id"],
        input_payload={"operation": "SELECT", "expected_reason_code": "leak"},
    )

    with pytest.raises(
        ValueError,
        match="contains expectation leak in attributes",
    ) as exc_info:
        assert_anti_gaming_invariants(manifest, [fixture])

    message = str(exc_info.value)
    assert fixture.fixture_id in message
    assert "$.input.expected_reason_code" in message


def test_assert_anti_gaming_invariants_rejects_redacted_fixture_with_tuple_leak(
) -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_redacted_fixture(
        dataset_version_id=manifest["dataset_version_id"],
        metadata={"wrapper": ({"expected_decision": "block"},)},
    )

    with pytest.raises(
        ValueError,
        match="contains expectation leak in attributes",
    ) as exc_info:
        assert_anti_gaming_invariants(manifest, [fixture])

    message = str(exc_info.value)
    assert fixture.fixture_id in message
    assert "$.metadata.wrapper[0].expected_decision" in message


def test_assert_anti_gaming_invariants_rejects_redacted_fixture_with_set_value(
) -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_redacted_fixture(
        dataset_version_id=manifest["dataset_version_id"],
        metadata={"strange": {"a", "b"}},
    )

    # impl `_find_prohibited_keys_recursive` は metadata dict を root として呼ばれるため
    # 報告 path は `$.<key>` (metadata 接頭辞なし)。test 期待値を impl 出力に揃える。
    expected = "unsupported value type set at $.strange"
    with pytest.raises(TypeError, match=re.escape(expected)):
        assert_anti_gaming_invariants(manifest, [fixture])


def test_find_prohibited_keys_recursive_rejects_non_string_dict_key() -> None:
    with pytest.raises(TypeError, match="unsupported dict key type int"):
        _find_prohibited_keys_recursive({1: "x"}, _PROHIBITED_REDACTED_KEYS)


def test_assert_anti_gaming_invariants_rejects_redacted_fixture_with_int_dict_key(
) -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_redacted_fixture(
        dataset_version_id=manifest["dataset_version_id"],
        metadata=cast(Any, {1: "x", "rls_ready": True}),
    )

    with pytest.raises(TypeError, match="unsupported dict key type"):
        assert_anti_gaming_invariants(manifest, [fixture])


def test_assert_anti_gaming_invariants_rejects_redacted_fixture_with_custom_object_dict_key(
) -> None:
    class ObjectKey:
        pass

    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_redacted_fixture(
        dataset_version_id=manifest["dataset_version_id"],
        metadata=cast(Any, {ObjectKey(): "x", "rls_ready": True}),
    )

    with pytest.raises(TypeError, match="unsupported dict key type"):
        assert_anti_gaming_invariants(manifest, [fixture])


def test_find_prohibited_keys_recursive_clean_tuple_passes() -> None:
    leaks = _find_prohibited_keys_recursive(
        {"x": (1, 2, "y")},
        _PROHIBITED_REDACTED_KEYS,
    )

    assert leaks == []


def test_find_prohibited_keys_recursive_nested_tuple_with_dict_detects() -> None:
    leaks = _find_prohibited_keys_recursive(
        {"a": {"b": ({"expected_decision": "x"},)}},
        _PROHIBITED_REDACTED_KEYS,
    )

    assert leaks == ["$.a.b[0].expected_decision"]


def test_assert_anti_gaming_invariants_accepts_clean_redacted_fixture() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_redacted_fixture(dataset_version_id=manifest["dataset_version_id"])

    assert_anti_gaming_invariants(manifest, [fixture])

    assert fixture.fixture_kind == "private_holdout"
    assert fixture.metadata["rls_ready"] is True
    assert "expected_decision" not in fixture.metadata
    assert "expected_reason_code" not in fixture.input
