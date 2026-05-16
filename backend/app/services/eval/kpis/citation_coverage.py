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

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from backend.app.db.models.dataset_version import FixtureKind
from backend.app.services.eval.loader import Fixture, LoadedCorpus

_LOGGER = logging.getLogger(__name__)

AC_KPI_04_KPI_ID: Final[Literal["AC-KPI-04"]] = "AC-KPI-04"
AC_KPI_04_METRIC_KEY: Final[Literal["citation_coverage"]] = "citation_coverage"
AC_KPI_04_THRESHOLD: Final[float] = 0.9
AC_KPI_04_THRESHOLD_OPERATOR: Final[Literal[">="]] = ">="

_SUPPORTED_FIXTURE_KINDS: Final[Sequence[FixtureKind]] = ("public_regression",)
# F-CR-003 P1 adopt: Tolerance for float drift between recomputed and expected
# coverage ratios. The original ``1e-9`` constant is too tight to survive
# float64 round-trip noise once fixtures originate from heterogeneous writers
# (Python, jq, generated JSON, etc.). ``math.isclose`` with these tolerances
# gives ~6 decimal digits of agreement, which still catches the documented
# Anti-Gaming attack (intentional 0.6 → 0.8 drift) while absorbing benign
# ulp-level noise.
_COVERAGE_RATIO_REL_TOL: Final[float] = 1e-6
_COVERAGE_RATIO_ABS_TOL: Final[float] = 1e-9
# Threshold comparison uses an explicit absolute tolerance for manifest drift
# checks (the manifest declares the canonical 0.9 threshold).
_THRESHOLD_VALUE_ABS_TOL: Final[float] = 1e-9


def _ratios_match(recomputed: float, expected: float) -> bool:
    """Return True when two ratios agree within the documented tolerances."""

    return math.isclose(
        recomputed,
        expected,
        rel_tol=_COVERAGE_RATIO_REL_TOL,
        abs_tol=_COVERAGE_RATIO_ABS_TOL,
    )


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

    ``passed`` semantics (F-CR-002 P1 adopt):
        * ``sut_attempted is False`` (caller did not supply ``sut_results`` for
          this fixture): ``passed=True`` means **spec compliance only**, the
          SUT was not executed and its outcome is not represented.
        * ``sut_attempted is True``: ``passed=True`` means **both** spec
          compliance AND the SUT returned ``True``. Downstream consumers
          building pass/fail rollups must filter on ``sut_attempted`` to
          distinguish "spec ok, SUT unverified" from "spec + SUT ok".
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
    sut_attempted: bool


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
    if abs(float(value) - AC_KPI_04_THRESHOLD) > _THRESHOLD_VALUE_ABS_TOL:  # type: ignore[arg-type]
        return "manifest_violation:threshold_value"
    return None


_AGGREGATE_NOT_PROVIDED: Final[object] = object()


