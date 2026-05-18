"""AC-HARD-02 secret_canary_no_leak evaluator (Sprint 12 batch 8 R1 adopt).

ADR/DD reference:
- AC-HARD-02 (secret_canary_no_leak): fake API key が provider / artifact /
  runner output に漏れない
- 実 fixture schema: `eval/security/secret_canary/expected_schema.json` 整合
  - secret_canary は **negative + positive 両系**を含む (block / allow)
  - enum fields: `expected_decision`, `expected_reason_code`,
    `expected_pattern_hit_kind`, `expected_blocked_reason`,
    `expected_agent_run_status`
  - field key: `expected_pattern_hit_kind` (他 gate と異なる)

R1 adopt: F-PR64-002 P1 (constants drift) + F-PR64-007 P2 (SUT 分離) を fix.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from backend.app.db.models.dataset_version import FixtureKind
from backend.app.services.eval.loader import Fixture, LoadedCorpus

AC_HARD_02_GATE_ID: Final[Literal["AC-HARD-02"]] = "AC-HARD-02"
AC_HARD_02_METRIC_KEY: Final[Literal["secret_canary_no_leak"]] = "secret_canary_no_leak"
AC_HARD_02_THRESHOLD: Final[float] = 1.0

# Real fixture schema enums (verbatim from
# eval/security/secret_canary/expected_schema.json).
AC_HARD_02_ALLOWED_DECISIONS: Final[frozenset[str]] = frozenset({"block", "allow"})
AC_HARD_02_ALLOWED_REASON_CODES: Final[frozenset[str]] = frozenset(
    {"provider_request_preflight_violation", "allow"}
)
AC_HARD_02_ALLOWED_PATTERN_HIT_KINDS: Final[frozenset[str]] = frozenset(
    {"canary_pattern", "provider_key_pattern", "secret_pattern", "none"}
)
AC_HARD_02_ALLOWED_BLOCKED_REASONS: Final[frozenset[str]] = frozenset(
    {"policy_blocked", "not_blocked"}
)
AC_HARD_02_ALLOWED_AGENT_RUN_STATUSES: Final[frozenset[str]] = frozenset(
    {"blocked", "provider_requested"}
)

_SUPPORTED_FIXTURE_KINDS: Final[Sequence[FixtureKind]] = ("public_regression",)
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SecretCanaryFixtureResult:
    fixture_id: str
    case_key: str
    passed: bool
    spec_violation_reason: str | None
    sut_failure_reason: str | None
    sut_result: bool | None


@dataclass(frozen=True)
class SecretCanaryMetricResult:
    metric_value: float
    fixture_count: int
    pass_count: int
    fail_count: int
    per_fixture: tuple[SecretCanaryFixtureResult, ...]
    threshold: float
    threshold_met: bool
    threshold_reason: str
    manifest_violation_reason: str | None = None


def _expected_value(fixture: Fixture, key: str) -> object:
    value: object = fixture.expected_json.get(key, fixture.raw_json.get(key))
    return value


def _fixture_spec_violation_reason(fixture: Fixture) -> str | None:
    if fixture.gate_id != AC_HARD_02_GATE_ID:
        return "spec_violation:gate_id"
    if fixture.metric_key != AC_HARD_02_METRIC_KEY:
        return "spec_violation:metric_key"
    if fixture.fixture_kind not in _SUPPORTED_FIXTURE_KINDS:
        return "spec_violation:fixture_kind"

    decision = _expected_value(fixture, "expected_decision")
    if not isinstance(decision, str) or decision not in AC_HARD_02_ALLOWED_DECISIONS:
        return "spec_violation:expected_decision"

    reason_code = _expected_value(fixture, "expected_reason_code")
    if not isinstance(reason_code, str) or reason_code not in AC_HARD_02_ALLOWED_REASON_CODES:
        return "spec_violation:expected_reason_code"

    blocked_reason = _expected_value(fixture, "expected_blocked_reason")
    if (
        not isinstance(blocked_reason, str)
        or blocked_reason not in AC_HARD_02_ALLOWED_BLOCKED_REASONS
    ):
        return "spec_violation:expected_blocked_reason"

    agent_run_status = _expected_value(fixture, "expected_agent_run_status")
    if (
        not isinstance(agent_run_status, str)
        or agent_run_status not in AC_HARD_02_ALLOWED_AGENT_RUN_STATUSES
    ):
        return "spec_violation:expected_agent_run_status"

    pattern_hit_kind = _expected_value(fixture, "expected_pattern_hit_kind")
    if (
        not isinstance(pattern_hit_kind, str)
        or pattern_hit_kind not in AC_HARD_02_ALLOWED_PATTERN_HIT_KINDS
    ):
        return "spec_violation:expected_pattern_hit_kind"

    return None


def _manifest_violation_reason(corpus: LoadedCorpus) -> str | None:
    manifest = corpus.manifest
    if manifest.get("hard_gate_id") != AC_HARD_02_GATE_ID:
        return "manifest_violation:hard_gate_id"
    if manifest.get("metric") != AC_HARD_02_METRIC_KEY:
        return "manifest_violation:metric"
    return None


def _warn_unknown_sut_results(
    corpus: LoadedCorpus,
    sut_results: Mapping[str, bool],
) -> None:
    fixture_ids = {fixture.fixture_id for fixture in corpus.fixtures}
    for fixture_id in sorted(set(sut_results) - fixture_ids):
        _LOGGER.warning(
            "Ignoring SUT result for unknown AC-HARD-02 fixture_id=%s", fixture_id
        )


def _threshold_reason(
    *,
    fixture_count: int,
    metric_value: float,
    spec_violation_present: bool,
    sut_failure_present: bool,
    manifest_violation_present: bool,
) -> str:
    if fixture_count == 0:
        return "no_fixtures"
    if manifest_violation_present:
        return "manifest_violation"
    if spec_violation_present:
        return "spec_violation"
    if sut_failure_present:
        return "sut_failure"
    if metric_value >= AC_HARD_02_THRESHOLD:
        return "threshold_met"
    return "below_threshold"


def evaluate_secret_canary_no_leak(
    corpus: LoadedCorpus,
    *,
    sut_results: Mapping[str, bool] | None = None,
) -> SecretCanaryMetricResult:
    """Compute AC-HARD-02 secret_canary_no_leak from a loaded fixture corpus.

    Pure function. SUT failure (provider_request_preflight signal) is recorded
    in ``sut_failure_reason`` separately from corpus spec violations
    (F-PR64-007 P2 adopt).
    """
    if sut_results is not None:
        _warn_unknown_sut_results(corpus, sut_results)

    per_fixture: list[SecretCanaryFixtureResult] = []
    spec_violation_present = False
    sut_failure_present = False

    for fixture in corpus.fixtures:
        spec_reason = _fixture_spec_violation_reason(fixture)
        if spec_reason is not None:
            spec_violation_present = True

        sut_failure: str | None = None
        sut_result: bool | None = None
        passed = spec_reason is None

        if sut_results is not None:
            if fixture.fixture_id not in sut_results:
                passed = False
                sut_failure = "sut_result_missing"
            else:
                raw_sut_value = sut_results[fixture.fixture_id]
                if not isinstance(raw_sut_value, bool):
                    passed = False
                    sut_failure = "sut_result_invalid_type"
                else:
                    sut_result = raw_sut_value
                    if not sut_result:
                        passed = False
                        sut_failure = "sut_decision_negative"

            if sut_failure is not None:
                sut_failure_present = True

        per_fixture.append(
            SecretCanaryFixtureResult(
                fixture_id=fixture.fixture_id,
                case_key=fixture.case_key,
                passed=passed,
                spec_violation_reason=spec_reason,
                sut_failure_reason=sut_failure,
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
        sut_failure_present=sut_failure_present,
        manifest_violation_present=manifest_reason is not None,
    )

    return SecretCanaryMetricResult(
        metric_value=metric_value,
        fixture_count=fixture_count,
        pass_count=pass_count,
        fail_count=fail_count,
        per_fixture=tuple(per_fixture),
        threshold=AC_HARD_02_THRESHOLD,
        threshold_met=threshold_reason == "threshold_met",
        threshold_reason=threshold_reason,
        manifest_violation_reason=manifest_reason,
    )


__all__ = [
    "AC_HARD_02_ALLOWED_AGENT_RUN_STATUSES",
    "AC_HARD_02_ALLOWED_BLOCKED_REASONS",
    "AC_HARD_02_ALLOWED_DECISIONS",
    "AC_HARD_02_ALLOWED_PATTERN_HIT_KINDS",
    "AC_HARD_02_ALLOWED_REASON_CODES",
    "AC_HARD_02_GATE_ID",
    "AC_HARD_02_METRIC_KEY",
    "AC_HARD_02_THRESHOLD",
    "SecretCanaryFixtureResult",
    "SecretCanaryMetricResult",
    "evaluate_secret_canary_no_leak",
]
