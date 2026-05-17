"""AC-KPI-05 ``cost_per_completed_task`` aggregator.

Computes the AC-KPI-05 KPI (USD cost per completed AgentRun) from a fixture
corpus loaded by :func:`backend.app.services.eval.loader.load_fixture_corpus`.

Anti-Gaming invariants (manifest ``anti_gaming_rules.kpi_specific``):

1. ``cost_per_completed_task is calculated from normalized provider usage
   after BudgetGuard accounting`` — the aggregator never trusts the fixture's
   declared ``cost_per_completed_task_usd``; it always **recomputes** the
   metric from ``input.sample_runs``.
2. ``only AgentRun status=completed contributes to numerator and denominator``
   — failed / cancelled / refused / repair-exhausted runs must be filtered out
   of both the cost numerator and the completed-task denominator.

The function is pure (no DB / file system / network access). Optional
``sut_results`` is consumed read-only for forward-compatibility with the
BL-0127b / SP-012 programmatic SUT execution path.

The KPI is "lower is better": ``threshold_met`` requires the recomputed
``cost_per_completed_task_usd`` to be **at or below** ``AC_KPI_05_THRESHOLD_USD``.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Final, Literal
from uuid import UUID

from backend.app.db.models.dataset_version import FixtureKind
from backend.app.services.eval.loader import Fixture, LoadedCorpus

_LOGGER = logging.getLogger(__name__)

AC_KPI_05_KPI_ID: Final[Literal["AC-KPI-05"]] = "AC-KPI-05"
AC_KPI_05_METRIC_KEY: Final[Literal["cost_per_completed_task"]] = "cost_per_completed_task"
AC_KPI_05_THRESHOLD_USD: Final[float] = 0.5
AC_KPI_05_CURRENCY: Final[Literal["USD"]] = "USD"

# AC-KPI-05 contract: only AgentRun ``status=completed`` runs contribute to the
# numerator and denominator. The wider 16-state AgentRun status enum (see
# ``backend/app/db/models/agent_run.py``) is accepted on input — non-completed
# runs are simply filtered out — but unknown / missing status values are a
# spec violation because the fixture cannot be Anti-Gaming-safely classified.
_KPI_05_COMPLETED_STATUS: Final[Literal["completed"]] = "completed"

# AgentRun 16 状態 (recognised values; runs outside this set are rejected as
# spec violations so a future status name change can't bypass the
# completed-status filter silently).
_KNOWN_AGENT_RUN_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "queued",
        "gathering_context",
        "running",
        "generated_artifact",
        "schema_validated",
        "policy_linted",
        "diff_ready",
        "waiting_approval",
        "blocked",
        "provider_refused",
        "provider_incomplete",
        "validation_failed",
        "repair_exhausted",
        "completed",
        "failed",
        "cancelled",
    }
)

_SUPPORTED_FIXTURE_KINDS: Final[Sequence[FixtureKind]] = ("public_regression",)

# Drift tolerances mirror batch 5d (citation_coverage) so float64 round-trip
# noise across heterogeneous fixture writers cannot trigger false-positive
# drift, but documented attack-pattern drifts (e.g., declaring $0.2 while the
# real run set sums to $0.6) exceed these orders of magnitude trivially.
#
# F-PR32-R3-003 P2 adopt: ``abs_tol`` was tightened to ``1e-6`` so the
# evaluator's drift oracle matches the existing
# ``eval/quality/cost_per_completed_task/loader.py`` which rounds money
# values to 6 decimal places and accepts ``±0.000001`` drift. The
# unrounded float recomputation can otherwise differ from the rounded
# declared aggregate by ~1e-7 on penny-sized cost rows even though both
# sides agree to the documented 6-decimal precision.
#
# F-PR32-R4-001 P2 adopt: ``rel_tol`` is now ``0.0`` so money drift checks
# use the loader's documented **absolute** 6-decimal precision only. The
# earlier ``rel_tol=1e-6`` accepted whole-dollar drift on large aggregates
# (e.g., a declared $5_000_005 on a recomputed $5_000_000 would have passed
# even though the loader rejects any money-field drift > 0.000001).
_COST_REL_TOL: Final[float] = 0.0
_COST_ABS_TOL: Final[float] = 1e-6
_THRESHOLD_USD_ABS_TOL: Final[float] = 1e-9
# F-PR32-R4-002/003 P2 adopt: the cost fixture loader normalizes money
# values to 6 decimal places. Threshold comparisons must use that same
# normalization so a fixture / corpus whose declared aggregate sits at the
# rounded threshold (e.g., recomputed 0.5000004 rounded to 0.500000) is not
# falsely rejected as drift / above_threshold.
#
# F-PR32-R5-001 P2 adopt: the loader uses ``Decimal(_MONEY_QUANT, ROUND_HALF_UP)``
# (banker's-round NOT used). Python's built-in ``round()`` is half-even, so
# exact-halfway values (e.g., $0.5000005) would diverge between the loader
# (-> $0.500001) and the aggregator (-> $0.500000). Mirror the loader's
# ``ROUND_HALF_UP`` quantization here so threshold_passed / threshold_met
# decisions agree at the documented precision.
_MONEY_DECIMAL_PLACES: Final[int] = 6
_MONEY_QUANT: Final[Decimal] = Decimal("0.000001")


def _normalize_money(value: float) -> float:
    """Quantize money to the loader's 6-decimal ``ROUND_HALF_UP`` precision.

    Mirrors ``eval/quality/cost_per_completed_task/loader.py::_money_to_float``
    (``Decimal(value).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)``)
    so the aggregator's threshold decisions never diverge from the loader's
    rounding for fixtures that bypass JSON Schema validation.
    """

    try:
        quantized = Decimal(str(value)).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        # ``value`` should be finite by the time we get here (the caller
        # already passes through ``_is_finite_number``); fall back to a
        # half-even ``round`` rather than re-raise so an unexpected float
        # cannot crash the aggregator.
        return round(value, _MONEY_DECIMAL_PLACES)
    return float(quantized)

# Sentinel that distinguishes "key absent" from "key present but malformed"
# (mirrors the citation_coverage aggregator).
_AGGREGATE_NOT_PROVIDED: Final[object] = object()

# F-PR31-R5-002 lesson: persisted corpora that bypass JSON Schema can ship
# arbitrary string shapes. ``evidence_set_hash`` is not part of the
# AC-KPI-05 contract (the live fixture explicitly leaves it ``null``), so
# we do NOT validate it here. Status enum and UUID structural validation
# carry the Anti-Gaming load instead.
# F-PR32-R1-005 P2 + R2-004 P2 adopt: AC-KPI-05 fixture schema constrains
# ``run_id`` to a canonical RFC 4122 UUID **in lowercase**. The version nibble
# (first hex of the 3rd group) must be 1-5 and the variant nibble (first hex
# of the 4th group) must be 8/9/a/b (the ``10xx`` variant). The nil UUID
# (all zeros) is excluded by the version constraint. The pattern is
# case-sensitive so an upper-case spelling fails — preventing the same logical
# UUID from being counted twice via mixed-case duplicate-detection bypass.
_UUID_TEXT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


@dataclass(frozen=True)
class SampleRun:
    """A single AgentRun observation extracted from ``input.sample_runs``."""

    run_id: str
    tenant_id: int
    project_id: int
    status: str
    cost_usd: float


@dataclass(frozen=True)
class CostPerCompletedTaskFixtureResult:
    """Per-fixture cost-KPI result.

    The dual ``spec_violation_reason`` / ``sut_failure_reason`` contract is
    identical to the batch 5d citation_coverage aggregator: at most one of
    these fields is non-None per row. ``passed=True`` with ``sut_attempted=False``
    means **spec compliance only** (SUT was not executed and its outcome is
    not represented); ``passed=True`` with ``sut_attempted=True`` means both
    spec and SUT pass.
    """

    fixture_id: str
    case_key: str
    total_runs: int
    completed_runs: int
    recomputed_completed_runs: int
    recomputed_total_cost_usd: float
    recomputed_cost_per_completed_task_usd: float | None
    expected_cost_per_completed_task_usd: float | None
    passed: bool
    spec_violation_reason: str | None
    sut_failure_reason: str | None
    sut_result: bool | None
    sut_attempted: bool


@dataclass(frozen=True)
class CostPerCompletedTaskMetricResult:
    """Corpus-level cost-KPI result.

    ``metric_value`` is the corpus-wide recomputed
    ``sum(cost_usd of completed runs) / count(completed runs)``. When the
    corpus has zero completed runs, ``metric_value`` is ``None`` (the KPI is
    undefined) and ``threshold_met`` is ``False`` with
    ``threshold_reason="no_completed_runs"``.
    """

    metric_value: float | None
    fixture_count: int
    total_completed_runs_across_corpus: int
    total_cost_usd_across_corpus: float
    pass_count: int
    fail_count: int
    per_fixture: tuple[CostPerCompletedTaskFixtureResult, ...]
    threshold_usd: float
    currency: str
    threshold_met: bool
    threshold_reason: str
    manifest_violation_reason: str | None


def _is_finite_number(value: object) -> bool:
    """Return True for finite ``int`` / ``float`` (excluding ``bool``).

    F-PR32-R6-002 P2 adopt: persisted corpora that bypass JSON Schema can
    ship a Python integer with hundreds of digits (e.g., a JSON number
    like ``10**500``). ``float(huge_int)`` raises ``OverflowError`` and
    would otherwise crash the eval run. Catch the overflow and return
    ``False`` so the caller emits ``spec_violation:*`` instead of an
    uncaught exception. ``math.isfinite`` itself accepts float infinities
    by definition and we still reject those via the explicit
    ``math.isfinite`` check.
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


