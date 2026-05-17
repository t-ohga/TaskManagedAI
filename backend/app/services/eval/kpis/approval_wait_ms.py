"""AC-KPI-03 ``approval_wait_ms`` aggregator.

Computes the AC-KPI-03 KPI (Approval ``requested_at`` → ``decided_at`` median
ms) from a fixture corpus loaded by
:func:`backend.app.services.eval.loader.load_fixture_corpus`. The aggregator
follows the Anti-Gaming invariant declared in the corpus manifest::

    "approval_wait_ms is recomputed from input.sample_approvals,
     not copied from expected_aggregate"

i.e., the canonical median is always **recomputed** from the fixture's
``input.sample_approvals`` list. ``expected_aggregate.median_ms`` is
consumed purely as a drift-detection oracle.

Per plan v2 §2.1 the metric is defined as::

    duration_ms[i] = decided_at[i] - requested_at[i]    (status ∈ {approved, rejected})
    metric_value_ms = median(duration_ms[i])

with the strict causality invariant that ``decided_at >= requested_at``
(boundary equality is valid; same convention as AC-KPI-02 ``merged_at``).
Causality violation rejects at parse time as
``spec_violation:decided_at_causality`` (no silent skip / no clamp).

Causality semantic alignment (plan v2 §2.5 / HIGH-H4):
* The existing ``eval/quality/approval_wait_ms/loader.py`` silently skips
  ``decided_at < requested_at`` rows when recomputing
  ``expected_aggregate.median_ms`` (line 340 ``if decided_at <
  requested_at: continue``).
* This new aggregator independently parses ``input.sample_approvals`` and
  REJECTS the entire fixture as ``spec_violation:decided_at_causality``
  when a decided row violates causality.
* Both behaviors converge on causality-clean fixtures (same median); on
  causality-violating fixtures the aggregator surfaces the spec violation
  while the loader-recomputed median (excluding the bad row) would still
  match the fixture's declared ``expected_aggregate.median_ms`` (since
  the same fixture authoring tool was used). This is documented
  two-layer defense-in-depth.

The function is pure (no DB / file system / network access). Optional
``sut_results`` is consumed read-only for forward-compatibility with the
BL-0127b / SP-012 programmatic SUT execution path.

The KPI is "lower is better": ``threshold_met`` requires the recomputed
``metric_value_ms`` to be **at or below** ``AC_KPI_03_THRESHOLD_MS``
(14_400_000 ms = 4 hours).

5+ source enum integrity (plan v2 §2.3):
1. DB CHECK ``approval_requests_ck_status`` in
   ``backend/app/db/models/approval_request.py:36-41``
2. ORM Literal ``ApprovalStatus`` in ``approval_request.py:20``
3. Aggregator frozenset ``_KNOWN_APPROVAL_STATUSES`` (below)
4. Pytest ``EXPECTED_KNOWN_APPROVAL_STATUSES``
5. Fixture schema ``expected_schema.json``
   ``properties.input.items.properties.status.enum``

Partition: ``_DECIDED_STATUSES = frozenset({"approved", "rejected"})``,
strict subset of ``_KNOWN_APPROVAL_STATUSES``; excluded set =
``{"pending", "expired", "invalidated"}``.
"""

from __future__ import annotations

import datetime as _datetime
import logging
import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from backend.app.db.models.dataset_version import FixtureKind
from backend.app.services.eval.loader import Fixture, LoadedCorpus

_LOGGER = logging.getLogger(__name__)

AC_KPI_03_KPI_ID: Final[Literal["AC-KPI-03"]] = "AC-KPI-03"
AC_KPI_03_METRIC_KEY: Final[Literal["approval_wait_ms"]] = "approval_wait_ms"
AC_KPI_03_THRESHOLD_MS: Final[int] = 14_400_000  # 4 hours
AC_KPI_03_THRESHOLD_HOURS: Final[float] = 4.0
AC_KPI_03_THRESHOLD_OPERATOR: Final[Literal["<="]] = "<="

# 5-element approval status enum. Sources: see module docstring.
_KNOWN_APPROVAL_STATUSES: Final[frozenset[str]] = frozenset(
    {"pending", "approved", "rejected", "expired", "invalidated"}
)
_DECIDED_STATUSES: Final[frozenset[str]] = frozenset({"approved", "rejected"})

