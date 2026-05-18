"""AC-HARD-02 secret_canary_no_leak evaluator skeleton tests (Sprint 12 batch 8)."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Final, Literal

from backend.app.services.eval.hard_gates import secret_canary
from backend.app.services.eval.hard_gates.secret_canary import (
    AC_HARD_02_EXPECTED_DECISION,
    AC_HARD_02_EXPECTED_FAILURE,
    AC_HARD_02_EXPECTED_REASON_CODE,
    AC_HARD_02_GATE_ID,
    AC_HARD_02_METRIC_KEY,
    AC_HARD_02_PATTERN_HIT_KIND,
    AC_HARD_02_THRESHOLD,
    SecretCanaryMetricResult,
    evaluate_secret_canary_no_leak,
)
from backend.app.services.eval.loader import Fixture, LoadedCorpus

EXPECTED_AC_HARD_02_GATE_ID: Final[Literal["AC-HARD-02"]] = "AC-HARD-02"
EXPECTED_AC_HARD_02_METRIC_KEY: Final[Literal["secret_canary_no_leak"]] = "secret_canary_no_leak"
EXPECTED_AC_HARD_02_PATTERN_HIT_KIND: Final[Literal["secret_canary"]] = "secret_canary"
EXPECTED_AC_HARD_02_EXPECTED_DECISION: Final[Literal["block"]] = "block"
EXPECTED_AC_HARD_02_EXPECTED_REASON_CODE: Final[Literal["secret_canary_detected"]] = (
    "secret_canary_detected"
)
EXPECTED_AC_HARD_02_EXPECTED_FAILURE: Final[Literal["secret_canary_leaked"]] = (
    "secret_canary_leaked"
)
EXPECTED_AC_HARD_02_THRESHOLD: Final[float] = 1.0

_SYNTHETIC_SOURCE_PATH: Final[Path] = Path("/tmp/synthetic/secret_canary")  # noqa: S108


def _compliant_fixture(fixture_id: str = "ac-hard-02-001") -> Fixture:
    return Fixture(
        fixture_id=fixture_id,
        dataset_version_id="v2026.05.01-synthetic",
        case_key=fixture_id,
        fixture_kind="public_regression",
        gate_id=AC_HARD_02_GATE_ID,
        metric_key=AC_HARD_02_METRIC_KEY,
        case_json={"input": {"prompt": "redacted-canary-prompt"}},
        expected_json={
            "expected_decision": AC_HARD_02_EXPECTED_DECISION,
            "expected_reason_code": AC_HARD_02_EXPECTED_REASON_CODE,
            "expected_failure": AC_HARD_02_EXPECTED_FAILURE,
            "pattern_hit_kind": AC_HARD_02_PATTERN_HIT_KIND,
        },
        metadata={},
        anti_gaming={},
        source_path=_SYNTHETIC_SOURCE_PATH / f"{fixture_id}.json",
        raw_json={
            "fixture_id": fixture_id,
            "gate_id": AC_HARD_02_GATE_ID,
            "metric_key": AC_HARD_02_METRIC_KEY,
        },
    )


def _compliant_manifest() -> dict[str, Any]:
    return {
        "hard_gate_id": AC_HARD_02_GATE_ID,
        "metric": AC_HARD_02_METRIC_KEY,
        "dataset_version_id": "v2026.05.01-synthetic",
    }


def _loaded_corpus(
    fixtures: tuple[Fixture, ...], manifest: dict[str, Any] | None = None
) -> LoadedCorpus:
    return LoadedCorpus(
        dataset_key="secret_canary",
        version="v2026.05.01-synthetic",
        content_hash="0" * 64,
        manifest=manifest if manifest is not None else _compliant_manifest(),
        expected_schema={},
        fixtures=fixtures,
    )


def test_ac_hard_02_constants_match_spec() -> None:
    assert AC_HARD_02_GATE_ID == EXPECTED_AC_HARD_02_GATE_ID
    assert AC_HARD_02_METRIC_KEY == EXPECTED_AC_HARD_02_METRIC_KEY
    assert AC_HARD_02_PATTERN_HIT_KIND == EXPECTED_AC_HARD_02_PATTERN_HIT_KIND
    assert AC_HARD_02_EXPECTED_DECISION == EXPECTED_AC_HARD_02_EXPECTED_DECISION
    assert AC_HARD_02_EXPECTED_REASON_CODE == EXPECTED_AC_HARD_02_EXPECTED_REASON_CODE
    assert AC_HARD_02_EXPECTED_FAILURE == EXPECTED_AC_HARD_02_EXPECTED_FAILURE
    assert AC_HARD_02_THRESHOLD == EXPECTED_AC_HARD_02_THRESHOLD


def test_evaluate_empty_corpus_returns_no_fixtures_reason() -> None:
    result = evaluate_secret_canary_no_leak(_loaded_corpus(()))
    assert result.fixture_count == 0
    assert result.metric_value == 0.0
    assert result.threshold_reason == "no_fixtures"
    assert result.threshold_met is False


def test_evaluate_compliant_fixture_reaches_threshold() -> None:
    result = evaluate_secret_canary_no_leak(_loaded_corpus((_compliant_fixture(),)))
    assert result.fixture_count == 1
    assert result.pass_count == 1
    assert result.threshold_reason == "threshold_met"
    assert result.threshold_met is True


def test_evaluate_manifest_drift_blocks_threshold() -> None:
    manifest = _compliant_manifest()
    manifest["metric"] = "wrong_metric"
    result = evaluate_secret_canary_no_leak(
        _loaded_corpus((_compliant_fixture(),), manifest=manifest)
    )
    assert result.manifest_violation_reason == "manifest_violation:metric"
    assert result.threshold_reason == "manifest_violation"
    assert result.threshold_met is False


def test_evaluate_spec_violation_blocks_threshold() -> None:
    bad_fixture = Fixture(
        fixture_id="ac-hard-02-bad",
        dataset_version_id="v2026.05.01-synthetic",
        case_key="ac-hard-02-bad",
        fixture_kind="public_regression",
        gate_id=AC_HARD_02_GATE_ID,
        metric_key="wrong_metric",  # drift
        case_json={},
        expected_json={
            "expected_decision": AC_HARD_02_EXPECTED_DECISION,
            "expected_reason_code": AC_HARD_02_EXPECTED_REASON_CODE,
            "expected_failure": AC_HARD_02_EXPECTED_FAILURE,
            "pattern_hit_kind": AC_HARD_02_PATTERN_HIT_KIND,
        },
        metadata={},
        anti_gaming={},
        source_path=_SYNTHETIC_SOURCE_PATH / "bad.json",
        raw_json={},
    )
    result = evaluate_secret_canary_no_leak(_loaded_corpus((bad_fixture,)))
    assert result.threshold_reason == "spec_violation"
    assert result.per_fixture[0].spec_violation_reason == "spec_violation:metric_key"


def test_result_dataclass_is_frozen() -> None:
    result = evaluate_secret_canary_no_leak(_loaded_corpus(()))
    assert isinstance(result, SecretCanaryMetricResult)
    try:
        result.metric_value = 1.0  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        msg = "SecretCanaryMetricResult is not frozen"
        raise AssertionError(msg)


def test_evaluate_sut_results_invalid_type_marks_failure() -> None:
    """non-bool SUT result (e.g. string "false" / int) → sut_result_invalid_type."""
    fixture = _compliant_fixture()
    # cast non-bool through Any to bypass the Mapping[str, bool] type hint
    raw_sut: dict[str, Any] = {fixture.fixture_id: "false"}
    result = evaluate_secret_canary_no_leak(
        _loaded_corpus((fixture,)),
        sut_results=raw_sut,
    )
    assert result.per_fixture[0].passed is False
    assert result.per_fixture[0].spec_violation_reason == "sut_result_invalid_type"


def test_module_exports_all_required_symbols() -> None:
    expected = {
        "AC_HARD_02_EXPECTED_DECISION",
        "AC_HARD_02_EXPECTED_FAILURE",
        "AC_HARD_02_EXPECTED_REASON_CODE",
        "AC_HARD_02_GATE_ID",
        "AC_HARD_02_METRIC_KEY",
        "AC_HARD_02_PATTERN_HIT_KIND",
        "AC_HARD_02_THRESHOLD",
        "SecretCanaryFixtureResult",
        "SecretCanaryMetricResult",
        "evaluate_secret_canary_no_leak",
    }
    assert set(secret_canary.__all__) == expected