def _costs_match(recomputed: float, expected: float) -> bool:
    return math.isclose(recomputed, expected, rel_tol=_COST_REL_TOL, abs_tol=_COST_ABS_TOL)


def _manifest_violation_reason(corpus: LoadedCorpus) -> str | None:
    """Validate manifest top-level constants for AC-KPI-05."""

    manifest = corpus.manifest
    if manifest.get("kpi_id") != AC_KPI_05_KPI_ID:
        return "manifest_violation:kpi_id"
    if manifest.get("metric") != AC_KPI_05_METRIC_KEY:
        return "manifest_violation:metric"

    threshold = manifest.get("threshold")
    if not isinstance(threshold, dict):
        return "manifest_violation:threshold"
    threshold_map: Mapping[str, object] = threshold
    threshold_value = threshold_map.get("cost_per_completed_task_usd_max")
    if not _is_finite_number(threshold_value):
        return "manifest_violation:threshold_value"
    if abs(float(threshold_value) - AC_KPI_05_THRESHOLD_USD) > _THRESHOLD_USD_ABS_TOL:  # type: ignore[arg-type]
        return "manifest_violation:threshold_value"
    if threshold_map.get("currency") != AC_KPI_05_CURRENCY:
        return "manifest_violation:currency"
    return None


def _envelope_violation_reason(fixture: Fixture) -> str | None:
    if fixture.kpi_id != AC_KPI_05_KPI_ID:
        return "spec_violation:kpi_id"
    if fixture.metric_key != AC_KPI_05_METRIC_KEY:
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


