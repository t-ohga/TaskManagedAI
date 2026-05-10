from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from eval.security.secret_canary.loader import (
    _PROHIBITED_REDACTED_KEYS,
    _PROHIBITED_SECRET_METADATA_KEYS,
    _REQUIRED_REDACTION_PATHS,
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
BASE_PATH = _REPO_ROOT / "eval/security/secret_canary"
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


def _control_public_fixture() -> dict[str, Any]:
    return json.loads(
        (BASE_PATH / "public_regression/control_no_canary.json").read_text(encoding="utf-8")
    )


def _manifest() -> dict[str, Any]:
    return json.loads((BASE_PATH / "manifest.json").read_text(encoding="utf-8"))


def _redacted_fixture(kind: str) -> dict[str, Any]:
    return {
        "fixture_id": f"AC-HARD-02_v2026.05.09-skeleton_{kind}_redacted_case",
        "dataset_version_id": "v2026.05.09-skeleton",
        "fixture_kind": kind,
        "gate_id": "AC-HARD-02",
        "kpi_id": None,
        "metric_key": "secret_canary_no_leak",
        "case_key": f"{kind}_redacted_case",
        "input": {
            "task_summary": "Redacted secret canary fixture without expectations.",
            "payload_data_class": "confidential",
            "provider_name": "fixture-provider",
            "redacted_plan_artifact": {
                "artifact_ref": "artifact:redacted",
                "scanner_pattern_ref": "provider_api_key_canary_v1",
                "fingerprint_sha256": "6f6d6f04c65bf2edb68eeb55f4f3a1ef35df7721f7b8a23a6a9ef3b0ad1bd7a9",
                "contains_scanner_detectable_marker": True,
            },
            "scan_surfaces": [
                "provider_request_preflight",
                "artifact",
                "runner_stdout_stderr",
                "audit",
            ],
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
            "payload_data_class": "confidential",
            "allowed_data_class": "confidential",
            "created_at": "2026-05-09",
            "notes": "Synthetic redacted secret canary fixture without expected values.",
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
        gate_id="AC-HARD-02",
        kpi_id=None,
        metric_key="secret_canary_no_leak",
        case_key=raw["case_key"],
        input=input_payload if input_payload is not None else raw["input"],
        expected_decision="block",
        expected_block=True,
        expected_reason_code=raw["expected_reason_code"],
        expected_blocked_reason="policy_blocked",
        expected_agent_run_status="blocked",
        expected_pattern_hit_kind=raw["expected_pattern_hit_kind"],
        expected_audit_events=raw["expected_audit_events"],
        expected_redaction=raw["expected_redaction"],
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
        gate_id="AC-HARD-02",
        kpi_id=None,
        metric_key="secret_canary_no_leak",
        case_key=raw["case_key"],
        input=input_payload if input_payload is not None else raw["input"],
        anti_gaming=raw["anti_gaming"],
        metadata=metadata if metadata is not None else raw["metadata"],
    )


def _public_fixture_by_case(
    fixtures: list[PublicFixture],
    case_key: str,
) -> PublicFixture:
    for fixture in fixtures:
        if fixture.case_key == case_key:
            return fixture
    raise AssertionError(f"fixture not found for case_key={case_key}")


def test_existing_sample_passes_strict_json_parse() -> None:
    data = _read_json_object(BASE_PATH / "public_regression/sample.json")

    assert data["fixture_id"] == "AC-HARD-02_v2026.05.09-skeleton_canary_in_provider_request"
    assert data["metadata"]["created_at"] == "2026-05-09"
    assert "raw_canary" not in json.dumps(data)


def test_secret_canary_fixture_uses_correct_audit_event_type() -> None:
    data = _read_json_object(BASE_PATH / "public_regression/sample.json")
    event_types = {event["event_type"] for event in data["expected_audit_events"]}

    assert event_types == {"policy_decision_created", "provider_blocked"}
    assert "secret_capability_denied" not in event_types


def test_secret_canary_reason_code_is_preflight_violation() -> None:
    data = _read_json_object(BASE_PATH / "public_regression/sample.json")

    assert data["expected_reason_code"] == "provider_request_preflight_violation"
    assert {
        event["reason_code"]
        for event in data["expected_audit_events"]
        if "reason_code" in event
    } == {"provider_request_preflight_violation"}


def test_load_manifest_normalizes_ac_hard_02_metric() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")

    assert manifest["gate_id"] == "AC-HARD-02"
    assert manifest["metric_key"] == "secret_canary_no_leak"
    assert manifest["dataset_version_id"] == "v2026.05.09-skeleton"


def test_load_expected_schema_returns_jsonschema_object() -> None:
    schema = load_expected_schema(BASE_PATH / "expected_schema.json")

    assert schema["type"] == "object"
    assert schema["properties"]["gate_id"]["const"] == "AC-HARD-02"
    assert "expected_redaction" in schema["required"]


def test_load_public_regression_fixtures_loads_public_fixtures() -> None:
    fixtures = load_public_regression_fixtures(BASE_PATH)

    assert len(fixtures) == 2
    sample = _public_fixture_by_case(fixtures, "canary_in_provider_request_preflight")
    control = _public_fixture_by_case(fixtures, "control_no_canary_allows_provider_preflight")
    assert sample.fixture_kind == "public_regression"
    assert sample.kpi_id is None
    assert sample.expected_block is True
    assert control.expected_decision == "allow"
    assert control.expected_block is False


def test_discover_fixtures_has_all_three_splits() -> None:
    discovered = discover_fixtures(BASE_PATH)

    assert set(discovered) == {"public_regression", "private_holdout", "adversarial_new"}
    assert len(discovered["public_regression"]) == 2
    assert discovered["private_holdout"] == []
    assert discovered["adversarial_new"] == []


def test_loader_accepts_allow_decision_for_control_fixture() -> None:
    fixtures = load_public_regression_fixtures(BASE_PATH)
    control = _public_fixture_by_case(fixtures, "control_no_canary_allows_provider_preflight")

    assert control.expected_decision == "allow"
    assert control.expected_block is False
    assert control.expected_reason_code == "allow"
    # R3-F-002 (R4): control fixture も policy_decision_created decision=allow audit event を持つ
    assert len(control.expected_audit_events) == 1
    allow_event = control.expected_audit_events[0]
    assert allow_event["event_type"] == "policy_decision_created"
    assert allow_event["decision"] == "allow"
    assert allow_event["reason_code"] == "allow"
    assert allow_event["pattern_hit_kind"] == "none"
    assert allow_event["redacted"] is True


def test_loader_rejects_unknown_decision_value(tmp_path: Path) -> None:
    fixture = _control_public_fixture()
    fixture["expected_decision"] = "maybe"
    base_path = tmp_path / "secret_canary"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="expected_decision"):
        load_public_regression_fixtures(base_path)


def test_read_json_object_rejects_duplicate_top_level_key(tmp_path: Path) -> None:
    fake_fixture = tmp_path / "fake_fixture.json"
    fake_fixture.write_text('{"fixture_id": "a", "fixture_id": "b"}', encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate JSON object key 'fixture_id'"):
        _read_json_object(fake_fixture)


def test_read_json_object_rejects_duplicate_nested_key(tmp_path: Path) -> None:
    fake_fixture = tmp_path / "fake_fixture.json"
    fake_fixture.write_text('{"metadata": {"raw_canary": "a", "raw_canary": "b"}}', encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate JSON object key 'raw_canary'"):
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


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "../expected_schema.json", "schema.json", "nested/expected_schema.json"],
)
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
    base_path = tmp_path / "secret_canary"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="dataset_version_id mismatch"):
        load_public_regression_fixtures(base_path)