# Compile-time partition invariant (plan v2 §2.3, §4.1).
if not (_DECIDED_STATUSES < _KNOWN_APPROVAL_STATUSES):
    raise RuntimeError(
        "AC-KPI-03 partition invariant violation: _DECIDED_STATUSES must "
        "be a proper subset of _KNOWN_APPROVAL_STATUSES."
    )
if _KNOWN_APPROVAL_STATUSES - _DECIDED_STATUSES != frozenset(
    {"pending", "expired", "invalidated"}
):
    raise RuntimeError(
        "AC-KPI-03 excluded-set invariant violation: expected "
        "{'pending', 'expired', 'invalidated'}."
    )

_SUPPORTED_FIXTURE_KINDS: Final[Sequence[FixtureKind]] = ("public_regression",)

# Sentinel for "key absent" vs "key present but malformed".
_AGGREGATE_NOT_PROVIDED: Final[object] = object()

# Tolerance rationale (plan v2 §4.1, MED-M3 uniform ms-precision policy):
# duration_ms is ms-precise int. rel_tol=0 forces abs-only comparison;
# abs_tol=1.0 ms matches batch 5g (1/3.6e6 hours = 1 ms equivalent). The
# threshold tolerance is also 1 ms, so a recomputed median = threshold +
# 1 ms is within the boundary band.
_DURATION_REL_TOL: Final[float] = 0.0
_DURATION_ABS_TOL_MS: Final[float] = 1.0
_THRESHOLD_MS_ABS_TOL: Final[float] = 1.0


@dataclass(frozen=True)
class SampleApproval:
    """One approval observation from ``input.sample_approvals``.

    Plan v2 §4.4 + LOW-L2: corpus-wide uniqueness key is the tuple
    ``(requested_at_ms, decided_at_ms, status)`` — a **best-effort**
    duplicate-detection signal, not a strong unique-key guarantee.
    Approval fixtures (Sprint 3 era schema) have no per-row UUID by
    design; a full per-row UUID would require an SP-012 schema
    migration of the existing fixture format.
    """

    requested_at_ms: int
    decided_at_ms: int | None
    status: str


@dataclass(frozen=True)
class ApprovalWaitMsFixtureResult:
    """Per-fixture result. ``spec_violation_reason`` and
    ``sut_failure_reason`` are mutually exclusive (at most one non-None
    per row).
    """

    fixture_id: str
    case_key: str
    sample_count_total: int
    decided_count: int
    approved_count: int
    rejected_count: int
    pending_count: int
    expired_count: int
    invalidated_count: int
    recomputed_median_ms: float | None  # None when decided_count == 0
    expected_median_ms: float | None
    passed: bool
    spec_violation_reason: str | None
    sut_failure_reason: str | None
    sut_result: bool | None
    sut_attempted: bool


@dataclass(frozen=True)
class ApprovalWaitMsMetricResult:
    """Corpus-level result.

    ``metric_value`` is the pooled corpus-wide median of all decided
    approval wait durations in ms. When zero decided approvals exist,
    ``metric_value`` is ``None`` and ``threshold_met`` is ``False`` with
    ``threshold_reason="no_decided_approvals"`` (plan v2 §4.2.1).
    """

    metric_value: float | None
    fixture_count: int
    total_samples_across_corpus: int
    decided_count_across_corpus: int
    pass_count: int
    fail_count: int
    per_fixture: tuple[ApprovalWaitMsFixtureResult, ...]
    threshold_ms: int
    threshold_operator: str
    threshold_met: bool
    threshold_reason: str
    manifest_violation_reason: str | None


def _is_finite_number(value: object) -> bool:
    """Return True for finite ``int`` / ``float`` (excluding ``bool``)."""

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


def _durations_match(recomputed: float, expected: float) -> bool:
    """Return True when two durations (in ms) agree within the ms-precision
    tolerance. ``rel_tol=0.0`` is intentional (see module docstring).
    """

    return math.isclose(
        recomputed,
        expected,
        rel_tol=_DURATION_REL_TOL,
        abs_tol=_DURATION_ABS_TOL_MS,
    )


def _manifest_violation_reason(corpus: LoadedCorpus) -> str | None:
    """Validate manifest top-level constants for AC-KPI-03.

    The AC-KPI-03 manifest uses ``kpi_threshold_ms_median: int`` (Sprint 3
    batch 4 era), NOT the ``threshold: {operator, value, unit}`` envelope
    that batch 5e+ adopts. See plan v2 §4.3 / MED-M4.
    """

    manifest = corpus.manifest
    if manifest.get("kpi_id") != AC_KPI_03_KPI_ID:
        return "manifest_violation:kpi_id"
    if manifest.get("metric") != AC_KPI_03_METRIC_KEY:
        return "manifest_violation:metric"
    declared_threshold = manifest.get("kpi_threshold_ms_median")
    # LOW-L3 adopt: strict non-bool int type check.
    if not _is_non_bool_int(declared_threshold):
        return "manifest_violation:kpi_threshold_ms_median"
    if declared_threshold != AC_KPI_03_THRESHOLD_MS:
        return "manifest_violation:kpi_threshold_ms_median"
    return None


