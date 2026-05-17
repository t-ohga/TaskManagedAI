"""AC-KPI-02 ``time_to_merge`` aggregator.

Computes the AC-KPI-02 KPI (Ticket created_at → mock merge median hours)
from a fixture corpus loaded by
:func:`backend.app.services.eval.loader.load_fixture_corpus`. The
aggregator follows the Anti-Gaming invariant declared in the corpus
manifest::

    "time_to_merge is recomputed from input.sample_pull_requests,
     not copied from expected_aggregate"

i.e., the canonical median is always **recomputed** from the fixture's
``input.sample_pull_requests`` list. ``expected_aggregate.median_hours``
is consumed purely as a drift-detection oracle — a mismatch raises a
spec violation rather than silently overriding the recomputed value.

Per plan v2 §2.1 the metric is defined as::

    duration_ms[i] = merged_at[i] - ticket_created_at[i]    (status="merged")
    metric_value_hours = median(duration_ms[i] / 3_600_000)

with the strict causality invariant that ``merged_at >= ticket_created_at``
(boundary equality is valid — a PR merged exactly at ticket creation
contributes duration=0, intentional per plan v2 §2.1 / MED-003 adopt).
Causality violation is rejected at parse time as
``spec_violation:merged_at_causality`` (plan v2 §6 #12, no
``max(0, …)`` clamp — single source of truth).

The function is pure (no DB / file system / network access). Optional
``sut_results`` is consumed read-only for forward-compatibility with the
BL-0127b / SP-012 programmatic SUT execution path.

The KPI is "lower is better": ``threshold_met`` requires the recomputed
``metric_value_hours`` to be **at or below** ``AC_KPI_02_THRESHOLD_HOURS``
(2.0h).

Mock-only contract (plan v2 §6 #13): this aggregator does NOT read from
the live ``tickets`` table or any mock merge events table. Live wire-up
is SP-012 P0 Acceptance Test scope.

Note on tolerance constants (plan v2 §4.1 + MED-R2-001):
``_DURATION_REL_TOL = 0.0`` is intentional. Durations are ms-precise int
inputs; once converted to float hours the rounding error budget is bounded
absolutely (≈ 1 ms / 3.6e6 ≈ 2.78e-7 hours per row). A relative tolerance
would mis-scale on long-duration outliers (a 1000h PR would silently
accept ~3.6 ms drift, exceeding the documented ms-precision contract).
``math.isclose`` is therefore called with ``rel_tol=0.0`` and an
ms-derived ``abs_tol`` so drift detection scales with the *precision*
contract, not the *magnitude* of the duration.
"""

from __future__ import annotations

import datetime as _datetime
import logging
import math
import re
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from backend.app.db.models.dataset_version import FixtureKind
from backend.app.services.eval.loader import Fixture, LoadedCorpus

_LOGGER = logging.getLogger(__name__)

AC_KPI_02_KPI_ID: Final[Literal["AC-KPI-02"]] = "AC-KPI-02"
AC_KPI_02_METRIC_KEY: Final[Literal["time_to_merge"]] = "time_to_merge"
AC_KPI_02_THRESHOLD_HOURS: Final[float] = 2.0
AC_KPI_02_THRESHOLD_MS: Final[int] = 7_200_000  # 2.0h in ms
AC_KPI_02_THRESHOLD_OPERATOR: Final[Literal["<="]] = "<="

# PR status enum (fixture-only at P0; SP-012 will add a 5th source via
# live DB CHECK on the mock-merge-events table).
_KNOWN_PR_STATUSES: Final[frozenset[str]] = frozenset(
    {"open", "draft", "merged", "closed_without_merge"}
)
_MERGED_STATUS: Final[Literal["merged"]] = "merged"

# Compile-time partition invariant (plan v2 §6 #11 / §4.1).
if _MERGED_STATUS not in _KNOWN_PR_STATUSES:
    raise RuntimeError(
        "AC-KPI-02 partition invariant violation: "
        "_MERGED_STATUS must be in _KNOWN_PR_STATUSES."
    )