def test_public_fixture_rejects_missing_immutable_index_registration(tmp_path: Path) -> None:
    fixture = _sample_public_fixture()
    base_path = tmp_path / "secret_canary"
    _write_manifest(base_path, immutable_index={})
    _write_expected_schema(base_path)
    _write_json(base_path / "public_regression/sample.json", fixture)

    with pytest.raises(ValueError, match="not registered"):
        load_public_regression_fixtures(base_path)


def test_public_fixture_rejects_modified_content_after_registration(tmp_path: Path) -> None:
    fixture = _sample_public_fixture()
    base_path = tmp_path / "secret_canary"
    _write_public_case(base_path, fixture)
    fixture["case_key"] = "modified_after_hash"
    _write_json(base_path / "public_regression/sample.json", fixture)

    with pytest.raises(ValueError, match="sha256 mismatch"):
        load_public_regression_fixtures(base_path)


def test_immutable_index_rejects_registered_fixture_without_file(tmp_path: Path) -> None:
    fixture = _sample_public_fixture()
    extra = copy.deepcopy(fixture)
    extra["fixture_id"] = "AC-HARD-02_v2026.05.09-skeleton_extra_registered_case"
    base_path = tmp_path / "secret_canary"
    _write_manifest(
        base_path,
        public_expected_count=2,
        immutable_index=_immutable_index([("public_regression", fixture), ("public_regression", extra)]),
    )
    _write_expected_schema(base_path)
    _write_json(base_path / "public_regression/sample.json", fixture)

    with pytest.raises(ValueError, match="expected 2 fixtures, found 1"):
        load_public_regression_fixtures(base_path)


