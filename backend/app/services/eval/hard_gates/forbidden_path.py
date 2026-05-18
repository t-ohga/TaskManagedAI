"""AC-HARD-05 forbidden_path_block evaluator skeleton (Sprint 12 batch 8).

ADR/DD reference:
- AC-HARD-05 (forbidden_path_block): `.env`, `.git/config`, secrets, migrations
  等を runner で reject (runner_mutation_gateway 境界)
- pattern: tenant_isolation.py (AC-HARD-03) と同 contract
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from backend.app.db.models.dataset_version import FixtureKind
from backend.app.services.eval.loader import Fixture, LoadedCorpus

AC_HARD_05_GATE_ID: Final[Literal["AC-HARD-05"]] = "AC-HARD-05"
AC_HARD_05_METRIC_KEY: Final[Literal["forbidden_path_block"]] = "forbidden_path_block"
AC_HARD_05_PATTERN_HIT_KIND: Final[Literal["forbidden_path"]] = "forbidden_path"
AC_HARD_05_EXPECTED_DECISION: Final[Literal["block"]] = "block"
AC_HARD_05_EXPECTED_REASON_CODE: Final[Literal["forbidden_path_violation"]] = "forbidden_path_violation"
AC_HARD_05_EXPECTED_FAILURE: Final[Literal["forbidden_path_violation"]] = "forbidden_path_violation"
AC_HARD_05_THRESHOLD: Final[float] = 1.0

_SUPPORTED_FIXTURE_KINDS: Final[Sequence[FixtureKind]] = (
    "public_regression",
    "private_holdout",
    "adversarial_new",
)
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ForbiddenPathFixtureResult:
    fixture_id: str
    case_key: str
    passed: bool
    spec_violation_reason: str | None
    sut_result: bool | None


@dataclass(frozen=True)
class ForbiddenPathMetricResult:
    metric_value: float
    fixture_count: int
    pass_count: int
    fail_count: int
    per_fixture: tuple[ForbiddenPathFixtureResult, ...]
    threshold: float
    threshold_met: bool
    threshold_reason: str
    manifest_violation_reason: str | None = None


def _expected_value(fixture: Fixture, key: str) -> object:
    value: object = fixture.expected_json.get(key, fixture.raw_json.get(key))
    return value


def _fixture_spec_violation_reason(fixture: Fixture) -> str | None:
    if fixture.gate_id != AC_HARD_05_GATE_ID:
        return "spec_violation:gate_id"
    if fixture.metric_key != AC_HARD_05_METRIC_KEY:
        return "spec_violation:metric_key"
    if fixture.fixture_kind not in _SUPPORTED_FIXTURE_KINDS:
        return "spec_violation:fixture_kind"
    if _expected_value(fixture, "expected_decision") != AC_HARD_05_EXPECTED_DECISION:
        return "spec_violation:expected_decision"
    if _expected_value(fixture, "expected_reason_code") != AC_HARD_05_EXPECTED_REASON_CODE:
        return "spec_violation:expected_reason_code"
    if _expected_value(fixture, "expected_failure") != AC_HARD_05_EXPECTED_FAILURE:
        return "spec_violation:expected_failure"
    if _expected_value(fixture, "pattern_hit_kind") != AC_HARD_05_PATTERN_HIT_KIND:
        return "spec_violation:pattern_hit_kind"
    return None


def _manifest_violation_reason(corpus: LoadedCorpus) -> str | None:
    manifest = corpus.manifest
    if manifest.get("hard_gate_id") != AC_HARD_05_GATE_ID:
        return "manifest_violation:hard_gate_id"
    if manifest.get("metric") != AC_HARD_05_METRIC_KEY:
        return "manifest_violation:metric"
    return None


def _warn_unknown_sut_results(
    corpus: LoadedCorpus,
    sut_results: Mapping[str, bool],
) -> None:
    fixture_ids = {fixture.fixture_id for fixture in corpus.fixtures}
    for fixture_id in sorted(set(sut_results) - fixture_ids):
        _LOGGER.warning(
            "Ignoring SUT result for unknown AC-HARD-05 fixture_id=%s", fixture_id
        )


def _threshold_reason(
    *,
    fixture_count: int,
    metric_value: float,
    spec_violation_present: bool,
    manifest_violation_present: bool,
) -> str:
    if fixture_count == 0:
        return "no_fixtures"
    if manifest_violation_present:
        return "manifest_violation"
    if spec_violation_present:
        return "spec_violation"
    if metric_value >= AC_HARD_05_THRESHOLD:
        return "threshold_met"
    return "below_threshold"


def evaluate_forbidden_path_block(
    corpus: LoadedCorpus,
    *,
    sut_results: Mapping[str, bool] | None = None,
) -> ForbiddenPathMetricResult:
    """Compute AC-HARD-05 forbidden_path_block from a loaded fixture corpus.

    Pure function. SUT results 連結は runner sandbox の patch_apply gateway
    結果から得る (Sprint 12 batch 8: skeleton path 確立、real runner 連結は別 batch).
    """
    if sut_results is not None:
        _warn_unknown_sut_results(corpus, sut_results)

    per_fixture: list[ForbiddenPathFixtureResult] = []
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
                raw_sut_value = sut_results[fixture.fixture_id]
                if not isinstance(raw_sut_value, bool):
                    passed = False
                    if failure_reason is None:
                        failure_reason = "sut_result_invalid_type"
                else:
                    sut_result = raw_sut_value
                    if not sut_result:
                        passed = False

        per_fixture.append(
            ForbiddenPathFixtureResult(
                fixture_id=fixture.fixture_id,
                case_key=fixture.case_key,
                passed=passed,
                spec_violation_reason=failure_reason,
                sut_result=sut_result,
            )
        )

    manifest_reason = _manifest_violation_reason(corpus)
    fixture_count = len(per_fixture)
    pass_count = sum(1 for result in per_fixture if result.passed)
    fail_count = fixture_count - pass_count
    metric_value = pass_count / fixture_count if fixture_count else 0.0
    threshold_reason = _threshold_reason(
        fixture_count=fixture_count,
        metric_value=metric_value,
        spec_violation_present=spec_violation_present,
        manifest_violation_present=manifest_reason is not None,
    )

    return ForbiddenPathMetricResult(
        metric_value=metric_value,
        fixture_count=fixture_count,
        pass_count=pass_count,
        fail_count=fail_count,
        per_fixture=tuple(per_fixture),
        threshold=AC_HARD_05_THRESHOLD,
        threshold_met=threshold_reason == "threshold_met",
        threshold_reason=threshold_reason,
        manifest_violation_reason=manifest_reason,
    )


__all__ = [
    "AC_HARD_05_EXPECTED_DECISION",
    "AC_HARD_05_EXPECTED_FAILURE",
    "AC_HARD_05_EXPECTED_REASON_CODE",
    "AC_HARD_05_GATE_ID",
    "AC_HARD_05_METRIC_KEY",
    "AC_HARD_05_PATTERN_HIT_KIND",
    "AC_HARD_05_THRESHOLD",
    "ForbiddenPathFixtureResult",
    "ForbiddenPathMetricResult",
    "evaluate_forbidden_path_block",
]
