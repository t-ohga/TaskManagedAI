from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Final, Literal, cast, get_args
from unittest import mock

import pytest

import backend.app.services.eval.loader as eval_loader
from backend.app.services.eval.loader import FixtureLoadError, load_fixture_corpus

KnownNonPrefixedExpectationKey = Literal["pattern_hit_kind", "assertions"]
EXPECTED_KNOWN_NON_PREFIXED_EXPECTATION_KEYS: Final[frozenset[KnownNonPrefixedExpectationKey]] = cast(
    frozenset[KnownNonPrefixedExpectationKey],
    frozenset(get_args(KnownNonPrefixedExpectationKey)),
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DANGEROUS_COMMAND_PATH = _REPO_ROOT / "eval/security/dangerous_command"
FORBIDDEN_PATH_PATH = _REPO_ROOT / "eval/security/forbidden_path"
POLICY_BLOCK_PATH = _REPO_ROOT / "eval/security/policy_block"
PROMPT_INJECTION_PATH = _REPO_ROOT / "eval/security/prompt_injection"
SECRET_CANARY_PATH = _REPO_ROOT / "eval/security/secret_canary"
TENANT_ISOLATION_PATH = _REPO_ROOT / "eval/security/tenant_isolation"
APPROVAL_WAIT_MS_PATH = _REPO_ROOT / "eval/quality/approval_wait_ms"
CITATION_COVERAGE_PATH = _REPO_ROOT / "eval/quality/citation_coverage"
COST_PER_COMPLETED_TASK_PATH = _REPO_ROOT / "eval/quality/cost_per_completed_task"
BACKUP_RESTORE_PATH = _REPO_ROOT / "eval/ops/backup_restore"

ALL_CORPORA: Final[tuple[tuple[str, Path], ...]] = (
    ("dangerous_command", DANGEROUS_COMMAND_PATH),
    ("forbidden_path", FORBIDDEN_PATH_PATH),
    ("policy_block", POLICY_BLOCK_PATH),
    ("prompt_injection", PROMPT_INJECTION_PATH),
    ("secret_canary", SECRET_CANARY_PATH),
    ("tenant_isolation", TENANT_ISOLATION_PATH),
    ("approval_wait_ms", APPROVAL_WAIT_MS_PATH),
    ("citation_coverage", CITATION_COVERAGE_PATH),
    ("cost_per_completed_task", COST_PER_COMPLETED_TASK_PATH),
    ("backup_restore", BACKUP_RESTORE_PATH),
)
CORPORA_WITHOUT_IMMUTABLE_INDEX: Final[tuple[tuple[str, Path], ...]] = (
    ("dangerous_command", DANGEROUS_COMMAND_PATH),
    ("forbidden_path", FORBIDDEN_PATH_PATH),
    ("prompt_injection", PROMPT_INJECTION_PATH),
    ("backup_restore", BACKUP_RESTORE_PATH),
)


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _sample_fixture(corpus_path: Path) -> dict[str, Any]:
    return _read_json(corpus_path / "public_regression/sample.json")


def _created_at(fixture: dict[str, Any]) -> str:
    metadata = fixture.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("created_at"), str):
        return metadata["created_at"]
    return "2026-05-17"


def _manifest_for_single_public_fixture(
    corpus_path: Path,
    fixture: dict[str, Any],
    *,
    expectation_keys: object = None,
    immutable_index: object = "auto",
) -> dict[str, Any]:
    manifest = copy.deepcopy(_read_json(corpus_path / "manifest.json"))
    manifest["splits"]["public_regression"]["expected_count"] = 1
    manifest["splits"]["private_holdout"]["expected_count"] = 0
    manifest["splits"]["adversarial_new"]["expected_count"] = 0

    if expectation_keys is not None:
        manifest["expectation_keys"] = expectation_keys

    if immutable_index == "auto":
        fixture_id = fixture["fixture_id"]
        assert isinstance(fixture_id, str)
        manifest["fixture_immutable_index"] = {
            fixture_id: {
                "sha256": eval_loader._canonical_fixture_hash(fixture),
                "split": "public_regression",
                "created_at": _created_at(fixture),
            }
        }
    elif immutable_index == "absent":
        manifest.pop("fixture_immutable_index", None)
    else:
        manifest["fixture_immutable_index"] = immutable_index

    return manifest


def _write_single_public_corpus(
    base_path: Path,
    corpus_path: Path,
    *,
    fixture: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
    schema: dict[str, Any] | None = None,
) -> None:
    fixture_to_write = copy.deepcopy(fixture if fixture is not None else _sample_fixture(corpus_path))
    manifest_to_write = copy.deepcopy(
        manifest
        if manifest is not None
        else _manifest_for_single_public_fixture(corpus_path, fixture_to_write)
    )
    schema_to_write = copy.deepcopy(schema if schema is not None else _read_json(corpus_path / "expected_schema.json"))

    _write_json(base_path / "manifest.json", manifest_to_write)
    _write_json(base_path / "expected_schema.json", schema_to_write)
    _write_json(base_path / "public_regression/sample.json", fixture_to_write)