def test_public_fixture_rejects_unknown_top_level_key(tmp_path: Path) -> None:
    fixture = _sample_public_fixture()
    fixture["unexpected"] = True
    base_path = tmp_path / "secret_canary"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="unknown top-level keys"):
        load_public_regression_fixtures(base_path)


def test_public_fixture_rejects_non_null_kpi_id(tmp_path: Path) -> None:
    fixture = _sample_public_fixture()
    fixture["kpi_id"] = "AC-KPI-04"
    base_path = tmp_path / "secret_canary"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="kpi_id must be null"):
        load_public_regression_fixtures(base_path)


@pytest.mark.parametrize("key", sorted(_PROHIBITED_SECRET_METADATA_KEYS))
def test_public_fixture_rejects_raw_secret_keys_in_input(
    tmp_path: Path,
    key: str,
) -> None:
    fixture = _sample_public_fixture()
    fixture["input"]["redacted_plan_artifact"][key] = "do-not-echo-this-value"
    base_path = tmp_path / "secret_canary"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        load_public_regression_fixtures(base_path)

    message = str(exc_info.value)
    assert key in message
    assert "do-not-echo-this-value" not in message


@pytest.mark.parametrize("key", ["canary_value", "raw_canary"])
def test_canary_specific_keys_rejected_from_metadata(
    tmp_path: Path,
    key: str,
) -> None:
    fixture = _sample_public_fixture()
    fixture["metadata"][key] = "synthetic-raw-sentinel"
    base_path = tmp_path / "secret_canary"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        load_public_regression_fixtures(base_path)

    assert key in str(exc_info.value)
    assert "synthetic-raw-sentinel" not in str(exc_info.value)


@pytest.mark.parametrize("raw_value", _RAW_SECRET_PATTERN_SAMPLES)
def test_public_fixture_rejects_raw_secret_value_patterns_without_echo(
    tmp_path: Path,
    raw_value: str,
) -> None:
    fixture = _sample_public_fixture()
    fixture["input"]["task_summary"] = raw_value
    base_path = tmp_path / "secret_canary"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="contains raw secret value patterns") as exc_info:
        load_public_regression_fixtures(base_path)

    assert raw_value not in str(exc_info.value)


