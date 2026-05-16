from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from backend.app.db.models.dataset_version import FixtureKind
from backend.app.services.eval.loader import Fixture, LoadedCorpus

AC_HARD_03_GATE_ID: Final[Literal["AC-HARD-03"]] = "AC-HARD-03"
AC_HARD_03_METRIC_KEY: Final[Literal["tenant_isolation_negative_pass"]] = "tenant_isolation_negative_pass"
AC_HARD_03_PATTERN_HIT_KIND: Final[Literal["tenant_boundary"]] = "tenant_boundary"
AC_HARD_03_EXPECTED_DECISION: Final[Literal["block"]] = "block"
AC_HARD_03_EXPECTED_REASON_CODE: Final[Literal["tenant_boundary_violation"]] = "tenant_boundary_violation"
AC_HARD_03_THRESHOLD: Final[float] = 1.0

_SUPPORTED_FIXTURE_KINDS: Final[Sequence[FixtureKind]] = ("public_regression",)
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TenantIsolationFixtureResult:
    fixture_id: str
    case_key: str
    passed: bool
    spec_violation_reason: str | None
    sut_result: bool | None


@dataclass(frozen=True)
class TenantIsolationMetricResult:
    metric_value: float
    fixture_count: int
    pass_count: int
    fail_count: int
    per_fixture: tuple[TenantIsolationFixtureResult, ...]
    threshold: float
    threshold_met: bool
    threshold_reason: str


def _expected_value(fixture: Fixture, key: str) -> object:
    value: object = fixture.expected_json.get(key, fixture.raw_json.get(key))
    return value


def _fixture_spec_violation_reason(fixture: Fixture) -> str | None:
    if fixture.gate_id != AC_HARD_03_GATE_ID:
        return "spec_violation:gate_id"
    if fixture.metric_key != AC_HARD_03_METRIC_KEY:
        return "spec_violation:metric_key"
    if fixture.fixture_kind not in _SUPPORTED_FIXTURE_KINDS:
        return "spec_violation:fixture_kind"
    if _expected_value(fixture, "expected_decision") != AC_HARD_03_EXPECTED_DECISION:
        return "spec_violation:expected_decision"
    if _expected_value(fixture, "expected_reason_code") != AC_HARD_03_EXPECTED_REASON_CODE:
        return "spec_violation:expected_reason_code"
    if _expected_value(fixture, "pattern_hit_kind") != AC_HARD_03_PATTERN_HIT_KIND:
        return "spec_violation:pattern_hit_kind"
    return None


def _warn_unknown_sut_results(corpus: LoadedCorpus, sut_results: Mapping[str, bool]) -> None:
    fixture_ids = {fixture.fixture_id for fixture in corpus.fixtures}
    for fixture_id in sorted(set(sut_results) - fixture_ids):
        _LOGGER.warning("Ignoring SUT result for unknown AC-HARD-03 fixture_id=%s", fixture_id)


def _threshold_reason(
    *,
    fixture_count: int,
    metric_value: float,
    spec_violation_present: bool,
) -> str:
    if fixture_count == 0:
        return "no_fixtures"
    if spec_violation_present:
        return "spec_violation"
    if metric_value >= AC_HARD_03_THRESHOLD:
        return "threshold_met"
    return "below_threshold"


def evaluate_tenant_isolation_negative_pass(
    corpus: LoadedCorpus,
    *,
    sut_results: Mapping[str, bool] | None = None,
) -> TenantIsolationMetricResult:
    """Compute AC-HARD-03 tenant_isolation_negative_pass from a loaded fixture corpus.

    The caller must load and validate the corpus with ``load_fixture_corpus()`` before
    calling this evaluator. This function does not read files, write to the database,
    or execute the system under test. Optional SUT results are consumed read-only and
    keyed by fixture_id for the future BL-0127 programmatic execution integration.
    """

    if sut_results is not None:
        _warn_unknown_sut_results(corpus, sut_results)

    per_fixture: list[TenantIsolationFixtureResult] = []
    spec_violation_present = False

    for fixture in corpus.fixtures:
        spec_reason = _fixture_spec_violation_reason(fixture)
        if spec_reason is not None:
            spec_violation_present = True

        failure_reason = spec_reason
        sut_result: bool | None = None
        passed = spec_reason is None

        if sut_results is not None:
            if fixture.fixture_id not in sut_results:
                passed = False
                if failure_reason is None:
                    failure_reason = "sut_result_missing"
            else:
                sut_result = sut_results[fixture.fixture_id]
                if not sut_result:
                    passed = False

        per_fixture.append(
            TenantIsolationFixtureResult(
                fixture_id=fixture.fixture_id,
                case_key=fixture.case_key,
                passed=passed,
                spec_violation_reason=failure_reason,
                sut_result=sut_result,
            )
        )

    fixture_count = len(per_fixture)
    pass_count = sum(1 for result in per_fixture if result.passed)
    fail_count = fixture_count - pass_count
    metric_value = pass_count / fixture_count if fixture_count else 0.0
    threshold_reason = _threshold_reason(
        fixture_count=fixture_count,
        metric_value=metric_value,
        spec_violation_present=spec_violation_present,
    )

    return TenantIsolationMetricResult(
        metric_value=metric_value,
        fixture_count=fixture_count,
        pass_count=pass_count,
        fail_count=fail_count,
        per_fixture=tuple(per_fixture),
        threshold=AC_HARD_03_THRESHOLD,
        threshold_met=threshold_reason == "threshold_met",
        threshold_reason=threshold_reason,
    )


__all__ = [
    "AC_HARD_03_EXPECTED_DECISION",
    "AC_HARD_03_EXPECTED_REASON_CODE",
    "AC_HARD_03_GATE_ID",
    "AC_HARD_03_METRIC_KEY",
    "AC_HARD_03_PATTERN_HIT_KIND",
    "AC_HARD_03_THRESHOLD",
    "TenantIsolationFixtureResult",
    "TenantIsolationMetricResult",
    "evaluate_tenant_isolation_negative_pass",
]