def _collect_sample_runs(
    fixture: Fixture,
    *,
    corpus_seen_run_ids: set[str] | None = None,
) -> tuple[list[SampleRun], str | None, frozenset[str]]:
    """Walk ``input.sample_runs`` and validate each run's shape.

    Returns ``(runs, spec_violation_reason, pending_corpus_ids)``. On any
    structural violation the parser returns an empty list and an empty
    ``pending_corpus_ids`` so the aggregator does not undercount via a
    partial parse.

    F-PR32-R3-001 P2 adopt: ``corpus_seen_run_ids`` is shared across all
    fixtures within a single ``evaluate_cost_per_completed_task`` call so
    duplicate ``run_id`` values **across fixtures** are detected too. A
    multi-fixture corpus that reuses the same low-cost completed run would
    otherwise lower the corpus weighted average, even though ``run_id``
    identifies one AgentRun globally.

    F-PR32-R6-001 P2 adopt: this function **only stages** the corpus-wide
    UUID delta in ``pending_corpus_ids`` and never mutates the caller-owned
    ``corpus_seen_run_ids`` set. The orchestrator (``evaluate_cost_per_completed_task``)
    is responsible for merging the staged set only after **all** fixture
    validation gates pass (envelope / threshold / sample_runs /
    expected_aggregate). This prevents an invalid fixture from leaking its
    UUIDs and causing a later valid fixture to be falsely flagged as
    ``duplicate_run_id_across_fixtures``.
    """

    _EMPTY_PENDING: frozenset[str] = frozenset()
    case_input = fixture.case_json.get("input")
    if not isinstance(case_input, dict):
        return [], "spec_violation:input", _EMPTY_PENDING

    sample_runs = case_input.get("sample_runs")
    if not isinstance(sample_runs, list):
        return [], "spec_violation:sample_runs", _EMPTY_PENDING
    # F-PR32-R2-003 P2 adopt: AC-KPI-05 fixture schema declares
    # ``sample_runs`` with ``minItems=1``. Persisted corpora that bypass JSON
    # Schema and ship an empty list would otherwise yield ``passed=True`` as
    # long as the declared aggregate matches zero completed runs; the
    # corpus-level threshold path still falls through to ``no_completed_runs``,
    # but the per-fixture row should already mark the fixture spec-invalid.
    if not sample_runs:
        return [], "spec_violation:sample_runs", _EMPTY_PENDING

    runs: list[SampleRun] = []
    seen_run_ids: set[str] = set()
    # F-PR32-R5-003 + R6-001 P2 adopt: stage the corpus-level seen-set delta
    # locally. The orchestrator merges into ``corpus_seen_run_ids`` only
    # after the fixture has fully validated against **every** gate (envelope,
    # threshold, sample_runs, expected_aggregate).
    pending_corpus_ids: set[str] = set()
    for raw_run in sample_runs:
        if not isinstance(raw_run, dict):
            return [], "spec_violation:sample_runs", _EMPTY_PENDING

        run_id = raw_run.get("run_id")
        if not _validate_uuid_text(run_id) or not isinstance(run_id, str):
            return [], "spec_violation:run_id", _EMPTY_PENDING
        if run_id in seen_run_ids:
            return [], "spec_violation:duplicate_run_id", _EMPTY_PENDING
        if corpus_seen_run_ids is not None and run_id in corpus_seen_run_ids:
            return (
                [],
                "spec_violation:duplicate_run_id_across_fixtures",
                _EMPTY_PENDING,
            )
        seen_run_ids.add(run_id)
        if corpus_seen_run_ids is not None:
            pending_corpus_ids.add(run_id)

        tenant_id = raw_run.get("tenant_id")
        if not _is_non_bool_int(tenant_id) or tenant_id < 1:  # type: ignore[operator]
            return [], "spec_violation:tenant_id", _EMPTY_PENDING

        # F-PR32-R1-004 P2 adopt: AC-KPI-05 fixture schema requires
        # ``project_id`` to be an integer with minimum 1. Persisted corpora
        # could carry ``project_id=0`` (or negative) and otherwise feed the
        # completed-run totals; tighten to ``>= 1``.
        project_id = raw_run.get("project_id")
        if not _is_non_bool_int(project_id) or project_id < 1:  # type: ignore[operator]
            return [], "spec_violation:project_id", _EMPTY_PENDING

        status = raw_run.get("status")
        if not isinstance(status, str) or status not in _KNOWN_AGENT_RUN_STATUSES:
            return [], "spec_violation:status", _EMPTY_PENDING

        cost_usd = raw_run.get("cost_usd")
        if not _is_finite_number(cost_usd):
            return [], "spec_violation:cost_usd", _EMPTY_PENDING
        if float(cost_usd) < 0.0:  # type: ignore[arg-type]
            return [], "spec_violation:cost_usd", _EMPTY_PENDING

        # F-PR32-R2-001 P2 adopt: AC-KPI-05 fixture schema requires both
        # ``tokens_input`` and ``tokens_output`` as non-negative integers.
        # The manifest declares the KPI is based on normalized provider usage
        # **after BudgetGuard accounting**, so accepting rows without token
        # counters lets a persisted corpus drop the provider-usage trace while
        # still recording a cost — exactly the kind of Anti-Gaming bypass the
        # token oracles exist to catch.
        tokens_input = raw_run.get("tokens_input")
        if not _is_non_bool_int(tokens_input) or tokens_input < 0:  # type: ignore[operator]
            return [], "spec_violation:tokens_input", _EMPTY_PENDING
        tokens_output = raw_run.get("tokens_output")
        if not _is_non_bool_int(tokens_output) or tokens_output < 0:  # type: ignore[operator]
            return [], "spec_violation:tokens_output", _EMPTY_PENDING

        runs.append(
            SampleRun(
                run_id=run_id,
                tenant_id=int(tenant_id),  # type: ignore[arg-type]
                project_id=int(project_id),  # type: ignore[arg-type]
                status=status,
                cost_usd=float(cost_usd),  # type: ignore[arg-type]
            )
        )

    # Return the staged set as an immutable snapshot; the orchestrator
    # commits it only when the fixture passes all gates.
    return runs, None, frozenset(pending_corpus_ids)