def _envelope_violation_reason(fixture: Fixture) -> str | None:
    if fixture.kpi_id != AC_KPI_03_KPI_ID:
        return "spec_violation:kpi_id"
    if fixture.metric_key != AC_KPI_03_METRIC_KEY:
        return "spec_violation:metric_key"
    if fixture.fixture_kind not in _SUPPORTED_FIXTURE_KINDS:
        return "spec_violation:fixture_kind"
    return None


def _parse_timestamp_ms(value: object) -> int | None:
    """Parse an ISO-8601 / RFC 3339 timestamp into epoch ms UTC.

    Plan v2 §2.4 MED-001 carry-over: naive datetime rejected, non-UTC
    offset normalized, ``Z`` → ``+00:00``, sub-millisecond precision
    (``microsecond % 1000 != 0``) rejected (batch 5g F-PR34-R2-001
    carry-over). Returns ``None`` on any failure.
    """

    if not isinstance(value, str):
        return None
    if not value:
        return None
    candidate = value
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = _datetime.datetime.fromisoformat(candidate)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        return None
    if dt.microsecond % 1000 != 0:
        return None
    dt_utc = dt.astimezone(_datetime.UTC)
    try:
        return int(dt_utc.timestamp() * 1000)
    except (OverflowError, ValueError):
        return None


def _fixture_threshold(fixture: Fixture) -> object:
    """Look up a (illegal at schema level) per-fixture ``threshold`` block.

    Plan v2 §5 #15 / HIGH-H1 adopt: the existing fixture schema rejects
    a per-fixture ``threshold`` block at schema validation
    (``additionalProperties: false``). This helper covers the path where
    a persisted / DB-loaded corpus bypasses JSON Schema (raw_json or
    expected_json may carry it) and is rejected by the aggregator.
    """

    if "threshold" in fixture.expected_json:
        return fixture.expected_json["threshold"]
    if "threshold" in fixture.raw_json:
        return fixture.raw_json["threshold"]
    return _AGGREGATE_NOT_PROVIDED


def _fixture_threshold_violation_reason(fixture: Fixture) -> str | None:
    """Plan v2 §5 #15: existing AC-KPI-03 schema does NOT permit a
    per-fixture ``threshold`` block (``additionalProperties: false`` at
    fixture top level). If a persisted corpus bypasses the schema and
    delivers one, reject as ``spec_violation:threshold_unexpected``.
    """

    threshold = _fixture_threshold(fixture)
    if threshold is _AGGREGATE_NOT_PROVIDED:
        return None
    # Any non-absent value is unexpected. Even ``None`` is unexpected
    # because the field is structurally illegal in this schema.
    return "spec_violation:threshold_unexpected"


