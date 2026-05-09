from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

import eval.quality.citation_coverage.loader as citation_loader
from eval.quality.citation_coverage.loader import (
    _PROHIBITED_REDACTED_KEYS,
    _PROHIBITED_SECRET_METADATA_KEYS,
    PublicFixture,
    RedactedFixture,
    _canonical_fixture_hash,
    _compute_expected_aggregate,
    _find_prohibited_keys_recursive,
    _read_json_object,
    _resolve_expected_schema_path,
    _resolve_split_dir,
    _validate_aggregate_consistency,
    assert_anti_gaming_invariants,
    discover_fixtures,
    load_expected_schema,
    load_manifest,
    load_public_regression_fixtures,
    load_redacted_fixtures,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = _REPO_ROOT / "eval/quality/citation_coverage"
_REQUIRED_COMMON_RULES = (
    "private_holdout_expectations_not_used_for_tuning",
    "monthly_refresh_append_only",
    "separate_fixture_and_policy_or_prompt_commits",
    "persist_fixture_id_and_dataset_version",
    "avoid_private_expectation_leakage",
    "adversarial_new_append_only",
)


def _make_dummy_openai_token() -> str:
    """Synthetic OpenAI-shaped token; assembled to avoid repo scanner false positives."""

    return "sk-" + "X" * 28


def _make_dummy_anthropic_token() -> str:
    """Synthetic Anthropic-shaped token; assembled to avoid repo scanner false positives."""

    return "sk-" + "ant-" + "X" * 24


def _make_dummy_github_installation_token() -> str:
    return "ghs_" + "X" * 28


def _make_dummy_github_oauth_token() -> str:
    return "gho_" + "X" * 28


def _make_dummy_github_personal_token() -> str:
    return "ghp_" + "X" * 28


def _make_dummy_tailscale_auth_key() -> str:
    return "tskey-" + "a" * 16 + "-" + "b" * 16


def _make_dummy_age_private_key() -> str:
    return "AGE-SECRET-KEY-1" + "A" * 52


def _make_dummy_pem_header() -> str:
    """Synthetic PEM-shaped header; assembled to avoid repo scanner false positives."""

    return "-".join(["", "----BEGIN RSA PRIVATE KEY", "----"])


_RAW_SECRET_PATTERN_SAMPLES = (
    _make_dummy_openai_token(),
    _make_dummy_anthropic_token(),
    _make_dummy_github_installation_token(),
    _make_dummy_github_oauth_token(),
    _make_dummy_github_personal_token(),
    _make_dummy_tailscale_auth_key(),
    _make_dummy_age_private_key(),
    _make_dummy_pem_header(),
)


def _sample_public_fixture() -> dict[str, Any]:
    return json.loads((BASE_PATH / "public_regression/sample.json").read_text(encoding="utf-8"))


def _manifest() -> dict[str, Any]:
    return json.loads((BASE_PATH / "manifest.json").read_text(encoding="utf-8"))


def _redacted_fixture(kind: str) -> dict[str, Any]:
    return {
        "fixture_id": f"AC-KPI-04_v2026.05.09-skeleton_{kind}_redacted_case",
        "dataset_version_id": "v2026.05.09-skeleton",
        "fixture_kind": kind,
        "kpi_id": "AC-KPI-04",
        "metric_key": "citation_coverage",
        "case_key": f"{kind}_redacted_case",
        "input": {
            "evidence_set_hash": "0d5f2c6c3b750c9c2cf23f5e8af58c4f7f4a7d1b2cdb3d1f1a3f1d1cf87f4d13",
            "dataset_version": "v2026.05.09-skeleton",
            "sample_claims": [
                {
                    "claim_id": "claim-redacted",
                    "claim_text": "Redacted citation coverage fixture.",
                    "evidence_ids": ["ev-redacted"],
                    "citation_ids": [],
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
            "notes": "Synthetic redacted citation coverage fixture without expected values.",
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _immutable_index(fixtures: list[tuple[str, dict[str, Any]]]) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for split, fixture in fixtures:
        created_at = "2026-05-09"
        metadata = fixture.get("metadata")
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
    _write_manifest(
        base_path,
        public_expected_count=1,
        immutable_index=_immutable_index([("public_regression", fixture)]),
    )
    _write_expected_schema(base_path)
    _write_json(base_path / "public_regression/sample.json", fixture)


def _write_redacted_case(base_path: Path, kind: str, fixture: dict[str, Any]) -> None:
    _write_manifest(
        base_path,
        private_expected_count=1 if kind == "private_holdout" else 0,
        adversarial_expected_count=1 if kind == "adversarial_new" else 0,
        immutable_index=_immutable_index([(kind, fixture)]),
    )
    _write_json(base_path / f"{kind}/redacted.json", fixture)


def _manifest_with_split_path(kind: str, path: str) -> dict[str, Any]:
    manifest = _manifest()
    manifest["splits"][kind]["path"] = path
    return manifest


def _manifest_with_expected_schema(path: str) -> dict[str, Any]:
    manifest = _manifest()
    manifest["expected_schema"] = path
    return manifest


def _direct_public_fixture(
    *,
    dataset_version_id: str,
    fixture_kind: Any = "public_regression",
    input_payload: dict[str, Any] | None = None,
) -> PublicFixture:
    raw = _sample_public_fixture()
    return PublicFixture(
        fixture_id=raw["fixture_id"],
        dataset_version_id=dataset_version_id,
        fixture_kind=cast(Any, fixture_kind),
        kpi_id="AC-KPI-04",
        metric_key="citation_coverage",
        case_key=raw["case_key"],
        input=input_payload if input_payload is not None else raw["input"],
        expected_aggregate=raw["expected_aggregate"],
        threshold=raw["threshold"],
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
        kpi_id="AC-KPI-04",
        metric_key="citation_coverage",
        case_key=raw["case_key"],
        input=input_payload if input_payload is not None else raw["input"],
        anti_gaming=raw["anti_gaming"],
        metadata=metadata if metadata is not None else raw["metadata"],
    )


def _load_public_fixture_direct(fixture: dict[str, Any]) -> PublicFixture:
    return citation_loader._public_fixture_from_data(
        fixture,
        source_path=Path("sample.json"),
        dataset_version_id=fixture["dataset_version_id"],
    )


def test_existing_sample_passes_strict_json_parse() -> None:
    data = _read_json_object(BASE_PATH / "public_regression/sample.json")

    assert data["fixture_id"] == "AC-KPI-04_v2026.05.09-skeleton_citation_coverage_minimal"
    assert data["metadata"]["created_at"] == "2026-05-09"


def test_load_manifest_normalizes_ac_kpi_04_metric() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")

    assert manifest["kpi_id"] == "AC-KPI-04"
    assert manifest["metric_key"] == "citation_coverage"
    assert manifest["dataset_version_id"] == "v2026.05.09-skeleton"
    assert manifest["threshold"]["value"] == 0.9


def test_load_manifest_accepts_threshold_field() -> None:
    manifest = load_manifest(_REPO_ROOT / "eval/quality/citation_coverage/manifest.json")

    assert manifest["threshold"]["value"] == 0.9


def test_load_expected_schema_returns_jsonschema_object() -> None:
    schema = load_expected_schema(BASE_PATH / "expected_schema.json")

    assert schema["type"] == "object"
    assert schema["properties"]["kpi_id"]["const"] == "AC-KPI-04"
    assert "expected_aggregate" in schema["required"]


def test_load_public_regression_fixtures_loads_one_public_fixture() -> None:
    fixtures = load_public_regression_fixtures(BASE_PATH)

    assert len(fixtures) == 1
    assert fixtures[0].fixture_kind == "public_regression"
    assert fixtures[0].expected_aggregate["coverage_ratio"] == 0.6


def test_discover_fixtures_has_all_three_splits() -> None:
    discovered = discover_fixtures(BASE_PATH)

    assert set(discovered) == {"public_regression", "private_holdout", "adversarial_new"}
    assert len(discovered["public_regression"]) == 1
    assert discovered["private_holdout"] == []
    assert discovered["adversarial_new"] == []


def test_compute_expected_aggregate_recomputes_minimal_sample() -> None:
    sample_claims = _sample_public_fixture()["input"]["sample_claims"]

    assert _compute_expected_aggregate(sample_claims) == {
        "total_claims": 5,
        "claims_with_citation": 3,
        "coverage_ratio": 0.6,
    }


def test_compute_expected_aggregate_handles_empty_claim_list() -> None:
    assert _compute_expected_aggregate([]) == {
        "total_claims": 0,
        "claims_with_citation": 0,
        "coverage_ratio": 0.0,
    }


def test_compute_expected_aggregate_rejects_non_object_claim() -> None:
    with pytest.raises(ValueError, match="sample_claims\\[0\\] must be a JSON object"):
        _compute_expected_aggregate(cast(Any, ["bad"]))


def test_read_json_object_rejects_duplicate_top_level_key(tmp_path: Path) -> None:
    fake_fixture = tmp_path / "fake_fixture.json"
    fake_fixture.write_text('{"fixture_id": "a", "fixture_id": "b"}', encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate JSON object key 'fixture_id'"):
        _read_json_object(fake_fixture)


def test_read_json_object_rejects_duplicate_nested_key(tmp_path: Path) -> None:
    fake_fixture = tmp_path / "fake_fixture.json"
    fake_fixture.write_text('{"expected_aggregate": {"total_claims": 1, "total_claims": 2}}', encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate JSON object key 'total_claims'"):
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


@pytest.mark.parametrize("path", ["/etc/passwd", "../expected_schema.json", "schema.json", "nested/expected_schema.json"])
def test_resolve_expected_schema_path_rejects_noncanonical_paths(
    tmp_path: Path,
    path: str,
) -> None:
    manifest = _manifest_with_expected_schema(path)

    with pytest.raises(ValueError):
        _resolve_expected_schema_path(tmp_path, manifest)


@pytest.mark.parametrize(
    ("kind", "path"),
    [
        ("public_regression", "/tmp/public_regression"),
        ("public_regression", "../public_regression"),
        ("public_regression", "public"),
        ("private_holdout", "public_regression"),
        ("adversarial_new", ""),
    ],
)
def test_resolve_split_dir_rejects_bad_split_paths(
    tmp_path: Path,
    kind: str,
    path: str,
) -> None:
    manifest = _manifest_with_split_path(kind, path)

    with pytest.raises(ValueError):
        _resolve_split_dir(tmp_path, kind, manifest)


def test_resolve_split_dir_rejects_unknown_kind(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown split kind"):
        _resolve_split_dir(tmp_path, "unknown", _manifest())


def test_manifest_rejects_unknown_immutable_index_key(tmp_path: Path) -> None:
    manifest = _manifest()
    fixture_id, entry = next(iter(manifest["fixture_immutable_index"].items()))
    entry["unexpected"] = "nope"
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="has unknown keys"):
        load_manifest(manifest_path)


def test_manifest_rejects_missing_immutable_index_key(tmp_path: Path) -> None:
    manifest = _manifest()
    fixture_id, entry = next(iter(manifest["fixture_immutable_index"].items()))
    del entry["sha256"]
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="is missing required keys"):
        load_manifest(manifest_path)


def test_manifest_rejects_invalid_calendar_date(tmp_path: Path) -> None:
    manifest = _manifest()
    fixture_id, entry = next(iter(manifest["fixture_immutable_index"].items()))
    entry["created_at"] = "2026-02-31"
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="not a valid calendar date"):
        load_manifest(manifest_path)


def test_manifest_rejects_non_ascii_date_format(tmp_path: Path) -> None:
    manifest = _manifest()
    fixture_id, entry = next(iter(manifest["fixture_immutable_index"].items()))
    entry["created_at"] = "２０２６-０５-０９"
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="ASCII digits"):
        load_manifest(manifest_path)


def test_public_fixture_rejects_dataset_version_mismatch(tmp_path: Path) -> None:
    fixture = _sample_public_fixture()
    fixture["dataset_version_id"] = "v2026.05.10-skeleton"
    base_path = tmp_path / "citation_coverage"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="dataset_version_id mismatch"):
        load_public_regression_fixtures(base_path)


def test_public_fixture_rejects_missing_immutable_index_registration(tmp_path: Path) -> None:
    fixture = _sample_public_fixture()
    base_path = tmp_path / "citation_coverage"
    _write_manifest(base_path, immutable_index={})
    _write_expected_schema(base_path)
    _write_json(base_path / "public_regression/sample.json", fixture)

    with pytest.raises(ValueError, match="not registered"):
        load_public_regression_fixtures(base_path)


def test_public_fixture_rejects_modified_content_after_registration(tmp_path: Path) -> None:
    fixture = _sample_public_fixture()
    base_path = tmp_path / "citation_coverage"
    _write_public_case(base_path, fixture)
    fixture["case_key"] = "modified_after_hash"
    _write_json(base_path / "public_regression/sample.json", fixture)

    with pytest.raises(ValueError, match="sha256 mismatch"):
        load_public_regression_fixtures(base_path)


def test_public_fixture_rejects_split_expected_count_mismatch(tmp_path: Path) -> None:
    fixture = _sample_public_fixture()
    base_path = tmp_path / "citation_coverage"
    _write_manifest(
        base_path,
        public_expected_count=2,
        immutable_index=_immutable_index([("public_regression", fixture)]),
    )
    _write_expected_schema(base_path)
    _write_json(base_path / "public_regression/sample.json", fixture)

    with pytest.raises(ValueError, match="expected 2 fixtures, found 1"):
        load_public_regression_fixtures(base_path)


def test_public_fixture_rejects_unknown_top_level_key(tmp_path: Path) -> None:
    fixture = _sample_public_fixture()
    fixture["unexpected"] = True
    base_path = tmp_path / "citation_coverage"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="unknown top-level keys"):
        load_public_regression_fixtures(base_path)


@pytest.mark.parametrize("field", ["total_claims", "claims_with_citation", "coverage_ratio"])
def test_validate_aggregate_consistency_rejects_tampered_expected_aggregate(
    tmp_path: Path,
    field: str,
) -> None:
    fixture = _sample_public_fixture()
    if field == "coverage_ratio":
        fixture["expected_aggregate"][field] = 0.8
    else:
        fixture["expected_aggregate"][field] += 1
    base_path = tmp_path / "citation_coverage"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match=f"expected_aggregate.{field} mismatch"):
        load_public_regression_fixtures(base_path)


def test_validate_aggregate_consistency_direct_rejects_ratio_drift() -> None:
    raw = _sample_public_fixture()
    fixture = _load_public_fixture_direct(raw)
    tampered = replace(fixture, expected_aggregate={**fixture.expected_aggregate, "coverage_ratio": 0.6015})

    with pytest.raises(ValueError, match="coverage_ratio mismatch"):
        _validate_aggregate_consistency(tampered, Path("sample.json"))


@pytest.mark.parametrize(
    "bad_hash",
    [
        "abc",
        "0d5f2c6c3b750c9c2cf23f5e8af58c4f7f4a7d1b2cdb3d1f1a3f1d1cf87f4d1z",
        "0D5F2C6C3B750C9C2CF23F5E8AF58C4F7F4A7D1B2CDB3D1F1A3F1D1CF87F4D13",
        "",
    ],
)
def test_evidence_set_hash_must_be_64_lowercase_hex(tmp_path: Path, bad_hash: str) -> None:
    fixture = _sample_public_fixture()
    fixture["input"]["evidence_set_hash"] = bad_hash
    base_path = tmp_path / "citation_coverage"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="evidence_set_hash"):
        load_public_regression_fixtures(base_path)


