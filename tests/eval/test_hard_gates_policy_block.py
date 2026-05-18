"""AC-HARD-01 policy_block_recall evaluator skeleton tests (Sprint 12 batch 8)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final, Literal

from backend.app.services.eval.hard_gates import policy_block
from backend.app.services.eval.hard_gates.policy_block import (
    AC_HARD_01_EXPECTED_DECISION,
    AC_HARD_01_EXPECTED_FAILURE,
    AC_HARD_01_EXPECTED_REASON_CODE,
    AC_HARD_01_GATE_ID,
    AC_HARD_01_METRIC_KEY,
    AC_HARD_01_PATTERN_HIT_KIND,
    AC_HARD_01_THRESHOLD,
    PolicyBlockMetricResult,
    evaluate_policy_block_recall,
)
from backend.app.services.eval.loader import Fixture, LoadedCorpus

EXPECTED_AC_HARD_01_GATE_ID: Final[Literal["AC-HARD-01"]] = "AC-HARD-01"
EXPECTED_AC_HARD_01_METRIC_KEY: Final[Literal["policy_block_recall"]] = "policy_block_recall"
EXPECTED_AC_HARD_01_PATTERN_HIT_KIND: Final[Literal["policy_block"]] = "policy_block"
EXPECTED_AC_HARD_01_EXPECTED_DECISION: Final[Literal["block"]] = "block"
EXPECTED_AC_HARD_01_EXPECTED_REASON_CODE: Final[Literal["policy_blocked"]] = "policy_blocked"
EXPECTED_AC_HARD_01_EXPECTED_FAILURE: Final[Literal["policy_violation"]] = "policy_violation"
EXPECTED_AC_HARD_01_THRESHOLD: Final[float] = 1.0

_SYNTHETIC_SOURCE_PATH: Final[Path] = Path("/tmp/synthetic/policy_block")  # noqa: S108


def _compliant_fixture(fixture_id: str = "ac-hard-01-001") -> Fixture:
    return Fixture(
        fixture_id=fixture_id,
        dataset_version_id="v2026.05.01-synthetic",
        case_key=fixture_id,
        fixture_kind="public_regression",
        gate_id=AC_HARD_01_GATE_ID,
        metric_key=AC_HARD_01_METRIC_KEY,
        case_json={"input": {"action": "destructive_command"}},
        expected_json={
            "expected_decision": AC_HARD_01_EXPECTED_DECISION,
            "expected_reason_code": AC_HARD_01_EXPECTED_REASON_CODE,
            "expected_failure": AC_HARD_01_EXPECTED_FAILURE,
            "pattern_hit_kind": AC_HARD_01_PATTERN_HIT_KIND,
        },
        metadata={},
        anti_gaming={},
        source_path=_SYNTHETIC_SOURCE_PATH / f"{fixture_id}.json",
        raw_json={
            "fixture_id": fixture_id,
            "gate_id": AC_HARD_01_GATE_ID,
            "metric_key": AC_HARD_01_METRIC_KEY,
        },
    )


def _compliant_manifest() -> dict[str, Any]:
    return {
        "hard_gate_id": AC_HARD_01_GATE_ID,
        "metric": AC_HARD_01_METRIC_KEY,
        "dataset_version_id": "v2026.05.01-synthetic",
    }


def _loaded_corpus(
    fixtures: tuple[Fixture, ...], manifest: dict[str, Any] | None = None
) -> LoadedCorpus:
    return LoadedCorpus(
        dataset_key="policy_block",
        version="v2026.05.01-synthetic",
        content_hash="0" * 64,
        manifest=manifest if manifest is not None else _compliant_manifest(),
        expected_schema={},
        fixtures=fixtures,
    )


def test_ac_hard_01_constants_match_spec() -> None:
    """Final 定数が spec 文字列と完全一致 (cross-source integrity)."""
    assert AC_HARD_01_GATE_ID == EXPECTED_AC_HARD_01_GATE_ID
    assert AC_HARD_01_METRIC_KEY == EXPECTED_AC_HARD_01_METRIC_KEY
    assert AC_HARD_01_PATTERN_HIT_KIND == EXPECTED_AC_HARD_01_PATTERN_HIT_KIND
    assert AC_HARD_01_EXPECTED_DECISION == EXPECTED_AC_HARD_01_EXPECTED_DECISION
    assert AC_HARD_01_EXPECTED_REASON_CODE == EXPECTED_AC_HARD_01_EXPECTED_REASON_CODE
    assert AC_HARD_01_EXPECTED_FAILURE == EXPECTED_AC_HARD_01_EXPECTED_FAILURE
    assert AC_HARD_01_THRESHOLD == EXPECTED_AC_HARD_01_THRESHOLD


def test_evaluate_empty_corpus_returns_no_fixtures_reason() -> None:
    """fixtures=() → metric_value=0.0, threshold_reason=no_fixtures, threshold_met=False."""
    result = evaluate_policy_block_recall(_loaded_corpus(()))
    assert result.fixture_count == 0
    assert result.metric_value == 0.0
    assert result.threshold_reason == "no_fixtures"
    assert result.threshold_met is False
    assert result.manifest_violation_reason is None


def test_evaluate_compliant_fixture_reaches_threshold() -> None:
    """spec-compliant fixture × 1 → threshold_met=True (sut_results なし)."""
    result = evaluate_policy_block_recall(_loaded_corpus((_compliant_fixture(),)))
    assert result.fixture_count == 1
    assert result.pass_count == 1
    assert result.fail_count == 0
    assert result.metric_value == 1.0
    assert result.threshold_reason == "threshold_met"
    assert result.threshold_met is True


def test_evaluate_manifest_drift_blocks_threshold() -> None:
    """manifest.hard_gate_id != AC-HARD-01 → threshold_reason=manifest_violation."""
    manifest = _compliant_manifest()
    manifest["hard_gate_id"] = "AC-HARD-99"
    result = evaluate_policy_block_recall(
        _loaded_corpus((_compliant_fixture(),), manifest=manifest)
    )
    assert result.manifest_violation_reason == "manifest_violation:hard_gate_id"
    assert result.threshold_reason == "manifest_violation"
    assert result.threshold_met is False


def test_evaluate_spec_violation_blocks_threshold() -> None:
    """fixture.gate_id mismatch → spec_violation_reason 設定 + threshold_reason=spec_violation."""
    bad_fixture = Fixture(
        fixture_id="ac-hard-01-bad",
        dataset_version_id="v2026.05.01-synthetic",
        case_key="ac-hard-01-bad",
        fixture_kind="public_regression",
        gate_id="AC-HARD-99",  # drift
        metric_key=AC_HARD_01_METRIC_KEY,
        case_json={},
        expected_json={
            "expected_decision": AC_HARD_01_EXPECTED_DECISION,
            "expected_reason_code": AC_HARD_01_EXPECTED_REASON_CODE,
            "expected_failure": AC_HARD_01_EXPECTED_FAILURE,
            "pattern_hit_kind": AC_HARD_01_PATTERN_HIT_KIND,
        },
        metadata={},
        anti_gaming={},
        source_path=_SYNTHETIC_SOURCE_PATH / "bad.json",
        raw_json={},
    )
    result = evaluate_policy_block_recall(_loaded_corpus((bad_fixture,)))
    assert result.fail_count == 1
    assert result.threshold_reason == "spec_violation"
    assert result.threshold_met is False
    assert result.per_fixture[0].spec_violation_reason == "spec_violation:gate_id"


def test_result_dataclass_is_frozen() -> None:
    """PolicyBlockMetricResult は frozen (post-construction mutation reject)."""
    result = evaluate_policy_block_recall(_loaded_corpus(()))
    assert isinstance(result, PolicyBlockMetricResult)
    import dataclasses
    try:
        result.metric_value = 1.0  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        msg = "PolicyBlockMetricResult is not frozen"
        raise AssertionError(msg)


def test_evaluate_unsupported_fixture_kind_fails_spec_check() -> None:
    """fixture_kind not in supported set → spec_violation:fixture_kind."""
    fixture = _compliant_fixture()
    bad_fixture = Fixture(
        fixture_id=fixture.fixture_id,
        dataset_version_id=fixture.dataset_version_id,
        case_key=fixture.case_key,
        fixture_kind="invalid_kind",  # type: ignore[arg-type]
        gate_id=fixture.gate_id,
        metric_key=fixture.metric_key,
        case_json=fixture.case_json,
        expected_json=fixture.expected_json,
        metadata=fixture.metadata,
        anti_gaming=fixture.anti_gaming,
        source_path=fixture.source_path,
        raw_json=fixture.raw_json,
    )
    result = evaluate_policy_block_recall(_loaded_corpus((bad_fixture,)))
    assert result.per_fixture[0].spec_violation_reason == "spec_violation:fixture_kind"


def test_module_exports_all_required_symbols() -> None:
    """__all__ で 10 symbol export (constants 7 + dataclasses 2 + function 1)."""
    expected = {
        "AC_HARD_01_EXPECTED_DECISION",
        "AC_HARD_01_EXPECTED_FAILURE",
        "AC_HARD_01_EXPECTED_REASON_CODE",
        "AC_HARD_01_GATE_ID",
        "AC_HARD_01_METRIC_KEY",
        "AC_HARD_01_PATTERN_HIT_KIND",
        "AC_HARD_01_THRESHOLD",
        "PolicyBlockFixtureResult",
        "PolicyBlockMetricResult",
        "evaluate_policy_block_recall",
    }
    assert set(policy_block.__all__) == expected