def _fixture_threshold(fixture: Fixture) -> object:
    if "threshold" in fixture.expected_json:
        return fixture.expected_json["threshold"]
    if "threshold" in fixture.raw_json:
        return fixture.raw_json["threshold"]
    return _AGGREGATE_NOT_PROVIDED


def _fixture_threshold_violation_reason(fixture: Fixture) -> str | None:
    """Validate the fixture-declared ``threshold`` against AC-KPI-05 constants.

    The cost fixture's ``threshold`` field is optional in the live corpus
    (the minimal skeleton fixture leaves it ``null``); however, when present
    and non-null it must match the AC-KPI-05 contract exactly so a persisted
    corpus cannot declare a relaxed cost ceiling.
    """

    threshold = _fixture_threshold(fixture)
    if threshold is _AGGREGATE_NOT_PROVIDED or threshold is None:
        # Fixture-level threshold is optional for cost; the manifest is the
        # canonical source. Permit None / absent and rely on manifest check.
        return None
    if not isinstance(threshold, dict):
        return "spec_violation:threshold"
    declared_max = threshold.get("cost_per_completed_task_usd_max")
    if not _is_finite_number(declared_max):
        return "spec_violation:threshold_value"
    if abs(float(declared_max) - AC_KPI_05_THRESHOLD_USD) > _THRESHOLD_USD_ABS_TOL:  # type: ignore[arg-type]
        return "spec_violation:threshold_value"
    if threshold.get("currency") != AC_KPI_05_CURRENCY:
        return "spec_violation:currency"
    return None


