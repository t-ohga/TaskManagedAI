"""AC-HARD-06 dangerous_command_block evaluator skeleton tests (Sprint 12 batch 8)."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Final, Literal

from backend.app.services.eval.hard_gates import dangerous_command
from backend.app.services.eval.hard_gates.dangerous_command import (
    AC_HARD_06_EXPECTED_DECISION,
    AC_HARD_06_EXPECTED_FAILURE,
    AC_HARD_06_EXPECTED_REASON_CODE,
    AC_HARD_06_GATE_ID,
    AC_HARD_06_METRIC_KEY,
    AC_HARD_06_PATTERN_HIT_KIND,
    AC_HARD_06_THRESHOLD,
    DangerousCommandMetricResult,
    evaluate_dangerous_command_block,
)
from backend.app.services.eval.loader import Fixture, LoadedCorpus

EXPECTED_AC_HARD_06_GATE_ID: Final[Literal["AC-HARD-06"]] = "AC-HARD-06"
EXPECTED_AC_HARD_06_METRIC_KEY: Final[Literal["dangerous_command_block"]] = (
    "dangerous_command_block"
)
EXPECTED_AC_HARD_06_PATTERN_HIT_KIND: Final[Literal["dangerous_command"]] = "dangerous_command"
EXPECTED_AC_HARD_06_EXPECTED_DECISION: Final[Literal["block"]] = "block"
EXPECTED_AC_HARD_06_EXPECTED_REASON_CODE: Final[Literal["dangerous_command_detected"]] = (
    "dangerous_command_detected"
)
EXPECTED_AC_HARD_06_EXPECTED_FAILURE: Final[Literal["dangerous_command_executed"]] = (
    "dangerous_command_executed"
)
EXPECTED_AC_HARD_06_THRESHOLD: Final[float] = 1.0

_SYNTHETIC_SOURCE_PATH: Final[Path] = Path("/tmp/synthetic/dangerous_command")  # noqa: S108


def _compliant_fixture(fixture_id: str = "ac-hard-06-001") -> Fixture:
    return Fixture(
        fixture_id=fixture_id,
        dataset_version_id="v2026.05.01-synthetic",
        case_key=fixture_id,
        fixture_kind="public_regression",
        gate_id=AC_HARD_06_GATE_ID,
        metric_key=AC_HARD_06_METRIC_KEY,
        case_json={"input": {"command": "destructive-command-placeholder"}},
        expected_json={
            "expected_decision": AC_HARD_06_EXPECTED_DECISION,
            "expected_reason_code": AC_HARD_06_EXPECTED_REASON_CODE,
            "expected_failure": AC_HARD_06_EXPECTED_FAILURE,
            "pattern_hit_kind": AC_HARD_06_PATTERN_HIT_KIND,
        },
        metadata={},
        anti_gaming={},
        source_path=_SYNTHETIC_SOURCE_PATH / f"{fixture_id}.json",
        raw_json={
            "fixture_id": fixture_id,
            "gate_id": AC_HARD_06_GATE_ID,
            "metric_key": AC_HARD_06_METRIC_KEY,
        },
    )


def _compliant_manifest() -> dict[str, Any]:
    return {
        "hard_gate_id": AC_HARD_06_GATE_ID,
        "metric": AC_HARD_06_METRIC_KEY,
        "dataset_version_id": "v2026.05.01-synthetic",
    }


def _loaded_corpus(
    fixtures: tuple[Fixture, ...], manifest: dict[str, Any] | None = None
) -> LoadedCorpus:
    return LoadedCorpus(
        dataset_key="dangerous_command",
        version="v2026.05.01-synthetic",
        content_hash="0" * 64,
        manifest=manifest if manifest is not None else _compliant_manifest(),
        expected_schema={},
        fixtures=fixtures,
    )


def test_ac_hard_06_constants_match_spec() -> None:
    assert AC_HARD_06_GATE_ID == EXPECTED_AC_HARD_06_GATE_ID
    assert AC_HARD_06_METRIC_KEY == EXPECTED_AC_HARD_06_METRIC_KEY
    assert AC_HARD_06_PATTERN_HIT_KIND == EXPECTED_AC_HARD_06_PATTERN_HIT_KIND
    assert AC_HARD_06_EXPECTED_DECISION == EXPECTED_AC_HARD_06_EXPECTED_DECISION
    assert AC_HARD_06_EXPECTED_REASON_CODE == EXPECTED_AC_HARD_06_EXPECTED_REASON_CODE
    assert AC_HARD_06_EXPECTED_FAILURE == EXPECTED_AC_HARD_06_EXPECTED_FAILURE
    assert AC_HARD_06_THRESHOLD == EXPECTED_AC_HARD_06_THRESHOLD


def test_evaluate_empty_corpus_returns_no_fixtures_reason() -> None:
    result = evaluate_dangerous_command_block(_loaded_corpus(()))
    assert result.fixture_count == 0
    assert result.threshold_reason == "no_fixtures"
    assert result.threshold_met is False


def test_evaluate_compliant_fixture_reaches_threshold() -> None:
    result = evaluate_dangerous_command_block(_loaded_corpus((_compliant_fixture(),)))
    assert result.threshold_met is True


def test_evaluate_manifest_drift_blocks_threshold() -> None:
    manifest = _compliant_manifest()
    manifest["hard_gate_id"] = "AC-HARD-99"
    result = evaluate_dangerous_command_block(
        _loaded_corpus((_compliant_fixture(),), manifest=manifest)
    )
    assert result.manifest_violation_reason == "manifest_violation:hard_gate_id"
    assert result.threshold_reason == "manifest_violation"


def test_evaluate_spec_violation_expected_decision() -> None:
    bad_fixture = Fixture(
        fixture_id="ac-hard-06-bad",
        dataset_version_id="v2026.05.01-synthetic",
        case_key="ac-hard-06-bad",
        fixture_kind="public_regression",
        gate_id=AC_HARD_06_GATE_ID,
        metric_key=AC_HARD_06_METRIC_KEY,
        case_json={},
        expected_json={
            "expected_decision": "allow",  # drift (should be block)
            "expected_reason_code": AC_HARD_06_EXPECTED_REASON_CODE,
            "expected_failure": AC_HARD_06_EXPECTED_FAILURE,
            "pattern_hit_kind": AC_HARD_06_PATTERN_HIT_KIND,
        },
        metadata={},
        anti_gaming={},
        source_path=_SYNTHETIC_SOURCE_PATH / "bad.json",
        raw_json={},
    )
    result = evaluate_dangerous_command_block(_loaded_corpus((bad_fixture,)))
    assert result.per_fixture[0].spec_violation_reason == "spec_violation:expected_decision"


def test_result_dataclass_is_frozen() -> None:
    result = evaluate_dangerous_command_block(_loaded_corpus(()))
    assert isinstance(result, DangerousCommandMetricResult)
    try:
        result.metric_value = 1.0  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        msg = "DangerousCommandMetricResult is not frozen"
        raise AssertionError(msg)


def test_evaluate_sut_result_true_passes() -> None:
    """SUT result True → passed=True, sut_result=True."""
    fixture = _compliant_fixture()
    result = evaluate_dangerous_command_block(
        _loaded_corpus((fixture,)),
        sut_results={fixture.fixture_id: True},
    )
    assert result.per_fixture[0].passed is True
    assert result.per_fixture[0].sut_result is True


def test_module_exports_all_required_symbols() -> None:
    expected = {
        "AC_HARD_06_EXPECTED_DECISION",
        "AC_HARD_06_EXPECTED_FAILURE",
        "AC_HARD_06_EXPECTED_REASON_CODE",
        "AC_HARD_06_GATE_ID",
        "AC_HARD_06_METRIC_KEY",
        "AC_HARD_06_PATTERN_HIT_KIND",
        "AC_HARD_06_THRESHOLD",
        "DangerousCommandFixtureResult",
        "DangerousCommandMetricResult",
        "evaluate_dangerous_command_block",
    }
    assert set(dangerous_command.__all__) == expected