@pytest.mark.parametrize("key", sorted(_PROHIBITED_SECRET_METADATA_KEYS))
def test_public_fixture_rejects_raw_secret_keys_in_claim(
    tmp_path: Path,
    key: str,
) -> None:
    fixture = _sample_public_fixture()
    fixture["input"]["sample_claims"][0][key] = "do-not-echo-this-value"
    base_path = tmp_path / "citation_coverage"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        load_public_regression_fixtures(base_path)

    assert key in str(exc_info.value)
    assert "do-not-echo-this-value" not in str(exc_info.value)


@pytest.mark.parametrize("raw_value", _RAW_SECRET_PATTERN_SAMPLES)
def test_public_fixture_rejects_raw_secret_value_patterns_without_echo(
    tmp_path: Path,
    raw_value: str,
) -> None:
    fixture = _sample_public_fixture()
    fixture["input"]["sample_claims"][0]["claim_text"] = raw_value
    base_path = tmp_path / "citation_coverage"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="contains raw secret value patterns") as exc_info:
        load_public_regression_fixtures(base_path)

    assert raw_value not in str(exc_info.value)


@pytest.mark.parametrize("key", sorted(_PROHIBITED_REDACTED_KEYS))
def test_redacted_fixture_rejects_expectation_leak_keys(
    tmp_path: Path,
    key: str,
) -> None:
    fixture = _redacted_fixture("private_holdout")
    fixture[key] = {"leak": True} if key == "expected_aggregate" else "leak"
    base_path = tmp_path / "citation_coverage"
    _write_redacted_case(base_path, "private_holdout", fixture)

    with pytest.raises(ValueError, match="expectation leak"):
        load_redacted_fixtures(base_path, kind="private_holdout")