def _expected_aggregate_value(fixture: Fixture) -> object:
    if "expected_aggregate" in fixture.expected_json:
        return fixture.expected_json["expected_aggregate"]
    if "expected_aggregate" in fixture.raw_json:
        return fixture.raw_json["expected_aggregate"]
    return _AGGREGATE_NOT_PROVIDED


def _expected_aggregate_violation_reason(
    fixture: Fixture,
    *,
    recomputed_completed_runs: int,
    recomputed_total_cost_usd: float,
    recomputed_ratio: float | None,
) -> str | None:
    raw = _expected_aggregate_value(fixture)
    if raw is _AGGREGATE_NOT_PROVIDED:
        return "spec_violation:expected_aggregate_missing"
    if not isinstance(raw, dict):
        return "spec_violation:expected_aggregate"

    declared_completed = raw.get("total_completed_runs")
    if not _is_non_bool_int(declared_completed):
        return "spec_violation:expected_aggregate"
    if declared_completed != recomputed_completed_runs:
        return "spec_violation:expected_aggregate_completed_drift"

    declared_total_cost = raw.get("total_cost_usd")
    if not _is_finite_number(declared_total_cost):
        return "spec_violation:expected_aggregate"
    # F-PR32-R5-002 P2 adopt: the fixture schema requires
    # ``total_cost_usd >= 0.0``. Persisted corpora that bypass JSON Schema
    # could declare a tiny-negative drift (e.g., ``-0.0000005``) and slip
    # past ``_costs_match`` because the absolute tolerance is ``1e-6``.
    # Reject negative declared money values **before** applying the
    # tolerance so the drift oracle stays trustworthy.
    if float(declared_total_cost) < 0.0:  # type: ignore[arg-type]
        return "spec_violation:expected_aggregate"
    if not _costs_match(float(declared_total_cost), recomputed_total_cost_usd):  # type: ignore[arg-type]
        return "spec_violation:expected_aggregate_total_cost_drift"

    if "cost_per_completed_task_usd" not in raw:
        return "spec_violation:expected_aggregate"
    declared_ratio_raw = raw["cost_per_completed_task_usd"]
    if recomputed_ratio is None:
        # F-PR32-R1-003 P2 + R3-002 P2 adopt: with zero completed runs, the
        # recomputed ratio is undefined. The fixture must declare either
        # ``None`` (the existing cost-loader emits ``null`` in this case
        # since the schema permits it) or ``0.0`` (the canonical undefined
        # sentinel for cost rollups). Any other value is drift.
        if declared_ratio_raw is None:
            pass  # acceptable null sentinel
        elif _is_finite_number(declared_ratio_raw) and float(declared_ratio_raw) == 0.0:
            pass  # acceptable zero sentinel
        else:
            return "spec_violation:expected_aggregate_ratio_drift"
    else:
        if not _is_finite_number(declared_ratio_raw):
            return "spec_violation:expected_aggregate"
        # F-PR32-R5-002 P2 adopt: same non-negative guard for the declared
        # ratio. Negative declared ratios cannot occur for a real cost
        # KPI; reject before tolerance.
        if float(declared_ratio_raw) < 0.0:
            return "spec_violation:expected_aggregate"
        if not _costs_match(float(declared_ratio_raw), recomputed_ratio):
            return "spec_violation:expected_aggregate_ratio_drift"

    # F-PR32-R1-001 P2 + R1-002 P2 adopt: ``threshold_usd`` and
    # ``threshold_passed`` are documented in the expected_aggregate as
    # denormalized echoes of the manifest threshold + the per-fixture
    # pass/fail. Both are required (the AC-KPI-05 schema and this
    # aggregator's contract list them as drift oracles); fail-closed when
    # absent so a persisted corpus cannot silently weaken the ceiling.
    if "threshold_usd" not in raw:
        return "spec_violation:expected_aggregate"
    declared_threshold_usd = raw["threshold_usd"]
    if not _is_finite_number(declared_threshold_usd):
        return "spec_violation:expected_aggregate"
    if abs(float(declared_threshold_usd) - AC_KPI_05_THRESHOLD_USD) > _THRESHOLD_USD_ABS_TOL:
        return "spec_violation:expected_aggregate_threshold_drift"

    if "threshold_passed" not in raw:
        return "spec_violation:expected_aggregate"
    declared_threshold_passed = raw["threshold_passed"]
    if not isinstance(declared_threshold_passed, bool):
        return "spec_violation:expected_aggregate"
    # F-PR32-R4-002 P2 adopt: normalize the recomputed ratio to the loader's
    # documented 6-decimal money precision before the threshold comparison.
    # Otherwise an unrounded ratio of 0.5000004 (declared as 0.500000 by the
    # loader's ``_money_to_float()``) would be reported as
    # ``spec_violation:expected_aggregate_passed_drift`` even though both
    # sides agree at the documented precision.
    actual_passed = (
        recomputed_ratio is not None
        and _normalize_money(recomputed_ratio)
        <= AC_KPI_05_THRESHOLD_USD + _THRESHOLD_USD_ABS_TOL
    )
    if declared_threshold_passed != actual_passed:
        return "spec_violation:expected_aggregate_passed_drift"

    return None