def _collect_sample_approvals(
    fixture: Fixture,
    *,
    corpus_seen_keys: set[tuple[int, int | None, str]] | None = None,
) -> tuple[
    list[SampleApproval], str | None, frozenset[tuple[int, int | None, str]]
]:
    """Walk ``input.sample_approvals`` and validate each row.

    Returns ``(approvals, spec_violation_reason, pending_corpus_keys)``.
    On any structural violation the parser returns an empty list and
    empty pending set.

    Plan v2 §4.4 / LOW-L2: corpus-wide uniqueness via
    ``(requested_at_ms, decided_at_ms, status)`` tuple is best-effort
    only. Plan v2 §5 #1.

    Plan v2 §5 #9 + §5 #14 + #12 + #13:
    * Late-commit corpus seen keys (orchestrator merges only on
      successful fixture).
    * ``decided_at`` required iff status ∈ ``{approved, rejected}``;
      null required otherwise (``spec_violation:decided_at_required``
      / ``decided_at_unexpected``).
    * Causality: ``decided_at >= requested_at`` for decided statuses;
      boundary == valid.
    * Sub-ms precision rejected by ``_parse_timestamp_ms``.
    """

    empty_keys: frozenset[tuple[int, int | None, str]] = frozenset()
    case_input = fixture.case_json.get("input")
    if not isinstance(case_input, dict):
        return [], "spec_violation:input", empty_keys

    sample_approvals = case_input.get("sample_approvals")
    if not isinstance(sample_approvals, list):
        return [], "spec_violation:sample_approvals", empty_keys
    if not sample_approvals:
        return [], "spec_violation:sample_approvals", empty_keys

    approvals: list[SampleApproval] = []
    seen_keys: set[tuple[int, int | None, str]] = set()
    pending_keys: set[tuple[int, int | None, str]] = set()
    for raw_approval in sample_approvals:
        if not isinstance(raw_approval, dict):
            return [], "spec_violation:sample_approvals", empty_keys

        status = raw_approval.get("status")
        if not isinstance(status, str) or status not in _KNOWN_APPROVAL_STATUSES:
            return [], "spec_violation:status", empty_keys

        requested_at_raw = raw_approval.get("requested_at")
        requested_at_ms = _parse_timestamp_ms(requested_at_raw)
        if requested_at_ms is None:
            return [], "spec_violation:requested_at", empty_keys

        decided_at_raw = raw_approval.get("decided_at")
        decided_at_ms: int | None
        if status in _DECIDED_STATUSES:
            if decided_at_raw is None:
                return (
                    [],
                    "spec_violation:decided_at_required",
                    empty_keys,
                )
            decided_at_ms = _parse_timestamp_ms(decided_at_raw)
            if decided_at_ms is None:
                return [], "spec_violation:decided_at", empty_keys
            # Plan v2 §2.5 / §5 #12: causality with boundary == valid.
            if decided_at_ms < requested_at_ms:
                return (
                    [],
                    "spec_violation:decided_at_causality",
                    empty_keys,
                )
        else:
            # Plan v2 §5 #14: decided_at must be null for non-decided
            # statuses.
            if decided_at_raw is not None:
                return (
                    [],
                    "spec_violation:decided_at_unexpected",
                    empty_keys,
                )
            decided_at_ms = None

        # Corpus-wide best-effort uniqueness (plan v2 §5 #1).
        approval_key = (requested_at_ms, decided_at_ms, status)
        if approval_key in seen_keys:
            return [], "spec_violation:duplicate_approval", empty_keys
        if corpus_seen_keys is not None and approval_key in corpus_seen_keys:
            return (
                [],
                "spec_violation:duplicate_approval_across_fixtures",
                empty_keys,
            )
        seen_keys.add(approval_key)
        if corpus_seen_keys is not None:
            pending_keys.add(approval_key)

        approvals.append(
            SampleApproval(
                requested_at_ms=requested_at_ms,
                decided_at_ms=decided_at_ms,
                status=status,
            )
        )

    return approvals, None, frozenset(pending_keys)


def _expected_aggregate_value(fixture: Fixture) -> object:
    if "expected_aggregate" in fixture.expected_json:
        return fixture.expected_json["expected_aggregate"]
    if "expected_aggregate" in fixture.raw_json:
        return fixture.raw_json["expected_aggregate"]
    return _AGGREGATE_NOT_PROVIDED


def _expected_aggregate_violation_reason(
    fixture: Fixture,
    *,
    recomputed_decided_count: int,
    recomputed_median_ms: float | None,
) -> str | None:
    raw = _expected_aggregate_value(fixture)
    if raw is _AGGREGATE_NOT_PROVIDED:
        return "spec_violation:expected_aggregate_missing"
    if not isinstance(raw, dict):
        return "spec_violation:expected_aggregate"

    # Plan v2 §4.2.2 / MED-M2: ``expected_aggregate.sample_count`` is the
    # **decided_count** by existing loader semantics.
    declared_sample_count = raw.get("sample_count")
    if not _is_non_bool_int(declared_sample_count) or declared_sample_count < 0:  # type: ignore[operator]
        return "spec_violation:expected_aggregate"
    if declared_sample_count != recomputed_decided_count:
        return "spec_violation:expected_aggregate_decided_drift"

    # Plan v2 §2.6 / HIGH-H2: per-fixture decided_count == 0 is a
    # by-construction spec violation because the schema requires
    # ``median_ms: number`` (no null allowed).
    if "median_ms" not in raw:
        return "spec_violation:expected_aggregate"
    declared_median_ms_raw = raw["median_ms"]
    if not _is_finite_number(declared_median_ms_raw):
        return "spec_violation:expected_aggregate"
    declared_median_ms = float(declared_median_ms_raw)
    # Plan v2 §5 #3: reject negative declared median.
    if declared_median_ms < 0.0:
        return "spec_violation:expected_aggregate"

    if recomputed_median_ms is None:
        # By-construction: schema-required numeric median_ms vs no
        # decided rows ⇒ fixture is internally inconsistent.
        return "spec_violation:expected_aggregate_median_drift"
    if not _durations_match(declared_median_ms, recomputed_median_ms):
        return "spec_violation:expected_aggregate_median_drift"

    # Optional fields (p95_ms / min_ms / max_ms): verify non-negative
    # if present, but do not enforce drift (loader-side computation is
    # canonical).
    for opt_key in ("p95_ms", "min_ms", "max_ms"):
        if opt_key not in raw:
            continue
        opt_value = raw[opt_key]
        if opt_value is None:
            continue
        if not _is_finite_number(opt_value):
            return "spec_violation:expected_aggregate"
        if float(opt_value) < 0.0:
            return "spec_violation:expected_aggregate"

    return None


