from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, Literal

import pytest

from backend.app.db.models.base import JsonDict
from backend.app.db.models.dataset_version import FixtureKind
from backend.app.services.eval.hard_gates import tenant_isolation
from backend.app.services.eval.hard_gates.tenant_isolation import (
    AC_HARD_03_EXPECTED_DECISION,
    AC_HARD_03_EXPECTED_REASON_CODE,
    AC_HARD_03_GATE_ID,
    AC_HARD_03_METRIC_KEY,
    AC_HARD_03_PATTERN_HIT_KIND,
    AC_HARD_03_THRESHOLD,
    TenantIsolationFixtureResult,
    TenantIsolationMetricResult,
    evaluate_tenant_isolation_negative_pass,
)
from backend.app.services.eval.loader import Fixture, LoadedCorpus, load_fixture_corpus

_REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = _REPO_ROOT / "eval/security/tenant_isolation"

EXPECTED_AC_HARD_03_GATE_ID: Final[Literal["AC-HARD-03"]] = "AC-HARD-03"
EXPECTED_AC_HARD_03_METRIC_KEY: Final[Literal["tenant_isolation_negative_pass"]] = (
    "tenant_isolation_negative_pass"
)
EXPECTED_AC_HARD_03_PATTERN_HIT_KIND: Final[Literal["tenant_boundary"]] = "tenant_boundary"
EXPECTED_AC_HARD_03_EXPECTED_DECISION: Final[Literal["block"]] = "block"
EXPECTED_AC_HARD_03_EXPECTED_REASON_CODE: Final[Literal["tenant_boundary_violation"]] = (
    "tenant_boundary_violation"
)
EXPECTED_AC_HARD_03_THRESHOLD: Final[float] = 1.0
EXPECTED_TENANT_ISOLATION_FIXTURE_COUNT: Final[int] = 17

_EXPECTED_CONSTANTS: Final[Mapping[str, str]] = {
    "AC_HARD_03_GATE_ID": EXPECTED_AC_HARD_03_GATE_ID,
    "AC_HARD_03_METRIC_KEY": EXPECTED_AC_HARD_03_METRIC_KEY,
    "AC_HARD_03_PATTERN_HIT_KIND": EXPECTED_AC_HARD_03_PATTERN_HIT_KIND,
    "AC_HARD_03_EXPECTED_DECISION": EXPECTED_AC_HARD_03_EXPECTED_DECISION,
    "AC_HARD_03_EXPECTED_REASON_CODE": EXPECTED_AC_HARD_03_EXPECTED_REASON_CODE,
}


def _load_tenant_isolation_corpus() -> LoadedCorpus:
    return load_fixture_corpus(BASE_PATH, dataset_key="tenant_isolation")


def _synthetic_raw_json(
    *,
    fixture_id: str,
    fixture_kind: FixtureKind,
    gate_id: str,
    metric_key: str,
    expected_decision: object,
    expected_reason_code: object,
    pattern_hit_kind: object,
    raw_marker: str,
) -> JsonDict:
    return {
        "fixture_id": fixture_id,
        "dataset_version_id": "v2026.05.01-synthetic",
        "fixture_kind": fixture_kind,
        "gate_id": gate_id,
        "metric_key": metric_key,
        "case_key": "synthetic_case",
        "input": {
            "operation": "SELECT",
            "raw_marker": raw_marker,
        },
        "expected_decision": expected_decision,
        "expected_failure": "tenant_boundary_violation",
        "expected_reason_code": expected_reason_code,
        "pattern_hit_kind": pattern_hit_kind,
        "assertions": [
            {
                "name": "synthetic_boundary_check",
                "expected": raw_marker,
            }
        ],
        "anti_gaming": {
            "private_expectation_visible_to_policy_author": False,
            "append_only_refresh": True,
            "separate_fixture_and_policy_commits": True,
        },
        "metadata": {
            "notes": raw_marker,
            "rls_ready": True,
        },
    }