_SUPPORTED_FIXTURE_KINDS: Final[Sequence[FixtureKind]] = ("public_regression",)

# Sentinel that distinguishes "key absent" from "key present but malformed".
_AGGREGATE_NOT_PROVIDED: Final[object] = object()

# Lowercase canonical RFC 4122 UUID pattern.
_UUID_TEXT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

# Tolerance constants (plan v2 §4.1, MED-R2-001 rationale documented above).
# _DURATION_ABS_TOL_HOURS = 1 ms in hours; the canonical name encodes both
# the magnitude (≈ 2.78e-7) and the underlying ms-precision contract.
_DURATION_REL_TOL: Final[float] = 0.0
_DURATION_ABS_TOL_HOURS: Final[float] = 1.0 / 3_600_000  # 1 ms in hours
_THRESHOLD_HOURS_ABS_TOL: Final[float] = _DURATION_ABS_TOL_HOURS

# Anti-Gaming counter-defense thresholds (plan v2 §2.2 / §7.10).
_HIGH_REJECT_RATIO_THRESHOLD: Final[float] = 0.5
_ZERO_DURATION_WARNING_MIN_COUNT: Final[int] = 5


@dataclass(frozen=True)
class SamplePullRequest:
    """One PR observation from ``input.sample_pull_requests``.

    Plan v2 §4.2 / MED-004 adopt: the corpus-wide uniqueness key is
    ``(ticket_id, repository_id)`` so a single ticket may have multiple
    PR events on different repositories (Draft re-open / squash flows),
    as long as each pair is unique within the corpus.

    Mock-only contract (plan v2 §6 #13): ``ticket_id`` is a fixture
    identifier matching the schema pattern; live ``tickets.id`` ↔
    AgentRun bind is deferred to SP-012.
    """

    ticket_id: str
    tenant_id: int
    project_id: str
    repository_id: str | None
    status: str
    ticket_created_at_ms: int
    merged_at_ms: int | None


@dataclass(frozen=True)
class TimeToMergeFixtureResult:
    """Per-fixture result. ``spec_violation_reason`` and
    ``sut_failure_reason`` are mutually exclusive (at most one non-None
    per row; mirrors batch 5d/5e/5f pattern).
    """

    fixture_id: str
    case_key: str
    pulls_count: int
    merged_count: int
    open_count: int
    draft_count: int
    closed_without_merge_count: int
    recomputed_median_hours: float | None  # None when merged_count == 0
    expected_median_hours: float | None
    passed: bool
    spec_violation_reason: str | None
    sut_failure_reason: str | None
    sut_result: bool | None
    sut_attempted: bool


@dataclass(frozen=True)
class TimeToMergeMetricResult:
    """Corpus-level result.

    ``metric_value`` is the pooled (un-weighted) corpus-wide median of
    all merged PR durations in hours. When the corpus has zero merged
    PRs, ``metric_value`` is ``None`` (the KPI is undefined) and
    ``threshold_met`` is ``False`` with
    ``threshold_reason="no_merged_pulls"`` (plan v2 §4.2.2 HIGH-002
    explicit).
    """

    metric_value: float | None
    fixture_count: int
    total_pulls_across_corpus: int
    merged_count_across_corpus: int
    pass_count: int
    fail_count: int
    per_fixture: tuple[TimeToMergeFixtureResult, ...]
    threshold_hours: float
    threshold_operator: str
    threshold_met: bool
    threshold_reason: str
    manifest_violation_reason: str | None