def test_known_non_prefixed_expectation_keys_cross_source_integrity() -> None:
    assert eval_loader._KNOWN_NON_PREFIXED_EXPECTATION_KEYS == EXPECTED_KNOWN_NON_PREFIXED_EXPECTATION_KEYS


def test_happy_path_multi_corpus_loads_all_existing_corpora() -> None:
    loaded = {
        dataset_key: load_fixture_corpus(corpus_path, dataset_key=dataset_key)
        for dataset_key, corpus_path in ALL_CORPORA
    }

    assert set(loaded) == {dataset_key for dataset_key, _ in ALL_CORPORA}
    assert len(loaded["tenant_isolation"].fixtures) == 17
    assert sum(len(corpus.fixtures) for corpus in loaded.values()) >= 27

    for corpus in loaded.values():
        assert corpus.fixtures
        for fixture in corpus.fixtures:
            assert fixture.dataset_version_id == corpus.version
            assert fixture.fixture_kind in eval_loader.LOADER_FIXTURE_KINDS
            assert fixture.fixture_id
            assert fixture.metric_key
            assert fixture.case_key
            assert fixture.gate_id or fixture.kpi_id
            assert "input" in fixture.case_json
            assert fixture.expected_json
            assert not (set(fixture.case_json) & set(fixture.expected_json))


def test_kpi_id_only_citation_coverage_is_accepted_and_splits_threshold() -> None:
    corpus = load_fixture_corpus(CITATION_COVERAGE_PATH, dataset_key="citation_coverage")

    assert corpus.fixtures
    for fixture in corpus.fixtures:
        assert fixture.gate_id is None
        assert fixture.kpi_id == "AC-KPI-04"
        assert fixture.raw_json["kpi_id"] == "AC-KPI-04"
        assert "threshold" in fixture.expected_json
        assert "threshold" not in fixture.case_json


def test_gate_id_only_tenant_isolation_still_loads_all_public_fixtures() -> None:
    corpus = load_fixture_corpus(TENANT_ISOLATION_PATH, dataset_key="tenant_isolation")

    assert len(corpus.fixtures) == 17
    assert {fixture.gate_id for fixture in corpus.fixtures} == {"AC-HARD-03"}
    assert {fixture.kpi_id for fixture in corpus.fixtures} == {None}


def test_both_gate_id_and_kpi_id_are_accepted_for_synthetic_fixture(tmp_path: Path) -> None:
    fixture = _sample_fixture(CITATION_COVERAGE_PATH)
    fixture["gate_id"] = "AC-KPI-04-GATE"
    schema = _read_json(CITATION_COVERAGE_PATH / "expected_schema.json")
    properties = schema["properties"]
    assert isinstance(properties, dict)
    properties["gate_id"] = {"type": "string", "const": "AC-KPI-04-GATE"}

    base_path = tmp_path / "both_ids"
    _write_single_public_corpus(
        base_path,
        CITATION_COVERAGE_PATH,
        fixture=fixture,
        schema=schema,
    )

    corpus = load_fixture_corpus(base_path, dataset_key="both_ids")

    assert len(corpus.fixtures) == 1
    assert corpus.fixtures[0].gate_id == "AC-KPI-04-GATE"
    assert corpus.fixtures[0].kpi_id == "AC-KPI-04"


def test_gate_id_and_kpi_id_both_missing_is_rejected(tmp_path: Path) -> None:
    fixture = _sample_fixture(CITATION_COVERAGE_PATH)
    fixture.pop("gate_id", None)
    fixture.pop("kpi_id", None)
    base_path = tmp_path / "missing_ids"
    _write_single_public_corpus(base_path, CITATION_COVERAGE_PATH, fixture=fixture)

    with pytest.raises(FixtureLoadError, match="missing gate_id or kpi_id"):
        load_fixture_corpus(base_path, dataset_key="missing_ids")


def test_gate_id_and_kpi_id_both_empty_is_rejected(tmp_path: Path) -> None:
    fixture = _sample_fixture(CITATION_COVERAGE_PATH)
    fixture["gate_id"] = ""
    fixture["kpi_id"] = ""
    base_path = tmp_path / "empty_ids"
    _write_single_public_corpus(base_path, CITATION_COVERAGE_PATH, fixture=fixture)

    with pytest.raises(FixtureLoadError, match="missing gate_id or kpi_id"):
        load_fixture_corpus(base_path, dataset_key="empty_ids")