def _synthetic_fixture(
    *,
    fixture_id: str = "AC-HARD-03_v2026.05.01-synthetic_case",
    fixture_kind: FixtureKind = "public_regression",
    gate_id: str = EXPECTED_AC_HARD_03_GATE_ID,
    metric_key: str = EXPECTED_AC_HARD_03_METRIC_KEY,
    expected_decision: object = EXPECTED_AC_HARD_03_EXPECTED_DECISION,
    expected_reason_code: object = EXPECTED_AC_HARD_03_EXPECTED_REASON_CODE,
    pattern_hit_kind: object = EXPECTED_AC_HARD_03_PATTERN_HIT_KIND,
    raw_marker: str = "synthetic-fixture-raw-marker",
) -> Fixture:
    raw_json = _synthetic_raw_json(
        fixture_id=fixture_id,
        fixture_kind=fixture_kind,
        gate_id=gate_id,
        metric_key=metric_key,
        expected_decision=expected_decision,
        expected_reason_code=expected_reason_code,
        pattern_hit_kind=pattern_hit_kind,
        raw_marker=raw_marker,
    )
    expected_json: JsonDict = {
        "expected_decision": expected_decision,
        "expected_failure": "tenant_boundary_violation",
        "expected_reason_code": expected_reason_code,
        "pattern_hit_kind": pattern_hit_kind,
        "assertions": raw_json["assertions"],
    }
    case_json: JsonDict = {
        "fixture_id": fixture_id,
        "dataset_version_id": "v2026.05.01-synthetic",
        "fixture_kind": fixture_kind,
        "gate_id": gate_id,
        "metric_key": metric_key,
        "case_key": "synthetic_case",
        "input": raw_json["input"],
        "anti_gaming": raw_json["anti_gaming"],
        "metadata": raw_json["metadata"],
    }

    return Fixture(
        fixture_id=fixture_id,
        dataset_version_id="v2026.05.01-synthetic",
        fixture_kind=fixture_kind,
        gate_id=gate_id,
        metric_key=metric_key,
        case_key="synthetic_case",
        case_json=case_json,
        expected_json=expected_json,
        metadata={"notes": raw_marker, "rls_ready": True},
        anti_gaming={
            "private_expectation_visible_to_policy_author": False,
            "append_only_refresh": True,
            "separate_fixture_and_policy_commits": True,
        },
        source_path=Path("synthetic/tenant_isolation_fixture.json"),
        raw_json=raw_json,
    )


def _synthetic_corpus(fixtures: Sequence[Fixture]) -> LoadedCorpus:
    return LoadedCorpus(
        dataset_key="tenant_isolation",
        version="v2026.05.01-synthetic",
        content_hash="0" * 64,
        manifest={},
        expected_schema={},
        fixtures=tuple(fixtures),
    )


def _single_fixture_result(result: TenantIsolationMetricResult) -> TenantIsolationFixtureResult:
    assert result.fixture_count == 1
    return result.per_fixture[0]


def _assert_single_spec_violation(fixture: Fixture, expected_reason: str) -> TenantIsolationMetricResult:
    result = evaluate_tenant_isolation_negative_pass(_synthetic_corpus([fixture]))

    per_fixture = _single_fixture_result(result)
    assert result.metric_value == 0.0
    assert result.pass_count == 0
    assert result.fail_count == 1
    assert result.threshold == EXPECTED_AC_HARD_03_THRESHOLD
    assert result.threshold_met is False
    assert result.threshold_reason == "spec_violation"
    assert per_fixture.passed is False
    assert per_fixture.spec_violation_reason == expected_reason
    assert per_fixture.sut_result is None
    return result


def test_ac_hard_03_constants_match_test_layer_expected_constants() -> None:
    actual = {
        "AC_HARD_03_GATE_ID": AC_HARD_03_GATE_ID,
        "AC_HARD_03_METRIC_KEY": AC_HARD_03_METRIC_KEY,
        "AC_HARD_03_PATTERN_HIT_KIND": AC_HARD_03_PATTERN_HIT_KIND,
        "AC_HARD_03_EXPECTED_DECISION": AC_HARD_03_EXPECTED_DECISION,
        "AC_HARD_03_EXPECTED_REASON_CODE": AC_HARD_03_EXPECTED_REASON_CODE,
    }

    assert actual == dict(_EXPECTED_CONSTANTS)
    assert AC_HARD_03_THRESHOLD == EXPECTED_AC_HARD_03_THRESHOLD


def test_ac_hard_03_constants_are_exported_from_module_all() -> None:
    exported_names = set(tenant_isolation.__all__)

    assert set(_EXPECTED_CONSTANTS) <= exported_names
    assert {
        "AC_HARD_03_THRESHOLD",
        "TenantIsolationFixtureResult",
        "TenantIsolationMetricResult",
        "evaluate_tenant_isolation_negative_pass",
    } <= exported_names


