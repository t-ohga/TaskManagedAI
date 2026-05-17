"""AC-KPI-01 ``acceptance_pass_rate`` aggregator.

Computes the AC-KPI-01 KPI (受入条件達成率) from a fixture corpus loaded by
:func:`backend.app.services.eval.loader.load_fixture_corpus`. The aggregator
follows the Anti-Gaming invariant declared in the corpus manifest::

    "acceptance_pass_rate is recomputed from input.sample_acceptance_criteria,
     not copied from expected_aggregate"

i.e., the canonical pass rate is always **recomputed** from the fixture's
``input.sample_acceptance_criteria`` list. ``expected_aggregate.acceptance_pass_rate``
is consumed purely as a drift-detection oracle — a mismatch raises a spec
violation rather than silently overriding the recomputed value.

Per plan v2 §2.1 the metric is defined as::

    acceptance_pass_rate = count(status = "satisfied") /
                           count(status in {"satisfied", "rejected"})

with ``pending`` and ``deferred`` excluded from **both** numerator and
denominator (see plan v2 §2.2 rationale and §2.2.2 Anti-Gaming counter-defense
against "flip-to-deferred" attacks).

The function is pure (no DB / file system / network access). Optional
``sut_results`` is consumed read-only for forward-compatibility with the
BL-0127b / SP-012 programmatic SUT execution path.

The KPI is "higher is better": ``threshold_met`` requires the recomputed
``acceptance_pass_rate`` to be **at or above** ``AC_KPI_01_THRESHOLD``.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from backend.app.db.models.dataset_version import FixtureKind
from backend.app.services.eval.loader import Fixture, LoadedCorpus

_LOGGER = logging.getLogger(__name__)

AC_KPI_01_KPI_ID: Final[Literal["AC-KPI-01"]] = "AC-KPI-01"
AC_KPI_01_METRIC_KEY: Final[Literal["acceptance_pass_rate"]] = "acceptance_pass_rate"
AC_KPI_01_THRESHOLD: Final[float] = 0.6
AC_KPI_01_THRESHOLD_OPERATOR: Final[Literal[">="]] = ">="

# AC-KPI-01 contract: AcceptanceCriteria.status enum is the canonical source.
# See ``backend/app/db/models/acceptance_criteria.py`` ``AcceptanceCriteriaStatus``
# (Literal) and ``acceptance_criteria_ck_status`` DB CHECK constraint. The
# four-element frozenset below is one of the five sources cross-checked by
# the test suite (see plan v2 §2.3 and §7.1).
_KNOWN_ACCEPTANCE_STATUSES: Final[frozenset[str]] = frozenset(
    {"pending", "satisfied", "rejected", "deferred"}
)
# Only ``satisfied`` rows contribute to the numerator.
_PASS_NUMERATOR_STATUSES: Final[frozenset[str]] = frozenset({"satisfied"})
# Only ``satisfied`` and ``rejected`` rows contribute to the denominator
# (i.e., only evaluated criteria count). ``pending`` (not yet evaluated) and
# ``deferred`` (explicitly out-of-scope) are excluded from both.
_PASS_DENOMINATOR_STATUSES: Final[frozenset[str]] = frozenset(
    {"satisfied", "rejected"}
)

# Compile-time partition invariant (plan v2 §4.1 / HIGH-003 superset).
# This catches future enum drift at import time before any test runs.
# Runtime raise (not assert) so the check survives ``python -O`` and the
# ruff S101 (assert in production code) lint.
if not (_PASS_NUMERATOR_STATUSES < _PASS_DENOMINATOR_STATUSES):
    raise RuntimeError(
        "AC-KPI-01 partition invariant violation: "
        "_PASS_NUMERATOR_STATUSES must be a proper subset of "
        "_PASS_DENOMINATOR_STATUSES."
    )
if not (_PASS_DENOMINATOR_STATUSES <= _KNOWN_ACCEPTANCE_STATUSES):
    raise RuntimeError(
        "AC-KPI-01 partition invariant violation: "
        "_PASS_DENOMINATOR_STATUSES must be a subset of "
        "_KNOWN_ACCEPTANCE_STATUSES."
    )
if _KNOWN_ACCEPTANCE_STATUSES - _PASS_DENOMINATOR_STATUSES != frozenset(
    {"pending", "deferred"}
):
    raise RuntimeError(
        "AC-KPI-01 partition invariant violation: excluded set must equal "
        "{'pending', 'deferred'}."
    )

_SUPPORTED_FIXTURE_KINDS: Final[Sequence[FixtureKind]] = ("public_regression",)

# Tolerance rationale (plan v2 §4.1 / MEDIUM-005 adopt):
# acceptance_pass_rate is an exact rational (int / int). float64 round-trip
# noise across heterogeneous fixture writers is ~1e-15. Mirror batch 5d
# (citation_coverage, also a ratio metric) tolerance levels — rel_tol=1e-6 +
# abs_tol=1e-9. batch 5e money tolerance (``rel_tol=0.0, abs_tol=1e-6`` with
# ``_normalize_money`` ROUND_HALF_UP) does NOT apply to ratios; money
# precision is unrelated.
_RATIO_REL_TOL: Final[float] = 1e-6
_RATIO_ABS_TOL: Final[float] = 1e-9
_THRESHOLD_VALUE_ABS_TOL: Final[float] = 1e-9

# Sentinel that distinguishes "key absent" from "key present but malformed"
# (mirrors the citation_coverage / cost_per_completed_task aggregators).
_AGGREGATE_NOT_PROVIDED: Final[object] = object()

# Lowercase canonical RFC 4122 UUID pattern. Mirrors batch 5e to keep
# duplicate-detection bypass via mixed-case UUID variants closed.
_UUID_TEXT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

# Anti-Gaming sanity check threshold (plan v2 §2.2.2 #3): emit a log warning
# when a fixture has > 50% of its criteria as ``deferred``. Informational
# only — does not affect ``passed`` or ``threshold_met``.
_DEFERRED_RATIO_WARNING_THRESHOLD: Final[float] = 0.5


@dataclass(frozen=True)
class SampleAcceptanceCriterion:
    """A single acceptance criterion extracted from
    ``input.sample_acceptance_criteria``.

    Type rationale (plan v2 §4.2 / HIGH-004 adopt):
        All four ID fields are PG_UUID strings, mirroring the DB schema in
        ``backend/app/db/models/acceptance_criteria.py`` (criterion_id =
        ``id``, project_id, ticket_id all ``PG_UUID(as_uuid=True)``). This
        differs from batch 5e ``SampleRun.project_id: int``, which is a
        fixture-synthetic identifier for AgentRun aggregation only; the
        real ``agent_runs.project_id`` ↔ AgentRun bind is deferred to
        SP-012. For AC-KPI-01, the fixture schema matches the real DB
        column types directly because each criterion_id is a globally
        unique acceptance row.
    """

    criterion_id: str
    tenant_id: int
    project_id: str
    ticket_id: str
    status: str


@dataclass(frozen=True)
class AcceptancePassRateFixtureResult:
    """Per-fixture acceptance-pass-rate result.

    The dual ``spec_violation_reason`` / ``sut_failure_reason`` contract is
    identical to the batch 5d/5e aggregators: at most one of these fields
    is non-None per row. ``passed=True`` with ``sut_attempted=False`` means
    **spec compliance only** (SUT was not executed); ``passed=True`` with
    ``sut_attempted=True`` means both spec and SUT pass.
    """

    fixture_id: str
    case_key: str
    total_criteria: int
    evaluated_criteria: int  # = satisfied + rejected
    satisfied_criteria: int  # numerator
    rejected_criteria: int  # drift oracle (plan v2 MEDIUM-004)
    pending_criteria: int  # excluded from both numerator and denominator
    deferred_criteria: int  # excluded from both numerator and denominator
    recomputed_pass_rate: float | None  # None when evaluated_criteria == 0
    expected_pass_rate: float | None
    passed: bool
    spec_violation_reason: str | None
    sut_failure_reason: str | None
    sut_result: bool | None
    sut_attempted: bool


@dataclass(frozen=True)
class AcceptancePassRateMetricResult:
    """Corpus-level acceptance-pass-rate result.

    ``metric_value`` is the corpus-wide recomputed
    ``sum(satisfied) / sum(satisfied + rejected)``. When the corpus has
    zero evaluated criteria, ``metric_value`` is ``None`` (the KPI is
    undefined) and ``threshold_met`` is ``False`` with
    ``threshold_reason="no_evaluated_criteria"``.
    """

    metric_value: float | None
    fixture_count: int
    total_criteria_across_corpus: int
    evaluated_criteria_across_corpus: int
    satisfied_criteria_across_corpus: int
    rejected_criteria_across_corpus: int
    pass_count: int
    fail_count: int
    per_fixture: tuple[AcceptancePassRateFixtureResult, ...]
    threshold: float
    threshold_operator: str
    threshold_met: bool
    threshold_reason: str
    manifest_violation_reason: str | None


def _is_finite_number(value: object) -> bool:
    """Return True for finite ``int`` / ``float`` (excluding ``bool``).

    Mirrors the batch 5e (F-PR32-R6-002 P2 adopt) overflow guard: persisted
    corpora that bypass JSON Schema can ship a Python integer with hundreds
    of digits (e.g., ``10**500``). ``float(huge_int)`` raises
    ``OverflowError`` and would otherwise crash the eval run. Catch the
    overflow and return ``False`` so the caller emits ``spec_violation:*``
    instead of an uncaught exception.
    """

    if not isinstance(value, int | float):
        return False
    if isinstance(value, bool):
        return False
    try:
        as_float = float(value)
    except (OverflowError, ValueError):
        return False
    return math.isfinite(as_float)


def _is_non_bool_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _ratios_match(recomputed: float, expected: float) -> bool:
    """Return True when two ratios agree within the documented tolerances."""

    return math.isclose(
        recomputed, expected, rel_tol=_RATIO_REL_TOL, abs_tol=_RATIO_ABS_TOL
    )


def _manifest_violation_reason(corpus: LoadedCorpus) -> str | None:
    """Validate manifest top-level constants for AC-KPI-01."""

    manifest = corpus.manifest
    if manifest.get("kpi_id") != AC_KPI_01_KPI_ID:
        return "manifest_violation:kpi_id"
    if manifest.get("metric") != AC_KPI_01_METRIC_KEY:
        return "manifest_violation:metric"

    threshold = manifest.get("threshold")
    if not isinstance(threshold, dict):
        return "manifest_violation:threshold"
    threshold_map: Mapping[str, object] = threshold
    operator = threshold_map.get("operator")
    if operator != AC_KPI_01_THRESHOLD_OPERATOR:
        return "manifest_violation:threshold_operator"
    threshold_value = threshold_map.get("value")
    if not _is_finite_number(threshold_value):
        return "manifest_violation:threshold_value"
    if (
        abs(float(threshold_value) - AC_KPI_01_THRESHOLD)  # type: ignore[arg-type]
        > _THRESHOLD_VALUE_ABS_TOL
    ):
        return "manifest_violation:threshold_value"
    return None


def _envelope_violation_reason(fixture: Fixture) -> str | None:
    if fixture.kpi_id != AC_KPI_01_KPI_ID:
        return "spec_violation:kpi_id"
    if fixture.metric_key != AC_KPI_01_METRIC_KEY:
        return "spec_violation:metric_key"
    if fixture.fixture_kind not in _SUPPORTED_FIXTURE_KINDS:
        return "spec_violation:fixture_kind"
    return None


def _validate_uuid_text(value: object) -> bool:
    if not isinstance(value, str):
        return False
    if not _UUID_TEXT_PATTERN.fullmatch(value):
        return False
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _fixture_threshold(fixture: Fixture) -> object:
    if "threshold" in fixture.expected_json:
        return fixture.expected_json["threshold"]
    if "threshold" in fixture.raw_json:
        return fixture.raw_json["threshold"]
    return _AGGREGATE_NOT_PROVIDED


def _fixture_threshold_violation_reason(fixture: Fixture) -> str | None:
    """Validate the fixture-declared ``threshold`` against AC-KPI-01 constants.

    The fixture-level ``threshold`` may be ``None`` / absent (the manifest is
    canonical); however when present and non-null it must match the
    AC-KPI-01 contract exactly so a persisted corpus cannot declare a
    relaxed acceptance threshold.
    """

    threshold = _fixture_threshold(fixture)
    if threshold is _AGGREGATE_NOT_PROVIDED or threshold is None:
        return None
    if not isinstance(threshold, dict):
        return "spec_violation:threshold"
    declared_op = threshold.get("operator")
    if declared_op != AC_KPI_01_THRESHOLD_OPERATOR:
        return "spec_violation:threshold_operator"
    declared_value = threshold.get("value")
    if not _is_finite_number(declared_value):
        return "spec_violation:threshold_value"
    if (
        abs(float(declared_value) - AC_KPI_01_THRESHOLD)  # type: ignore[arg-type]
        > _THRESHOLD_VALUE_ABS_TOL
    ):
        return "spec_violation:threshold_value"
    return None


def _collect_sample_criteria(
    fixture: Fixture,
    *,
    corpus_seen_criterion_ids: set[str] | None = None,
) -> tuple[list[SampleAcceptanceCriterion], str | None, frozenset[str]]:
    """Walk ``input.sample_acceptance_criteria`` and validate each row.

    Returns ``(criteria, spec_violation_reason, pending_corpus_ids)``. On
    any structural violation the parser returns an empty list and an empty
    ``pending_corpus_ids`` so the aggregator does not undercount via a
    partial parse.

    Plan v2 §4.3 + §6 #1 / #9 (batch 5e F-PR32-R6-001 carry-over): this
    function **only stages** the corpus-wide UUID delta in
    ``pending_corpus_ids`` and never mutates the caller-owned
    ``corpus_seen_criterion_ids`` set. The orchestrator
    (``evaluate_acceptance_pass_rate``) is responsible for merging the
    staged set only after **all** fixture validation gates pass (envelope /
    threshold / sample_criteria / expected_aggregate). This prevents an
    invalid fixture from leaking its UUIDs and causing a later valid
    fixture to be falsely flagged as
    ``duplicate_criterion_id_across_fixtures``.
    """

    _EMPTY_PENDING: frozenset[str] = frozenset()
    case_input = fixture.case_json.get("input")
    if not isinstance(case_input, dict):
        return [], "spec_violation:input", _EMPTY_PENDING

    sample_criteria = case_input.get("sample_acceptance_criteria")
    if not isinstance(sample_criteria, list):
        return [], "spec_violation:sample_criteria", _EMPTY_PENDING
    if not sample_criteria:
        return [], "spec_violation:sample_criteria", _EMPTY_PENDING

    criteria: list[SampleAcceptanceCriterion] = []
    seen_criterion_ids: set[str] = set()
    pending_corpus_ids: set[str] = set()
    for raw_row in sample_criteria:
        if not isinstance(raw_row, dict):
            return [], "spec_violation:sample_criteria", _EMPTY_PENDING

        criterion_id = raw_row.get("criterion_id")
        if not _validate_uuid_text(criterion_id) or not isinstance(
            criterion_id, str
        ):
            return [], "spec_violation:criterion_id", _EMPTY_PENDING
        if criterion_id in seen_criterion_ids:
            return [], "spec_violation:duplicate_criterion_id", _EMPTY_PENDING
        if (
            corpus_seen_criterion_ids is not None
            and criterion_id in corpus_seen_criterion_ids
        ):
            return (
                [],
                "spec_violation:duplicate_criterion_id_across_fixtures",
                _EMPTY_PENDING,
            )
        seen_criterion_ids.add(criterion_id)
        if corpus_seen_criterion_ids is not None:
            pending_corpus_ids.add(criterion_id)

        tenant_id = raw_row.get("tenant_id")
        if not _is_non_bool_int(tenant_id) or tenant_id < 1:  # type: ignore[operator]
            return [], "spec_violation:tenant_id", _EMPTY_PENDING

        project_id = raw_row.get("project_id")
        if not _validate_uuid_text(project_id) or not isinstance(
            project_id, str
        ):
            return [], "spec_violation:project_id", _EMPTY_PENDING

        ticket_id = raw_row.get("ticket_id")
        if not _validate_uuid_text(ticket_id) or not isinstance(ticket_id, str):
            return [], "spec_violation:ticket_id", _EMPTY_PENDING

        status = raw_row.get("status")
        if not isinstance(status, str) or status not in _KNOWN_ACCEPTANCE_STATUSES:
            return [], "spec_violation:status", _EMPTY_PENDING

        criteria.append(
            SampleAcceptanceCriterion(
                criterion_id=criterion_id,
                tenant_id=int(tenant_id),  # type: ignore[arg-type]
                project_id=project_id,
                ticket_id=ticket_id,
                status=status,
            )
        )

    return criteria, None, frozenset(pending_corpus_ids)


def _expected_aggregate_value(fixture: Fixture) -> object:
    if "expected_aggregate" in fixture.expected_json:
        return fixture.expected_json["expected_aggregate"]
    if "expected_aggregate" in fixture.raw_json:
        return fixture.raw_json["expected_aggregate"]
    return _AGGREGATE_NOT_PROVIDED


def _expected_aggregate_violation_reason(
    fixture: Fixture,
    *,
    recomputed_total_criteria: int,
    recomputed_evaluated_criteria: int,
    recomputed_satisfied_criteria: int,
    recomputed_rejected_criteria: int,
    recomputed_pending_criteria: int,
    recomputed_deferred_criteria: int,
    recomputed_pass_rate: float | None,
) -> str | None:
    raw = _expected_aggregate_value(fixture)
    if raw is _AGGREGATE_NOT_PROVIDED:
        return "spec_violation:expected_aggregate_missing"
    if not isinstance(raw, dict):
        return "spec_violation:expected_aggregate"

    # Each declared count field must be a strict non-negative non-bool int
    # (plan v2 §6 #2). Non-bool int requirement prevents True/False from
    # silently passing the int check.
    declared_total = raw.get("total_criteria")
    if not _is_non_bool_int(declared_total) or declared_total < 0:  # type: ignore[operator]
        return "spec_violation:expected_aggregate"
    declared_evaluated = raw.get("evaluated_criteria")
    if not _is_non_bool_int(declared_evaluated) or declared_evaluated < 0:  # type: ignore[operator]
        return "spec_violation:expected_aggregate"
    declared_satisfied = raw.get("satisfied_criteria")
    if not _is_non_bool_int(declared_satisfied) or declared_satisfied < 0:  # type: ignore[operator]
        return "spec_violation:expected_aggregate"
    declared_rejected = raw.get("rejected_criteria")
    if not _is_non_bool_int(declared_rejected) or declared_rejected < 0:  # type: ignore[operator]
        return "spec_violation:expected_aggregate"
    declared_pending = raw.get("pending_criteria")
    if not _is_non_bool_int(declared_pending) or declared_pending < 0:  # type: ignore[operator]
        return "spec_violation:expected_aggregate"
    declared_deferred = raw.get("deferred_criteria")
    if not _is_non_bool_int(declared_deferred) or declared_deferred < 0:  # type: ignore[operator]
        return "spec_violation:expected_aggregate"

    if declared_total != recomputed_total_criteria:
        return "spec_violation:expected_aggregate_total_drift"
    if declared_evaluated != recomputed_evaluated_criteria:
        return "spec_violation:expected_aggregate_evaluated_drift"
    if declared_satisfied != recomputed_satisfied_criteria:
        return "spec_violation:expected_aggregate_satisfied_drift"
    if declared_rejected != recomputed_rejected_criteria:
        return "spec_violation:expected_aggregate_rejected_drift"
    if declared_pending != recomputed_pending_criteria:
        return "spec_violation:expected_aggregate_pending_drift"
    if declared_deferred != recomputed_deferred_criteria:
        return "spec_violation:expected_aggregate_deferred_drift"

    # Closure invariant (plan v2 §6 #10 / MEDIUM-004): the declared status
    # counts must partition ``total_criteria`` exactly.
    #
    # F-PR33-001 (code-reviewer PR #33 HIGH adopt) note: this branch is
    # **defense-in-depth** and currently unreachable through the public
    # API because each declared count above is already required to equal
    # its recomputed counterpart, and ``_collect_sample_criteria``
    # partitions every accepted row into one of the four status buckets
    # exactly. The check stays here as a guardrail against future bugs in
    # ``_collect_sample_criteria`` (e.g., a 5th status leaking in via
    # incomplete enum updates) that would otherwise produce inconsistent
    # bucket counts. SP-012 should revisit if a stricter raw-input
    # partition recompute is introduced.
    if (
        declared_satisfied + declared_rejected + declared_pending + declared_deferred
        != declared_total
    ):
        return "spec_violation:expected_aggregate_closure_violation"

    # ``acceptance_pass_rate`` drift check.
    if "acceptance_pass_rate" not in raw:
        return "spec_violation:expected_aggregate"
    declared_rate_raw = raw["acceptance_pass_rate"]
    if recomputed_pass_rate is None:
        # Plan v2 §6 #4 (batch 5e F-PR32-R1-003 + R3-002 carry-over): with
        # zero evaluated criteria the recomputed ratio is undefined. The
        # fixture must declare either ``None`` (preferred — the schema
        # permits it) or ``0.0`` (canonical zero sentinel). Any other
        # value is drift.
        if declared_rate_raw is None:
            pass  # acceptable null sentinel
        elif (
            _is_finite_number(declared_rate_raw)
            and float(declared_rate_raw) == 0.0
        ):
            pass  # acceptable zero sentinel
        else:
            return "spec_violation:expected_aggregate_pass_rate_drift"
    else:
        if not _is_finite_number(declared_rate_raw):
            return "spec_violation:expected_aggregate"
        # Plan v2 §6 #3 (batch 5e F-PR32-R5-002 carry-over): reject
        # out-of-range declared ratios before applying the tolerance.
        declared_rate = float(declared_rate_raw)
        if declared_rate < 0.0 or declared_rate > 1.0:
            return "spec_violation:expected_aggregate"
        if not _ratios_match(declared_rate, recomputed_pass_rate):
            return "spec_violation:expected_aggregate_pass_rate_drift"

    return None


def _warn_unknown_sut_results(
    corpus: LoadedCorpus, sut_results: Mapping[str, bool]
) -> None:
    fixture_ids = {fixture.fixture_id for fixture in corpus.fixtures}
    for fixture_id in sorted(set(sut_results) - fixture_ids):
        _LOGGER.warning(
            "Ignoring SUT result for unknown AC-KPI-01 fixture_id=%s",
            fixture_id,
        )


def _maybe_warn_high_deferred(
    fixture_id: str, deferred_criteria: int, total_criteria: int
) -> None:
    """Plan v2 §2.2.2 #3: informational sanity warning when the deferred
    ratio is high. Does NOT affect ``passed`` or ``threshold_met`` — purely
    log output for SP-012 observability.
    """

    if total_criteria <= 0:
        return
    deferred_ratio = deferred_criteria / total_criteria
    if deferred_ratio > _DEFERRED_RATIO_WARNING_THRESHOLD:
        _LOGGER.warning(
            "AC-KPI-01 fixture %s declares deferred_ratio=%.3f (> %.2f); "
            "review for Anti-Gaming deferred bypass.",
            fixture_id,
            deferred_ratio,
            _DEFERRED_RATIO_WARNING_THRESHOLD,
        )


def _threshold_reason(
    *,
    fixture_count: int,
    evaluated_criteria: int,
    metric_value: float | None,
    spec_violation_present: bool,
    manifest_violation_present: bool,
    sut_failure_present: bool,
) -> str:
    """Plan v2 §4.2.1 priority order."""

    if fixture_count == 0:
        return "no_fixtures"
    if manifest_violation_present:
        return "manifest_violation"
    if spec_violation_present:
        return "spec_violation"
    if sut_failure_present:
        return "sut_failure"
    if evaluated_criteria == 0 or metric_value is None:
        return "no_evaluated_criteria"
    if metric_value >= AC_KPI_01_THRESHOLD - _THRESHOLD_VALUE_ABS_TOL:
        return "threshold_met"
    return "below_threshold"


def _expected_pass_rate_from_aggregate(fixture: Fixture) -> float | None:
    """Return the fixture's declared ``acceptance_pass_rate`` for diagnostic
    surfacing in the per-fixture row. Returns ``None`` for any malformed /
    missing value.
    """

    raw = _expected_aggregate_value(fixture)
    if not isinstance(raw, dict):
        return None
    declared = raw.get("acceptance_pass_rate")
    if declared is None:
        return None
    if not _is_finite_number(declared):
        return None
    return float(declared)


def evaluate_acceptance_pass_rate(
    corpus: LoadedCorpus,
    *,
    sut_results: Mapping[str, bool] | None = None,
) -> AcceptancePassRateMetricResult:
    """Compute AC-KPI-01 ``acceptance_pass_rate`` from a loaded corpus.

    The caller must load and validate the corpus via
    :func:`backend.app.services.eval.loader.load_fixture_corpus` first. The
    function is pure: no DB / file system / network access. Optional
    ``sut_results`` is consumed read-only and keyed by ``fixture_id``.

    Anti-Gaming invariants (manifest ``anti_gaming_rules.kpi_specific``):

    * ``acceptance_pass_rate`` is **always recomputed** from
      ``input.sample_acceptance_criteria``; the fixture's declared
      ``expected_aggregate.acceptance_pass_rate`` is consumed as a
      drift-detection oracle only.
    * Only criteria with status in ``{"satisfied", "rejected"}`` contribute
      to the numerator and denominator. ``pending`` (not yet evaluated) and
      ``deferred`` (explicitly out-of-scope) are excluded from both (see
      plan v2 §2.2 rationale).
    * Unknown statuses reject as ``spec_violation:status`` so future
      ``AcceptanceCriteriaStatus`` enum changes do not quietly bypass the
      filter (5+ source enum integrity).

    Per-fixture procedure:
        1. Skip non-public-regression fixtures (redacted splits are SP-022+).
        2. Validate the fixture envelope and optional fixture-level
           ``threshold`` against AC-KPI-01 constants.
        3. Walk ``input.sample_acceptance_criteria`` validating UUID /
           tenant_id / project_id / ticket_id / status shapes.
        4. Bucket each criterion by status; recompute
           ``acceptance_pass_rate = satisfied / (satisfied + rejected)``.
        5. Drift-check against ``expected_aggregate`` (total / evaluated /
           satisfied / rejected / pending / deferred / pass_rate, closure
           invariant).
        6. Optionally cross-check ``sut_results[fixture_id]``; non-boolean
           values reject as ``sut_result_invalid_type``.

    Per-fixture reason priority:
        envelope_violation > fixture_threshold_violation >
        criteria_parsing_violation > expected_aggregate_* violations. SUT
        processing is **skipped** entirely when a spec violation is
        detected, keeping the dataclass invariant (at most one of
        ``spec_violation_reason`` / ``sut_failure_reason`` non-None).

    Corpus-level metric:
        ``metric_value = sum(satisfied) / sum(satisfied + rejected)``
        ``threshold_met`` ⇔ ``metric_value >= AC_KPI_01_THRESHOLD`` AND
        ``fixture_count > 0`` AND ``evaluated_criteria > 0`` AND no
        spec/manifest/SUT failure.
        ``threshold_reason`` ∈ {``no_fixtures``, ``manifest_violation``,
        ``spec_violation``, ``sut_failure``, ``no_evaluated_criteria``,
        ``threshold_met``, ``below_threshold``} with that priority order.
    """

    if sut_results is not None:
        _warn_unknown_sut_results(corpus, sut_results)

    per_fixture: list[AcceptancePassRateFixtureResult] = []
    spec_violation_present = False
    sut_failure_present = False
    total_criteria_across_corpus = 0
    evaluated_criteria_across_corpus = 0
    satisfied_criteria_across_corpus = 0
    rejected_criteria_across_corpus = 0
    # Plan v2 §6 #1 / batch 5e F-PR32-R3-001 carry-over: share the seen-set
    # across fixtures so cross-fixture duplicate criterion_id values are
    # flagged.
    corpus_seen_criterion_ids: set[str] = set()

    for fixture in corpus.fixtures:
        if fixture.fixture_kind not in _SUPPORTED_FIXTURE_KINDS:
            # Redacted splits deferred to SP-022+ (encrypted-holdout path).
            continue

        envelope_reason = _envelope_violation_reason(fixture)
        threshold_reason_violation = (
            _fixture_threshold_violation_reason(fixture)
            if envelope_reason is None
            else None
        )
        criteria, criteria_violation, pending_corpus_ids = _collect_sample_criteria(
            fixture,
            corpus_seen_criterion_ids=corpus_seen_criterion_ids,
        )

        # Bucket by status.
        satisfied = [c for c in criteria if c.status == "satisfied"]
        rejected = [c for c in criteria if c.status == "rejected"]
        pending = [c for c in criteria if c.status == "pending"]
        deferred = [c for c in criteria if c.status == "deferred"]
        satisfied_count = len(satisfied)
        rejected_count = len(rejected)
        pending_count = len(pending)
        deferred_count = len(deferred)
        evaluated_count = satisfied_count + rejected_count
        total_count = len(criteria)
        recomputed_rate: float | None = (
            satisfied_count / evaluated_count if evaluated_count else None
        )

        spec_reason: str | None = envelope_reason
        if spec_reason is None and threshold_reason_violation is not None:
            spec_reason = threshold_reason_violation
        if spec_reason is None and criteria_violation is not None:
            spec_reason = criteria_violation
        if spec_reason is None:
            spec_reason = _expected_aggregate_violation_reason(
                fixture,
                recomputed_total_criteria=total_count,
                recomputed_evaluated_criteria=evaluated_count,
                recomputed_satisfied_criteria=satisfied_count,
                recomputed_rejected_criteria=rejected_count,
                recomputed_pending_criteria=pending_count,
                recomputed_deferred_criteria=deferred_count,
                recomputed_pass_rate=recomputed_rate,
            )

        # Plan v2 §6 #9 / batch 5e F-PR32-R6-001 carry-over: gate both
        # corpus-wide totals **and** the cross-fixture seen-set commit on
        # the final spec_reason. An otherwise-structurally-valid set of
        # sample_criteria in a fixture that fails its envelope / threshold /
        # expected_aggregate gates must not leak its UUIDs (which would
        # falsely flag a later valid fixture as
        # ``duplicate_criterion_id_across_fixtures``) nor inflate the
        # corpus-level totals.
        if spec_reason is None:
            total_criteria_across_corpus += total_count
            evaluated_criteria_across_corpus += evaluated_count
            satisfied_criteria_across_corpus += satisfied_count
            rejected_criteria_across_corpus += rejected_count
            if pending_corpus_ids:
                corpus_seen_criterion_ids.update(pending_corpus_ids)
            # Informational warning only when the fixture is otherwise valid.
            _maybe_warn_high_deferred(
                fixture.fixture_id, deferred_count, total_count
            )

        spec_violation_reason = spec_reason
        sut_failure_reason: str | None = None
        sut_result: bool | None = None
        sut_attempted = False
        passed = spec_reason is None

        # Mirror batch 5d/5e: skip SUT processing entirely when the
        # fixture spec is invalid so the dataclass contract holds (at most
        # one of spec_violation_reason / sut_failure_reason non-None).
        if sut_results is not None and spec_violation_reason is None:
            sut_attempted = True
            if fixture.fixture_id not in sut_results:
                passed = False
                sut_failure_reason = "sut_result_missing"
                sut_failure_present = True
            else:
                raw_sut_value = sut_results[fixture.fixture_id]
                if not isinstance(raw_sut_value, bool):
                    passed = False
                    sut_failure_reason = "sut_result_invalid_type"
                    sut_failure_present = True
                else:
                    sut_result = raw_sut_value
                    if not sut_result:
                        passed = False
                        sut_failure_reason = "sut_returned_false"
                        sut_failure_present = True

        if spec_violation_reason is not None:
            spec_violation_present = True

        per_fixture.append(
            AcceptancePassRateFixtureResult(
                fixture_id=fixture.fixture_id,
                case_key=fixture.case_key,
                total_criteria=total_count,
                evaluated_criteria=evaluated_count,
                satisfied_criteria=satisfied_count,
                rejected_criteria=rejected_count,
                pending_criteria=pending_count,
                deferred_criteria=deferred_count,
                recomputed_pass_rate=recomputed_rate,
                expected_pass_rate=_expected_pass_rate_from_aggregate(fixture),
                passed=passed,
                spec_violation_reason=spec_violation_reason,
                sut_failure_reason=sut_failure_reason,
                sut_result=sut_result,
                sut_attempted=sut_attempted,
            )
        )

    fixture_count = len(per_fixture)
    pass_count = sum(1 for result in per_fixture if result.passed)
    fail_count = fixture_count - pass_count
    metric_value: float | None = (
        satisfied_criteria_across_corpus / evaluated_criteria_across_corpus
        if evaluated_criteria_across_corpus
        else None
    )
    manifest_reason = _manifest_violation_reason(corpus)
    threshold_reason = _threshold_reason(
        fixture_count=fixture_count,
        evaluated_criteria=evaluated_criteria_across_corpus,
        metric_value=metric_value,
        spec_violation_present=spec_violation_present,
        manifest_violation_present=manifest_reason is not None,
        sut_failure_present=sut_failure_present,
    )

    return AcceptancePassRateMetricResult(
        metric_value=metric_value,
        fixture_count=fixture_count,
        total_criteria_across_corpus=total_criteria_across_corpus,
        evaluated_criteria_across_corpus=evaluated_criteria_across_corpus,
        satisfied_criteria_across_corpus=satisfied_criteria_across_corpus,
        rejected_criteria_across_corpus=rejected_criteria_across_corpus,
        pass_count=pass_count,
        fail_count=fail_count,
        per_fixture=tuple(per_fixture),
        threshold=AC_KPI_01_THRESHOLD,
        threshold_operator=AC_KPI_01_THRESHOLD_OPERATOR,
        threshold_met=threshold_reason == "threshold_met",
        threshold_reason=threshold_reason,
        manifest_violation_reason=manifest_reason,
    )


__all__ = [
    "AC_KPI_01_KPI_ID",
    "AC_KPI_01_METRIC_KEY",
    "AC_KPI_01_THRESHOLD",
    "AC_KPI_01_THRESHOLD_OPERATOR",
    "AcceptancePassRateFixtureResult",
    "AcceptancePassRateMetricResult",
    "SampleAcceptanceCriterion",
    "evaluate_acceptance_pass_rate",
]