def test_load_manifest_rejects_threshold_in_redacted_fixture_body(tmp_path: Path) -> None:
    fixture = _redacted_fixture("private_holdout")
    fixture["input"]["threshold"] = {"operator": ">=", "value": 0.9}
    base_path = tmp_path / "citation_coverage"
    _write_redacted_case(base_path, "private_holdout", fixture)

    with pytest.raises(ValueError, match="expectation leak"):
        load_redacted_fixtures(base_path, kind="private_holdout")


def test_redacted_fixture_rejects_nested_expectation_leak(tmp_path: Path) -> None:
    fixture = _redacted_fixture("adversarial_new")
    fixture["metadata"]["nested"] = {"expected_aggregate": {"coverage_ratio": 0.9}}
    base_path = tmp_path / "citation_coverage"
    _write_redacted_case(base_path, "adversarial_new", fixture)

    with pytest.raises(ValueError, match="nested prohibited keys"):
        load_redacted_fixtures(base_path, kind="adversarial_new")


def test_redacted_fixture_rejects_unknown_top_level_key(tmp_path: Path) -> None:
    fixture = _redacted_fixture("private_holdout")
    fixture["unexpected"] = True
    base_path = tmp_path / "citation_coverage"
    _write_redacted_case(base_path, "private_holdout", fixture)

    with pytest.raises(ValueError, match="unknown top-level keys"):
        load_redacted_fixtures(base_path, kind="private_holdout")