def test_ac_hard_03_fixture_raw_json_matches_evaluator_constants() -> None:
    corpus = _load_tenant_isolation_corpus()

    assert len(corpus.fixtures) == EXPECTED_TENANT_ISOLATION_FIXTURE_COUNT
    assert {fixture.fixture_kind for fixture in corpus.fixtures} == {"public_regression"}
    actual = {
        "gate_id": {fixture.raw_json["gate_id"] for fixture in corpus.fixtures},
        "metric_key": {fixture.raw_json["metric_key"] for fixture in corpus.fixtures},
        "pattern_hit_kind": {fixture.raw_json["pattern_hit_kind"] for fixture in corpus.fixtures},
        "expected_decision": {fixture.raw_json["expected_decision"] for fixture in corpus.fixtures},
        "expected_reason_code": {fixture.raw_json["expected_reason_code"] for fixture in corpus.fixtures},
    }
    expected = {
        "gate_id": {EXPECTED_AC_HARD_03_GATE_ID},
        "metric_key": {EXPECTED_AC_HARD_03_METRIC_KEY},
        "pattern_hit_kind": {EXPECTED_AC_HARD_03_PATTERN_HIT_KIND},
        "expected_decision": {EXPECTED_AC_HARD_03_EXPECTED_DECISION},
        "expected_reason_code": {EXPECTED_AC_HARD_03_EXPECTED_REASON_CODE},
    }

    assert actual == expected


def test_evaluate_tenant_isolation_negative_pass_happy_path_uses_loaded_corpus() -> None:
    corpus = _load_tenant_isolation_corpus()

    result = evaluate_tenant_isolation_negative_pass(corpus)

    assert result.metric_value == 1.0
    assert result.fixture_count == EXPECTED_TENANT_ISOLATION_FIXTURE_COUNT
    assert result.pass_count == EXPECTED_TENANT_ISOLATION_FIXTURE_COUNT
    assert result.fail_count == 0
    assert result.threshold == EXPECTED_AC_HARD_03_THRESHOLD
    assert result.threshold_met is True
    assert result.threshold_reason == "threshold_met"
    assert all(fixture_result.passed for fixture_result in result.per_fixture)
    assert all(fixture_result.spec_violation_reason is None for fixture_result in result.per_fixture)
    assert all(fixture_result.sut_result is None for fixture_result in result.per_fixture)


def test_evaluate_tenant_isolation_negative_pass_with_all_true_sut_results() -> None:
    corpus = _load_tenant_isolation_corpus()
    sut_results = {fixture.fixture_id: True for fixture in corpus.fixtures}

    result = evaluate_tenant_isolation_negative_pass(corpus, sut_results=sut_results)

    assert result.metric_value == 1.0
    assert result.pass_count == EXPECTED_TENANT_ISOLATION_FIXTURE_COUNT
    assert result.fail_count == 0
    assert result.threshold_met is True
    assert result.threshold_reason == "threshold_met"
    assert all(fixture_result.sut_result is True for fixture_result in result.per_fixture)


def test_evaluate_tenant_isolation_negative_pass_with_all_false_sut_results() -> None:
    corpus = _load_tenant_isolation_corpus()
    sut_results = {fixture.fixture_id: False for fixture in corpus.fixtures}

    result = evaluate_tenant_isolation_negative_pass(corpus, sut_results=sut_results)

    assert result.metric_value == 0.0
    assert result.fixture_count == EXPECTED_TENANT_ISOLATION_FIXTURE_COUNT
    assert result.pass_count == 0
    assert result.fail_count == EXPECTED_TENANT_ISOLATION_FIXTURE_COUNT
    assert result.threshold_met is False
    assert result.threshold_reason == "below_threshold"
    assert all(fixture_result.sut_result is False for fixture_result in result.per_fixture)
    assert all(fixture_result.spec_violation_reason is None for fixture_result in result.per_fixture)


def test_evaluate_tenant_isolation_negative_pass_with_partial_sut_results() -> None:
    corpus = _load_tenant_isolation_corpus()
    true_fixture_ids = {fixture.fixture_id for fixture in corpus.fixtures[:10]}
    sut_results = {fixture.fixture_id: fixture.fixture_id in true_fixture_ids for fixture in corpus.fixtures}

    result = evaluate_tenant_isolation_negative_pass(corpus, sut_results=sut_results)

    assert result.metric_value == pytest.approx(10 / EXPECTED_TENANT_ISOLATION_FIXTURE_COUNT)
    assert result.fixture_count == EXPECTED_TENANT_ISOLATION_FIXTURE_COUNT
    assert result.pass_count == 10
    assert result.fail_count == 7
    assert result.threshold_met is False
    assert result.threshold_reason == "below_threshold"


