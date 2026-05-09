from __future__ import annotations

import copy
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

import eval.quality.cost_per_completed_task.loader as cost_loader
from eval.quality.cost_per_completed_task.loader import (
    _PROHIBITED_REDACTED_KEYS,
    _PROHIBITED_SECRET_METADATA_KEYS,
    PublicFixture,
    RedactedFixture,
    _canonical_fixture_hash,
    _compute_expected_aggregate,
    _find_prohibited_keys_recursive,
    _find_raw_secret_value_patterns_recursive,
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
BASE_PATH = _REPO_ROOT / "eval/quality/cost_per_completed_task"
_MIGRATION_PATH = _REPO_ROOT / "migrations" / "versions" / "0004_secret_refs_capability_tokens.py"
_REQUIRED_COMMON_RULES = (
    "private_holdout_expectations_not_used_for_tuning",
    "monthly_refresh_append_only",
    "separate_fixture_and_policy_or_prompt_commits",
    "persist_fixture_id_and_dataset_version",
    "avoid_private_expectation_leakage",
    "adversarial_new_append_only",
)
_DERIVED_REDACTED_LEAK_KEYS = (
    "total_completed_runs",
    "total_cost_usd",
    "cost_per_completed_task_usd",
    "threshold_usd",
    "threshold_passed",
    "expected_total_completed_runs",
    "expected_total_cost_usd",
    "expected_cost_per_completed_task_usd",
)
_RAW_SECRET_PATTERN_KINDS = (
    "openai_api_key",
    "anthropic_api_key",
    "github_installation_token",
    "github_oauth_token",
    "github_personal_token",
    "tailscale_auth_key",
    "age_private_key",
    "pem_private_key",
)


def _extract_db_secret_metadata_keys_from_migration() -> frozenset[str]:
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
        raise AssertionError("key extraction mismatch")
    if not keys:
        raise AssertionError("No @.key patterns found in PROHIBITED_METADATA_KEYS_JSONPATH")
    return frozenset(keys)


def _sample_public_fixture() -> dict[str, Any]:
    return json.loads((BASE_PATH / "public_regression/sample.json").read_text(encoding="utf-8"))


def _redacted_fixture(kind: str) -> dict[str, Any]:
    return {
        "fixture_id": f"AC-KPI-05_ac-kpi-05-v2026.05.09-skeleton_{kind}_redacted_case",
        "dataset_version_id": "ac-kpi-05-v2026.05.09-skeleton",
        "fixture_kind": kind,
        "kpi_id": "AC-KPI-05",
        "metric_key": "cost_per_completed_task",
        "case_key": f"{kind}_redacted_case",
        "input": {
            "sample_runs": [
                {
                    "tenant_id": 1,
                    "project_id": 1,
                    "run_id": "00000000-0000-4000-8000-000000005999",
                    "status": "completed",
                    "cost_usd": 0.1,
                    "tokens_input": 10,
                    "tokens_output": 5,
                }
            ],
        },
        "anti_gaming": {
            "private_expectation_visible_to_policy_author": False,
            "append_only_refresh": True,
            "separate_fixture_and_policy_commits": True,
        },
        "metadata": {
            "created_at": "2026-05-09",
            "notes": "Synthetic redacted cost fixture without expected values.",
            "source": "redacted usage source",
            "currency": "USD",
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _dummy_raw_secret_marker(pattern_kind: str) -> str:
    suffix = "X" * 24
    if pattern_kind == "openai_api_key":
        return "sk" + "-" + suffix
    if pattern_kind == "anthropic_api_key":
        return "sk" + "-" + "ant" + "-" + suffix
    if pattern_kind == "github_installation_token":
        return "ghs" + "_" + suffix
    if pattern_kind == "github_oauth_token":
        return "gho" + "_" + suffix
    if pattern_kind == "github_personal_token":
        return "ghp" + "_" + suffix
    if pattern_kind == "tailscale_auth_key":
        return "tskey" + "-" + ("a" * 16) + "-" + ("b" * 16)
    if pattern_kind == "age_private_key":
        return "AGE" + "-" + "SECRET" + "-" + "KEY" + "-" + "1" + ("A" * 52)
    if pattern_kind == "pem_private_key":
        return "-----BEGIN " + "RSA " + "PRIVATE KEY-----"
    raise AssertionError(f"unknown raw secret pattern kind: {pattern_kind}")


def _derived_leak_value(leak_key: str) -> object:
    if leak_key.endswith("threshold_passed"):
        return True
    if "cost" in leak_key or leak_key == "threshold_usd":
        return 0.1
    return 1


def _manifest() -> dict[str, Any]:
    return json.loads((BASE_PATH / "manifest.json").read_text(encoding="utf-8"))


def _manifest_with_split_path(kind: str, path: str) -> dict[str, Any]:
    manifest = _manifest()
    manifest["splits"][kind]["path"] = path
    return manifest


def _manifest_with_expected_schema(path: str) -> dict[str, Any]:
    manifest = _manifest()
    manifest["expected_schema"] = path
    return manifest


def _immutable_index(
    fixtures: list[tuple[str, dict[str, Any]]],
) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for split, fixture in fixtures:
        metadata = fixture.get("metadata")
        created_at = "2026-05-09"
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
    manifest = _manifest()
    manifest["splits"]["public_regression"]["expected_count"] = public_expected_count
    manifest["splits"]["private_holdout"]["expected_count"] = private_expected_count
    manifest["splits"]["adversarial_new"]["expected_count"] = adversarial_expected_count
    if immutable_index is not None:
        manifest["fixture_immutable_index"] = immutable_index
    _write_json(base_path / "manifest.json", manifest)


def _write_expected_schema(base_path: Path) -> None:
    schema = json.loads((BASE_PATH / "expected_schema.json").read_text(encoding="utf-8"))
    _write_json(base_path / "expected_schema.json", schema)


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


def _sample_public_immutable_index_entry() -> tuple[str, dict[str, Any]]:
    index = _immutable_index([("public_regression", _sample_public_fixture())])
    fixture_id, entry = next(iter(index.items()))
    return fixture_id, dict(entry)


def _load_manifest_with_immutable_index(
    tmp_path: Path,
    immutable_index: dict[str, Any],
) -> dict[str, Any]:
    base_path = tmp_path / "cost_per_completed_task"
    _write_manifest(base_path, immutable_index=immutable_index)
    return load_manifest(base_path / "manifest.json")


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
        kpi_id="AC-KPI-05",
        metric_key="cost_per_completed_task",
        case_key=raw["case_key"],
        input=raw["input"],
        expected_aggregate=raw["expected_aggregate"],
        assertions=raw["assertions"],
        anti_gaming=raw["anti_gaming"],
        metadata=raw["metadata"],
    )


def _direct_redacted_fixture(
    *,
    dataset_version_id: str,
    fixture_kind: Any = "private_holdout",
    input_payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> RedactedFixture:
    raw = _redacted_fixture("private_holdout")
    return RedactedFixture(
        fixture_id=raw["fixture_id"],
        dataset_version_id=dataset_version_id,
        fixture_kind=cast(Any, fixture_kind),
        kpi_id="AC-KPI-05",
        metric_key="cost_per_completed_task",
        case_key=raw["case_key"],
        input=input_payload if input_payload is not None else raw["input"],
        anti_gaming=raw["anti_gaming"],
        metadata=metadata if metadata is not None else raw["metadata"],
    )


def _load_public_fixture_direct(fixture: dict[str, Any]) -> PublicFixture:
    return cost_loader._public_fixture_from_data(
        fixture,
        source_path=Path("sample.json"),
        dataset_version_id=fixture["dataset_version_id"],
    )


def test_read_json_object_rejects_duplicate_top_level_key(tmp_path: Path) -> None:
    fake_fixture = tmp_path / "fake_fixture.json"
    fake_fixture.write_text(
        '{"fixture_id": "a", "fixture_id": "b", "metadata": {}}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JSON object key 'fixture_id'"):
        _read_json_object(fake_fixture)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_read_json_object_rejects_non_canonical_json_constants(
    tmp_path: Path,
    constant: str,
) -> None:
    fake_fixture = tmp_path / "constant_fixture.json"
    fake_fixture.write_text(f'{{"foo": {constant}}}', encoding="utf-8")

    with pytest.raises(ValueError, match=f"non-canonical JSON constant {constant!r}"):
        _read_json_object(fake_fixture)


def test_canonical_fixture_hash_rejects_nan_value() -> None:
    with pytest.raises(ValueError, match="Out of range float values are not JSON compliant"):
        _canonical_fixture_hash({"foo": float("nan")})


def test_existing_sample_passes_strict_json_parse() -> None:
    data = _read_json_object(BASE_PATH / "public_regression/sample.json")

    assert data["fixture_id"] == (
        "AC-KPI-05_ac-kpi-05-v2026.05.09-skeleton_cost_per_completed_task_minimal"
    )
    assert data["metadata"]["created_at"] == "2026-05-09"


def test_compute_expected_aggregate_counts_completed_only() -> None:
    fixture = _sample_public_fixture()
    computed = _compute_expected_aggregate(fixture["input"]["sample_runs"])

    assert computed == {
        "total_completed_runs": 3,
        "total_cost_usd": 0.6,
        "cost_per_completed_task_usd": 0.2,
        "threshold_usd": 0.5,
        "threshold_passed": True,
    }


def test_compute_expected_aggregate_handles_zero_completed_runs() -> None:
    computed = _compute_expected_aggregate(
        [
            {
                "status": "failed",
                "cost_usd": 10,
            },
            {
                "status": "cancelled",
                "cost_usd": 10,
            },
        ]
    )

    assert computed["total_completed_runs"] == 0
    assert computed["total_cost_usd"] == 0.0
    assert computed["cost_per_completed_task_usd"] is None
    assert computed["threshold_passed"] is False


def test_load_manifest_normalizes_ac_kpi_05_metric() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")

    assert manifest["kpi_id"] == "AC-KPI-05"
    assert manifest["metric_key"] == "cost_per_completed_task"
    assert manifest["dataset_version_id"] == "ac-kpi-05-v2026.05.09-skeleton"


def test_load_manifest_enforces_threshold() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")

    assert manifest["threshold"] == {
        "cost_per_completed_task_usd_max": 0.5,
        "currency": "USD",
    }


@pytest.mark.parametrize(
    "bad_threshold",
    [
        None,
        {},
        {"cost_per_completed_task_usd_max": 0.6, "currency": "USD"},
        {"cost_per_completed_task_usd_max": 0.5, "currency": "JPY"},
    ],
)
def test_load_manifest_rejects_invalid_threshold(tmp_path: Path, bad_threshold: Any) -> None:
    manifest = _manifest()
    manifest["threshold"] = bad_threshold
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="threshold"):
        load_manifest(manifest_path)


def test_load_manifest_rejects_top_level_expected_aggregate(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["expected_aggregate"] = {"cost_per_completed_task_usd": 1}
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="contains expectation leak keys") as exc_info:
        load_manifest(manifest_path)

    assert "$.expected_aggregate" in str(exc_info.value)


def test_load_manifest_rejects_top_level_raw_secret(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["raw_secret"] = "leak"
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        load_manifest(manifest_path)

    assert "$.raw_secret" in str(exc_info.value)
    assert "leak" not in str(exc_info.value)


def test_load_expected_schema_returns_jsonschema_object() -> None:
    schema = load_expected_schema(BASE_PATH / "expected_schema.json")

    assert schema["type"] == "object"
    assert schema["properties"]["kpi_id"]["const"] == "AC-KPI-05"
    assert schema["properties"]["metric_key"]["const"] == "cost_per_completed_task"
    assert "expected_aggregate" in schema["required"]


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


@pytest.mark.parametrize("bad_split", [None, 0, []])
def test_load_manifest_rejects_malformed_split_field(
    tmp_path: Path,
    bad_split: Any,
) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry["split"] = bad_split

    with pytest.raises(ValueError, match="split must be a string"):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


def test_load_manifest_rejects_unknown_split_value(tmp_path: Path) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry["split"] = "deprecated"

    with pytest.raises(ValueError, match="split must be one of"):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


@pytest.mark.parametrize("bad_entry", ["string", 123, [1, 2]])
def test_load_manifest_rejects_non_object_entry(
    tmp_path: Path,
    bad_entry: Any,
) -> None:
    fixture_id, _entry = _sample_public_immutable_index_entry()

    with pytest.raises(ValueError, match="must be an object"):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: bad_entry})


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
    entry["assertions"] = [{"name": "x"}]

    with pytest.raises(ValueError, match=re.escape("has unknown keys ['assertions']")):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


def test_load_manifest_rejects_index_entry_missing_required_key(tmp_path: Path) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry.pop("created_at")

    with pytest.raises(ValueError, match=re.escape("missing required keys ['created_at']")):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


@pytest.mark.parametrize(
    ("bad_created_at", "expected_message"),
    [
        ("2026/05/09", "created_at must match YYYY-MM-DD"),
        ("abc", "created_at must match YYYY-MM-DD"),
        (20260509, "created_at must be a string"),
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
    entry["created_at"] = "２０２６-０５-０９"

    with pytest.raises(ValueError, match="ASCII digits"):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


def test_load_manifest_rejects_invalid_calendar_day(tmp_path: Path) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry["created_at"] = "2026-02-30"

    with pytest.raises(ValueError, match="not a valid calendar date"):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


def test_load_public_regression_fixtures_reads_expected_values() -> None:
    fixtures = load_public_regression_fixtures(BASE_PATH)

    assert len(fixtures) == 1
    assert isinstance(fixtures[0], PublicFixture)
    assert fixtures[0].fixture_id == (
        "AC-KPI-05_ac-kpi-05-v2026.05.09-skeleton_cost_per_completed_task_minimal"
    )
    assert fixtures[0].fixture_kind == "public_regression"
    assert fixtures[0].kpi_id == "AC-KPI-05"
    assert fixtures[0].metric_key == "cost_per_completed_task"
    assert fixtures[0].expected_aggregate["total_completed_runs"] == 3
    assert fixtures[0].expected_aggregate["total_cost_usd"] == 0.6
    assert fixtures[0].expected_aggregate["cost_per_completed_task_usd"] == 0.2


def test_load_public_regression_fixtures_accepts_unmodified_registered_fixture() -> None:
    fixtures = load_public_regression_fixtures(BASE_PATH)
    manifest = load_manifest(BASE_PATH / "manifest.json")
    entry = manifest["fixture_immutable_index"][fixtures[0].fixture_id]

    assert len(fixtures) == 1
    assert entry["split"] == "public_regression"
    assert entry["sha256"] == "bd0bc62e0a9d3fa58d3db74491035cd7bfb082e3653ad052c347def8acce8853"


def test_aggregate_consistency_rejects_tampered_total_completed_runs(tmp_path: Path) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    fixture = _sample_public_fixture()
    fixture["expected_aggregate"]["total_completed_runs"] = 4
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="expected_aggregate.total_completed_runs mismatch"):
        load_public_regression_fixtures(base_path)


def test_aggregate_consistency_rejects_tampered_total_cost(tmp_path: Path) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    fixture = _sample_public_fixture()
    fixture["expected_aggregate"]["total_cost_usd"] = 1.0
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="expected_aggregate.total_cost_usd mismatch"):
        load_public_regression_fixtures(base_path)


def test_aggregate_consistency_rejects_tampered_cost_per_completed_task(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    fixture = _sample_public_fixture()
    fixture["expected_aggregate"]["cost_per_completed_task_usd"] = 0.3
    _write_public_case(base_path, fixture)

    with pytest.raises(
        ValueError,
        match="expected_aggregate.cost_per_completed_task_usd mismatch",
    ):
        load_public_regression_fixtures(base_path)


def test_aggregate_consistency_rejects_tampered_threshold_passed(tmp_path: Path) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    fixture = _sample_public_fixture()
    fixture["expected_aggregate"]["threshold_passed"] = False
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="expected_aggregate.threshold_passed mismatch"):
        load_public_regression_fixtures(base_path)


def test_aggregate_consistency_passes_for_canonical_sample() -> None:
    fixtures = load_public_regression_fixtures(BASE_PATH)

    assert fixtures[0].expected_aggregate == {
        "total_completed_runs": 3,
        "total_cost_usd": 0.6,
        "cost_per_completed_task_usd": 0.2,
        "threshold_usd": 0.5,
        "threshold_passed": True,
    }


def test_aggregate_consistency_excludes_failed_and_cancelled_statuses() -> None:
    fixture = _sample_public_fixture()
    fixture["input"]["sample_runs"].append(
        {
            "tenant_id": 1,
            "project_id": 99,
            "run_id": "00000000-0000-4000-8000-000000005998",
            "status": "failed",
            "cost_usd": 99,
            "tokens_input": 1,
            "tokens_output": 1,
        }
    )

    loaded = _load_public_fixture_direct(fixture)

    assert loaded.expected_aggregate["total_completed_runs"] == 3
    assert loaded.expected_aggregate["cost_per_completed_task_usd"] == 0.2


def test_prohibited_secret_metadata_keys_match_secret_refs_db_check() -> None:
    db_keys = _extract_db_secret_metadata_keys_from_migration()

    assert db_keys == _PROHIBITED_SECRET_METADATA_KEYS


def test_load_public_regression_fixtures_rejects_raw_secret_in_metadata(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    fixture = _sample_public_fixture()
    fixture["metadata"]["raw_secret"] = "leaked"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        load_public_regression_fixtures(base_path)

    assert "$.raw_secret" in str(exc_info.value)
    assert "leaked" not in str(exc_info.value)


def test_load_public_regression_fixtures_rejects_nested_api_key_in_metadata(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    fixture = _sample_public_fixture()
    fixture["metadata"]["wrapper"] = {"api_key": "leak"}
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        load_public_regression_fixtures(base_path)

    assert "$.wrapper.api_key" in str(exc_info.value)
    assert "leak" not in str(exc_info.value)


def test_load_public_regression_fixtures_rejects_raw_token_in_input(tmp_path: Path) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    fixture = _sample_public_fixture()
    fixture["input"]["raw_token"] = "leak"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        load_public_regression_fixtures(base_path)

    assert "$.raw_token" in str(exc_info.value)
    assert "leak" not in str(exc_info.value)


def test_load_redacted_fixtures_rejects_private_key_in_metadata(tmp_path: Path) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    leaked = _redacted_fixture("private_holdout")
    leaked["metadata"]["private_key"] = "leak"
    _write_redacted_case(base_path, "private_holdout", leaked)

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        load_redacted_fixtures(base_path, kind="private_holdout")

    assert "$.private_key" in str(exc_info.value)
    assert "leak" not in str(exc_info.value)


def test_load_redacted_fixtures_rejects_age_key_in_input(tmp_path: Path) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    leaked = _redacted_fixture("adversarial_new")
    leaked["input"]["age_key"] = "leak"
    _write_redacted_case(base_path, "adversarial_new", leaked)

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        load_redacted_fixtures(base_path, kind="adversarial_new")

    assert "$.age_key" in str(exc_info.value)
    assert "leak" not in str(exc_info.value)


def test_load_public_regression_fixtures_rejects_raw_secret_tuple_nested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    fixture = _sample_public_fixture()
    fixture["metadata"]["wrapper"] = ({"raw_secret": "tuple-secret-value"},)
    _write_public_case(base_path, fixture)
    original_read_json_object = cost_loader._read_json_object

    def fake_read_json_object(path: Path) -> dict[str, Any]:
        if path == base_path / "public_regression/sample.json":
            return fixture
        return original_read_json_object(path)

    monkeypatch.setattr(cost_loader, "_read_json_object", fake_read_json_object)

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        load_public_regression_fixtures(base_path)

    assert "$.wrapper[0].raw_secret" in str(exc_info.value)
    assert "tuple-secret-value" not in str(exc_info.value)


@pytest.mark.parametrize("pattern_kind", _RAW_SECRET_PATTERN_KINDS)
def test_load_public_regression_fixtures_rejects_raw_secret_value_pattern_in_metadata_notes(
    tmp_path: Path,
    pattern_kind: str,
) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    marker = _dummy_raw_secret_marker(pattern_kind)
    fixture = _sample_public_fixture()
    fixture["metadata"]["notes"] = "Synthetic note with marker " + marker
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match=re.escape(pattern_kind)) as exc_info:
        load_public_regression_fixtures(base_path)

    assert marker not in str(exc_info.value)


@pytest.mark.parametrize("pattern_kind", _RAW_SECRET_PATTERN_KINDS)
def test_load_redacted_fixtures_rejects_raw_secret_value_pattern_in_metadata_notes(
    tmp_path: Path,
    pattern_kind: str,
) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    marker = _dummy_raw_secret_marker(pattern_kind)
    leaked = _redacted_fixture("private_holdout")
    leaked["metadata"]["notes"] = "Synthetic note with marker " + marker
    _write_redacted_case(base_path, "private_holdout", leaked)

    with pytest.raises(ValueError, match=re.escape(pattern_kind)) as exc_info:
        load_redacted_fixtures(base_path, kind="private_holdout")

    assert marker not in str(exc_info.value)


def test_load_manifest_rejects_raw_secret_value_pattern(tmp_path: Path) -> None:
    marker = _dummy_raw_secret_marker("github_personal_token")
    manifest = _manifest()
    manifest["notes"] = "Synthetic manifest note " + marker
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="github_personal_token") as exc_info:
        load_manifest(manifest_path)

    assert marker not in str(exc_info.value)


def test_find_raw_secret_value_patterns_recursive_reports_path_without_value() -> None:
    marker = _dummy_raw_secret_marker("openai_api_key")
    leaks = _find_raw_secret_value_patterns_recursive({"metadata": {"notes": marker}})

    assert leaks == ["$.metadata.notes:openai_api_key"]
    assert marker not in repr(leaks)


def test_load_redacted_fixtures_rejects_expected_aggregate_leak(tmp_path: Path) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    leaked = _redacted_fixture("private_holdout")
    leaked["expected_aggregate"] = {"cost_per_completed_task_usd": 1}
    _write_redacted_case(base_path, "private_holdout", leaked)

    with pytest.raises(ValueError, match="expectation leak") as exc_info:
        load_redacted_fixtures(base_path, kind="private_holdout")

    assert "prohibited top-level keys ['expected_aggregate']" in str(exc_info.value)


def test_load_redacted_fixtures_rejects_unknown_top_level_key(tmp_path: Path) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    leaked = _redacted_fixture("private_holdout")
    leaked["oracle_decision"] = "block"
    _write_redacted_case(base_path, "private_holdout", leaked)

    with pytest.raises(ValueError, match="has unknown top-level keys") as exc_info:
        load_redacted_fixtures(base_path, kind="private_holdout")

    assert "oracle_decision" in str(exc_info.value)


def test_load_redacted_fixtures_rejects_nested_metadata_assertions(tmp_path: Path) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    leaked = _redacted_fixture("private_holdout")
    leaked["metadata"]["something"] = {"assertions": [{"name": "leak"}]}
    _write_redacted_case(base_path, "private_holdout", leaked)

    expected = "nested prohibited keys at ['$.metadata.something.assertions']"
    with pytest.raises(ValueError, match=re.escape(expected)):
        load_redacted_fixtures(base_path, kind="private_holdout")


@pytest.mark.parametrize("container_name", ["input", "metadata"])
@pytest.mark.parametrize("leak_key", _DERIVED_REDACTED_LEAK_KEYS)
def test_load_redacted_fixtures_rejects_derived_value_leak(
    tmp_path: Path,
    leak_key: str,
    container_name: str,
) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    leaked = _redacted_fixture("private_holdout")
    leaked[container_name]["nested"] = {leak_key: _derived_leak_value(leak_key)}
    _write_redacted_case(base_path, "private_holdout", leaked)

    with pytest.raises(ValueError, match=re.escape(leak_key)) as exc_info:
        load_redacted_fixtures(base_path, kind="private_holdout")

    assert "expectation leak" in str(exc_info.value)


def test_load_redacted_fixtures_accepts_redacted_private_holdout(tmp_path: Path) -> None:
    base_path = tmp_path / "cost_per_completed_task"
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
    assert not hasattr(fixtures[0], "expected_aggregate")
    assert not hasattr(fixtures[0], "assertions")


def test_load_redacted_fixtures_accepts_adversarial_new(tmp_path: Path) -> None:
    base_path = tmp_path / "cost_per_completed_task"
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


def test_load_public_regression_fixtures_rejects_top_level_extra_key(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    fixture = _sample_public_fixture()
    fixture["extra_key"] = "schema should reject this"
    _write_public_case(base_path, fixture)

    with pytest.raises(
        ValueError,
        match=r"fails expected_schema validation: path=.*additionalProperties",
    ):
        load_public_regression_fixtures(base_path)


def test_validate_fixture_error_does_not_leak_raw_value(tmp_path: Path) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    fixture = _sample_public_fixture()
    fixture["input"]["sample_runs"][0]["tokens_input"] = "secret-looking-value"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match=r"fails expected_schema validation: path=.*type") as exc:
        load_public_regression_fixtures(base_path)

    assert "secret-looking-value" not in str(exc.value)
    assert "validator=type" in str(exc.value)


def test_load_public_regression_fixtures_rejects_extra_file(tmp_path: Path) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    _write_manifest(base_path, public_expected_count=1)
    _write_expected_schema(base_path)
    _write_json(base_path / "public_regression/sample.json", _sample_public_fixture())

    extra = _sample_public_fixture()
    extra["fixture_id"] = "AC-KPI-05_ac-kpi-05-v2026.05.09-skeleton_extra_case"
    extra["case_key"] = "extra_case"
    _write_json(base_path / "public_regression/extra.json", extra)

    with pytest.raises(ValueError, match="expected 1 fixtures, found 2"):
        load_public_regression_fixtures(base_path)


def test_load_public_regression_fixtures_rejects_missing_file(tmp_path: Path) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    _write_manifest(base_path, public_expected_count=1)
    _write_expected_schema(base_path)

    with pytest.raises(ValueError, match="expected 1 fixtures, found 0"):
        load_public_regression_fixtures(base_path)


def test_load_public_regression_fixtures_rejects_missing_registered_index_entry(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    orphan_fixture_id = "AC-KPI-05_ac-kpi-05-v2026.05.09-skeleton_deleted_public_case"
    _write_manifest(
        base_path,
        public_expected_count=0,
        immutable_index={
            orphan_fixture_id: {
                "sha256": "0" * 64,
                "split": "public_regression",
                "created_at": "2026-05-09",
            },
        },
    )
    _write_expected_schema(base_path)

    with pytest.raises(ValueError, match="fixture_immutable_index has entries"):
        load_public_regression_fixtures(base_path)


def test_load_public_regression_fixtures_rejects_unregistered_fixture(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    fixture = _sample_public_fixture()
    fixture["fixture_id"] = "AC-KPI-05_ac-kpi-05-v2026.05.09-skeleton_unregistered_case"
    fixture["case_key"] = "unregistered_case"
    _write_manifest(base_path, public_expected_count=1)
    _write_expected_schema(base_path)
    _write_json(base_path / "public_regression/new.json", fixture)

    with pytest.raises(ValueError, match="not registered in manifest.fixture_immutable_index"):
        load_public_regression_fixtures(base_path)


def test_load_public_regression_fixtures_rejects_modified_fixture_content(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    fixture = _sample_public_fixture()
    fixture["case_key"] = "modified_cost_per_completed_task"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="content has been modified"):
        load_public_regression_fixtures(base_path)


def test_load_redacted_fixtures_skips_immutable_index_for_empty_split() -> None:
    private = load_redacted_fixtures(BASE_PATH, kind="private_holdout")
    adversarial = load_redacted_fixtures(BASE_PATH, kind="adversarial_new")

    assert private == []
    assert adversarial == []


def test_discover_fixtures_returns_three_splits_with_correct_types(tmp_path: Path) -> None:
    base_path = tmp_path / "cost_per_completed_task"
    _write_three_split_fixture_tree(base_path)

    discovered = discover_fixtures(base_path)

    assert set(discovered) == {"public_regression", "private_holdout", "adversarial_new"}
    assert len(discovered["public_regression"]) == 1
    assert len(discovered["private_holdout"]) == 1
    assert len(discovered["adversarial_new"]) == 1
    assert isinstance(discovered["public_regression"][0], PublicFixture)
    assert isinstance(discovered["private_holdout"][0], RedactedFixture)
    assert isinstance(discovered["adversarial_new"][0], RedactedFixture)


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
    drifted_fixture = replace(fixtures[0], dataset_version_id="ac-kpi-05-v2099.01.01-drift")

    with pytest.raises(ValueError, match="dataset_version_id mismatch"):
        assert_anti_gaming_invariants(manifest, [drifted_fixture])


def test_assert_anti_gaming_invariants_rejects_public_fixture_spoofed_as_private() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_public_fixture(
        dataset_version_id=manifest["dataset_version_id"],
        fixture_kind="private_holdout",
    )

    with pytest.raises(ValueError, match="PublicFixture .* spoofed fixture_kind"):
        assert_anti_gaming_invariants(manifest, [fixture])


def test_assert_anti_gaming_invariants_rejects_redacted_fixture_spoofed_as_public() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_redacted_fixture(
        dataset_version_id=manifest["dataset_version_id"],
        fixture_kind="public_regression",
    )

    with pytest.raises(ValueError, match="RedactedFixture .* spoofed fixture_kind"):
        assert_anti_gaming_invariants(manifest, [fixture])


def test_assert_anti_gaming_invariants_rejects_unsupported_fixture_type() -> None:
    class FakeFixture:
        pass

    manifest = load_manifest(BASE_PATH / "manifest.json")

    with pytest.raises(TypeError, match="unsupported fixture type FakeFixture"):
        assert_anti_gaming_invariants(manifest, cast(Any, [FakeFixture()]))


def test_assert_anti_gaming_invariants_rejects_redacted_fixture_with_expectation_leak() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_redacted_fixture(dataset_version_id=manifest["dataset_version_id"])
    replaced_fixture = replace(
        fixture,
        metadata={"created_at": "2026-05-09", "expected_aggregate": {"median_ms": 1}},
    )

    with pytest.raises(ValueError, match="contains expectation leak in attributes") as exc:
        assert_anti_gaming_invariants(manifest, [replaced_fixture])

    assert "$.metadata.expected_aggregate" in str(exc.value)


def test_assert_anti_gaming_invariants_rejects_redacted_fixture_with_tuple_leak() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_redacted_fixture(
        dataset_version_id=manifest["dataset_version_id"],
        metadata={"created_at": "2026-05-09", "wrapper": ({"assertions": []},)},
    )

    with pytest.raises(ValueError, match="contains expectation leak in attributes") as exc:
        assert_anti_gaming_invariants(manifest, [fixture])

    assert "$.metadata.wrapper[0].assertions" in str(exc.value)


def test_assert_anti_gaming_invariants_rejects_redacted_fixture_with_set_value() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_redacted_fixture(
        dataset_version_id=manifest["dataset_version_id"],
        metadata={"created_at": "2026-05-09", "strange": {"a", "b"}},
    )

    expected = "unsupported value type set at $.metadata.strange"
    with pytest.raises(TypeError, match=re.escape(expected)):
        assert_anti_gaming_invariants(manifest, [fixture])


def test_find_prohibited_keys_recursive_rejects_non_string_dict_key() -> None:
    with pytest.raises(TypeError, match="unsupported dict key type int"):
        _find_prohibited_keys_recursive({1: "x"}, _PROHIBITED_REDACTED_KEYS)


def test_find_prohibited_keys_recursive_clean_tuple_passes() -> None:
    leaks = _find_prohibited_keys_recursive({"x": (1, 2, "y")}, _PROHIBITED_REDACTED_KEYS)

    assert leaks == []


def test_find_prohibited_keys_recursive_nested_tuple_with_dict_detects() -> None:
    leaks = _find_prohibited_keys_recursive(
        {"a": {"b": ({"expected_aggregate": {"cost_per_completed_task_usd": 1}},)}},
        _PROHIBITED_REDACTED_KEYS,
    )

    assert leaks == ["$.a.b[0].expected_aggregate"]


def test_assert_anti_gaming_invariants_accepts_clean_redacted_fixture() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_redacted_fixture(dataset_version_id=manifest["dataset_version_id"])

    assert_anti_gaming_invariants(manifest, [fixture])

    assert fixture.fixture_kind == "private_holdout"
    assert "expected_aggregate" not in fixture.metadata
    assert "assertions" not in fixture.input