def test_redacted_fixture_rejects_fixture_kind_spoof(tmp_path: Path) -> None:
    fixture = _redacted_fixture("private_holdout")
    fixture["fixture_kind"] = "adversarial_new"
    base_path = tmp_path / "citation_coverage"
    _write_redacted_case(base_path, "private_holdout", fixture)

    with pytest.raises(ValueError, match="does not match split"):
        load_redacted_fixtures(base_path, kind="private_holdout")


@pytest.mark.parametrize("rule_name", _REQUIRED_COMMON_RULES)
def test_manifest_requires_all_six_common_anti_gaming_rules(
    tmp_path: Path,
    rule_name: str,
) -> None:
    fixture = _sample_public_fixture()
    base_path = tmp_path / "citation_coverage"
    _write_public_case(base_path, fixture)
    manifest = json.loads((base_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["anti_gaming_rules"]["common"][rule_name] = False
    _write_json(base_path / "manifest.json", manifest)

    with pytest.raises(ValueError, match=f"anti-gaming rule violation: {rule_name}"):
        load_public_regression_fixtures(base_path)


def test_assert_anti_gaming_rejects_public_fixture_spoof() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_public_fixture(
        dataset_version_id=manifest["dataset_version_id"],
        fixture_kind="private_holdout",
    )

    with pytest.raises(ValueError, match="PublicFixture .* spoofed fixture_kind"):
        assert_anti_gaming_invariants(manifest, [fixture])


def test_assert_anti_gaming_rejects_redacted_fixture_spoof() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_redacted_fixture(
        dataset_version_id=manifest["dataset_version_id"],
        fixture_kind="public_regression",
    )

    with pytest.raises(ValueError, match="RedactedFixture .* spoofed fixture_kind"):
        assert_anti_gaming_invariants(manifest, [fixture])


def test_assert_anti_gaming_rejects_dataset_version_drift() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_public_fixture(dataset_version_id="v2026.05.10-skeleton")

    with pytest.raises(ValueError, match="dataset_version_id mismatch"):
        assert_anti_gaming_invariants(manifest, [fixture])


def test_assert_anti_gaming_rejects_constructed_redacted_leak() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_redacted_fixture(
        dataset_version_id=manifest["dataset_version_id"],
        metadata={"created_at": "2026-05-09", "nested": {"threshold": {"value": 0.9}}},
    )

    with pytest.raises(ValueError, match="expectation leak in attributes"):
        assert_anti_gaming_invariants(manifest, [fixture])


def test_assert_anti_gaming_rejects_tuple_non_string_key() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = replace(
        _direct_public_fixture(dataset_version_id=manifest["dataset_version_id"]),
        input={("tuple",): "bad"},
    )

    with pytest.raises(TypeError, match="unsupported dict key type tuple"):
        assert_anti_gaming_invariants(manifest, [fixture])


def test_find_prohibited_keys_recursive_rejects_non_json_value_type() -> None:
    with pytest.raises(TypeError, match="unsupported value type object"):
        _find_prohibited_keys_recursive({"wrapper": object()}, _PROHIBITED_SECRET_METADATA_KEYS)


def test_load_redacted_private_and_adversarial_fixtures(tmp_path: Path) -> None:
    base_path = tmp_path / "citation_coverage"
    private = _redacted_fixture("private_holdout")
    adversarial = _redacted_fixture("adversarial_new")
    _write_manifest(
        base_path,
        private_expected_count=1,
        adversarial_expected_count=1,
        public_expected_count=0,
        immutable_index=_immutable_index(
            [("private_holdout", private), ("adversarial_new", adversarial)]
        ),
    )
    _write_json(base_path / "private_holdout/redacted.json", private)
    _write_json(base_path / "adversarial_new/redacted.json", adversarial)

    private_loaded = load_redacted_fixtures(base_path, kind="private_holdout")
    adversarial_loaded = load_redacted_fixtures(base_path, kind="adversarial_new")

    assert private_loaded[0].fixture_kind == "private_holdout"
    assert adversarial_loaded[0].fixture_kind == "adversarial_new"


def test_manifest_rejects_threshold_drift(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["threshold"]["value"] = 0.8
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="threshold.value must be 0.9"):
        load_manifest(manifest_path)


def test_public_fixture_rejects_threshold_operator_drift(tmp_path: Path) -> None:
    fixture = _sample_public_fixture()
    fixture["threshold"]["operator"] = ">"
    base_path = tmp_path / "citation_coverage"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="threshold.operator"):
        load_public_regression_fixtures(base_path)