def test_evaluate_tenant_isolation_negative_pass_marks_missing_sut_result_as_failure() -> None:
    corpus = _load_tenant_isolation_corpus()
    missing_fixture = corpus.fixtures[0]
    sut_results = {fixture.fixture_id: True for fixture in corpus.fixtures[1:]}

    result = evaluate_tenant_isolation_negative_pass(corpus, sut_results=sut_results)

    assert result.metric_value == pytest.approx(16 / EXPECTED_TENANT_ISOLATION_FIXTURE_COUNT)
    assert result.pass_count == 16
    assert result.fail_count == 1
    assert result.threshold_met is False
    assert result.threshold_reason == "below_threshold"
    missing_results = [
        fixture_result
        for fixture_result in result.per_fixture
        if fixture_result.fixture_id == missing_fixture.fixture_id
    ]
    assert len(missing_results) == 1
    assert missing_results[0].passed is False
    assert missing_results[0].sut_result is None
    assert missing_results[0].spec_violation_reason == "sut_result_missing"


def test_evaluate_tenant_isolation_negative_pass_handles_empty_corpus() -> None:
    result = evaluate_tenant_isolation_negative_pass(_synthetic_corpus([]))

    assert result.metric_value == 0.0
    assert result.fixture_count == 0
    assert result.pass_count == 0
    assert result.fail_count == 0
    assert result.per_fixture == ()
    assert result.threshold == EXPECTED_AC_HARD_03_THRESHOLD
    assert result.threshold_met is False
    assert result.threshold_reason == "no_fixtures"


def test_evaluate_tenant_isolation_negative_pass_detects_wrong_expected_decision() -> None:
    _assert_single_spec_violation(
        _synthetic_fixture(expected_decision="allow"),
        "spec_violation:expected_decision",
    )


def test_evaluate_tenant_isolation_negative_pass_detects_wrong_expected_reason_code() -> None:
    _assert_single_spec_violation(
        _synthetic_fixture(expected_reason_code="wrong_reason"),
        "spec_violation:expected_reason_code",
    )


def test_evaluate_tenant_isolation_negative_pass_detects_wrong_pattern_hit_kind() -> None:
    _assert_single_spec_violation(
        _synthetic_fixture(pattern_hit_kind="wrong_pattern"),
        "spec_violation:pattern_hit_kind",
    )


def test_evaluate_tenant_isolation_negative_pass_detects_wrong_gate_id() -> None:
    _assert_single_spec_violation(
        _synthetic_fixture(gate_id="AC-HARD-99"),
        "spec_violation:gate_id",
    )


def test_evaluate_tenant_isolation_negative_pass_detects_wrong_metric_key() -> None:
    _assert_single_spec_violation(
        _synthetic_fixture(metric_key="wrong_metric"),
        "spec_violation:metric_key",
    )


def test_evaluate_tenant_isolation_negative_pass_rejects_redacted_split_for_batch_5b() -> None:
    _assert_single_spec_violation(
        _synthetic_fixture(fixture_kind="private_holdout"),
        "spec_violation:fixture_kind",
    )


def test_spec_violation_reason_does_not_embed_raw_fixture_content() -> None:
    raw_marker = "raw-fixture-content-must-not-leak"

    result = _assert_single_spec_violation(
        _synthetic_fixture(expected_decision="allow", raw_marker=raw_marker),
        "spec_violation:expected_decision",
    )

    reason = _single_fixture_result(result).spec_violation_reason
    assert reason is not None
    assert raw_marker not in reason
    assert "allow" not in reason


def test_unknown_sut_result_logging_does_not_embed_raw_fixture_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_marker = "raw-content-that-must-stay-out-of-logs"
    fixture = _synthetic_fixture(raw_marker=raw_marker)
    corpus = _synthetic_corpus([fixture])

    caplog.set_level(logging.WARNING, logger=tenant_isolation.__name__)
    result = evaluate_tenant_isolation_negative_pass(
        corpus,
        sut_results={
            fixture.fixture_id: True,
            "AC-HARD-03_v2026.05.01-synthetic_unknown_fixture": True,
        },
    )

    assert result.metric_value == 1.0
    assert result.threshold_met is True
    assert "AC-HARD-03_v2026.05.01-synthetic_unknown_fixture" in caplog.text
    assert raw_marker not in caplog.text