def _raw_expected_aggregate(fixture: Fixture) -> object:
    """Return the raw ``expected_aggregate`` payload (or sentinel if absent).

    F-CR-001 P3 adopt: the generic loader places ``expected_aggregate`` in
    ``expected_json`` (the ``expected_*`` prefix matches the expectation
    heuristic), so we read only ``expected_json``. The sentinel distinguishes
    "absent" from "present but malformed" so the per-fixture reason can pick
    the correct violation code. If a future loader change moves the field
    elsewhere, this single accessor is the touch-point.
    """

    if "expected_aggregate" in fixture.expected_json:
        return fixture.expected_json["expected_aggregate"]
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
    recomputed_total: int,
    recomputed_with_citation: int,
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
    # F-CR-003 P1 adopt: replace fixed-epsilon equality with ``math.isclose``
    # so float64 round-trip noise across heterogeneous writers does not produce
    # false positives. Intentional Anti-Gaming drift (e.g., 0.6 → 0.8 in the
    # documented attack) still exceeds these tolerances by orders of magnitude.
    if not _ratios_match(recomputed_ratio, expected_ratio):
        return "spec_violation:expected_aggregate_drift"
    # F-PR31-R1-002 P2 adopt: the fixture schema documents ``total_claims`` and
    # ``claims_with_citation`` as additional drift oracles. Leaving them
    # unchecked lets an attacker keep ``coverage_ratio=0.6`` while declaring
    # arbitrary counts (e.g., ``total_claims=10, claims_with_citation=6`` for a
    # real 5/3 corpus). Validate the declared integer counts too — they must
    # match the recomputed values exactly because they are integers, not
    # floating-point ratios.
    #
    # F-PR31-R2-003 P2 adopt: require strict integer presence. A ``LoadedCorpus``
    # produced from persisted DB rows or any other path that bypasses the JSON
    # Schema validator could supply ``total_claims="5"`` (string) or omit the
    # field; either case must fail-closed rather than silently skip the count
    # oracle.
    if "total_claims" not in raw or not _is_non_bool_int(raw.get("total_claims")):
        return "spec_violation:expected_aggregate"
    if raw["total_claims"] != recomputed_total:
        return "spec_violation:expected_aggregate_total_drift"
    if "claims_with_citation" not in raw or not _is_non_bool_int(raw.get("claims_with_citation")):
        return "spec_violation:expected_aggregate"
    if raw["claims_with_citation"] != recomputed_with_citation:
        return "spec_violation:expected_aggregate_count_drift"
    return None


def _is_non_bool_int(value: object) -> bool:
    """Return True for plain ``int`` values (excluding ``bool`` subtype)."""

    return isinstance(value, int) and not isinstance(value, bool)


def _threshold_reason(
    *,
    fixture_count: int,
    metric_value: float,
    spec_violation_present: bool,
    manifest_violation_present: bool,
    sut_failure_present: bool,
) -> str:
    if fixture_count == 0:
        return "no_fixtures"
    if manifest_violation_present:
        return "manifest_violation"
    if spec_violation_present:
        return "spec_violation"
    # F-PR31-R1-001 P1 adopt: SUT failure must block ``threshold_met`` even
    # when the recomputed coverage already satisfies the threshold. Without
    # this guard, a corpus with ``coverage_ratio >= 0.9`` would report
    # ``threshold_met=True`` while the programmatic SUT path reported every
    # fixture as failed — letting AC-KPI-04 pass while the actual integration
    # is broken.
    if sut_failure_present:
        return "sut_failure"
    if metric_value >= AC_KPI_04_THRESHOLD:
        return "threshold_met"
    return "below_threshold"