def _warn_unknown_sut_results(corpus: LoadedCorpus, sut_results: Mapping[str, bool]) -> None:
    fixture_ids = {fixture.fixture_id for fixture in corpus.fixtures}
    for fixture_id in sorted(set(sut_results) - fixture_ids):
        _LOGGER.warning(
            "Ignoring SUT result for unknown AC-KPI-05 fixture_id=%s",
            fixture_id,
        )


def _threshold_reason(
    *,
    fixture_count: int,
    total_completed_runs: int,
    metric_value: float | None,
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
    if sut_failure_present:
        return "sut_failure"
    if total_completed_runs == 0 or metric_value is None:
        return "no_completed_runs"
    # F-PR32-R4-003 P2 adopt: normalize the corpus metric to the loader's
    # documented 6-decimal money precision before the corpus-gate threshold
    # comparison. A corpus-wide average of 0.5000004 (which the loader
    # records as 0.500000) must report ``threshold_met`` instead of
    # ``above_threshold`` so the corpus gate agrees with the per-fixture
    # drift oracle at the documented precision.
    if _normalize_money(metric_value) <= AC_KPI_05_THRESHOLD_USD + _THRESHOLD_USD_ABS_TOL:
        return "threshold_met"
    return "above_threshold"


def evaluate_cost_per_completed_task(
    corpus: LoadedCorpus,
    *,
    sut_results: Mapping[str, bool] | None = None,
) -> CostPerCompletedTaskMetricResult:
    """Compute AC-KPI-05 ``cost_per_completed_task`` from a loaded corpus.

    The caller must load and validate the corpus via
    :func:`backend.app.services.eval.loader.load_fixture_corpus` first. The
    function is pure: no DB / file system / network access. Optional
    ``sut_results`` is consumed read-only and keyed by ``fixture_id``.

    Anti-Gaming invariants (manifest ``anti_gaming_rules.kpi_specific``):

    * ``cost_per_completed_task`` is **always recomputed** from
      ``input.sample_runs``; the fixture's declared
      ``expected_aggregate.cost_per_completed_task_usd`` is consumed as a
      drift-detection oracle only.
    * **Only ``status="completed"`` runs** contribute to both numerator and
      denominator. Failed / cancelled / refused / repair-exhausted /
      non-terminal runs are filtered out of both totals.
    * Unknown status values are rejected as ``spec_violation:status`` so a
      future AgentRun status name change can't quietly bypass the filter.

    Per-fixture procedure:
        1. Skip non-public-regression fixtures (redacted splits are SP-022+).
        2. Validate the fixture envelope and the optional fixture-level
           ``threshold`` against AC-KPI-05 constants.
        3. Walk ``input.sample_runs`` validating UUID / tenant_id /
           project_id / status / cost_usd shapes.
        4. Filter to completed runs and recompute
           ``cost_per_completed_task_usd``.
        5. Drift-check against ``expected_aggregate`` (completed count,
           total cost, recomputed ratio, declared threshold, declared pass).
        6. Optionally cross-check ``sut_results[fixture_id]``; non-boolean
           values reject as ``sut_result_invalid_type``.

    Per-fixture reason priority:
        envelope_violation > fixture_threshold_violation >
        run_parsing_violation > expected_aggregate_* violations. SUT
        processing is **skipped** entirely when a spec violation is detected,
        keeping the dataclass invariant (at most one of
        ``spec_violation_reason`` / ``sut_failure_reason`` non-None).

    Corpus-level metric:
        ``metric_value = sum(cost_usd over completed runs) /
                          count(completed runs)``
        ``threshold_met`` ⇔ ``metric_value <= AC_KPI_05_THRESHOLD_USD`` AND
        ``fixture_count > 0`` AND ``total_completed_runs > 0`` AND no
        spec/manifest/SUT failure.
        ``threshold_reason`` ∈ {``no_fixtures``, ``manifest_violation``,
        ``spec_violation``, ``sut_failure``, ``no_completed_runs``,
        ``threshold_met``, ``above_threshold``} with that priority order.
    """

    if sut_results is not None:
        _warn_unknown_sut_results(corpus, sut_results)

    per_fixture: list[CostPerCompletedTaskFixtureResult] = []
    spec_violation_present = False
    sut_failure_present = False
    total_completed_runs_across_corpus = 0
    total_cost_usd_across_corpus = 0.0
    # F-PR32-R3-001 P2 adopt: share the seen-set across fixtures so duplicate
    # ``run_id`` values across the corpus are flagged.
    corpus_seen_run_ids: set[str] = set()

    for fixture in corpus.fixtures:
        if fixture.fixture_kind not in _SUPPORTED_FIXTURE_KINDS:
            # Redacted splits deferred to SP-022+ (encrypted-holdout path).
            continue

        envelope_reason = _envelope_violation_reason(fixture)
        threshold_reason_violation = (
            _fixture_threshold_violation_reason(fixture) if envelope_reason is None else None
        )
        runs, run_violation, pending_corpus_ids = _collect_sample_runs(
            fixture,
            corpus_seen_run_ids=corpus_seen_run_ids,
        )
        completed_runs = [run for run in runs if run.status == _KPI_05_COMPLETED_STATUS]
        recomputed_completed_count = len(completed_runs)
        recomputed_total_cost = sum(run.cost_usd for run in completed_runs)
        recomputed_ratio: float | None = (
            recomputed_total_cost / recomputed_completed_count
            if recomputed_completed_count
            else None
        )

        spec_reason: str | None = envelope_reason
        if spec_reason is None and threshold_reason_violation is not None:
            spec_reason = threshold_reason_violation
        if spec_reason is None and run_violation is not None:
            spec_reason = run_violation
        if spec_reason is None:
            spec_reason = _expected_aggregate_violation_reason(
                fixture,
                recomputed_completed_runs=recomputed_completed_count,
                recomputed_total_cost_usd=recomputed_total_cost,
                recomputed_ratio=recomputed_ratio,
            )

        # F-PR32-R6-001 P2 adopt: gate both corpus-wide totals **and** the
        # cross-fixture seen-set commit on the final spec_reason. An
        # otherwise-structurally-valid set of sample_runs in a fixture that
        # fails its envelope / threshold / expected_aggregate gates must not
        # leak its UUIDs (which would falsely flag a later valid fixture as
        # ``duplicate_run_id_across_fixtures``) nor inflate the corpus-level
        # numerator / denominator.
        if spec_reason is None:
            total_completed_runs_across_corpus += recomputed_completed_count
            total_cost_usd_across_corpus += recomputed_total_cost
            if pending_corpus_ids:
                corpus_seen_run_ids.update(pending_corpus_ids)

        spec_violation_reason = spec_reason
        sut_failure_reason: str | None = None
        sut_result: bool | None = None
        sut_attempted = False
        passed = spec_reason is None

        # Mirror batch 5d (citation_coverage): skip SUT processing entirely
        # when the fixture spec is invalid so the dataclass contract holds.
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
                        sut_failure_reason = "sut_result_false"
                        sut_failure_present = True

        if spec_violation_reason is not None:
            spec_violation_present = True

        per_fixture.append(
            CostPerCompletedTaskFixtureResult(
                fixture_id=fixture.fixture_id,
                case_key=fixture.case_key,
                total_runs=len(runs),
                completed_runs=recomputed_completed_count,
                recomputed_completed_runs=recomputed_completed_count,
                recomputed_total_cost_usd=recomputed_total_cost,
                recomputed_cost_per_completed_task_usd=recomputed_ratio,
                expected_cost_per_completed_task_usd=_expected_ratio_from_aggregate(fixture),
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
    metric_value = (
        total_cost_usd_across_corpus / total_completed_runs_across_corpus
        if total_completed_runs_across_corpus
        else None
    )
    manifest_reason = _manifest_violation_reason(corpus)
    threshold_reason = _threshold_reason(
        fixture_count=fixture_count,
        total_completed_runs=total_completed_runs_across_corpus,
        metric_value=metric_value,
        spec_violation_present=spec_violation_present,
        manifest_violation_present=manifest_reason is not None,
        sut_failure_present=sut_failure_present,
    )

    return CostPerCompletedTaskMetricResult(
        metric_value=metric_value,
        fixture_count=fixture_count,
        total_completed_runs_across_corpus=total_completed_runs_across_corpus,
        total_cost_usd_across_corpus=total_cost_usd_across_corpus,
        pass_count=pass_count,
        fail_count=fail_count,
        per_fixture=tuple(per_fixture),
        threshold_usd=AC_KPI_05_THRESHOLD_USD,
        currency=AC_KPI_05_CURRENCY,
        threshold_met=threshold_reason == "threshold_met",
        threshold_reason=threshold_reason,
        manifest_violation_reason=manifest_reason,
    )


def _expected_ratio_from_aggregate(fixture: Fixture) -> float | None:
    raw = _expected_aggregate_value(fixture)
    if not isinstance(raw, dict):
        return None
    declared_ratio = raw.get("cost_per_completed_task_usd")
    if not _is_finite_number(declared_ratio):
        return None
    return float(declared_ratio)  # type: ignore[arg-type]


__all__ = [
    "AC_KPI_05_CURRENCY",
    "AC_KPI_05_KPI_ID",
    "AC_KPI_05_METRIC_KEY",
    "AC_KPI_05_THRESHOLD_USD",
    "CostPerCompletedTaskFixtureResult",
    "CostPerCompletedTaskMetricResult",
    "SampleRun",
    "evaluate_cost_per_completed_task",
]