def _warn_unknown_sut_results(
    corpus: LoadedCorpus, sut_results: Mapping[str, bool]
) -> None:
    fixture_ids = {fixture.fixture_id for fixture in corpus.fixtures}
    for fixture_id in sorted(set(sut_results) - fixture_ids):
        _LOGGER.warning(
            "Ignoring SUT result for unknown AC-KPI-03 fixture_id=%s",
            fixture_id,
        )


def _threshold_reason(
    *,
    fixture_count: int,
    decided_count_across_corpus: int,
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
    if decided_count_across_corpus == 0 or metric_value is None:
        return "no_decided_approvals"
    if metric_value <= AC_KPI_03_THRESHOLD_MS + _THRESHOLD_MS_ABS_TOL:
        return "threshold_met"
    return "above_threshold"


def _expected_median_from_aggregate(fixture: Fixture) -> float | None:
    raw = _expected_aggregate_value(fixture)
    if not isinstance(raw, dict):
        return None
    declared = raw.get("median_ms")
    if declared is None:
        return None
    if not _is_finite_number(declared):
        return None
    return float(declared)


def evaluate_approval_wait_ms(
    corpus: LoadedCorpus,
    *,
    sut_results: Mapping[str, bool] | None = None,
) -> ApprovalWaitMsMetricResult:
    """Compute AC-KPI-03 ``approval_wait_ms`` from a loaded corpus.

    Anti-Gaming invariants (manifest ``anti_gaming_rules.kpi_specific``):

    * ``approval_wait_ms`` is **always recomputed** from
      ``input.sample_approvals``; the fixture's declared
      ``expected_aggregate.median_ms`` is consumed as a drift-detection
      oracle only.
    * Only approvals with status ∈ ``{approved, rejected}`` contribute
      to the median.
    * Unknown statuses reject as ``spec_violation:status``.
    * Causality: ``decided_at >= requested_at`` for decided statuses
      (boundary equality valid).
    * Sub-millisecond precision rejected (carry-over from batch 5g
      F-PR34-R2-001).

    Per-fixture procedure:
        1. Skip non-public-regression fixtures (redacted splits SP-022+).
        2. Validate envelope.
        3. Validate fixture-level ``threshold`` block (defense-in-depth
           per plan v2 §5 #15).
        4. Walk ``input.sample_approvals``: status enum, timestamp,
           decided_at required/null per status, causality, corpus-wide
           best-effort uniqueness.
        5. Bucket by status; recompute median from decided durations.
        6. Drift-check against ``expected_aggregate``.
        7. Optionally cross-check ``sut_results[fixture_id]``.

    Corpus-level metric:
        Pooled (un-weighted) corpus median of all decided durations.
        ``threshold_met`` ⇔ ``metric_value <= 14_400_000 + 1ms`` AND
        ``fixture_count > 0`` AND ``decided_count_across_corpus > 0``
        AND no spec/manifest/SUT failure.
    """

    if sut_results is not None:
        _warn_unknown_sut_results(corpus, sut_results)

    per_fixture: list[ApprovalWaitMsFixtureResult] = []
    spec_violation_present = False
    sut_failure_present = False
    total_samples_across_corpus = 0
    decided_count_across_corpus = 0
    all_durations_ms: list[float] = []
    corpus_seen_keys: set[tuple[int, int | None, str]] = set()

    for fixture in corpus.fixtures:
        if fixture.fixture_kind not in _SUPPORTED_FIXTURE_KINDS:
            continue

        envelope_reason = _envelope_violation_reason(fixture)
        # Plan v2 §5 #15: per-fixture threshold rejection.
        threshold_violation = (
            _fixture_threshold_violation_reason(fixture)
            if envelope_reason is None
            else None
        )
        approvals, parsing_violation, pending_keys = _collect_sample_approvals(
            fixture,
            corpus_seen_keys=corpus_seen_keys,
        )

        approved = [a for a in approvals if a.status == "approved"]
        rejected = [a for a in approvals if a.status == "rejected"]
        pending = [a for a in approvals if a.status == "pending"]
        expired = [a for a in approvals if a.status == "expired"]
        invalidated = [a for a in approvals if a.status == "invalidated"]
        approved_count = len(approved)
        rejected_count = len(rejected)
        pending_count = len(pending)
        expired_count = len(expired)
        invalidated_count = len(invalidated)
        decided_count = approved_count + rejected_count
        sample_count_total = len(approvals)

        # Compute durations for decided rows. Causality is already
        # enforced upstream (defense #12), so each duration is >= 0.
        durations_ms: list[float] = []
        for approval in approved + rejected:
            if approval.decided_at_ms is None:
                continue  # invariant; should not occur
            durations_ms.append(
                float(approval.decided_at_ms - approval.requested_at_ms)
            )
        recomputed_median_ms: float | None = (
            statistics.median(durations_ms) if durations_ms else None
        )

        spec_reason: str | None = envelope_reason
        if spec_reason is None and threshold_violation is not None:
            spec_reason = threshold_violation
        if spec_reason is None and parsing_violation is not None:
            spec_reason = parsing_violation
        if spec_reason is None:
            spec_reason = _expected_aggregate_violation_reason(
                fixture,
                recomputed_decided_count=decided_count,
                recomputed_median_ms=recomputed_median_ms,
            )

        # Plan v2 §5 #9 / batch 5g F-PR32-R6-001 carry-over: gate
        # corpus state on final spec_reason.
        if spec_reason is None:
            total_samples_across_corpus += sample_count_total
            decided_count_across_corpus += decided_count
            all_durations_ms.extend(durations_ms)
            if pending_keys:
                corpus_seen_keys.update(pending_keys)

        spec_violation_reason = spec_reason
        sut_failure_reason: str | None = None
        sut_result: bool | None = None
        sut_attempted = False
        passed = spec_reason is None

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
            ApprovalWaitMsFixtureResult(
                fixture_id=fixture.fixture_id,
                case_key=fixture.case_key,
                sample_count_total=sample_count_total,
                decided_count=decided_count,
                approved_count=approved_count,
                rejected_count=rejected_count,
                pending_count=pending_count,
                expired_count=expired_count,
                invalidated_count=invalidated_count,
                recomputed_median_ms=recomputed_median_ms,
                expected_median_ms=_expected_median_from_aggregate(fixture),
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
        statistics.median(all_durations_ms) if all_durations_ms else None
    )
    manifest_reason = _manifest_violation_reason(corpus)
    threshold_reason = _threshold_reason(
        fixture_count=fixture_count,
        decided_count_across_corpus=decided_count_across_corpus,
        metric_value=metric_value,
        spec_violation_present=spec_violation_present,
        manifest_violation_present=manifest_reason is not None,
        sut_failure_present=sut_failure_present,
    )

    return ApprovalWaitMsMetricResult(
        metric_value=metric_value,
        fixture_count=fixture_count,
        total_samples_across_corpus=total_samples_across_corpus,
        decided_count_across_corpus=decided_count_across_corpus,
        pass_count=pass_count,
        fail_count=fail_count,
        per_fixture=tuple(per_fixture),
        threshold_ms=AC_KPI_03_THRESHOLD_MS,
        threshold_operator=AC_KPI_03_THRESHOLD_OPERATOR,
        threshold_met=threshold_reason == "threshold_met",
        threshold_reason=threshold_reason,
        manifest_violation_reason=manifest_reason,
    )


__all__ = [
    "AC_KPI_03_KPI_ID",
    "AC_KPI_03_METRIC_KEY",
    "AC_KPI_03_THRESHOLD_HOURS",
    "AC_KPI_03_THRESHOLD_MS",
    "AC_KPI_03_THRESHOLD_OPERATOR",
    "ApprovalWaitMsFixtureResult",
    "ApprovalWaitMsMetricResult",
    "SampleApproval",
    "evaluate_approval_wait_ms",
]