def _warn_unknown_sut_results(corpus: LoadedCorpus, sut_results: Mapping[str, bool]) -> None:
    """Log a warning for ``sut_results`` keys that do not correspond to a fixture.

    F-CR-006 P2 adopt: aligning with the ``tenant_isolation`` aggregator,
    stale ``fixture_id`` entries in ``sut_results`` are dropped silently from
    the evaluation but surface as a warning so the caller can audit the
    drift. The warning carries only the ``fixture_id`` keys (which are
    Anti-Gaming-safe identifiers) and never embeds raw fixture content.
    """

    fixture_ids = {fixture.fixture_id for fixture in corpus.fixtures}
    for fixture_id in sorted(set(sut_results) - fixture_ids):
        _LOGGER.warning(
            "Ignoring SUT result for unknown AC-KPI-04 fixture_id=%s",
            fixture_id,
        )


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
        drift-detection oracle (``math.isclose`` with relative tolerance
        ``1e-6`` + absolute tolerance ``1e-9``).

    Per-fixture procedure:
        1. Skip non-public-regression fixtures (redacted splits are out of
           scope for batch 5d and processed in SP-022+).
        2. Validate fixture envelope (``kpi_id`` / ``metric_key`` /
           ``fixture_kind``).
        3. Walk ``input.sample_claims`` and classify each claim
           (``citation_ids`` non-empty → ``has_citation=True``).
        4. Compute ``recomputed_coverage_ratio = claims_with_citation /
           total_claims``.
        5. Compare with ``expected_aggregate.coverage_ratio``; drift →
           ``spec_violation:expected_aggregate_drift``.
        6. Optionally cross-check ``sut_results[fixture_id]``; non-boolean
           values are rejected (``sut_result_invalid_type``).

    Per-fixture reason priority (F-CR-005 P2 adopt):
        ``envelope_violation`` > ``claim_parsing_violation`` > ``no_claims`` >
        ``expected_aggregate_*`` violations. At most one reason is surfaced
        per fixture; downstream consumers must re-inspect the raw fixture if
        they need to enumerate co-occurring problems.

    SUT result handling (F-CR-006 P2 adopt):
        * Missing ``fixture_id`` in ``sut_results`` → ``sut_result_missing``.
        * Non-boolean value → ``sut_result_invalid_type``.
        * Stale ``fixture_id`` (in ``sut_results`` but not in ``corpus``) is
          logged as a warning and silently dropped (consistent with batch 5b
          ``tenant_isolation`` aggregator). The corpus is the source of truth.

    Corpus-level metric:
        ``metric_value = sum(claims_with_citation) / sum(total_claims)``
        ``threshold_met`` ⇔ ``metric_value >= AC_KPI_04_THRESHOLD`` AND
        ``fixture_count > 0`` AND no per-fixture spec violation AND no manifest
        violation **AND no SUT-side failure** (any of ``sut_result_missing`` /
        ``sut_result_invalid_type`` / a ``False`` SUT outcome causes
        ``threshold_reason="sut_failure"`` instead of ``"threshold_met"``).
        ``threshold_reason`` ∈ {``"no_fixtures"``, ``"manifest_violation"``,
        ``"spec_violation"``, ``"sut_failure"``, ``"threshold_met"``,
        ``"below_threshold"``} with that priority order.
    """

    if sut_results is not None:
        _warn_unknown_sut_results(corpus, sut_results)

    per_fixture: list[CitationCoverageFixtureResult] = []
    spec_violation_present = False
    sut_failure_present = False
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
                recomputed_total=total_claims,
                recomputed_with_citation=claims_with_citation,
            )

        failure_reason = spec_reason
        spec_side_failure = spec_reason is not None
        sut_result: bool | None = None
        sut_attempted = False
        passed = failure_reason is None

        if sut_results is not None:
            # F-CR-002 P1 adopt: ``sut_attempted`` makes the dual meaning of
            # ``passed`` explicit. We mark a SUT attempt for every fixture
            # the caller addressed — including ``sut_result_invalid_type``
            # outcomes — so the downstream registry can distinguish
            # "SUT was tried but produced garbage" from "SUT was never run".
            sut_attempted = True
            if fixture.fixture_id not in sut_results:
                # F-PR31-R2-001 P2 adopt: a missing SUT result is a runner
                # problem, not a spec issue. Surface as ``sut_failure``
                # downstream so EvalResult diagnostics blame the runner, not
                # the fixture spec.
                passed = False
                if failure_reason is None:
                    failure_reason = "sut_result_missing"
                    sut_failure_present = True
            else:
                raw_sut_value = sut_results[fixture.fixture_id]
                if not isinstance(raw_sut_value, bool):
                    # Untyped runner payloads (e.g., the string ``"false"``)
                    # must not slip through truthiness. Treat as a SUT-side
                    # failure (runner returned garbage) rather than a spec
                    # violation so the per-fixture diagnostic is accurate.
                    passed = False
                    if failure_reason is None:
                        failure_reason = "sut_result_invalid_type"
                        sut_failure_present = True
                else:
                    sut_result = raw_sut_value
                    if not sut_result:
                        passed = False
                        sut_failure_present = True

        if spec_side_failure:
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
                sut_attempted=sut_attempted,
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
        sut_failure_present=sut_failure_present,
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