def test_manifest_expectation_keys_override_splits_threshold(tmp_path: Path) -> None:
    fixture = _sample_fixture(CITATION_COVERAGE_PATH)
    manifest = _manifest_for_single_public_fixture(
        CITATION_COVERAGE_PATH,
        fixture,
        expectation_keys=["threshold"],
    )
    base_path = tmp_path / "threshold_override"
    _write_single_public_corpus(
        base_path,
        CITATION_COVERAGE_PATH,
        fixture=fixture,
        manifest=manifest,
    )

    corpus = load_fixture_corpus(base_path, dataset_key="threshold_override")

    assert corpus.manifest["expectation_keys"] == ["threshold"]
    assert corpus.fixtures[0].expected_json["threshold"] == fixture["threshold"]
    assert "threshold" not in corpus.fixtures[0].case_json


def test_expectation_keys_override_absent_corpus_uses_known_non_prefixed_keys_only() -> None:
    manifest = _read_json(TENANT_ISOLATION_PATH / "manifest.json")
    assert "expectation_keys" not in manifest

    corpus = load_fixture_corpus(TENANT_ISOLATION_PATH, dataset_key="tenant_isolation")
    # tenant_isolation case_key set expanded across Sprint 10 batches; assert
    # the known-non-prefixed expectations end up in expected_json on every
    # fixture, regardless of the case_key naming convention.
    assert corpus.fixtures, "tenant_isolation corpus must contain at least one fixture"
    for sample in corpus.fixtures:
        assert "pattern_hit_kind" in sample.expected_json, sample.fixture_id
        assert "assertions" in sample.expected_json, sample.fixture_id
        assert "pattern_hit_kind" not in sample.case_json, sample.fixture_id
        assert "assertions" not in sample.case_json, sample.fixture_id


@pytest.mark.parametrize(
    ("expectation_keys", "match"),
    (
        ("not-an-array", "expectation_keys must be an array"),
        ([123], "expectation_keys\\[0\\] must be a string"),
        (["UPPERCASE"], "snake_case lowercase"),
        ([""], "must be a non-empty string"),
        (["fixture_id"], "conflicts with fixture envelope key"),
    ),
)
def test_expectation_keys_malformed_values_are_rejected(
    tmp_path: Path,
    expectation_keys: object,
    match: str,
) -> None:
    fixture = _sample_fixture(CITATION_COVERAGE_PATH)
    manifest = _manifest_for_single_public_fixture(
        CITATION_COVERAGE_PATH,
        fixture,
        expectation_keys=expectation_keys,
    )
    base_path = tmp_path / "malformed_expectation_keys"
    _write_single_public_corpus(
        base_path,
        CITATION_COVERAGE_PATH,
        fixture=fixture,
        manifest=manifest,
    )

    with pytest.raises(FixtureLoadError, match=match):
        load_fixture_corpus(base_path, dataset_key="malformed_expectation_keys")


@pytest.mark.parametrize(("dataset_key", "corpus_path"), CORPORA_WITHOUT_IMMUTABLE_INDEX)
def test_immutable_index_absent_warns_once_without_failing(dataset_key: str, corpus_path: Path) -> None:
    with mock.patch.object(eval_loader._LOGGER, "warning") as warning:
        corpus = load_fixture_corpus(corpus_path, dataset_key=dataset_key)

    assert corpus.fixtures
    warning.assert_called_once()
    assert warning.call_args.args == (
        "fixture_immutable_index absent for corpus dataset_key=%s; tamper detection disabled",
        dataset_key,
    )


def test_immutable_index_empty_object_warns_once_without_failing(tmp_path: Path) -> None:
    fixture = _sample_fixture(CITATION_COVERAGE_PATH)
    manifest = _manifest_for_single_public_fixture(
        CITATION_COVERAGE_PATH,
        fixture,
        immutable_index={},
    )
    base_path = tmp_path / "empty_index"
    _write_single_public_corpus(
        base_path,
        CITATION_COVERAGE_PATH,
        fixture=fixture,
        manifest=manifest,
    )

    with mock.patch.object(eval_loader._LOGGER, "warning") as warning:
        corpus = load_fixture_corpus(base_path, dataset_key="empty_index")

    assert len(corpus.fixtures) == 1
    warning.assert_called_once()
    assert warning.call_args.args == (
        "fixture_immutable_index absent for corpus dataset_key=%s; tamper detection disabled",
        "empty_index",
    )


def test_immutable_index_present_non_empty_keeps_strict_sha256_check(tmp_path: Path) -> None:
    fixture = _sample_fixture(TENANT_ISOLATION_PATH)
    base_path = tmp_path / "tenant_tampered"
    _write_single_public_corpus(base_path, TENANT_ISOLATION_PATH, fixture=fixture)

    tampered = copy.deepcopy(fixture)
    tampered["case_key"] = "tampered_case_key"
    _write_json(base_path / "public_regression/sample.json", tampered)

    with pytest.raises(FixtureLoadError, match="sha256 mismatch"):
        load_fixture_corpus(base_path, dataset_key="tenant_tampered")