def _is_finite_number(value: object) -> bool:
    """Return True for finite ``int`` / ``float`` (excluding ``bool``).

    Mirrors batch 5e/5f F-PR32-R6-002 overflow guard.
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


def _durations_match(recomputed: float, expected: float) -> bool:
    """Return True when two durations (in hours) agree within the
    documented absolute ms-precision tolerance. ``rel_tol=0.0`` is
    intentional (see module docstring MED-R2-001 rationale).
    """

    return math.isclose(
        recomputed,
        expected,
        rel_tol=_DURATION_REL_TOL,
        abs_tol=_DURATION_ABS_TOL_HOURS,
    )


def _manifest_violation_reason(corpus: LoadedCorpus) -> str | None:
    """Validate manifest top-level constants for AC-KPI-02."""

    manifest = corpus.manifest
    if manifest.get("kpi_id") != AC_KPI_02_KPI_ID:
        return "manifest_violation:kpi_id"
    if manifest.get("metric") != AC_KPI_02_METRIC_KEY:
        return "manifest_violation:metric"

    threshold = manifest.get("threshold")
    if not isinstance(threshold, dict):
        return "manifest_violation:threshold"
    threshold_map: Mapping[str, object] = threshold
    operator = threshold_map.get("operator")
    if operator != AC_KPI_02_THRESHOLD_OPERATOR:
        return "manifest_violation:threshold_operator"
    threshold_value = threshold_map.get("value")
    if not _is_finite_number(threshold_value):
        return "manifest_violation:threshold_value"
    if (
        abs(float(threshold_value) - AC_KPI_02_THRESHOLD_HOURS)  # type: ignore[arg-type]
        > _THRESHOLD_HOURS_ABS_TOL
    ):
        return "manifest_violation:threshold_value"
    unit = threshold_map.get("unit")
    if unit != "hours":
        return "manifest_violation:threshold_unit"
    return None


def _envelope_violation_reason(fixture: Fixture) -> str | None:
    if fixture.kpi_id != AC_KPI_02_KPI_ID:
        return "spec_violation:kpi_id"
    if fixture.metric_key != AC_KPI_02_METRIC_KEY:
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


def _parse_timestamp_ms(value: object) -> int | None:
    """Parse an ISO-8601 / RFC 3339 timestamp into epoch ms UTC.

    Returns ``None`` on any failure (not a string, not parseable, naive
    datetime, sub-millisecond precision, etc.). Aggregator caller maps
    the ``None`` to the appropriate ``spec_violation:*`` reason.

    Plan v2 §2.3 MED-001 contract:
      * naive datetime (no tzinfo) is rejected
      * trailing ``Z`` suffix is normalized to ``+00:00`` then parsed
      * non-UTC offset is accepted then normalized to UTC
      * OverflowError on huge int / float fields is caught upstream by
        ``_is_finite_number``; this helper only sees strings.

    F-PR34-R2-001 P2 adopt: reject sub-millisecond precision (any
    ``microsecond`` value not exactly divisible by 1000). The aggregator
    canonical representation is epoch ms; allowing sub-ms precision and
    floor-truncating would let two distinct timestamps with sub-ms
    deltas collapse to the same ms value, bypassing the causality check
    in ``_collect_sample_pulls`` (e.g., created=":00.9999+00:00",
    merged=":00.9991+00:00" both → :00.999, hiding a negative
    duration).
    """

    if not isinstance(value, str):
        return None
    if not value:
        return None
    # Normalize ``Z`` suffix (RFC 3339) to ``+00:00`` for fromisoformat.
    candidate = value
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = _datetime.datetime.fromisoformat(candidate)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        return None  # naive datetime reject (plan v2 §2.3)
    # Reject sub-millisecond precision (F-PR34-R2-001 P2 adopt).
    if dt.microsecond % 1000 != 0:
        return None
    # Normalize to UTC and convert to epoch ms.
    dt_utc = dt.astimezone(_datetime.UTC)
    try:
        return int(dt_utc.timestamp() * 1000)
    except (OverflowError, ValueError):
        return None


def _collect_sample_pulls(
    fixture: Fixture,
    *,
    corpus_seen_pr_keys: set[tuple[str, str | None]] | None = None,
) -> tuple[
    list[SamplePullRequest], str | None, frozenset[tuple[str, str | None]]
]:
    """Walk ``input.sample_pull_requests`` and validate each row.

    Returns ``(pulls, spec_violation_reason, pending_corpus_keys)``. On
    any structural violation the parser returns an empty list and empty
    pending set.

    Plan v2 §4.3 + §6 #1 / #9 (batch 5e F-PR32-R6-001 carry-over): this
    function **only stages** the corpus-wide ``(ticket_id, repository_id)``
    delta in ``pending_corpus_keys`` and never mutates the caller-owned
    ``corpus_seen_pr_keys`` set. The orchestrator merges only after the
    fixture passes all gates.

    MED-004 adopt: corpus-wide uniqueness key is ``(ticket_id,
    repository_id)`` so a single ticket may have multiple PR events on
    different repositories.
    """

    empty_keys: frozenset[tuple[str, str | None]] = frozenset()
    case_input = fixture.case_json.get("input")
    if not isinstance(case_input, dict):
        return [], "spec_violation:input", empty_keys

    sample_pulls = case_input.get("sample_pull_requests")
    if not isinstance(sample_pulls, list):
        return [], "spec_violation:sample_pull_requests", empty_keys
    if not sample_pulls:
        return [], "spec_violation:sample_pull_requests", empty_keys

    pulls: list[SamplePullRequest] = []
    seen_pr_keys: set[tuple[str, str | None]] = set()
    pending_keys: set[tuple[str, str | None]] = set()
    for raw_pull in sample_pulls:
        if not isinstance(raw_pull, dict):
            return [], "spec_violation:sample_pull_requests", empty_keys

        ticket_id = raw_pull.get("ticket_id")
        if not _validate_uuid_text(ticket_id) or not isinstance(ticket_id, str):
            return [], "spec_violation:ticket_id", empty_keys

        tenant_id = raw_pull.get("tenant_id")
        if not _is_non_bool_int(tenant_id) or tenant_id < 1:  # type: ignore[operator]
            return [], "spec_violation:tenant_id", empty_keys

        project_id = raw_pull.get("project_id")
        if not _validate_uuid_text(project_id) or not isinstance(project_id, str):
            return [], "spec_violation:project_id", empty_keys

        # repository_id is optional (None allowed for non-merged statuses;
        # see LOW-R2-001 rationale). When status="merged", repository_id
        # must be non-null (enforced below after status parse).
        repository_id_raw = raw_pull.get("repository_id")
        if repository_id_raw is None:
            repository_id: str | None = None
        elif _validate_uuid_text(repository_id_raw) and isinstance(
            repository_id_raw, str
        ):
            repository_id = repository_id_raw
        else:
            return [], "spec_violation:repository_id", empty_keys

        status = raw_pull.get("status")
        if not isinstance(status, str) or status not in _KNOWN_PR_STATUSES:
            return [], "spec_violation:status", empty_keys

        # LOW-R2-001 adopt: a merged PR must have a non-null repository_id.
        # The repository the PR was merged into is a defining piece of the
        # merge event; allowing None would let two distinct merges share
        # the corpus seen-key (ticket_id, None) and silently de-duplicate.
        if status == _MERGED_STATUS and repository_id is None:
            return [], "spec_violation:repository_id", empty_keys

        # Corpus-wide uniqueness check (MED-004) on (ticket_id, repository_id).
        pr_key = (ticket_id, repository_id)
        if pr_key in seen_pr_keys:
            return [], "spec_violation:duplicate_pr_key", empty_keys
        if corpus_seen_pr_keys is not None and pr_key in corpus_seen_pr_keys:
            return (
                [],
                "spec_violation:duplicate_pr_key_across_fixtures",
                empty_keys,
            )
        seen_pr_keys.add(pr_key)
        if corpus_seen_pr_keys is not None:
            pending_keys.add(pr_key)

        ticket_created_at_raw = raw_pull.get("ticket_created_at")
        ticket_created_at_ms = _parse_timestamp_ms(ticket_created_at_raw)
        if ticket_created_at_ms is None:
            return [], "spec_violation:ticket_created_at", empty_keys

        merged_at_raw = raw_pull.get("merged_at")
        merged_at_ms: int | None
        if status == _MERGED_STATUS:
            # Plan v2 §6 #12 / HIGH-001: merged_at must be non-null AND
            # >= ticket_created_at (boundary == valid per MED-003).
            if merged_at_raw is None:
                return [], "spec_violation:merged_at_required", empty_keys
            merged_at_ms = _parse_timestamp_ms(merged_at_raw)
            if merged_at_ms is None:
                return [], "spec_violation:merged_at", empty_keys
            if merged_at_ms < ticket_created_at_ms:
                return [], "spec_violation:merged_at_causality", empty_keys
        else:
            # Plan v2 §7.5 (merged_at non-null when not merged): reject
            # to keep the fixture clean. When ``merged_at`` is null OR
            # absent for a non-merged status, accept.
            if merged_at_raw is not None:
                return [], "spec_violation:merged_at_unexpected", empty_keys
            merged_at_ms = None

        pulls.append(
            SamplePullRequest(
                ticket_id=ticket_id,
                tenant_id=int(tenant_id),  # type: ignore[arg-type]
                project_id=project_id,
                repository_id=repository_id,
                status=status,
                ticket_created_at_ms=ticket_created_at_ms,
                merged_at_ms=merged_at_ms,
            )
        )

    return pulls, None, frozenset(pending_keys)


def _fixture_threshold(fixture: Fixture) -> object:
    if "threshold" in fixture.expected_json:
        return fixture.expected_json["threshold"]
    if "threshold" in fixture.raw_json:
        return fixture.raw_json["threshold"]
    return _AGGREGATE_NOT_PROVIDED


def _fixture_threshold_violation_reason(fixture: Fixture) -> str | None:
    """Validate the fixture-declared ``threshold`` against AC-KPI-02
    constants (F-PR34-R2-002 P2 adopt).

    The per-fixture ``threshold`` field is optional (the manifest is the
    canonical source); however when present and non-null it must match
    the AC-KPI-02 contract exactly (``operator: "<="``, ``value: 2.0``,
    ``unit: "hours"``) so a persisted corpus that bypasses the JSON
    Schema layer cannot declare a relaxed fixture-level threshold
    (e.g., ``value: 999`` to make ``threshold_passed`` look valid).

    Mirrors the batch 5e ``cost_per_completed_task`` defense-in-depth
    pattern.
    """

    threshold = _fixture_threshold(fixture)
    if threshold is _AGGREGATE_NOT_PROVIDED or threshold is None:
        # Fixture-level threshold is optional; the manifest is canonical.
        return None
    if not isinstance(threshold, dict):
        return "spec_violation:threshold"
    declared_op = threshold.get("operator")
    if declared_op != AC_KPI_02_THRESHOLD_OPERATOR:
        return "spec_violation:threshold_operator"
    declared_value = threshold.get("value")
    if not _is_finite_number(declared_value):
        return "spec_violation:threshold_value"
    if (
        abs(float(declared_value) - AC_KPI_02_THRESHOLD_HOURS)  # type: ignore[arg-type]
        > _THRESHOLD_HOURS_ABS_TOL
    ):
        return "spec_violation:threshold_value"
    declared_unit = threshold.get("unit")
    if declared_unit != "hours":
        return "spec_violation:threshold_unit"
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
    recomputed_pulls: int,
    recomputed_merged: int,
    recomputed_open: int,
    recomputed_draft: int,
    recomputed_closed_without_merge: int,
    recomputed_median_hours: float | None,
) -> str | None:
    raw = _expected_aggregate_value(fixture)
    if raw is _AGGREGATE_NOT_PROVIDED:
        return "spec_violation:expected_aggregate_missing"
    if not isinstance(raw, dict):
        return "spec_violation:expected_aggregate"

    # Each declared count field must be a strict non-negative non-bool int.
    declared_pulls = raw.get("pulls_count")
    if not _is_non_bool_int(declared_pulls) or declared_pulls < 0:  # type: ignore[operator]
        return "spec_violation:expected_aggregate"
    declared_merged = raw.get("merged_count")
    if not _is_non_bool_int(declared_merged) or declared_merged < 0:  # type: ignore[operator]
        return "spec_violation:expected_aggregate"
    declared_open = raw.get("open_count")
    if not _is_non_bool_int(declared_open) or declared_open < 0:  # type: ignore[operator]
        return "spec_violation:expected_aggregate"
    declared_draft = raw.get("draft_count")
    if not _is_non_bool_int(declared_draft) or declared_draft < 0:  # type: ignore[operator]
        return "spec_violation:expected_aggregate"
    declared_closed = raw.get("closed_without_merge_count")
    if not _is_non_bool_int(declared_closed) or declared_closed < 0:  # type: ignore[operator]
        return "spec_violation:expected_aggregate"

    if declared_pulls != recomputed_pulls:
        return "spec_violation:expected_aggregate_pulls_drift"
    if declared_merged != recomputed_merged:
        return "spec_violation:expected_aggregate_merged_drift"
    if declared_open != recomputed_open:
        return "spec_violation:expected_aggregate_open_drift"
    if declared_draft != recomputed_draft:
        return "spec_violation:expected_aggregate_draft_drift"
    if declared_closed != recomputed_closed_without_merge:
        return "spec_violation:expected_aggregate_closed_drift"

    # Closure invariant (plan v2 §6 #10 / MEDIUM-004 carry-over).
    # Defensive-in-depth: by construction this branch is unreachable when
    # every count drift check above passes and ``_collect_sample_pulls``
    # exhaustively partitions the input into the four status buckets.
    # F-PR33-001 lesson from batch 5f carry-over.
    if (
        declared_merged
        + declared_open
        + declared_draft
        + declared_closed
        != declared_pulls
    ):
        return "spec_violation:expected_aggregate_closure_violation"

    # median_hours drift check.
    if "median_hours" not in raw:
        return "spec_violation:expected_aggregate"
    declared_median_raw = raw["median_hours"]
    if recomputed_median_hours is None:
        # Plan v2 §6 #4: merged_count == 0 → null OR 0.0 acceptable.
        if declared_median_raw is None:
            pass
        elif (
            _is_finite_number(declared_median_raw)
            and float(declared_median_raw) == 0.0
        ):
            pass
        else:
            return "spec_violation:expected_aggregate_median_drift"
    else:
        if not _is_finite_number(declared_median_raw):
            return "spec_violation:expected_aggregate"
        # Plan v2 §6 #3: reject negative declared median before tolerance.
        declared_median = float(declared_median_raw)
        if declared_median < 0.0:
            return "spec_violation:expected_aggregate"
        if not _durations_match(declared_median, recomputed_median_hours):
            return "spec_violation:expected_aggregate_median_drift"

    return None


def _warn_unknown_sut_results(
    corpus: LoadedCorpus, sut_results: Mapping[str, bool]
) -> None:
    fixture_ids = {fixture.fixture_id for fixture in corpus.fixtures}
    for fixture_id in sorted(set(sut_results) - fixture_ids):
        _LOGGER.warning(
            "Ignoring SUT result for unknown AC-KPI-02 fixture_id=%s",
            fixture_id,
        )


def _maybe_warn_anti_gaming(
    fixture_id: str,
    *,
    pulls_count: int,
    merged_count: int,
    closed_without_merge_count: int,
    durations_hours: Sequence[float],
) -> None:
    """Plan v2 §2.2 + §7.10: informational warnings (do NOT reject)."""

    if pulls_count > 0:
        reject_ratio = closed_without_merge_count / pulls_count
        if reject_ratio > _HIGH_REJECT_RATIO_THRESHOLD:
            _LOGGER.warning(
                "AC-KPI-02 fixture %s declares closed_without_merge_ratio=%.3f "
                "(> %.2f); review for Anti-Gaming high-rejection pattern.",
                fixture_id,
                reject_ratio,
                _HIGH_REJECT_RATIO_THRESHOLD,
            )
    if (
        merged_count >= _ZERO_DURATION_WARNING_MIN_COUNT
        and durations_hours
        and all(d == 0.0 for d in durations_hours)
    ):
        _LOGGER.warning(
            "AC-KPI-02 fixture %s declares %d merged PRs all with duration=0.0; "
            "review for Anti-Gaming all-zero-duration pattern.",
            fixture_id,
            merged_count,
        )


def _threshold_reason(
    *,
    fixture_count: int,
    merged_count_across_corpus: int,
    metric_value: float | None,
    spec_violation_present: bool,
    manifest_violation_present: bool,
    sut_failure_present: bool,
) -> str:
    """Plan v2 §4.2.2 priority order."""

    if fixture_count == 0:
        return "no_fixtures"
    if manifest_violation_present:
        return "manifest_violation"
    if spec_violation_present:
        return "spec_violation"
    if sut_failure_present:
        return "sut_failure"
    if merged_count_across_corpus == 0 or metric_value is None:
        return "no_merged_pulls"
    if metric_value <= AC_KPI_02_THRESHOLD_HOURS + _THRESHOLD_HOURS_ABS_TOL:
        return "threshold_met"
    return "above_threshold"


def _expected_median_from_aggregate(fixture: Fixture) -> float | None:
    raw = _expected_aggregate_value(fixture)
    if not isinstance(raw, dict):
        return None
    declared = raw.get("median_hours")
    if declared is None:
        return None
    if not _is_finite_number(declared):
        return None
    return float(declared)


def evaluate_time_to_merge(
    corpus: LoadedCorpus,
    *,
    sut_results: Mapping[str, bool] | None = None,
) -> TimeToMergeMetricResult:
    """Compute AC-KPI-02 ``time_to_merge`` from a loaded corpus.

    Anti-Gaming invariants (manifest ``anti_gaming_rules.kpi_specific``):

    * ``time_to_merge`` is **always recomputed** from
      ``input.sample_pull_requests``; the fixture's declared
      ``expected_aggregate.median_hours`` is consumed as a drift-detection
      oracle only.
    * Only PRs with status ``"merged"`` contribute to the median.
    * Unknown statuses reject as ``spec_violation:status``.
    * Causality: ``merged_at >= ticket_created_at`` (boundary equality
      valid per plan v2 §2.1 / MED-003).
    * The corpus-wide median is the **pooled (un-weighted)** median of
      ALL merged durations (plan v2 §4.2.1 MED-002).

    Per-fixture procedure:
        1. Skip non-public-regression fixtures.
        2. Validate envelope and fixture-level threshold against
           AC-KPI-02 constants.
        3. Walk ``input.sample_pull_requests`` validating shapes +
           causality + corpus-wide uniqueness.
        4. Bucket by status; recompute ``median_hours`` from merged
           durations.
        5. Drift-check against ``expected_aggregate``.
        6. Optionally cross-check ``sut_results[fixture_id]``.

    Corpus-level metric:
        ``metric_value = median(all merged durations in hours)``
        ``threshold_met`` ⇔ ``metric_value <= 2.0 + epsilon`` AND
        ``fixture_count > 0`` AND ``merged_count_across_corpus > 0`` AND
        no spec/manifest/SUT failure.
    """

    if sut_results is not None:
        _warn_unknown_sut_results(corpus, sut_results)

    per_fixture: list[TimeToMergeFixtureResult] = []
    spec_violation_present = False
    sut_failure_present = False
    total_pulls_across_corpus = 0
    merged_count_across_corpus = 0
    all_durations_hours: list[float] = []
    corpus_seen_pr_keys: set[tuple[str, str | None]] = set()

    for fixture in corpus.fixtures:
        if fixture.fixture_kind not in _SUPPORTED_FIXTURE_KINDS:
            continue

        envelope_reason = _envelope_violation_reason(fixture)
        pulls, parsing_violation, pending_pr_keys = _collect_sample_pulls(
            fixture,
            corpus_seen_pr_keys=corpus_seen_pr_keys,
        )

        merged_pulls = [p for p in pulls if p.status == _MERGED_STATUS]
        open_pulls = [p for p in pulls if p.status == "open"]
        draft_pulls = [p for p in pulls if p.status == "draft"]
        closed_pulls = [p for p in pulls if p.status == "closed_without_merge"]
        merged_count = len(merged_pulls)
        open_count = len(open_pulls)
        draft_count = len(draft_pulls)
        closed_count = len(closed_pulls)
        pulls_count = len(pulls)

        # By construction (defense #12), every merged pull has a valid
        # merged_at_ms >= ticket_created_at_ms.
        durations_hours: list[float] = []
        for pr in merged_pulls:
            # Invariant guaranteed by ``_collect_sample_pulls`` defense
            # #12 (causality): every merged pull has a valid
            # ``merged_at_ms`` >= ``ticket_created_at_ms``. Re-check via
            # ``if`` (not ``assert``, per ruff S101) so ``python -O``
            # cannot strip the safety net.
            if pr.merged_at_ms is None:
                continue
            duration_ms = pr.merged_at_ms - pr.ticket_created_at_ms
            durations_hours.append(duration_ms / 3_600_000.0)
        recomputed_median_hours: float | None = (
            statistics.median(durations_hours) if durations_hours else None
        )

        spec_reason: str | None = envelope_reason
        # F-PR34-R2-002 P2 adopt: validate fixture-level threshold (if
        # declared) before falling through to expected_aggregate.
        if spec_reason is None:
            spec_reason = _fixture_threshold_violation_reason(fixture)
        if spec_reason is None and parsing_violation is not None:
            spec_reason = parsing_violation
        if spec_reason is None:
            spec_reason = _expected_aggregate_violation_reason(
                fixture,
                recomputed_pulls=pulls_count,
                recomputed_merged=merged_count,
                recomputed_open=open_count,
                recomputed_draft=draft_count,
                recomputed_closed_without_merge=closed_count,
                recomputed_median_hours=recomputed_median_hours,
            )

        # Plan v2 §6 #9: gate corpus state on final spec_reason.
        if spec_reason is None:
            total_pulls_across_corpus += pulls_count
            merged_count_across_corpus += merged_count
            all_durations_hours.extend(durations_hours)
            if pending_pr_keys:
                corpus_seen_pr_keys.update(pending_pr_keys)
            _maybe_warn_anti_gaming(
                fixture.fixture_id,
                pulls_count=pulls_count,
                merged_count=merged_count,
                closed_without_merge_count=closed_count,
                durations_hours=durations_hours,
            )

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
            TimeToMergeFixtureResult(
                fixture_id=fixture.fixture_id,
                case_key=fixture.case_key,
                pulls_count=pulls_count,
                merged_count=merged_count,
                open_count=open_count,
                draft_count=draft_count,
                closed_without_merge_count=closed_count,
                recomputed_median_hours=recomputed_median_hours,
                expected_median_hours=_expected_median_from_aggregate(fixture),
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
    # Plan v2 §4.2.1: pooled (un-weighted) corpus-wide median across all
    # merged durations.
    metric_value: float | None = (
        statistics.median(all_durations_hours)
        if all_durations_hours
        else None
    )
    manifest_reason = _manifest_violation_reason(corpus)
    threshold_reason = _threshold_reason(
        fixture_count=fixture_count,
        merged_count_across_corpus=merged_count_across_corpus,
        metric_value=metric_value,
        spec_violation_present=spec_violation_present,
        manifest_violation_present=manifest_reason is not None,
        sut_failure_present=sut_failure_present,
    )

    return TimeToMergeMetricResult(
        metric_value=metric_value,
        fixture_count=fixture_count,
        total_pulls_across_corpus=total_pulls_across_corpus,
        merged_count_across_corpus=merged_count_across_corpus,
        pass_count=pass_count,
        fail_count=fail_count,
        per_fixture=tuple(per_fixture),
        threshold_hours=AC_KPI_02_THRESHOLD_HOURS,
        threshold_operator=AC_KPI_02_THRESHOLD_OPERATOR,
        threshold_met=threshold_reason == "threshold_met",
        threshold_reason=threshold_reason,
        manifest_violation_reason=manifest_reason,
    )


__all__ = [
    "AC_KPI_02_KPI_ID",
    "AC_KPI_02_METRIC_KEY",
    "AC_KPI_02_THRESHOLD_HOURS",
    "AC_KPI_02_THRESHOLD_MS",
    "AC_KPI_02_THRESHOLD_OPERATOR",
    "SamplePullRequest",
    "TimeToMergeFixtureResult",
    "TimeToMergeMetricResult",
    "evaluate_time_to_merge",
]
