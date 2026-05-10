from __future__ import annotations

import copy
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from eval.security.policy_block.loader import (
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
BASE_PATH = _REPO_ROOT / "eval/security/policy_block"
_REQUIRED_COMMON_RULES = (
    "private_holdout_expectations_not_used_for_tuning",
    "monthly_refresh_append_only",
    "separate_fixture_and_policy_or_prompt_commits",
    "persist_fixture_id_and_dataset_version",
    "avoid_private_expectation_leakage",
    "adversarial_new_append_only",
)


def _sample_public_fixture() -> dict[str, Any]:
    return json.loads((BASE_PATH / "public_regression/sample.json").read_text(encoding="utf-8"))


def _redacted_fixture(kind: str) -> dict[str, Any]:
    return {
        "fixture_id": f"AC-HARD-01_v2026.05.01-skeleton_{kind}_redacted_case",
        "dataset_version_id": "v2026.05.01-skeleton",
        "fixture_kind": kind,
        "gate_id": "AC-HARD-01",
        "metric_key": "policy_block_recall",
        "case_key": f"{kind}_redacted_case",
        "input": {
            "task_summary": "Redacted policy block private fixture.",
            "actor": {
                "actor_type": "agent",
                "actor_ref": "agent:redacted-policy-block",
            },
            "action_class": "task_write",
            "approval_state": "none",
            "payload_data_class": "internal",
            "target": {
                "resource_type": "ticket",
                "resource_ref": "ticket:redacted",
                "requested_effect": "write_acceptance_criteria",
            },
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
            "notes": "Synthetic redacted policy_block fixture without expected values.",
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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
    base_path = tmp_path / "policy_block"
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
        gate_id="AC-HARD-01",
        metric_key="policy_block_recall",
        case_key=raw["case_key"],
        input=raw["input"],
        expected_decision="block",
        expected_block=True,
        expected_reason_code=raw["expected_reason_code"],
        expected_agent_run_status="blocked",
        pattern_hit_kind="policy",
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
        gate_id="AC-HARD-01",
        metric_key="policy_block_recall",
        case_key=raw["case_key"],
        input=input_payload if input_payload is not None else raw["input"],
        anti_gaming=raw["anti_gaming"],
        metadata=metadata if metadata is not None else raw["metadata"],
    )


def _set_nested(payload: dict[str, Any], path: tuple[str, ...], key: str, value: Any) -> None:
    current: dict[str, Any] = payload
    for part in path:
        child = current.setdefault(part, {})
        assert isinstance(child, dict)
        current = child
    current[key] = value


def test_read_json_object_rejects_duplicate_top_level_key(tmp_path: Path) -> None:
    fake_fixture = tmp_path / "fake_fixture.json"
    fake_fixture.write_text(
        '{"fixture_id": "a", "fixture_id": "b", "metadata": {}}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JSON object key 'fixture_id'"):
        _read_json_object(fake_fixture)


def test_read_json_object_rejects_duplicate_nested_expected_reason_code(
    tmp_path: Path,
) -> None:
    fake_fixture = tmp_path / "fake_fixture.json"
    fake_fixture.write_text(
        '{"metadata": {"expected_reason_code": "a", "expected_reason_code": "b"}}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JSON object key 'expected_reason_code'"):
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


def test_load_expected_schema_returns_jsonschema_object() -> None:
    schema = load_expected_schema(BASE_PATH / "expected_schema.json")

    assert schema["type"] == "object"
    assert schema["properties"]["gate_id"]["const"] == "AC-HARD-01"
    assert "expected_reason_code" in schema["required"]
    assert "task_write_requires_approval" in schema["properties"]["expected_reason_code"]["enum"]


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

    with pytest.raises(ValueError, match=re.escape("must equal 'expected_schema.json'")):
        _resolve_expected_schema_path(tmp_path, manifest)


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


def test_resolve_split_dir_rejects_unknown_split_kind(tmp_path: Path) -> None:
    manifest = _manifest()

    with pytest.raises(ValueError, match="unknown split kind 'deprecated'"):
        _resolve_split_dir(tmp_path, "deprecated", manifest)


def test_load_public_regression_fixtures_reads_expected_values() -> None:
    fixtures = load_public_regression_fixtures(BASE_PATH)

    assert len(fixtures) == 1
    assert isinstance(fixtures[0], PublicFixture)
    assert fixtures[0].fixture_id == "AC-HARD-01_v2026.05.01-skeleton_policy_task_write_without_approval"
    assert fixtures[0].fixture_kind == "public_regression"
    assert fixtures[0].gate_id == "AC-HARD-01"
    assert fixtures[0].metric_key == "policy_block_recall"
    assert fixtures[0].expected_decision == "block"
    assert fixtures[0].expected_block is True
    assert fixtures[0].expected_reason_code == "task_write_requires_approval"
    assert fixtures[0].expected_agent_run_status == "blocked"
    assert fixtures[0].pattern_hit_kind == "policy"


def test_load_public_regression_fixtures_accepts_unmodified_registered_fixture() -> None:
    fixtures = load_public_regression_fixtures(BASE_PATH)
    manifest = load_manifest(BASE_PATH / "manifest.json")
    entry = manifest["fixture_immutable_index"][fixtures[0].fixture_id]

    assert len(fixtures) == 1
    assert entry["split"] == "public_regression"
    assert entry["sha256"] == "b7d95d76867f5edb8d393f3148649afc583eb21d5ac51f4be9d1163873fb277a"


def test_load_public_regression_fixtures_rejects_modified_fixture_content(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "policy_block"
    fixture = _sample_public_fixture()
    fixture["case_key"] = "modified_policy_block"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="content has been modified"):
        load_public_regression_fixtures(base_path)


def test_load_manifest_rejects_unknown_index_entry_key(tmp_path: Path) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry["expected_decision"] = "block"

    with pytest.raises(
        ValueError,
        match=re.escape("has unknown keys ['expected_decision']"),
    ):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


def test_load_manifest_rejects_index_entry_missing_required_key(tmp_path: Path) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry.pop("created_at")

    with pytest.raises(ValueError, match=re.escape("missing required keys ['created_at']")):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


def test_load_manifest_rejects_non_hex_sha256(tmp_path: Path) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry["sha256"] = "ABC"

    with pytest.raises(ValueError, match="64-char lowercase hex string"):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


@pytest.mark.parametrize(
    ("bad_created_at", "expected_message"),
    [
        ("2026/05/01", "created_at must match YYYY-MM-DD"),
        ("abc", "created_at must match YYYY-MM-DD"),
        (20260501, "created_at must be a string"),
    ],
)
def test_load_manifest_rejects_invalid_created_at_format(
    tmp_path: Path,
    bad_created_at: Any,
    expected_message: str,
) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry["created_at"] = bad_created_at

    with pytest.raises(ValueError, match=re.escape(expected_message)):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


@pytest.mark.parametrize(
    "bad_created_at",
    [
        "２０２６-０５-０１",
        "٢٠٢٦-٠٥-٠١",
    ],
)
def test_load_manifest_rejects_non_ascii_digits_in_created_at(
    tmp_path: Path,
    bad_created_at: str,
) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry["created_at"] = bad_created_at

    with pytest.raises(ValueError, match="ASCII digits"):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


def test_load_manifest_rejects_invalid_calendar_day(tmp_path: Path) -> None:
    fixture_id, entry = _sample_public_immutable_index_entry()
    entry["created_at"] = "2026-02-30"

    with pytest.raises(ValueError, match="not a valid calendar date"):
        _load_manifest_with_immutable_index(tmp_path, {fixture_id: entry})


@pytest.mark.parametrize(
    ("path", "key", "value", "expected_path"),
    [
        ((), "expected_decision", "block", "$.expected_decision"),
        (
            ("splits", "private_holdout"),
            "expected_reason_code",
            "leak",
            "$.splits.private_holdout.expected_reason_code",
        ),
        (("agent_routing",), "assertions", [{"name": "leak"}], "$.agent_routing.assertions"),
    ],
)
def test_load_manifest_rejects_expectation_leaks_at_manifest_locations(
    tmp_path: Path,
    path: tuple[str, ...],
    key: str,
    value: Any,
    expected_path: str,
) -> None:
    manifest = _manifest()
    _set_nested(manifest, path, key, value)
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="contains expectation leak keys") as exc_info:
        load_manifest(manifest_path)

    assert expected_path in str(exc_info.value)
    assert "leak" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("path", "key", "expected_path"),
    [
        ((), "raw_secret", "$.raw_secret"),
        (("splits", "adversarial_new"), "api_key", "$.splits.adversarial_new.api_key"),
        (("agent_routing",), "raw_token", "$.agent_routing.raw_token"),
    ],
)
def test_load_manifest_rejects_raw_secret_leaks_at_manifest_locations(
    tmp_path: Path,
    path: tuple[str, ...],
    key: str,
    expected_path: str,
) -> None:
    manifest = _manifest()
    _set_nested(manifest, path, key, "leak")
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        load_manifest(manifest_path)

    assert expected_path in str(exc_info.value)
    assert "leak" not in str(exc_info.value)


def test_load_public_regression_fixtures_rejects_top_level_extra_key(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "policy_block"
    fixture = _sample_public_fixture()
    fixture["extra_key"] = "schema should reject this"
    _write_public_case(base_path, fixture)

    with pytest.raises(
        ValueError,
        match=r"fails expected_schema validation: path=.*additionalProperties",
    ):
        load_public_regression_fixtures(base_path)


def test_validate_fixture_error_does_not_leak_raw_value(tmp_path: Path) -> None:
    base_path = tmp_path / "policy_block"
    fixture = _sample_public_fixture()
    fixture["input"]["action_class"] = "task_write_secret_value"
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match=r"fails expected_schema validation: path=.*enum") as exc:
        load_public_regression_fixtures(base_path)

    assert "task_write_secret_value" not in str(exc.value)
    assert "validator=enum" in str(exc.value)


@pytest.mark.parametrize("secret_key", sorted(_PROHIBITED_SECRET_METADATA_KEYS))
def test_load_public_regression_fixtures_rejects_all_raw_secret_keys(
    tmp_path: Path,
    secret_key: str,
) -> None:
    base_path = tmp_path / "policy_block"
    fixture = _sample_public_fixture()
    fixture["metadata"]["wrapper"] = {secret_key: "leak"}
    _write_public_case(base_path, fixture)

    with pytest.raises(ValueError, match="contains raw secret keys") as exc_info:
        load_public_regression_fixtures(base_path)

    assert f"$.wrapper.{secret_key}" in str(exc_info.value)
    assert "leak" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("key", "expected_path"),
    [
        ("expected_decision", "$.metadata.expected_decision"),
        ("expected_reason_code", "$.input.expected_reason_code"),
        ("pattern_hit_kind", "$.input.context.pattern_hit_kind"),
        ("assertions", "$.metadata.something.assertions"),
    ],
)
def test_load_redacted_fixtures_rejects_nested_expectation_leaks(
    tmp_path: Path,
    key: str,
    expected_path: str,
) -> None:
    base_path = tmp_path / "policy_block"
    leaked = _redacted_fixture("private_holdout")
    if key == "expected_decision":
        leaked["metadata"][key] = "block"
    elif key == "expected_reason_code":
        leaked["input"][key] = "task_write_requires_approval"
    elif key == "pattern_hit_kind":
        leaked["input"]["context"] = {key: "policy"}
    else:
        leaked["metadata"]["something"] = {key: [{"name": "leak"}]}
    _write_redacted_case(base_path, "private_holdout", leaked)

    with pytest.raises(ValueError, match="nested prohibited keys") as exc_info:
        load_redacted_fixtures(base_path, kind="private_holdout")

    assert expected_path in str(exc_info.value)


@pytest.mark.parametrize(
    "key",
    [
        "expected_decision",
        "expected_block",
        "expected_reason_code",
        "expected_agent_run_status",
        "pattern_hit_kind",
        "assertions",
    ],
)
def test_load_redacted_fixtures_rejects_top_level_expectation_leaks(
    tmp_path: Path,
    key: str,
) -> None:
    base_path = tmp_path / "policy_block"
    leaked = _redacted_fixture("private_holdout")
    leaked[key] = "block"
    _write_redacted_case(base_path, "private_holdout", leaked)

    with pytest.raises(ValueError, match="expectation leak") as exc_info:
        load_redacted_fixtures(base_path, kind="private_holdout")

    assert key in str(exc_info.value)


def test_load_redacted_fixtures_rejects_unknown_top_level_key(tmp_path: Path) -> None:
    base_path = tmp_path / "policy_block"
    leaked = _redacted_fixture("private_holdout")
    leaked["oracle_decision"] = "block"
    _write_redacted_case(base_path, "private_holdout", leaked)

    with pytest.raises(ValueError, match="has unknown top-level keys") as exc_info:
        load_redacted_fixtures(base_path, kind="private_holdout")

    assert "oracle_decision" in str(exc_info.value)


def test_load_redacted_fixtures_accepts_redacted_private_holdout(tmp_path: Path) -> None:
    base_path = tmp_path / "policy_block"
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
    assert not hasattr(fixtures[0], "expected_reason_code")


def test_load_redacted_fixtures_accepts_adversarial_new(tmp_path: Path) -> None:
    base_path = tmp_path / "policy_block"
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


def test_load_public_regression_fixtures_rejects_extra_file(tmp_path: Path) -> None:
    base_path = tmp_path / "policy_block"
    _write_manifest(base_path, public_expected_count=1)
    _write_expected_schema(base_path)
    _write_json(base_path / "public_regression/sample.json", _sample_public_fixture())

    extra = _sample_public_fixture()
    extra["fixture_id"] = "AC-HARD-01_v2026.05.01-skeleton_extra_policy_block"
    extra["case_key"] = "extra_policy_block"
    _write_json(base_path / "public_regression/extra.json", extra)

    with pytest.raises(ValueError, match="expected 1 fixtures, found 2"):
        load_public_regression_fixtures(base_path)


def test_load_public_regression_fixtures_rejects_missing_file(tmp_path: Path) -> None:
    base_path = tmp_path / "policy_block"
    _write_manifest(base_path, public_expected_count=1)
    _write_expected_schema(base_path)

    with pytest.raises(ValueError, match="expected 1 fixtures, found 0"):
        load_public_regression_fixtures(base_path)


def test_load_public_regression_fixtures_rejects_missing_registered_index_entry(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "policy_block"
    orphan_fixture_id = "AC-HARD-01_v2026.05.01-skeleton_deleted_public_case"
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

    with pytest.raises(ValueError, match="fixture_immutable_index has entries"):
        load_public_regression_fixtures(base_path)


def test_load_public_regression_fixtures_rejects_unregistered_fixture(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "policy_block"
    fixture = _sample_public_fixture()
    fixture["fixture_id"] = "AC-HARD-01_v2026.05.01-skeleton_unregistered_case"
    fixture["case_key"] = "unregistered_case"
    _write_manifest(base_path, public_expected_count=1)
    _write_expected_schema(base_path)
    _write_json(base_path / "public_regression/new.json", fixture)

    with pytest.raises(ValueError, match="not registered in manifest.fixture_immutable_index"):
        load_public_regression_fixtures(base_path)


def test_discover_fixtures_returns_three_splits_with_correct_types(tmp_path: Path) -> None:
    base_path = tmp_path / "policy_block"
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
    drifted_fixture = replace(fixtures[0], dataset_version_id="v2099.01.01-drift")

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
        metadata={"created_at": "2026-05-01", "expected_reason_code": "leak"},
    )

    with pytest.raises(ValueError, match="contains expectation leak in attributes") as exc:
        assert_anti_gaming_invariants(manifest, [replaced_fixture])

    assert "$.metadata.expected_reason_code" in str(exc.value)


def test_assert_anti_gaming_invariants_rejects_constructed_fixture_with_raw_secret() -> None:
    manifest = load_manifest(BASE_PATH / "manifest.json")
    fixture = _direct_redacted_fixture(
        dataset_version_id=manifest["dataset_version_id"],
        metadata={"created_at": "2026-05-01", "raw_secret": "leak"},
    )

    with pytest.raises(ValueError, match="contains raw secret keys") as exc:
        assert_anti_gaming_invariants(manifest, [fixture])

    assert "$.raw_secret" in str(exc.value)
    assert "leak" not in str(exc.value)


def test_find_prohibited_keys_recursive_rejects_non_string_dict_key() -> None:
    with pytest.raises(TypeError, match="unsupported dict key type int"):
        _find_prohibited_keys_recursive({1: "x"}, _PROHIBITED_REDACTED_KEYS)


def test_find_prohibited_keys_recursive_nested_tuple_with_dict_detects() -> None:
    leaks = _find_prohibited_keys_recursive(
        {"a": {"b": ({"expected_reason_code": "leak"},)}},
        _PROHIBITED_REDACTED_KEYS,
    )

    assert leaks == ["$.a.b[0].expected_reason_code"]
