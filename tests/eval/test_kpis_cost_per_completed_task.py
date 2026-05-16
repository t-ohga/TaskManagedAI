"""Tests for the AC-KPI-05 cost_per_completed_task aggregator.

Covers the same five concerns as the citation_coverage suite (5+ source enum
integrity / live happy path / manifest drift / per-fixture spec violations /
SUT result integration), plus the AC-KPI-05-specific Anti-Gaming invariant
that **only ``status="completed"`` runs contribute to the numerator and
denominator**.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, Literal
from unittest import mock

import pytest

from backend.app.db.models.base import JsonDict
from backend.app.db.models.dataset_version import FixtureKind
from backend.app.services.eval.kpis import cost_per_completed_task
from backend.app.services.eval.kpis.cost_per_completed_task import (
    AC_KPI_05_CURRENCY,
    AC_KPI_05_KPI_ID,
    AC_KPI_05_METRIC_KEY,
    AC_KPI_05_THRESHOLD_USD,
    CostPerCompletedTaskFixtureResult,
    CostPerCompletedTaskMetricResult,
    SampleRun,
    evaluate_cost_per_completed_task,
)
from backend.app.services.eval.loader import Fixture, LoadedCorpus, load_fixture_corpus

_REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = _REPO_ROOT / "eval/quality/cost_per_completed_task"
MANIFEST_PATH = BASE_PATH / "manifest.json"

EXPECTED_AC_KPI_05_KPI_ID: Final[Literal["AC-KPI-05"]] = "AC-KPI-05"
EXPECTED_AC_KPI_05_METRIC_KEY: Final[Literal["cost_per_completed_task"]] = "cost_per_completed_task"
EXPECTED_AC_KPI_05_THRESHOLD_USD: Final[float] = 0.5
EXPECTED_AC_KPI_05_CURRENCY: Final[Literal["USD"]] = "USD"
# Live fixture: 5 sample_runs (3 completed at $0.3+$0.2+$0.1 = $0.6 total),
# expected ratio = $0.2 / completed task. Below threshold $0.5.
EXPECTED_FIXTURE_COUNT: Final[int] = 1
EXPECTED_SAMPLE_TOTAL_RUNS: Final[int] = 5
EXPECTED_SAMPLE_COMPLETED_RUNS: Final[int] = 3
EXPECTED_SAMPLE_TOTAL_COST_USD: Final[float] = 0.6
EXPECTED_SAMPLE_COST_PER_TASK_USD: Final[float] = 0.2


def _load_corpus() -> LoadedCorpus:
    return load_fixture_corpus(BASE_PATH, dataset_key="cost_per_completed_task")


def _read_json(path: Path) -> JsonDict:
    return json.loads(path.read_text(encoding="utf-8"))


def _uuid_for(seed: str) -> str:
    """Deterministic UUID-shaped string from a seed (synthetic fixture rows)."""

    import hashlib

    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"{digest[0:8]}-{digest[8:12]}-4{digest[13:16]}-8{digest[17:20]}-{digest[20:32]}"


def _sample_runs(
    *,
    completed_cost_usds: Sequence[float],
    extra_runs: Sequence[Mapping[str, object]] = (),
    prefix: str = "synth",
) -> list[JsonDict]:
    """Build a deterministic ``sample_runs`` payload.

    ``completed_cost_usds`` is the list of costs for completed runs (one entry
    per completed run). ``extra_runs`` carries additional runs with arbitrary
    statuses (failed / cancelled / etc.) so tests can verify the completed-only
    Anti-Gaming filter.
    """

    runs: list[JsonDict] = []
    for index, cost in enumerate(completed_cost_usds):
        runs.append(
            {
                "tenant_id": 1,
                "project_id": 10,
                "run_id": _uuid_for(f"{prefix}-completed-{index}"),
                "status": "completed",
                "cost_usd": cost,
            }
        )
    for entry in extra_runs:
        runs.append(dict(entry))
    return runs


def _synthetic_raw_json(
    *,
    fixture_id: str,
    kpi_id: str,
    metric_key: str,
    fixture_kind: FixtureKind,
    case_key: str,
    sample_runs: Sequence[JsonDict] | None,
    expected_aggregate: object,
    threshold: object,
) -> JsonDict:
    payload: JsonDict = {
        "fixture_id": fixture_id,
        "dataset_version_id": "ac-kpi-05-v2026.05.09-synthetic",
        "fixture_kind": fixture_kind,
        "kpi_id": kpi_id,
        "metric_key": metric_key,
        "case_key": case_key,
        "input": {
            "sample_runs": list(sample_runs) if sample_runs is not None else [],
        },
        "assertions": [
            {
                "name": "synthetic_cost_assert",
                "expected": "deterministic",
            }
        ],
        "anti_gaming": {
            "private_expectation_visible_to_policy_author": False,
            "append_only_refresh": True,
            "separate_fixture_and_policy_commits": True,
        },
        "metadata": {"rls_ready": True, "synthetic": True},
    }
    if threshold is not OMIT_THRESHOLD:
        payload["threshold"] = threshold  # type: ignore[assignment]
    if expected_aggregate is not OMIT_EXPECTED_AGGREGATE:
        payload["expected_aggregate"] = expected_aggregate  # type: ignore[assignment]
    return payload


# Sentinels: use distinct objects so default-fill vs explicit-omit are
# distinguishable in the synthetic_fixture helper.
_AUTO: Final[object] = object()
OMIT_EXPECTED_AGGREGATE: Final[object] = object()
OMIT_THRESHOLD: Final[object] = object()
_DEFAULT_THRESHOLD: Final[JsonDict] = {
    "cost_per_completed_task_usd_max": EXPECTED_AC_KPI_05_THRESHOLD_USD,
    "currency": EXPECTED_AC_KPI_05_CURRENCY,
}


def _default_completed_costs() -> tuple[float, ...]:
    return (0.3, 0.2, 0.1)


def _expected_aggregate_for(
    sample_runs: Sequence[JsonDict],
) -> JsonDict:
    completed = [
        run for run in sample_runs if run.get("status") == "completed"
    ]
    total_completed = len(completed)
    total_cost = sum(float(run.get("cost_usd") or 0.0) for run in completed)
    ratio = total_cost / total_completed if total_completed else 0.0
    return {
        "total_completed_runs": total_completed,
        "total_cost_usd": total_cost,
        "cost_per_completed_task_usd": ratio,
        "threshold_usd": EXPECTED_AC_KPI_05_THRESHOLD_USD,
        "threshold_passed": ratio <= EXPECTED_AC_KPI_05_THRESHOLD_USD,
    }


def _synthetic_fixture(
    *,
    fixture_id: str = "AC-KPI-05_v2026.05.09-synthetic_default",
    kpi_id: str = "AC-KPI-05",
    metric_key: str = "cost_per_completed_task",
    fixture_kind: FixtureKind = "public_regression",
    case_key: str = "synthetic_case",
    sample_runs: Sequence[JsonDict] | None = None,
    expected_aggregate: object = _AUTO,
    threshold: object = _AUTO,
) -> Fixture:
    if sample_runs is None:
        sample_runs = _sample_runs(completed_cost_usds=_default_completed_costs())
    if expected_aggregate is _AUTO:
        expected_aggregate = _expected_aggregate_for(sample_runs)
    if threshold is _AUTO:
        threshold = dict(_DEFAULT_THRESHOLD)

    raw_json = _synthetic_raw_json(
        fixture_id=fixture_id,
        kpi_id=kpi_id,
        metric_key=metric_key,
        fixture_kind=fixture_kind,
        case_key=case_key,
        sample_runs=sample_runs,
        expected_aggregate=expected_aggregate,
        threshold=threshold,
    )

    # Mirror the generic loader split: expectation-style keys go to expected_json.
    expectation_keys = {"expected_aggregate", "threshold", "assertions"}
    expected_json: JsonDict = {key: raw_json[key] for key in expectation_keys if key in raw_json}
    case_json: JsonDict = {key: value for key, value in raw_json.items() if key not in expectation_keys}

    return Fixture(
        fixture_id=fixture_id,
        dataset_version_id="ac-kpi-05-v2026.05.09-synthetic",
        fixture_kind=fixture_kind,
        gate_id=None,
        metric_key=metric_key,
        case_key=case_key,
        case_json=case_json,
        expected_json=expected_json,
        metadata={"rls_ready": True, "synthetic": True},
        anti_gaming=raw_json["anti_gaming"],
        source_path=Path("synthetic/cost_fixture.json"),
        raw_json=raw_json,
        kpi_id=kpi_id,
    )


_VALID_MANIFEST: Final[JsonDict] = {
    "kpi_id": EXPECTED_AC_KPI_05_KPI_ID,
    "metric": EXPECTED_AC_KPI_05_METRIC_KEY,
    "threshold": {
        "cost_per_completed_task_usd_max": EXPECTED_AC_KPI_05_THRESHOLD_USD,
        "currency": EXPECTED_AC_KPI_05_CURRENCY,
    },
}


def _synthetic_corpus(
    fixtures: Sequence[Fixture],
    *,
    manifest: JsonDict | None = None,
) -> LoadedCorpus:
    return LoadedCorpus(
        dataset_key="cost_per_completed_task",
        version="ac-kpi-05-v2026.05.09-synthetic",
        content_hash="0" * 64,
        manifest=manifest if manifest is not None else dict(_VALID_MANIFEST),
        expected_schema={},
        fixtures=tuple(fixtures),
    )


def _result_for(
    fixture: Fixture,
) -> tuple[CostPerCompletedTaskMetricResult, CostPerCompletedTaskFixtureResult]:
    corpus = _synthetic_corpus([fixture])
    result = evaluate_cost_per_completed_task(corpus)
    assert result.fixture_count == 1
    return result, result.per_fixture[0]


# ---------------------------------------------------------------------------
# 5+ source enum integrity
# ---------------------------------------------------------------------------


def test_ac_kpi_05_constants_match_test_layer_expected_constants() -> None:
    assert AC_KPI_05_KPI_ID == EXPECTED_AC_KPI_05_KPI_ID
    assert AC_KPI_05_METRIC_KEY == EXPECTED_AC_KPI_05_METRIC_KEY
    assert AC_KPI_05_THRESHOLD_USD == EXPECTED_AC_KPI_05_THRESHOLD_USD
    assert AC_KPI_05_CURRENCY == EXPECTED_AC_KPI_05_CURRENCY


def test_ac_kpi_05_constants_are_exported_from_module_all() -> None:
    exported = set(cost_per_completed_task.__all__)
    assert {
        "AC_KPI_05_KPI_ID",
        "AC_KPI_05_METRIC_KEY",
        "AC_KPI_05_THRESHOLD_USD",
        "AC_KPI_05_CURRENCY",
        "SampleRun",
        "CostPerCompletedTaskFixtureResult",
        "CostPerCompletedTaskMetricResult",
        "evaluate_cost_per_completed_task",
    } <= exported


def test_ac_kpi_05_constants_match_live_manifest_values() -> None:
    manifest = _read_json(MANIFEST_PATH)
    assert manifest["kpi_id"] == AC_KPI_05_KPI_ID
    assert manifest["metric"] == AC_KPI_05_METRIC_KEY
    threshold = manifest["threshold"]
    assert isinstance(threshold, dict)
    assert threshold["cost_per_completed_task_usd_max"] == pytest.approx(AC_KPI_05_THRESHOLD_USD)
    assert threshold["currency"] == AC_KPI_05_CURRENCY


def test_live_fixture_envelope_uses_expected_constants() -> None:
    corpus = _load_corpus()
    assert len(corpus.fixtures) == EXPECTED_FIXTURE_COUNT
    fixture = corpus.fixtures[0]
    assert fixture.kpi_id == AC_KPI_05_KPI_ID
    assert fixture.metric_key == AC_KPI_05_METRIC_KEY
    assert fixture.fixture_kind == "public_regression"


# ---------------------------------------------------------------------------
# Live happy path
# ---------------------------------------------------------------------------


def test_evaluate_cost_per_completed_task_happy_path_uses_loaded_corpus() -> None:
    corpus = _load_corpus()

    result = evaluate_cost_per_completed_task(corpus)

    assert result.fixture_count == EXPECTED_FIXTURE_COUNT
    assert result.total_completed_runs_across_corpus == EXPECTED_SAMPLE_COMPLETED_RUNS
    assert result.total_cost_usd_across_corpus == pytest.approx(EXPECTED_SAMPLE_TOTAL_COST_USD)
    assert result.metric_value == pytest.approx(EXPECTED_SAMPLE_COST_PER_TASK_USD)
    assert result.threshold_usd == AC_KPI_05_THRESHOLD_USD
    assert result.currency == AC_KPI_05_CURRENCY
    assert result.threshold_met is True
    assert result.threshold_reason == "threshold_met"
    assert result.manifest_violation_reason is None
    assert result.pass_count == EXPECTED_FIXTURE_COUNT
    assert result.fail_count == 0


def test_live_fixture_anti_gaming_completed_only_filter() -> None:
    """Verify failed / cancelled runs are excluded from numerator + denominator."""

    corpus = _load_corpus()
    result = evaluate_cost_per_completed_task(corpus)
    per_fixture = result.per_fixture[0]

    # Live fixture: 5 runs, 3 completed (cost $0.3 + $0.2 + $0.1 = $0.6),
    # 1 failed (cost $0.4), 1 cancelled (cost $0.05). The aggregator must
    # exclude the failed + cancelled costs from the totals.
    assert per_fixture.total_runs == EXPECTED_SAMPLE_TOTAL_RUNS
    assert per_fixture.completed_runs == EXPECTED_SAMPLE_COMPLETED_RUNS
    assert per_fixture.recomputed_total_cost_usd == pytest.approx(0.6)
    assert per_fixture.recomputed_cost_per_completed_task_usd == pytest.approx(0.2)
    # Failed cost ($0.4) and cancelled cost ($0.05) must NOT appear in totals.
    assert per_fixture.recomputed_total_cost_usd < (0.6 + 0.4 + 0.05) - 0.01


# ---------------------------------------------------------------------------
# Manifest drift
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("override", "expected_reason"),
    (
        ({"kpi_id": "AC-KPI-99"}, "manifest_violation:kpi_id"),
        ({"metric": "wrong_metric"}, "manifest_violation:metric"),
        ({"threshold": "not-a-dict"}, "manifest_violation:threshold"),
        (
            {
                "threshold": {
                    "cost_per_completed_task_usd_max": "not-numeric",
                    "currency": "USD",
                }
            },
            "manifest_violation:threshold_value",
        ),
        (
            {"threshold": {"cost_per_completed_task_usd_max": 0.1, "currency": "USD"}},
            "manifest_violation:threshold_value",
        ),
        (
            {
                "threshold": {
                    "cost_per_completed_task_usd_max": EXPECTED_AC_KPI_05_THRESHOLD_USD,
                    "currency": "JPY",
                }
            },
            "manifest_violation:currency",
        ),
        # Bool subtype must not be accepted as numeric.
        (
            {"threshold": {"cost_per_completed_task_usd_max": True, "currency": "USD"}},
            "manifest_violation:threshold_value",
        ),
    ),
)
def test_manifest_drift_breaks_the_gate(override: JsonDict, expected_reason: str) -> None:
    manifest = copy.deepcopy(_VALID_MANIFEST)
    manifest.update(override)
    result = evaluate_cost_per_completed_task(
        _synthetic_corpus([_synthetic_fixture()], manifest=manifest)
    )
    assert result.threshold_met is False
    assert result.threshold_reason == "manifest_violation"
    assert result.manifest_violation_reason == expected_reason


# ---------------------------------------------------------------------------
# Per-fixture spec violations
# ---------------------------------------------------------------------------


def test_envelope_violation_kpi_id_is_detected() -> None:
    result, per_fixture = _result_for(_synthetic_fixture(kpi_id="AC-KPI-99"))
    assert per_fixture.spec_violation_reason == "spec_violation:kpi_id"
    assert result.threshold_reason == "spec_violation"


def test_envelope_violation_metric_key_is_detected() -> None:
    result, per_fixture = _result_for(_synthetic_fixture(metric_key="wrong"))
    assert per_fixture.spec_violation_reason == "spec_violation:metric_key"
    assert result.threshold_reason == "spec_violation"


def test_non_public_fixture_kind_is_skipped() -> None:
    """Redacted splits are deferred to SP-022+."""

    corpus = _synthetic_corpus([_synthetic_fixture(fixture_kind="private_holdout")])
    result = evaluate_cost_per_completed_task(corpus)
    assert result.fixture_count == 0
    assert result.threshold_reason == "no_fixtures"


@pytest.mark.parametrize(
    ("threshold_override", "expected_reason"),
    (
        # None / absent is allowed (manifest is canonical).
        (None, None),
        # Non-dict, drifted value, wrong currency must reject.
        ("not-a-dict", "spec_violation:threshold"),
        (
            {"cost_per_completed_task_usd_max": 0.1, "currency": "USD"},
            "spec_violation:threshold_value",
        ),
        (
            {
                "cost_per_completed_task_usd_max": EXPECTED_AC_KPI_05_THRESHOLD_USD,
                "currency": "JPY",
            },
            "spec_violation:currency",
        ),
        (
            {"cost_per_completed_task_usd_max": "not-numeric", "currency": "USD"},
            "spec_violation:threshold_value",
        ),
    ),
)
def test_fixture_threshold_drift_is_detected(
    threshold_override: object, expected_reason: str | None
) -> None:
    """Fixture-level threshold must match the AC-KPI-05 contract when present."""

    fixture = _synthetic_fixture(threshold=threshold_override)
    _, per_fixture = _result_for(fixture)
    assert per_fixture.spec_violation_reason == expected_reason


def test_expected_aggregate_missing_is_detected() -> None:
    _, per_fixture = _result_for(_synthetic_fixture(expected_aggregate=OMIT_EXPECTED_AGGREGATE))
    assert per_fixture.spec_violation_reason == "spec_violation:expected_aggregate_missing"


def test_expected_aggregate_total_completed_drift_is_detected() -> None:
    fixture = _synthetic_fixture(
        sample_runs=_sample_runs(completed_cost_usds=(0.3, 0.2, 0.1), prefix="completed-drift"),
        expected_aggregate={
            "total_completed_runs": 5,  # lie: real value is 3
            "total_cost_usd": 0.6,
            "cost_per_completed_task_usd": 0.2,
            "threshold_usd": 0.5,
            "threshold_passed": True,
        },
    )
    _, per_fixture = _result_for(fixture)
    assert per_fixture.spec_violation_reason == "spec_violation:expected_aggregate_completed_drift"


def test_expected_aggregate_total_cost_drift_is_detected() -> None:
    fixture = _synthetic_fixture(
        sample_runs=_sample_runs(completed_cost_usds=(0.3, 0.2, 0.1), prefix="cost-drift"),
        expected_aggregate={
            "total_completed_runs": 3,
            "total_cost_usd": 0.9,  # lie: real value is 0.6
            "cost_per_completed_task_usd": 0.3,
            "threshold_usd": 0.5,
            "threshold_passed": True,
        },
    )
    _, per_fixture = _result_for(fixture)
    assert per_fixture.spec_violation_reason == "spec_violation:expected_aggregate_total_cost_drift"


def test_expected_aggregate_ratio_drift_is_detected() -> None:
    fixture = _synthetic_fixture(
        sample_runs=_sample_runs(completed_cost_usds=(0.3, 0.2, 0.1), prefix="ratio-drift"),
        expected_aggregate={
            "total_completed_runs": 3,
            "total_cost_usd": 0.6,
            "cost_per_completed_task_usd": 0.1,  # lie: real value is 0.2
            "threshold_usd": 0.5,
            "threshold_passed": True,
        },
    )
    _, per_fixture = _result_for(fixture)
    assert per_fixture.spec_violation_reason == "spec_violation:expected_aggregate_ratio_drift"


def test_expected_aggregate_threshold_drift_is_detected() -> None:
    fixture = _synthetic_fixture(
        expected_aggregate={
            "total_completed_runs": 3,
            "total_cost_usd": 0.6,
            "cost_per_completed_task_usd": 0.2,
            "threshold_usd": 0.1,  # lie: AC-KPI-05 is 0.5
            "threshold_passed": True,
        },
    )
    _, per_fixture = _result_for(fixture)
    assert per_fixture.spec_violation_reason == "spec_violation:expected_aggregate_threshold_drift"


def test_expected_aggregate_passed_drift_is_detected() -> None:
    # Real ratio = 0.6 / 3 = 0.2 < 0.5 → threshold_passed should be True.
    # The fixture lies and claims False.
    fixture = _synthetic_fixture(
        sample_runs=_sample_runs(completed_cost_usds=(0.3, 0.2, 0.1), prefix="passed-drift"),
        expected_aggregate={
            "total_completed_runs": 3,
            "total_cost_usd": 0.6,
            "cost_per_completed_task_usd": 0.2,
            "threshold_usd": 0.5,
            "threshold_passed": False,
        },
    )
    _, per_fixture = _result_for(fixture)
    assert per_fixture.spec_violation_reason == "spec_violation:expected_aggregate_passed_drift"


# ---------------------------------------------------------------------------
# sample_runs structural violations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    (
        ({"sample_runs": "not-a-list"}, "spec_violation:sample_runs"),
        ({"sample_runs": ["not-a-dict"]}, "spec_violation:sample_runs"),
    ),
)
def test_malformed_sample_runs_is_detected(
    mutation: JsonDict, expected_reason: str
) -> None:
    fixture = _synthetic_fixture()
    raw_input: dict[str, Any] = dict(fixture.case_json["input"])  # type: ignore[arg-type]
    raw_input.update(mutation)
    case_json = dict(fixture.case_json)
    case_json["input"] = raw_input
    raw_json = dict(fixture.raw_json)
    raw_json["input"] = raw_input
    rebuilt = Fixture(
        fixture_id=fixture.fixture_id,
        dataset_version_id=fixture.dataset_version_id,
        fixture_kind=fixture.fixture_kind,
        gate_id=fixture.gate_id,
        metric_key=fixture.metric_key,
        case_key=fixture.case_key,
        case_json=case_json,
        expected_json=fixture.expected_json,
        metadata=fixture.metadata,
        anti_gaming=fixture.anti_gaming,
        source_path=fixture.source_path,
        raw_json=raw_json,
        kpi_id=fixture.kpi_id,
    )
    _, per_fixture = _result_for(rebuilt)
    assert per_fixture.spec_violation_reason == expected_reason


@pytest.mark.parametrize(
    ("field", "value", "expected_reason"),
    (
        ("run_id", "not-a-uuid", "spec_violation:run_id"),
        ("run_id", "", "spec_violation:run_id"),
        ("tenant_id", 0, "spec_violation:tenant_id"),
        ("tenant_id", -1, "spec_violation:tenant_id"),
        ("tenant_id", "1", "spec_violation:tenant_id"),
        ("tenant_id", True, "spec_violation:tenant_id"),
        ("project_id", -5, "spec_violation:project_id"),
        ("project_id", "10", "spec_violation:project_id"),
        ("status", "unknown_status", "spec_violation:status"),
        ("status", None, "spec_violation:status"),
        ("cost_usd", -0.1, "spec_violation:cost_usd"),
        ("cost_usd", "0.5", "spec_violation:cost_usd"),
        ("cost_usd", True, "spec_violation:cost_usd"),
        ("cost_usd", float("inf"), "spec_violation:cost_usd"),
    ),
)
def test_per_run_field_validation(field: str, value: object, expected_reason: str) -> None:
    runs = _sample_runs(completed_cost_usds=(0.3, 0.2, 0.1), prefix="badrun")
    runs[0][field] = value  # type: ignore[assignment]
    fixture = _synthetic_fixture(sample_runs=runs)
    _, per_fixture = _result_for(fixture)
    assert per_fixture.spec_violation_reason == expected_reason


def test_duplicate_run_id_is_detected() -> None:
    runs = _sample_runs(completed_cost_usds=(0.3, 0.2, 0.1), prefix="dup")
    runs[1]["run_id"] = runs[0]["run_id"]
    fixture = _synthetic_fixture(sample_runs=runs)
    _, per_fixture = _result_for(fixture)
    assert per_fixture.spec_violation_reason == "spec_violation:duplicate_run_id"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_corpus_yields_no_fixtures_reason() -> None:
    result = evaluate_cost_per_completed_task(_synthetic_corpus([]))
    assert result.fixture_count == 0
    assert result.metric_value is None
    assert result.threshold_met is False
    assert result.threshold_reason == "no_fixtures"


def test_corpus_with_no_completed_runs_returns_no_completed_runs_reason() -> None:
    fixture = _synthetic_fixture(
        sample_runs=[
            {
                "tenant_id": 1,
                "project_id": 10,
                "run_id": _uuid_for("no-completed-failed"),
                "status": "failed",
                "cost_usd": 0.5,
            }
        ],
        expected_aggregate={
            "total_completed_runs": 0,
            "total_cost_usd": 0.0,
            "cost_per_completed_task_usd": 0.0,
            "threshold_usd": 0.5,
            "threshold_passed": False,
        },
    )
    result = evaluate_cost_per_completed_task(_synthetic_corpus([fixture]))
    assert result.fixture_count == 1
    assert result.total_completed_runs_across_corpus == 0
    assert result.metric_value is None
    assert result.threshold_met is False
    # spec_violation:expected_aggregate_passed_drift would otherwise fire,
    # but the fixture honestly declares passed=False so the spec is clean.
    assert result.per_fixture[0].spec_violation_reason is None
    assert result.threshold_reason == "no_completed_runs"


def test_threshold_at_boundary_passes() -> None:
    # cost_per_completed_task = 0.5 exactly (sum 1.5 / 3 completed).
    fixture = _synthetic_fixture(
        sample_runs=_sample_runs(completed_cost_usds=(0.5, 0.5, 0.5), prefix="boundary"),
    )
    result = evaluate_cost_per_completed_task(_synthetic_corpus([fixture]))
    assert result.metric_value == pytest.approx(0.5)
    assert result.threshold_met is True
    assert result.threshold_reason == "threshold_met"


def test_threshold_above_max_blocks_pass() -> None:
    # cost_per_completed_task = 0.6 (sum 1.8 / 3) → above $0.5 max.
    fixture = _synthetic_fixture(
        sample_runs=_sample_runs(completed_cost_usds=(0.6, 0.6, 0.6), prefix="above"),
    )
    result = evaluate_cost_per_completed_task(_synthetic_corpus([fixture]))
    assert result.metric_value == pytest.approx(0.6)
    assert result.threshold_met is False
    assert result.threshold_reason == "above_threshold"


# ---------------------------------------------------------------------------
# SUT result integration
# ---------------------------------------------------------------------------


def test_sut_results_all_true_passes() -> None:
    fixture = _synthetic_fixture()
    result = evaluate_cost_per_completed_task(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: True},
    )
    per_fixture = result.per_fixture[0]
    assert per_fixture.passed is True
    assert per_fixture.sut_attempted is True
    assert per_fixture.sut_result is True
    assert result.threshold_met is True
    assert result.threshold_reason == "threshold_met"


def test_sut_results_all_false_marks_failure() -> None:
    fixture = _synthetic_fixture()
    result = evaluate_cost_per_completed_task(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: False},
    )
    per_fixture = result.per_fixture[0]
    assert per_fixture.passed is False
    assert per_fixture.sut_result is False
    assert per_fixture.spec_violation_reason is None
    assert per_fixture.sut_failure_reason == "sut_result_false"
    assert result.threshold_reason == "sut_failure"
    assert result.threshold_met is False


def test_sut_results_missing_fixture_id_marks_failure() -> None:
    fixture = _synthetic_fixture()
    result = evaluate_cost_per_completed_task(
        _synthetic_corpus([fixture]),
        sut_results={},
    )
    per_fixture = result.per_fixture[0]
    assert per_fixture.passed is False
    assert per_fixture.spec_violation_reason is None
    assert per_fixture.sut_failure_reason == "sut_result_missing"
    assert result.threshold_reason == "sut_failure"


@pytest.mark.parametrize(
    "raw_sut_value",
    ("true", 1, 0, [], {"value": True}, None),
)
def test_non_boolean_sut_result_is_rejected(raw_sut_value: object) -> None:
    fixture = _synthetic_fixture()
    result = evaluate_cost_per_completed_task(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: raw_sut_value},  # type: ignore[dict-item]
    )
    per_fixture = result.per_fixture[0]
    assert per_fixture.passed is False
    assert per_fixture.sut_result is None
    assert per_fixture.spec_violation_reason is None
    assert per_fixture.sut_failure_reason == "sut_result_invalid_type"
    assert result.threshold_reason == "sut_failure"


def test_spec_violation_skips_sut_processing() -> None:
    """spec-invalid fixtures must not record SUT failures."""

    fixture = _synthetic_fixture(kpi_id="AC-KPI-99")
    result = evaluate_cost_per_completed_task(
        _synthetic_corpus([fixture]),
        sut_results={},  # would otherwise trigger sut_result_missing
    )
    per_fixture = result.per_fixture[0]
    assert per_fixture.spec_violation_reason == "spec_violation:kpi_id"
    assert per_fixture.sut_failure_reason is None
    assert per_fixture.sut_attempted is False
    assert result.threshold_reason == "spec_violation"


def test_stale_sut_result_fixture_id_is_logged_and_dropped() -> None:
    fixture = _synthetic_fixture()
    with mock.patch.object(cost_per_completed_task, "_LOGGER") as mock_logger:
        result = evaluate_cost_per_completed_task(
            _synthetic_corpus([fixture]),
            sut_results={
                fixture.fixture_id: True,
                "AC-KPI-05_v2026.05.09-synthetic_stale_unknown": True,
            },
        )

    assert result.fixture_count == 1
    assert result.per_fixture[0].passed is True
    assert mock_logger.warning.called
    formatted = "\n".join(
        (call.args[0] % call.args[1:]) if len(call.args) > 1 else str(call.args[0])
        for call in mock_logger.warning.call_args_list
    )
    assert "AC-KPI-05_v2026.05.09-synthetic_stale_unknown" in formatted


# ---------------------------------------------------------------------------
# Frozen dataclass + raw content non-leakage
# ---------------------------------------------------------------------------


def test_sample_run_dataclass_is_frozen() -> None:
    run = SampleRun(
        run_id=_uuid_for("frozen"),
        tenant_id=1,
        project_id=10,
        status="completed",
        cost_usd=0.1,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        run.cost_usd = 999.0  # type: ignore[misc]


def test_spec_violation_reason_does_not_embed_raw_run_data() -> None:
    """The dataclass repr must not surface concrete cost numbers verbatim.

    cost values themselves are non-sensitive numerics (not PII / secret), but
    we still ensure ``spec_violation_reason`` carries only reason codes — not
    raw fixture content — to keep error messages auditor-safe.
    """

    runs = _sample_runs(completed_cost_usds=(0.3, 0.2, 0.1), prefix="reason")
    runs[0]["cost_usd"] = -1.0  # negative → spec_violation:cost_usd
    fixture = _synthetic_fixture(sample_runs=runs)
    _, per_fixture = _result_for(fixture)
    assert per_fixture.spec_violation_reason == "spec_violation:cost_usd"
    assert per_fixture.spec_violation_reason is not None
    # The reason code carries no fixture-derived numeric / string payload.
    assert "-1.0" not in per_fixture.spec_violation_reason
    assert "tenant" not in per_fixture.spec_violation_reason


def test_drift_tolerance_absorbs_float64_round_trip_noise() -> None:
    """math.isclose tolerances absorb ulp-level cost noise."""

    runs = _sample_runs(completed_cost_usds=(0.3, 0.2, 0.1), prefix="ulp")
    recomputed_ratio = (0.3 + 0.2 + 0.1) / 3
    import math

    near_ratio = math.nextafter(recomputed_ratio, recomputed_ratio + 1)
    assert near_ratio != recomputed_ratio
    fixture = _synthetic_fixture(
        sample_runs=runs,
        expected_aggregate={
            "total_completed_runs": 3,
            "total_cost_usd": 0.3 + 0.2 + 0.1,
            "cost_per_completed_task_usd": near_ratio,
            "threshold_usd": 0.5,
            "threshold_passed": True,
        },
    )
    _, per_fixture = _result_for(fixture)
    assert per_fixture.spec_violation_reason is None


def test_weighted_average_across_two_fixtures() -> None:
    fixture_small = _synthetic_fixture(
        fixture_id="AC-KPI-05_synthetic_small",
        case_key="small",
        sample_runs=_sample_runs(completed_cost_usds=(0.1, 0.1, 0.1), prefix="small"),
    )
    fixture_large = _synthetic_fixture(
        fixture_id="AC-KPI-05_synthetic_large",
        case_key="large",
        sample_runs=_sample_runs(
            completed_cost_usds=(0.4, 0.4, 0.4, 0.4, 0.4, 0.4), prefix="large"
        ),
    )
    result = evaluate_cost_per_completed_task(_synthetic_corpus([fixture_small, fixture_large]))
    # weighted average = (0.3 + 2.4) / (3 + 6) = 2.7 / 9 = 0.3.
    assert result.fixture_count == 2
    assert result.total_completed_runs_across_corpus == 9
    assert result.total_cost_usd_across_corpus == pytest.approx(2.7)
    assert result.metric_value == pytest.approx(2.7 / 9)
    assert result.threshold_met is True


def test_completed_only_filter_excludes_failed_and_cancelled_costs() -> None:
    """Anti-Gaming invariant: ``status=completed`` only contributes to totals."""

    runs = _sample_runs(completed_cost_usds=(0.2,), prefix="anti-gaming")
    # Add many high-cost non-completed runs that would inflate totals if the
    # filter were broken. They must NOT contribute.
    runs.extend(
        [
            {
                "tenant_id": 1,
                "project_id": 10,
                "run_id": _uuid_for("anti-gaming-failed"),
                "status": "failed",
                "cost_usd": 99.0,
            },
            {
                "tenant_id": 1,
                "project_id": 10,
                "run_id": _uuid_for("anti-gaming-cancelled"),
                "status": "cancelled",
                "cost_usd": 99.0,
            },
            {
                "tenant_id": 1,
                "project_id": 10,
                "run_id": _uuid_for("anti-gaming-blocked"),
                "status": "blocked",
                "cost_usd": 99.0,
            },
        ]
    )
    fixture = _synthetic_fixture(
        sample_runs=runs,
        expected_aggregate={
            "total_completed_runs": 1,
            "total_cost_usd": 0.2,
            "cost_per_completed_task_usd": 0.2,
            "threshold_usd": 0.5,
            "threshold_passed": True,
        },
    )
    result = evaluate_cost_per_completed_task(_synthetic_corpus([fixture]))
    assert result.metric_value == pytest.approx(0.2)
    assert result.total_completed_runs_across_corpus == 1
    assert result.total_cost_usd_across_corpus == pytest.approx(0.2)
    assert result.threshold_met is True
    assert result.per_fixture[0].spec_violation_reason is None
