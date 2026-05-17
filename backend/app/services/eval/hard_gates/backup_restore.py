"""AC-HARD-04 ``backup_restore_rpo_rto`` hard-gate aggregator skeleton.

Computes the AC-HARD-04 hard-gate metric (`backup_restore_rpo_rto`) from
a fixture corpus loaded by
:func:`backend.app.services.eval.loader.load_fixture_corpus`. The
aggregator is the **fixture contract skeleton** for AC-HARD-04
(BL-0159) per SP-011 must_ship line 173. Real backup / restore SUT
execution + PITR activation are deferred to Sprint 11.5 BL-0159b
(:doc:`docs/sprints/SP-011-5_operational_hardening`).

PRD-01 §10.3 (Phase H PH-F-010 fix) is explicit: **P0 では PITR は要求
しない**. The existing fixture schema (``expected_pitr_success:
const true``) is a **forward-looking declaration contract** for Sprint
11.5 BL-0159b where the SUT layer will actually execute and verify
PITR. At P0 this aggregator validates the fixture envelope only — it
does NOT interpret ``expected_pitr_success == True`` as "PITR was
actually executed and succeeded".

Anti-Gaming invariants (manifest ``anti_gaming_rules.gate_specific``):

* restore timing and checksum evidence are captured before policy or
  script tuning (Sprint 11.5 SUT scope, deferred)
* private holdout backup paths and checksums are stored in an external
  encrypted vault (P0 scope satisfied via existing manifest declaration)
* monthly_refresh_append_only + separate_fixture_and_policy_commits at
  fixture envelope level (this aggregator's defense #14)

Hard-gate threshold: **1.0** (100% pass required). 0 spec violations +
all required ``drill_kind`` classes (skeleton: ``{"dev_restore"}``)
covered → pass; otherwise fail.

The function is pure (no DB / file system / network access). Optional
``sut_results`` is consumed read-only for forward-compatibility with
the Sprint 11.5 BL-0159b programmatic SUT execution path.

5+ source enum integrity:
1. Aggregator frozenset ``_KNOWN_DRILL_KINDS``
2. Skeleton required subset ``AC_HARD_04_REQUIRED_DRILL_KINDS_SKELETON``
3. Sprint 11.5 future required ``AC_HARD_04_FUTURE_REQUIRED_DRILL_KINDS``
4. Pytest ``EXPECTED_KNOWN_DRILL_KINDS`` constants
5. Fixture schema ``expected_schema.json properties.input.properties.drill_kind.enum``

Partition: ``_REQUIRED_SKELETON ⊆ _REQUIRED_FUTURE ⊆ _KNOWN``
(import-time runtime check, S101-safe).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from backend.app.db.models.dataset_version import FixtureKind
from backend.app.services.eval.loader import Fixture, LoadedCorpus

_LOGGER = logging.getLogger(__name__)

AC_HARD_04_GATE_ID: Final[Literal["AC-HARD-04"]] = "AC-HARD-04"
AC_HARD_04_METRIC_KEY: Final[Literal["backup_restore_rpo_rto"]] = "backup_restore_rpo_rto"
AC_HARD_04_PATTERN_HIT_KIND: Final[Literal["backup_restore"]] = "backup_restore"
AC_HARD_04_EXPECTED_DECISION: Final[Literal["pass"]] = "pass"
AC_HARD_04_RPO_HOURS_MAX: Final[float] = 24.0
AC_HARD_04_RTO_HOURS_MAX: Final[float] = 4.0
AC_HARD_04_THRESHOLD: Final[float] = 1.0
AC_HARD_04_REQUIRED_CHECKSUM_ALGORITHM: Final[Literal["sha256"]] = "sha256"

# 3-element drill_kind enum, matches fixture schema.
_KNOWN_DRILL_KINDS: Final[frozenset[str]] = frozenset(
    {"dev_restore", "private_staging_restore", "pitr"}
)
# Plan v2 §2.1: skeleton scope = 1 drill_kind required, Sprint 11.5
# BL-0159b expands to 3.
AC_HARD_04_REQUIRED_DRILL_KINDS_SKELETON: Final[frozenset[str]] = frozenset(
    {"dev_restore"}
)
AC_HARD_04_FUTURE_REQUIRED_DRILL_KINDS: Final[frozenset[str]] = frozenset(
    {"dev_restore", "private_staging_restore", "pitr"}
)
# Plan v2 §6 #15 / MED-2 adopt: backup descriptors must not carry PII /
# confidential content. payload_data_class ordinal is the canonical
# Provider Compliance ordinal; AC-HARD-04 fixtures stay at "internal"
# or below (skeleton fixture uses "internal").
_ALLOWED_PAYLOAD_DATA_CLASSES: Final[frozenset[str]] = frozenset(
    {"public", "internal"}
)

# Partition invariants — import-time runtime check (S101-safe).
if not (AC_HARD_04_REQUIRED_DRILL_KINDS_SKELETON <= AC_HARD_04_FUTURE_REQUIRED_DRILL_KINDS):
    raise RuntimeError(
        "AC-HARD-04 partition invariant violation: skeleton must be a "
        "subset of future required drill_kinds."
    )
if not (AC_HARD_04_FUTURE_REQUIRED_DRILL_KINDS <= _KNOWN_DRILL_KINDS):
    raise RuntimeError(
        "AC-HARD-04 partition invariant violation: future required must "
        "be a subset of known drill_kinds."
    )

_SUPPORTED_FIXTURE_KINDS: Final[Sequence[FixtureKind]] = ("public_regression",)


@dataclass(frozen=True)
class BackupRestoreFixtureResult:
    """Per-fixture AC-HARD-04 result.

    ``drill_kind`` is ``None`` when a spec violation prevented the
    parser from reading the value cleanly (e.g., unknown drill_kind
    enum). Otherwise it carries the validated drill_kind for
    corpus-wide coverage tracking.

    F-PR37-R1-001 (Codex R1 P2) adopt: separate ``spec_violation_reason``
    (fixture envelope defects) from ``sut_failure_reason`` (SUT runner
    failures: missing / invalid_type / returned_false). The KPI
    aggregator pattern (batch 5d/5e/5f/5g/5h-pre) physically separates
    these two failure modes so downstream dashboards don't misclassify
    SUT outages as fixture defects. ``at most one of these fields is
    non-None per row``.
    """

    fixture_id: str
    case_key: str
    drill_kind: str | None
    passed: bool
    spec_violation_reason: str | None
    sut_failure_reason: str | None
    sut_result: bool | None


@dataclass(frozen=True)
class BackupRestoreMetricResult:
    """Corpus-level AC-HARD-04 result.

    ``metric_value`` is the per-fixture pass-rate (0.0 — 1.0). Per
    plan v2 §1.2 the aggregator is a **pass-rate aggregator**;
    numeric ``backup_restore_rpo_hours`` / ``backup_restore_rto_hours``
    Grafana metrics are SP-022+ scope (SUT layer adds
    ``measured_rpo_hours`` / ``measured_rto_hours``).

    ``missing_drill_kinds`` reports skeleton-required kinds not
    covered (plan v2 §2.1). Sprint 11.5 BL-0159b will switch to
    ``AC_HARD_04_FUTURE_REQUIRED_DRILL_KINDS``.
    """

    metric_value: float
    fixture_count: int
    pass_count: int
    fail_count: int
    per_fixture: tuple[BackupRestoreFixtureResult, ...]
    threshold: float
    threshold_met: bool
    threshold_reason: str
    manifest_violation_reason: str | None = None
    missing_drill_kinds: tuple[str, ...] = ()


def _expected_value(fixture: Fixture, key: str) -> object:
    return fixture.expected_json.get(key, fixture.raw_json.get(key))


def _input_value(fixture: Fixture, *path: str) -> object:
    current: object = fixture.case_json.get("input")
    for segment in path:
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
    return current


def _fixture_spec_violation_reason(fixture: Fixture) -> str | None:
    """Validate fixture envelope against AC-HARD-04 hard-gate contract.

    Plan v2 §6 defense matrix #1-#7, #14, #15. Returns the first
    spec_violation reason encountered, or ``None`` on full compliance.
    """

    if fixture.gate_id != AC_HARD_04_GATE_ID:
        return "spec_violation:gate_id"
    if fixture.metric_key != AC_HARD_04_METRIC_KEY:
        return "spec_violation:metric_key"
    if fixture.fixture_kind not in _SUPPORTED_FIXTURE_KINDS:
        return "spec_violation:fixture_kind"
    if _expected_value(fixture, "expected_decision") != AC_HARD_04_EXPECTED_DECISION:
        return "spec_violation:expected_decision"
    if _expected_value(fixture, "pattern_hit_kind") != AC_HARD_04_PATTERN_HIT_KIND:
        return "spec_violation:pattern_hit_kind"

    # AC-HARD-04 boundary declarations (plan v2 §2, defense #2):
    rpo_max = _expected_value(fixture, "expected_rpo_hours_max")
    if not isinstance(rpo_max, int | float) or isinstance(rpo_max, bool):
        return "spec_violation:expected_rpo_hours_max"
    if float(rpo_max) > AC_HARD_04_RPO_HOURS_MAX:
        return "spec_violation:expected_rpo_hours_max"
    rto_max = _expected_value(fixture, "expected_rto_hours_max")
    if not isinstance(rto_max, int | float) or isinstance(rto_max, bool):
        return "spec_violation:expected_rto_hours_max"
    if float(rto_max) > AC_HARD_04_RTO_HOURS_MAX:
        return "spec_violation:expected_rto_hours_max"

    # Plan v2 §1.1 / defense #3: forward-looking declaration contract.
    # At P0 the aggregator validates the envelope ``True`` only; Sprint
    # 11.5 BL-0159b SUT will actually execute PITR.
    if _expected_value(fixture, "expected_pitr_success") is not True:
        return "spec_violation:expected_pitr_success"
    if _expected_value(fixture, "expected_checksum_match") is not True:
        return "spec_violation:expected_checksum_match"

    # input.* envelope (defenses #4-#7):
    drill_kind = _input_value(fixture, "drill_kind")
    if not isinstance(drill_kind, str) or drill_kind not in _KNOWN_DRILL_KINDS:
        return "spec_violation:drill_kind"
    if _input_value(fixture, "backup_artifact", "encrypted") is not True:
        return "spec_violation:backup_artifact_encrypted"
    if _input_value(fixture, "restore_target", "isolated") is not True:
        return "spec_violation:restore_target_isolated"
    if (
        _input_value(fixture, "checksum", "algorithm")
        != AC_HARD_04_REQUIRED_CHECKSUM_ALGORITHM
    ):
        return "spec_violation:checksum_algorithm"

    # F-PR37-R1-002 (Codex R1 P2) adopt: validate declared backup age
    # against the declared RPO. Without this check, a fixture could
    # declare ``expected_rpo_hours_max=24`` but supply
    # ``backup_artifact.created_at_offset_hours=999`` and the gate would
    # silently pass. The backup age is the actual evidence that the RPO
    # contract is feasible — if the backup is older than the declared
    # RPO window, the gate has already failed semantically.
    backup_age_hours = _input_value(
        fixture, "backup_artifact", "created_at_offset_hours"
    )
    if (
        not isinstance(backup_age_hours, int | float)
        or isinstance(backup_age_hours, bool)
        or float(backup_age_hours) < 0.0
    ):
        return "spec_violation:backup_artifact_created_at_offset_hours"
    if float(backup_age_hours) > float(rpo_max):
        return "spec_violation:backup_age_exceeds_rpo"

    # Plan v2 §6 defense #14 / MED-1 adopt: fixture-level anti_gaming
    # envelope (append_only_refresh + separate_fixture_and_policy_commits).
    anti_gaming = fixture.raw_json.get("anti_gaming")
    if not isinstance(anti_gaming, dict):
        return "spec_violation:anti_gaming"
    if anti_gaming.get("append_only_refresh") is not True:
        return "spec_violation:anti_gaming"
    if anti_gaming.get("separate_fixture_and_policy_commits") is not True:
        return "spec_violation:anti_gaming"

    # Plan v2 §6 defense #15 / MED-2 adopt: payload_data_class boundary
    # (backup descriptors must not carry PII / confidential).
    # F-PR37-004 (code-reviewer R1 LOW) adopt: use `get(..., default)` so
    # an empty dict in raw_json does NOT silently fall back to
    # ``fixture.metadata`` via `or` short-circuit (empty dict is falsy).
    metadata = fixture.raw_json.get("metadata", fixture.metadata)
    if not isinstance(metadata, dict):
        return "spec_violation:metadata"
    payload_data_class = metadata.get("payload_data_class")
    if (
        not isinstance(payload_data_class, str)
        or payload_data_class not in _ALLOWED_PAYLOAD_DATA_CLASSES
    ):
        return "spec_violation:payload_data_class"

    return None


def _drill_kind_for_fixture(fixture: Fixture) -> str | None:
    """Extract validated drill_kind for corpus-wide coverage tracking.

    Returns ``None`` when the fixture's drill_kind is unknown / missing
    (caller treats this as "does not contribute to coverage").
    """

    drill_kind = _input_value(fixture, "drill_kind")
    if isinstance(drill_kind, str) and drill_kind in _KNOWN_DRILL_KINDS:
        return drill_kind
    return None


def _manifest_violation_reason(corpus: LoadedCorpus) -> str | None:
    """Validate manifest top-level constants for AC-HARD-04.

    Plan v2 §6 defense #9 (carry-over from batch 5b F-PR29-R1-001) +
    F-PR37-001 adopt (code-reviewer R1 MEDIUM): also enforce
    ``dataset_version`` is a non-empty string and
    ``splits.public_regression.expected_count`` is a non-negative int
    matching the loaded ``public_regression`` fixture count. Otherwise a
    corpus where ``dataset_version`` is bumped without realigning
    ``expected_count`` passes silently, defeating the Anti-Gaming
    dataset_version pin (`.claude/rules/testing.md §10`).
    """

    manifest = corpus.manifest
    if manifest.get("hard_gate_id") != AC_HARD_04_GATE_ID:
        return "manifest_violation:hard_gate_id"
    if manifest.get("metric") != AC_HARD_04_METRIC_KEY:
        return "manifest_violation:metric"

    # F-PR37-001 adopt: dataset_version must be a non-empty string.
    dataset_version = manifest.get("dataset_version")
    if not isinstance(dataset_version, str) or not dataset_version:
        return "manifest_violation:dataset_version"

    # F-PR37-001 adopt: splits.public_regression.expected_count must
    # match the count of public_regression fixtures actually loaded into
    # the corpus. A drift here means the manifest's declared corpus
    # shape diverges from reality.
    splits = manifest.get("splits")
    if not isinstance(splits, dict):
        return "manifest_violation:splits"
    public_split = splits.get("public_regression")
    if not isinstance(public_split, dict):
        return "manifest_violation:splits"
    declared_expected_count = public_split.get("expected_count")
    if (
        not isinstance(declared_expected_count, int)
        or isinstance(declared_expected_count, bool)
        or declared_expected_count < 0
    ):
        return "manifest_violation:expected_count"
    actual_public_count = sum(
        1
        for fixture in corpus.fixtures
        if fixture.fixture_kind == "public_regression"
    )
    if declared_expected_count != actual_public_count:
        return "manifest_violation:expected_count"

    return None


def _missing_drill_kinds(
    fixtures: Sequence[BackupRestoreFixtureResult],
) -> tuple[str, ...]:
    """Return skeleton-required drill_kinds not covered by passing fixtures.

    Plan v2 §6 defense #12 carry-over: only fixtures with no
    spec_violation contribute to coverage tracking. A spec-violating
    fixture's drill_kind does NOT count toward coverage.
    """

    observed: set[str] = set()
    for result in fixtures:
        if result.spec_violation_reason is not None:
            continue
        if result.drill_kind is None:
            continue
        observed.add(result.drill_kind)
    return tuple(sorted(AC_HARD_04_REQUIRED_DRILL_KINDS_SKELETON - observed))


def _warn_unknown_sut_results(
    corpus: LoadedCorpus, sut_results: Mapping[str, bool]
) -> None:
    fixture_ids = {fixture.fixture_id for fixture in corpus.fixtures}
    for fixture_id in sorted(set(sut_results) - fixture_ids):
        _LOGGER.warning(
            "Ignoring SUT result for unknown AC-HARD-04 fixture_id=%s",
            fixture_id,
        )


def _threshold_reason(
    *,
    fixture_count: int,
    metric_value: float,
    spec_violation_present: bool,
    manifest_violation_present: bool,
    missing_drill_kinds_present: bool,
) -> str:
    """Plan v2 §5.3 priority order (MED-4 adopt: spec_violation >
    missing_drill_kinds because corruption is deeper root cause than
    coverage gap).
    """

    if fixture_count == 0:
        return "no_fixtures"
    if manifest_violation_present:
        return "manifest_violation"
    if spec_violation_present:
        return "spec_violation"
    if missing_drill_kinds_present:
        return "missing_drill_kinds"
    if metric_value >= AC_HARD_04_THRESHOLD:
        return "threshold_met"
    return "below_threshold"


def evaluate_backup_restore_rpo_rto(
    corpus: LoadedCorpus,
    *,
    sut_results: Mapping[str, bool] | None = None,
) -> BackupRestoreMetricResult:
    """Compute AC-HARD-04 ``backup_restore_rpo_rto`` from a loaded corpus.

    Plan v2 §1.1 PITR resolution: the aggregator validates the fixture
    envelope only. ``expected_pitr_success == True`` is a
    forward-looking declaration contract for Sprint 11.5 BL-0159b; this
    aggregator does NOT execute or verify real PITR.

    Plan v2 §1.2 metric layer separation: this is a **per-fixture
    pass-rate** aggregator (threshold = 1.0). Numeric Grafana metrics
    (``backup_restore_rpo_hours`` / ``backup_restore_rto_hours``) are
    SP-022+ scope.

    Per-fixture procedure:
        1. Skip non-public-regression fixtures (SP-022+ redacted splits).
        2. Validate envelope (gate_id / metric_key / fixture_kind /
           expected_decision / pattern_hit_kind / RPO ≤ 24 / RTO ≤ 4 /
           PITR=True / checksum_match=True / drill_kind enum / encrypted
           / isolated / sha256).
        3. Validate fixture-level anti_gaming envelope (append_only +
           separate_fixture_and_policy_commits).
        4. Validate metadata.payload_data_class ∈ {public, internal}.
        5. Optionally cross-check sut_results[fixture_id]
           (forward-compat Sprint 11.5).

    Corpus-level metric:
        ``metric_value = pass_count / fixture_count`` (0.0 — 1.0).
        ``threshold_met`` ⇔ metric_value >= 1.0 AND fixture_count > 0
        AND no spec/manifest violation AND no missing required
        drill_kinds.
        ``threshold_reason`` priority: no_fixtures → manifest_violation
        → spec_violation → missing_drill_kinds → threshold_met →
        below_threshold.
    """

    if sut_results is not None:
        _warn_unknown_sut_results(corpus, sut_results)

    per_fixture: list[BackupRestoreFixtureResult] = []
    spec_violation_present = False

    for fixture in corpus.fixtures:
        if fixture.fixture_kind not in _SUPPORTED_FIXTURE_KINDS:
            # Plan v2 §6 defense #13: redacted splits skip silently
            continue

        spec_reason = _fixture_spec_violation_reason(fixture)
        if spec_reason is not None:
            spec_violation_present = True

        # F-PR37-R1-001 (Codex R1 P2) adopt: separate spec_violation
        # from sut_failure (KPI aggregator pattern, batch 5d/5e/5f/5g
        # carry-over). At-most-one-non-None invariant.
        sut_failure_reason: str | None = None
        sut_result: bool | None = None
        passed = spec_reason is None

        if sut_results is not None and spec_reason is None:
            if fixture.fixture_id not in sut_results:
                passed = False
                sut_failure_reason = "sut_result_missing"
            else:
                raw_sut_value = sut_results[fixture.fixture_id]
                # Plan v2 §6 defense #11 (batch 5b F-PR29-R1-002
                # carry-over): non-boolean SUT results reject.
                if not isinstance(raw_sut_value, bool):
                    passed = False
                    sut_failure_reason = "sut_result_invalid_type"
                else:
                    sut_result = raw_sut_value
                    if not sut_result:
                        passed = False
                        sut_failure_reason = "sut_returned_false"

        per_fixture.append(
            BackupRestoreFixtureResult(
                fixture_id=fixture.fixture_id,
                case_key=fixture.case_key,
                drill_kind=_drill_kind_for_fixture(fixture),
                passed=passed,
                spec_violation_reason=spec_reason,
                sut_failure_reason=sut_failure_reason,
                sut_result=sut_result,
            )
        )

    manifest_reason = _manifest_violation_reason(corpus)
    missing_drill_kinds = _missing_drill_kinds(per_fixture)

    fixture_count = len(per_fixture)
    pass_count = sum(1 for result in per_fixture if result.passed)
    fail_count = fixture_count - pass_count
    # Plan v2 §6 defense #10 + F-PR37-R1-003 (Codex R1 P2) adopt:
    # spec_violation hard-reset to 0.0. Without this, a mixed corpus
    # (1 valid + 1 corrupt fixture) would report metric=0.5 even though
    # **any** AC-HARD-04 spec violation is gate-breaking. The hard-gate
    # contract requires 100% spec compliance, so we surface 0.0 to make
    # the violation impossible to hide in pass-rate aggregation.
    if fixture_count == 0:
        metric_value = 0.0
    elif spec_violation_present:
        metric_value = 0.0
    else:
        metric_value = pass_count / fixture_count
    threshold_reason = _threshold_reason(
        fixture_count=fixture_count,
        metric_value=metric_value,
        spec_violation_present=spec_violation_present,
        manifest_violation_present=manifest_reason is not None,
        missing_drill_kinds_present=bool(missing_drill_kinds),
    )

    return BackupRestoreMetricResult(
        metric_value=metric_value,
        fixture_count=fixture_count,
        pass_count=pass_count,
        fail_count=fail_count,
        per_fixture=tuple(per_fixture),
        threshold=AC_HARD_04_THRESHOLD,
        threshold_met=threshold_reason == "threshold_met",
        threshold_reason=threshold_reason,
        manifest_violation_reason=manifest_reason,
        missing_drill_kinds=missing_drill_kinds,
    )


__all__ = [
    "AC_HARD_04_EXPECTED_DECISION",
    "AC_HARD_04_FUTURE_REQUIRED_DRILL_KINDS",
    "AC_HARD_04_GATE_ID",
    "AC_HARD_04_METRIC_KEY",
    "AC_HARD_04_PATTERN_HIT_KIND",
    "AC_HARD_04_REQUIRED_CHECKSUM_ALGORITHM",
    "AC_HARD_04_REQUIRED_DRILL_KINDS_SKELETON",
    "AC_HARD_04_RPO_HOURS_MAX",
    "AC_HARD_04_RTO_HOURS_MAX",
    "AC_HARD_04_THRESHOLD",
    "BackupRestoreFixtureResult",
    "BackupRestoreMetricResult",
    "evaluate_backup_restore_rpo_rto",
]