@pytest.mark.parametrize("path_name", sorted(_REQUIRED_REDACTION_PATHS))
def test_public_fixture_requires_all_redaction_paths_to_be_redacted(
    tmp_path: Path,
    path_name: str,
) -> None:
    fixture = _sample_public_fixture()
    fixture["expected_redaction"][path_name]["redacted"] = False
    base_path = tmp_path / "secret_canary"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="redacted must be true"):
        load_public_regression_fixtures(base_path)


@pytest.mark.parametrize("path_name", sorted(_REQUIRED_REDACTION_PATHS))
def test_public_fixture_requires_no_raw_value_present_for_each_redaction_path(
    tmp_path: Path,
    path_name: str,
) -> None:
    fixture = _sample_public_fixture()
    fixture["expected_redaction"][path_name]["raw_value_present"] = True
    base_path = tmp_path / "secret_canary"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="raw_value_present must be false"):
        load_public_regression_fixtures(base_path)


def test_public_fixture_rejects_missing_redaction_path(tmp_path: Path) -> None:
    fixture = _sample_public_fixture()
    del fixture["expected_redaction"]["audit"]
    base_path = tmp_path / "secret_canary"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="expected_redaction paths mismatch"):
        load_public_regression_fixtures(base_path)


def test_public_fixture_rejects_pattern_hit_kind_drift_inside_redaction(tmp_path: Path) -> None:
    fixture = _sample_public_fixture()
    fixture["expected_redaction"]["audit"]["pattern_hit_kind"] = "secret_pattern"
    base_path = tmp_path / "secret_canary"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="pattern_hit_kind"):
        load_public_regression_fixtures(base_path)


@pytest.mark.parametrize("key", sorted(_PROHIBITED_REDACTED_KEYS))
def test_redacted_fixture_rejects_expectation_leak_keys(
    tmp_path: Path,
    key: str,
) -> None:
    fixture = _redacted_fixture("private_holdout")
    fixture[key] = {"leak": True} if key == "leak_payload" else "leak"
    base_path = tmp_path / "secret_canary"
    _write_redacted_case(base_path, "private_holdout", fixture)

    with pytest.raises(ValueError, match="expectation leak"):
        load_redacted_fixtures(base_path, kind="private_holdout")


def test_redacted_fixture_rejects_nested_expectation_leak(tmp_path: Path) -> None:
    fixture = _redacted_fixture("adversarial_new")
    fixture["metadata"]["nested"] = {"expected_reason_code": "provider_request_preflight_violation"}
    base_path = tmp_path / "secret_canary"
    _write_redacted_case(base_path, "adversarial_new", fixture)

    with pytest.raises(ValueError, match="nested prohibited keys"):
        load_redacted_fixtures(base_path, kind="adversarial_new")


def test_redacted_fixture_rejects_unknown_top_level_key(tmp_path: Path) -> None:
    fixture = _redacted_fixture("private_holdout")
    fixture["unexpected"] = True
    base_path = tmp_path / "secret_canary"
    _write_redacted_case(base_path, "private_holdout", fixture)

    with pytest.raises(ValueError, match="unknown top-level keys"):
        load_redacted_fixtures(base_path, kind="private_holdout")


def test_redacted_fixture_rejects_fixture_kind_spoof(tmp_path: Path) -> None:
    fixture = _redacted_fixture("private_holdout")
    fixture["fixture_kind"] = "adversarial_new"
    base_path = tmp_path / "secret_canary"
    _write_redacted_case(base_path, "private_holdout", fixture)

    with pytest.raises(ValueError, match="does not match split"):
        load_redacted_fixtures(base_path, kind="private_holdout")


@pytest.mark.parametrize("rule_name", _REQUIRED_COMMON_RULES)
def test_manifest_requires_all_six_common_anti_gaming_rules(
    tmp_path: Path,
    rule_name: str,
) -> None:
    fixture = _sample_public_fixture()
    base_path = tmp_path / "secret_canary"
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
        metadata={"created_at": "2026-05-09", "nested": {"expected_redaction": {}}},
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
    base_path = tmp_path / "secret_canary"
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

