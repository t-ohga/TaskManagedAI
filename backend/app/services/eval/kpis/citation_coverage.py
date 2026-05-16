"""AC-KPI-04 ``citation_coverage`` aggregator.

This module evaluates the ``citation_coverage`` KPI from a fixture corpus loaded
by :func:`backend.app.services.eval.loader.load_fixture_corpus`. The aggregator
follows the Anti-Gaming invariant declared in the corpus manifest::

    "citation_coverage is recomputed from input.sample_claims, not copied from
     expected_aggregate"

i.e., the canonical coverage ratio is always **recomputed** from the fixture's
``input.sample_claims`` list. ``expected_aggregate.coverage_ratio`` is consumed
purely as a drift-detection oracle — a mismatch raises a spec violation rather
than silently overriding the recomputed value.

Per Sprint 11 Pack §208 (QL-C cross-reference), the metric is a claim-level
weighted average across the corpus::

    metric_value = sum(claims_with_citation) / sum(total_claims)

The function is pure (no DB / file system / network access). Optional
``sut_results`` is consumed read-only for forward-compatibility with the
programmatic SUT execution path introduced by BL-0127b / SP-012.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from backend.app.db.models.dataset_version import FixtureKind
from backend.app.services.eval.loader import Fixture, LoadedCorpus

AC_KPI_04_KPI_ID: Final[Literal["AC-KPI-04"]] = "AC-KPI-04"
AC_KPI_04_METRIC_KEY: Final[Literal["citation_coverage"]] = "citation_coverage"
AC_KPI_04_THRESHOLD: Final[float] = 0.9
AC_KPI_04_THRESHOLD_OPERATOR: Final[Literal[">="]] = ">="

_SUPPORTED_FIXTURE_KINDS: Final[Sequence[FixtureKind]] = ("public_regression",)
# Tolerance for float drift between recomputed and expected coverage ratios.
# 1e-9 catches any drift larger than typical float64 round-trip noise while
# tolerating JSON-round-trip rounding.
_COVERAGE_RATIO_EPSILON: Final[float] = 1e-9


@dataclass(frozen=True)
class ClaimCoverageEntry:
    """Per-claim coverage classification used by the aggregator."""

    claim_id: str
    has_citation: bool


@dataclass(frozen=True)
class CitationCoverageFixtureResult:
    """Per-fixture coverage result.

    ``recomputed_coverage_ratio`` is the canonical value (Anti-Gaming).
    ``expected_coverage_ratio`` mirrors what the fixture declares in
    ``expected_aggregate.coverage_ratio`` and is reported for diagnostic
    purposes; it is not used to compute the corpus-level metric.
    """

    fixture_id: str
    case_key: str
    total_claims: int
    claims_with_citation: int
    recomputed_coverage_ratio: float
    expected_coverage_ratio: float | None
    passed: bool
    spec_violation_reason: str | None
    sut_result: bool | None


@dataclass(frozen=True)
class CitationCoverageMetricResult:
    """Corpus-level coverage result."""

    metric_value: float
    fixture_count: int
    total_claims_across_corpus: int
    claims_with_citation_across_corpus: int
    pass_count: int
    fail_count: int
    per_fixture: tuple[CitationCoverageFixtureResult, ...]
    threshold: float
    threshold_operator: str
    threshold_met: bool
    threshold_reason: str
    manifest_violation_reason: str | None


def _is_finite_number(value: object) -> bool:
    """Return True for finite ``int`` / ``float`` (excluding ``bool``)."""

    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _manifest_violation_reason(corpus: LoadedCorpus) -> str | None:
    """Validate manifest top-level constants for AC-KPI-04.

    The loader does not enforce manifest-level KPI identifiers, so a corpus
    accidentally registered under a different KPI would otherwise pass the
    gate based on per-fixture state alone. Reject up front.
    """

    manifest = corpus.manifest
    if manifest.get("kpi_id") != AC_KPI_04_KPI_ID:
        return "manifest_violation:kpi_id"
    if manifest.get("metric") != AC_KPI_04_METRIC_KEY:
        return "manifest_violation:metric"

    threshold_value = manifest.get("threshold")
    if not isinstance(threshold_value, dict):
        return "manifest_violation:threshold"
    threshold_map: Mapping[str, object] = threshold_value
    if threshold_map.get("operator") != AC_KPI_04_THRESHOLD_OPERATOR:
        return "manifest_violation:threshold_operator"
    value = threshold_map.get("value")
    if not _is_finite_number(value):
        return "manifest_violation:threshold_value"
    if abs(float(value) - AC_KPI_04_THRESHOLD) > _COVERAGE_RATIO_EPSILON:  # type: ignore[arg-type]
        return "manifest_violation:threshold_value"
    return None


_AGGREGATE_NOT_PROVIDED: Final[object] = object()


def _raw_expected_aggregate(fixture: Fixture) -> object:
    """Return the raw ``expected_aggregate`` payload (or sentinel if absent).

    The generic loader places ``expected_aggregate`` in ``expected_json`` (the
    ``expected_*`` prefix matches the expectation heuristic), but we also read
    ``raw_json`` as a fallback so the evaluator stays robust to future
    schema-driven classification changes. The sentinel distinguishes "absent"
    from "present but malformed" so the per-fixture reason can pick the
    correct violation code.
    """

    if "expected_aggregate" in fixture.expected_json:
        return fixture.expected_json["expected_aggregate"]
    if "expected_aggregate" in fixture.raw_json:
        return fixture.raw_json["expected_aggregate"]
    return _AGGREGATE_NOT_PROVIDED


def _expected_aggregate(fixture: Fixture) -> Mapping[str, object] | None:
    candidate = _raw_expected_aggregate(fixture)
    if isinstance(candidate, dict):
        return candidate
    return None


def _expected_coverage_ratio(fixture: Fixture) -> float | None:
    aggregate = _expected_aggregate(fixture)
    if aggregate is None:
        return None
    coverage = aggregate.get("coverage_ratio")
    if not _is_finite_number(coverage):
        return None
    return float(coverage)  # type: ignore[arg-type]


def _envelope_violation_reason(fixture: Fixture) -> str | None:
    if fixture.kpi_id != AC_KPI_04_KPI_ID:
        return "spec_violation:kpi_id"
    if fixture.metric_key != AC_KPI_04_METRIC_KEY:
        return "spec_violation:metric_key"
    if fixture.fixture_kind not in _SUPPORTED_FIXTURE_KINDS:
        return "spec_violation:fixture_kind"
    return None


def _collect_claim_entries(fixture: Fixture) -> tuple[list[ClaimCoverageEntry], str | None]:
    """Walk ``input.sample_claims`` and classify each claim.

    Returns ``(entries, spec_violation_reason)``. On structural violations the
    accumulated entries up to (but not including) the offending claim are
    discarded so that the aggregator never undercounts a partial parse — both
    counts in the result come from the same (empty) list.
    """

    case_input = fixture.case_json.get("input")
    if not isinstance(case_input, dict):
        return [], "spec_violation:input"

    sample_claims = case_input.get("sample_claims")
    if not isinstance(sample_claims, list):
        return [], "spec_violation:sample_claims"

    entries: list[ClaimCoverageEntry] = []
    seen_claim_ids: set[str] = set()
    for raw_claim in sample_claims:
        if not isinstance(raw_claim, dict):
            return [], "spec_violation:sample_claims"
        claim_id = raw_claim.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id:
            return [], "spec_violation:claim_id"
        if claim_id in seen_claim_ids:
            return [], "spec_violation:duplicate_claim_id"
        seen_claim_ids.add(claim_id)

        citation_ids = raw_claim.get("citation_ids")
        if not isinstance(citation_ids, list):
            return [], "spec_violation:citation_ids"
        for citation_id in citation_ids:
            if not isinstance(citation_id, str) or not citation_id:
                return [], "spec_violation:citation_ids"
        entries.append(ClaimCoverageEntry(claim_id=claim_id, has_citation=bool(citation_ids)))

    return entries, None


def _expected_aggregate_violation_reason(
    fixture: Fixture,
    *,
    expected_ratio: float | None,
    recomputed_ratio: float,
) -> str | None:
    raw = _raw_expected_aggregate(fixture)
    if raw is _AGGREGATE_NOT_PROVIDED:
        return "spec_violation:expected_aggregate_missing"
    if not isinstance(raw, dict):
        # Present but not a JSON object (e.g., a string or a number).
        return "spec_violation:expected_aggregate"
    if expected_ratio is None:
        # Aggregate is an object but ``coverage_ratio`` is missing or malformed.
        return "spec_violation:expected_aggregate"
    if abs(recomputed_ratio - expected_ratio) > _COVERAGE_RATIO_EPSILON:
        return "spec_violation:expected_aggregate_drift"
    return None


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
    if metric_value >= AC_KPI_04_THRESHOLD:
        return "threshold_met"
    return "below_threshold"


def evaluate_citation_coverage(
    corpus: LoadedCorpus,
    *,
    sut_results: Mapping[str, bool] | None = None,
) -> CitationCoverageMetricResult:
    """Compute AC-KPI-04 ``citation_coverage`` from a loaded fixture corpus.

    The caller must load and validate the corpus via
    :func:`backend.app.services.eval.loader.load_fixture_corpus` before invoking
    this evaluator. The function is pure: no DB / file system / network access.
    Optional ``sut_results`` is consumed read-only and keyed by ``fixture_id``
    for the future BL-0127b / SP-012 programmatic SUT execution integration.

    Anti-Gaming invariant (manifest ``anti_gaming_rules.kpi_specific[0]``):
        ``citation_coverage`` is recomputed from ``input.sample_claims``; the
        fixture's ``expected_aggregate.coverage_ratio`` is consumed only as a
        drift-detection oracle.

    Per-fixture procedure:
        1. Skip non-public-regression fixtures (redacted splits are out of
           scope for batch 5d and processed in SP-022+).
        2. Validate fixture envelope (``kpi_id`` / ``metric_key`` /
           ``fixture_kind``).
        3. Walk ``input.sample_claims`` and classify each claim
           (``citation_ids`` non-empty → ``has_citation=True``).
        4. Compute ``recomputed_coverage_ratio = claims_with_citation /
           total_claims``.
        5. Compare with ``expected_aggregate.coverage_ratio`` (drift epsilon
           ``1e-9``); a drift → ``spec_violation:expected_aggregate_drift``.
        6. Optionally cross-check ``sut_results[fixture_id]``; non-boolean
           values are rejected (``sut_result_invalid_type``).

    Corpus-level metric:
        ``metric_value = sum(claims_with_citation) / sum(total_claims)``
        ``threshold_met`` ⇔ ``metric_value >= AC_KPI_04_THRESHOLD`` AND
        ``fixture_count > 0`` AND no per-fixture spec violation AND no manifest
        violation.
    """

    per_fixture: list[CitationCoverageFixtureResult] = []
    spec_violation_present = False
    total_claims_across_corpus = 0
    claims_with_citation_across_corpus = 0

    for fixture in corpus.fixtures:
        if fixture.fixture_kind not in _SUPPORTED_FIXTURE_KINDS:
            # Redacted splits are deferred to SP-022+ which adds the
            # encrypted-holdout decryption path. Skipping keeps batch 5d's
            # threshold calculation honest (public_regression only).
            continue

        entries, claim_violation = _collect_claim_entries(fixture)
        total_claims = len(entries)
        claims_with_citation = sum(1 for entry in entries if entry.has_citation)
        recomputed_ratio = claims_with_citation / total_claims if total_claims else 0.0
        expected_ratio = _expected_coverage_ratio(fixture)

        total_claims_across_corpus += total_claims
        claims_with_citation_across_corpus += claims_with_citation

        # Envelope drift takes precedence over claim-parsing drift because a
        # mis-routed corpus (wrong kpi_id) shouldn't be diagnosed as a
        # sample_claims structural problem.
        spec_reason = _envelope_violation_reason(fixture)
        if spec_reason is None and claim_violation is not None:
            spec_reason = claim_violation
        if spec_reason is None and total_claims == 0:
            spec_reason = "spec_violation:no_claims"
        if spec_reason is None:
            spec_reason = _expected_aggregate_violation_reason(
                fixture,
                expected_ratio=expected_ratio,
                recomputed_ratio=recomputed_ratio,
            )

        failure_reason = spec_reason
        sut_result: bool | None = None
        passed = failure_reason is None

        if sut_results is not None:
            if fixture.fixture_id not in sut_results:
                passed = False
                if failure_reason is None:
                    failure_reason = "sut_result_missing"
            else:
                raw_sut_value = sut_results[fixture.fixture_id]
                if not isinstance(raw_sut_value, bool):
                    # Untyped runner payloads (e.g., the string ``"false"``)
                    # must not slip through truthiness. Treat as failure with
                    # an explicit reason so the surrounding registry can act.
                    passed = False
                    if failure_reason is None:
                        failure_reason = "sut_result_invalid_type"
                else:
                    sut_result = raw_sut_value
                    if not sut_result:
                        passed = False

        if failure_reason is not None:
            spec_violation_present = True

        per_fixture.append(
            CitationCoverageFixtureResult(
                fixture_id=fixture.fixture_id,
                case_key=fixture.case_key,
                total_claims=total_claims,
                claims_with_citation=claims_with_citation,
                recomputed_coverage_ratio=recomputed_ratio,
                expected_coverage_ratio=expected_ratio,
                passed=passed,
                spec_violation_reason=failure_reason,
                sut_result=sut_result,
            )
        )

    fixture_count = len(per_fixture)
    pass_count = sum(1 for result in per_fixture if result.passed)
    fail_count = fixture_count - pass_count
    metric_value = (
        claims_with_citation_across_corpus / total_claims_across_corpus
        if total_claims_across_corpus
        else 0.0
    )
    manifest_reason = _manifest_violation_reason(corpus)
    threshold_reason = _threshold_reason(
        fixture_count=fixture_count,
        metric_value=metric_value,
        spec_violation_present=spec_violation_present,
        manifest_violation_present=manifest_reason is not None,
    )

    return CitationCoverageMetricResult(
        metric_value=metric_value,
        fixture_count=fixture_count,
        total_claims_across_corpus=total_claims_across_corpus,
        claims_with_citation_across_corpus=claims_with_citation_across_corpus,
        pass_count=pass_count,
        fail_count=fail_count,
        per_fixture=tuple(per_fixture),
        threshold=AC_KPI_04_THRESHOLD,
        threshold_operator=AC_KPI_04_THRESHOLD_OPERATOR,
        threshold_met=threshold_reason == "threshold_met",
        threshold_reason=threshold_reason,
        manifest_violation_reason=manifest_reason,
    )


__all__ = [
    "AC_KPI_04_KPI_ID",
    "AC_KPI_04_METRIC_KEY",
    "AC_KPI_04_THRESHOLD",
    "AC_KPI_04_THRESHOLD_OPERATOR",
    "CitationCoverageFixtureResult",
    "CitationCoverageMetricResult",
    "ClaimCoverageEntry",
    "evaluate_citation_coverage",
]
