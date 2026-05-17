"""Tests for the AC-KPI-01 acceptance_pass_rate aggregator.

Covers the same five concerns as the batch 5d (citation_coverage) / 5e
(cost_per_completed_task) suites:

* 5+ source enum integrity (Python Literal / DB CHECK / aggregator frozenset
  / fixture schema enum + partition invariant).
* Live happy path + multi-fixture corpus weighted average.
* Anti-Gaming guards (pending / deferred exclusion, status enum, drift
  oracle).
* Manifest drift detection.
* Per-fixture spec violations + expected_aggregate violations (closure,
  partition, null-vs-zero sentinel, negative declared guard, overflow).
* SUT integration + spec/sut isolation.

Plus the AC-KPI-01-specific Anti-Gaming invariant that **only criteria
with status in {satisfied, rejected} contribute** to numerator and
denominator (plan v2 §2.2).
"""

from __future__ import annotations

import copy
import dataclasses
import json
import logging
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, Literal, get_args

import pytest

from backend.app.db.models.acceptance_criteria import AcceptanceCriteriaStatus
from backend.app.db.models.base import JsonDict
from backend.app.db.models.dataset_version import FixtureKind
from backend.app.services.eval.kpis import acceptance_pass_rate
from backend.app.services.eval.kpis.acceptance_pass_rate import (
    AC_KPI_01_KPI_ID,
    AC_KPI_01_METRIC_KEY,
    AC_KPI_01_THRESHOLD,
    AC_KPI_01_THRESHOLD_OPERATOR,
    AcceptancePassRateFixtureResult,
    AcceptancePassRateMetricResult,
    SampleAcceptanceCriterion,
    evaluate_acceptance_pass_rate,
)
from backend.app.services.eval.loader import Fixture, LoadedCorpus, load_fixture_corpus

_REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = _REPO_ROOT / "eval/quality/acceptance_pass_rate"
MANIFEST_PATH = BASE_PATH / "manifest.json"
SCHEMA_PATH = BASE_PATH / "expected_schema.json"
ACCEPTANCE_CRITERIA_MODEL_PATH = (
    _REPO_ROOT / "backend/app/db/models/acceptance_criteria.py"
)

EXPECTED_AC_KPI_01_KPI_ID: Final[Literal["AC-KPI-01"]] = "AC-KPI-01"
EXPECTED_AC_KPI_01_METRIC_KEY: Final[Literal["acceptance_pass_rate"]] = "acceptance_pass_rate"
EXPECTED_AC_KPI_01_THRESHOLD: Final[float] = 0.6
EXPECTED_AC_KPI_01_THRESHOLD_OPERATOR: Final[Literal[">="]] = ">="

EXPECTED_KNOWN_STATUSES: Final[frozenset[str]] = frozenset(
    {"pending", "satisfied", "rejected", "deferred"}
)
EXPECTED_PASS_NUMERATOR: Final[frozenset[str]] = frozenset({"satisfied"})
EXPECTED_PASS_DENOMINATOR: Final[frozenset[str]] = frozenset(
    {"satisfied", "rejected"}
)

# Live skeleton fixture: 5 criteria (3 satisfied / 1 rejected / 1 pending),
# pass_rate = 3 / 4 = 0.75.
EXPECTED_FIXTURE_COUNT: Final[int] = 1
EXPECTED_LIVE_TOTAL: Final[int] = 5
EXPECTED_LIVE_EVALUATED: Final[int] = 4
EXPECTED_LIVE_SATISFIED: Final[int] = 3
EXPECTED_LIVE_REJECTED: Final[int] = 1
EXPECTED_LIVE_PASS_RATE: Final[float] = 0.75


def _load_corpus() -> LoadedCorpus:
    return load_fixture_corpus(BASE_PATH, dataset_key="acceptance_pass_rate")


def _read_json(path: Path) -> JsonDict:
    return json.loads(path.read_text(encoding="utf-8"))


def _uuid_for(seed: str) -> str:
    """Deterministic UUID-shaped string from a seed (synthetic fixtures)."""

    import hashlib

    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"{digest[0:8]}-{digest[8:12]}-4{digest[13:16]}-8{digest[17:20]}-{digest[20:32]}"


_DEFAULT_PROJECT_ID: Final[str] = _uuid_for("synthetic-project-001")
_DEFAULT_TICKET_ID: Final[str] = _uuid_for("synthetic-ticket-001")


def _sample_criteria(
    *,
    satisfied: int = 0,
    rejected: int = 0,
    pending: int = 0,
    deferred: int = 0,
    extra: Sequence[Mapping[str, object]] = (),
    prefix: str = "synth",
    project_id: str | None = None,
    ticket_id: str | None = None,
) -> list[JsonDict]:
    """Build a deterministic ``sample_acceptance_criteria`` payload by status."""

    project_id = project_id or _DEFAULT_PROJECT_ID
    ticket_id = ticket_id or _DEFAULT_TICKET_ID
    rows: list[JsonDict] = []

    def _add(status: str, count: int) -> None:
        for index in range(count):
            rows.append(
                {
                    "criterion_id": _uuid_for(f"{prefix}-{status}-{index:03d}"),
                    "tenant_id": 1,
                    "project_id": project_id,
                    "ticket_id": ticket_id,
                    "status": status,
                }
            )

    _add("satisfied", satisfied)
    _add("rejected", rejected)
    _add("pending", pending)
    _add("deferred", deferred)
    for entry in extra:
        rows.append(dict(entry))
    return rows


_AUTO: Final[object] = object()
OMIT_EXPECTED_AGGREGATE: Final[object] = object()
OMIT_THRESHOLD: Final[object] = object()
_DEFAULT_THRESHOLD: Final[JsonDict] = {"operator": ">=", "value": 0.6}


def _expected_aggregate_for(rows: Sequence[Mapping[str, object]]) -> JsonDict:
    satisfied = sum(1 for r in rows if r.get("status") == "satisfied")
    rejected = sum(1 for r in rows if r.get("status") == "rejected")
    pending = sum(1 for r in rows if r.get("status") == "pending")
    deferred = sum(1 for r in rows if r.get("status") == "deferred")
    evaluated = satisfied + rejected
    total = satisfied + rejected + pending + deferred
    rate: float | None = satisfied / evaluated if evaluated else None
    return {
        "total_criteria": total,
        "evaluated_criteria": evaluated,
        "satisfied_criteria": satisfied,
        "rejected_criteria": rejected,
        "pending_criteria": pending,
        "deferred_criteria": deferred,
        "acceptance_pass_rate": rate,
    }


def _synthetic_raw_json(
    *,
    fixture_id: str,
    kpi_id: str,
    metric_key: str,
    fixture_kind: FixtureKind,
    case_key: str,
    sample_criteria: Sequence[JsonDict] | None,
    expected_aggregate: object,
    threshold: object,
) -> JsonDict:
    payload: JsonDict = {
        "fixture_id": fixture_id,
        "dataset_version_id": "v2026.05.17-synthetic",
        "fixture_kind": fixture_kind,
        "kpi_id": kpi_id,
        "metric_key": metric_key,
        "case_key": case_key,
        "input": {
            "sample_acceptance_criteria": (
                list(sample_criteria) if sample_criteria is not None else []
            ),
        },
        "assertions": [{"name": "synthetic_assert", "expected": "deterministic"}],
        "anti_gaming": {
            "private_expectation_visible_to_policy_author": False,
            "append_only_refresh": True,
            "separate_fixture_and_policy_commits": True,
        },
        "metadata": {"rls_ready": True, "synthetic": True},
    }
    if threshold is not OMIT_THRESHOLD:
        payload["threshold"] = threshold  # type: ignore[assignment]
    if expected_aggregate is not OMIT_EXPECTED_AGGREGATE:
        payload["expected_aggregate"] = expected_aggregate  # type: ignore[assignment]
    return payload


def _synthetic_fixture(
    *,
    fixture_id: str = "AC-KPI-01_v2026.05.17-synthetic_default",
    kpi_id: str = "AC-KPI-01",
    metric_key: str = "acceptance_pass_rate",
    fixture_kind: FixtureKind = "public_regression",
    case_key: str = "synthetic_case",
    sample_criteria: Sequence[JsonDict] | None = None,
    expected_aggregate: object = _AUTO,
    threshold: object = _AUTO,
) -> Fixture:
    if sample_criteria is None:
        sample_criteria = _sample_criteria(satisfied=3, rejected=1, pending=1)
    if expected_aggregate is _AUTO:
        expected_aggregate = _expected_aggregate_for(sample_criteria)
    if threshold is _AUTO:
        threshold = dict(_DEFAULT_THRESHOLD)

    raw_json = _synthetic_raw_json(
        fixture_id=fixture_id,
        kpi_id=kpi_id,
        metric_key=metric_key,
        fixture_kind=fixture_kind,
        case_key=case_key,
        sample_criteria=sample_criteria,
        expected_aggregate=expected_aggregate,
        threshold=threshold,
    )

    expectation_keys = {"expected_aggregate", "threshold", "assertions"}
    expected_json: JsonDict = {
        key: raw_json[key] for key in expectation_keys if key in raw_json
    }
    case_json: JsonDict = {
        key: value for key, value in raw_json.items() if key not in expectation_keys
    }

    return Fixture(
        fixture_id=fixture_id,
        dataset_version_id="v2026.05.17-synthetic",
        fixture_kind=fixture_kind,
        gate_id=None,
        metric_key=metric_key,
        case_key=case_key,
        case_json=case_json,
        expected_json=expected_json,
        metadata={"rls_ready": True, "synthetic": True},
        anti_gaming=raw_json["anti_gaming"],
        source_path=Path("synthetic/acceptance_pass_rate.json"),
        raw_json=raw_json,
        kpi_id=kpi_id,
    )


_VALID_MANIFEST: Final[JsonDict] = {
    "kpi_id": EXPECTED_AC_KPI_01_KPI_ID,
    "metric": EXPECTED_AC_KPI_01_METRIC_KEY,
    "threshold": {
        "operator": EXPECTED_AC_KPI_01_THRESHOLD_OPERATOR,
        "value": EXPECTED_AC_KPI_01_THRESHOLD,
    },
}


def _synthetic_corpus(
    fixtures: Sequence[Fixture],
    *,
    manifest: JsonDict | None = None,
) -> LoadedCorpus:
    return LoadedCorpus(
        dataset_key="acceptance_pass_rate",
        version="v2026.05.17-synthetic",
        content_hash="0" * 64,
        manifest=manifest if manifest is not None else dict(_VALID_MANIFEST),
        expected_schema={},
        fixtures=tuple(fixtures),
    )


def _result_for(
    fixture: Fixture,
) -> tuple[AcceptancePassRateMetricResult, AcceptancePassRateFixtureResult]:
    corpus = _synthetic_corpus([fixture])
    result = evaluate_acceptance_pass_rate(corpus)
    assert result.fixture_count == 1
    return result, result.per_fixture[0]


# ---------------------------------------------------------------------------
# 5+ source enum integrity (6 tests, plan v2 §7.1 + HIGH-003)
# ---------------------------------------------------------------------------


def test_ac_kpi_01_constants_match_test_layer_expected_constants() -> None:
    assert AC_KPI_01_KPI_ID == EXPECTED_AC_KPI_01_KPI_ID
    assert AC_KPI_01_METRIC_KEY == EXPECTED_AC_KPI_01_METRIC_KEY
    assert AC_KPI_01_THRESHOLD == EXPECTED_AC_KPI_01_THRESHOLD
    assert AC_KPI_01_THRESHOLD_OPERATOR == EXPECTED_AC_KPI_01_THRESHOLD_OPERATOR


def test_ac_kpi_01_constants_are_exported_from_module_all() -> None:
    expected = {
        "AC_KPI_01_KPI_ID",
        "AC_KPI_01_METRIC_KEY",
        "AC_KPI_01_THRESHOLD",
        "AC_KPI_01_THRESHOLD_OPERATOR",
        "AcceptancePassRateFixtureResult",
        "AcceptancePassRateMetricResult",
        "SampleAcceptanceCriterion",
        "evaluate_acceptance_pass_rate",
    }
    assert expected <= set(acceptance_pass_rate.__all__)


def test_acceptance_status_db_literal_matches_known_set() -> None:
    """5+ source #2: DB Literal AcceptanceCriteriaStatus vs aggregator
    frozenset _KNOWN_ACCEPTANCE_STATUSES exact set comparison.
    """

    assert frozenset(get_args(AcceptanceCriteriaStatus)) == EXPECTED_KNOWN_STATUSES
    assert (
        acceptance_pass_rate._KNOWN_ACCEPTANCE_STATUSES == EXPECTED_KNOWN_STATUSES
    )


def test_fixture_schema_status_enum_matches_known_set() -> None:
    """5+ source #5: fixture expected_schema.json status enum vs aggregator
    frozenset exact set comparison.
    """

    schema = _read_json(SCHEMA_PATH)
    schema_enum_values = (
        schema["properties"]["input"]["properties"]
        ["sample_acceptance_criteria"]["items"]["properties"]["status"]["enum"]
    )
    assert frozenset(schema_enum_values) == EXPECTED_KNOWN_STATUSES


def test_db_check_constraint_matches_known_set() -> None:
    """5+ source #1: extract DB CHECK constraint enum names from the source
    file and compare against the aggregator frozenset exact set.
    """

    source = ACCEPTANCE_CRITERIA_MODEL_PATH.read_text(encoding="utf-8")
    # The CHECK is declared as: "status in ('pending','satisfied','rejected','deferred')"
    match = re.search(
        r"status in \(([^)]+)\)",
        source,
    )
    assert match is not None, (
        "Could not locate AcceptanceCriteria status CHECK constraint in "
        "backend/app/db/models/acceptance_criteria.py"
    )
    raw_statuses = match.group(1)
    extracted = frozenset(re.findall(r"'([^']+)'", raw_statuses))
    assert extracted == EXPECTED_KNOWN_STATUSES


def test_partition_invariant_at_module_import() -> None:
    """5+ source #6: numerator ⊊ denominator ⊆ known, and excluded =
    {pending, deferred}.
    """

    assert acceptance_pass_rate._PASS_NUMERATOR_STATUSES == EXPECTED_PASS_NUMERATOR
    assert (
        acceptance_pass_rate._PASS_DENOMINATOR_STATUSES == EXPECTED_PASS_DENOMINATOR
    )
    assert EXPECTED_PASS_NUMERATOR < EXPECTED_PASS_DENOMINATOR
    assert EXPECTED_PASS_DENOMINATOR <= EXPECTED_KNOWN_STATUSES
    assert EXPECTED_KNOWN_STATUSES - EXPECTED_PASS_DENOMINATOR == frozenset(
        {"pending", "deferred"}
    )


# ---------------------------------------------------------------------------
# Live happy path (2 tests, plan v2 §7.2)
# ---------------------------------------------------------------------------


def test_live_skeleton_fixture_passes_threshold() -> None:
    corpus = _load_corpus()
    result = evaluate_acceptance_pass_rate(corpus)
    assert result.fixture_count == EXPECTED_FIXTURE_COUNT
    assert result.manifest_violation_reason is None
    assert result.total_criteria_across_corpus == EXPECTED_LIVE_TOTAL
    assert result.evaluated_criteria_across_corpus == EXPECTED_LIVE_EVALUATED
    assert result.satisfied_criteria_across_corpus == EXPECTED_LIVE_SATISFIED
    assert result.rejected_criteria_across_corpus == EXPECTED_LIVE_REJECTED
    assert result.metric_value == pytest.approx(EXPECTED_LIVE_PASS_RATE)
    assert result.threshold_met is True
    assert result.threshold_reason == "threshold_met"
    per = result.per_fixture[0]
    assert per.spec_violation_reason is None
    assert per.passed is True
    assert per.satisfied_criteria == EXPECTED_LIVE_SATISFIED
    assert per.rejected_criteria == EXPECTED_LIVE_REJECTED
    assert per.pending_criteria == 1
    assert per.deferred_criteria == 0
    assert per.recomputed_pass_rate == pytest.approx(EXPECTED_LIVE_PASS_RATE)


def test_corpus_weighted_average_across_two_fixtures() -> None:
    """Plan v2 §7.2: multi-fixture corpus computes the weighted average
    correctly across two synthetic fixtures.
    """

    fixture_a = _synthetic_fixture(
        fixture_id="AC-KPI-01_v2026.05.17-synthetic_corpus_a",
        sample_criteria=_sample_criteria(
            satisfied=3, rejected=1, prefix="corpus-a"
        ),
    )
    fixture_b = _synthetic_fixture(
        fixture_id="AC-KPI-01_v2026.05.17-synthetic_corpus_b",
        sample_criteria=_sample_criteria(
            satisfied=2, rejected=2, prefix="corpus-b"
        ),
    )
    result = evaluate_acceptance_pass_rate(_synthetic_corpus([fixture_a, fixture_b]))
    # 5 satisfied / (5 + 3) = 0.625
    assert result.metric_value == pytest.approx(0.625)
    assert result.satisfied_criteria_across_corpus == 5
    assert result.rejected_criteria_across_corpus == 3
    assert result.threshold_met is True


# ---------------------------------------------------------------------------
# Anti-Gaming (4 tests, plan v2 §7.3)
# ---------------------------------------------------------------------------


def test_pending_criteria_excluded_from_numerator_and_denominator() -> None:
    """Plan v2 §2.2: pending criteria are excluded from both. 2 satisfied
    + 2 pending → rate = 2 / 2 = 1.0 (not 2 / 4).
    """

    fixture = _synthetic_fixture(
        sample_criteria=_sample_criteria(satisfied=2, pending=2, prefix="pending-test"),
    )
    _, per = _result_for(fixture)
    assert per.spec_violation_reason is None
    assert per.recomputed_pass_rate == pytest.approx(1.0)
    assert per.evaluated_criteria == 2
    assert per.satisfied_criteria == 2
    assert per.pending_criteria == 2


def test_deferred_criteria_excluded_from_numerator_and_denominator() -> None:
    """Plan v2 §2.2 + §2.2.2 Anti-Gaming counter: deferred criteria are
    excluded. 2 satisfied + 2 deferred → rate = 2 / 2 = 1.0 (NOT 2 / 4 =
    0.5).
    """

    fixture = _synthetic_fixture(
        sample_criteria=_sample_criteria(
            satisfied=2, deferred=2, prefix="deferred-test"
        ),
    )
    _, per = _result_for(fixture)
    assert per.spec_violation_reason is None
    assert per.recomputed_pass_rate == pytest.approx(1.0)
    assert per.evaluated_criteria == 2
    assert per.satisfied_criteria == 2
    assert per.deferred_criteria == 2


def test_unknown_status_is_rejected_as_spec_violation() -> None:
    """Plan v2 §6 #5: unknown status fails 5+ source enum integrity."""

    rows = _sample_criteria(satisfied=1, prefix="bad-status")
    rows.append(
        {
            "criterion_id": _uuid_for("bad-status-extra"),
            "tenant_id": 1,
            "project_id": _DEFAULT_PROJECT_ID,
            "ticket_id": _DEFAULT_TICKET_ID,
            "status": "withdrawn",  # unknown enum value
        }
    )
    fixture = _synthetic_fixture(sample_criteria=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:status"


def test_expected_aggregate_drift_detected() -> None:
    """Plan v2 §2 Anti-Gaming invariant: aggregator recomputes from
    sample_criteria and rejects declared drift.
    """

    rows = _sample_criteria(satisfied=3, rejected=1)
    # Recomputed rate = 0.75; lie 0.95 in expected.
    drift_aggregate = _expected_aggregate_for(rows)
    drift_aggregate["acceptance_pass_rate"] = 0.95
    fixture = _synthetic_fixture(
        sample_criteria=rows, expected_aggregate=drift_aggregate
    )
    _, per = _result_for(fixture)
    assert (
        per.spec_violation_reason
        == "spec_violation:expected_aggregate_pass_rate_drift"
    )


# ---------------------------------------------------------------------------
# Manifest drift (4 parametrize tests, plan v2 §7.4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mutation_key", "mutation_value", "expected_reason"),
    [
        ("kpi_id", "AC-KPI-99", "manifest_violation:kpi_id"),
        ("metric", "something_else", "manifest_violation:metric"),
        ("threshold_operator", "<", "manifest_violation:threshold_operator"),
        ("threshold_value", 0.9, "manifest_violation:threshold_value"),
    ],
)
def test_manifest_violations_are_detected(
    mutation_key: str,
    mutation_value: object,
    expected_reason: str,
) -> None:
    manifest = copy.deepcopy(_VALID_MANIFEST)
    if mutation_key == "threshold_operator":
        manifest["threshold"]["operator"] = mutation_value
    elif mutation_key == "threshold_value":
        manifest["threshold"]["value"] = mutation_value
    else:
        manifest[mutation_key] = mutation_value

    fixture = _synthetic_fixture()
    result = evaluate_acceptance_pass_rate(
        _synthetic_corpus([fixture], manifest=manifest)
    )
    assert result.manifest_violation_reason == expected_reason
    assert result.threshold_reason == "manifest_violation"


# ---------------------------------------------------------------------------
# Per-fixture spec violations (12 tests, plan v2 §7.5)
# ---------------------------------------------------------------------------


def test_empty_sample_acceptance_criteria_is_rejected() -> None:
    fixture = _synthetic_fixture(
        sample_criteria=[],
        expected_aggregate={
            "total_criteria": 0,
            "evaluated_criteria": 0,
            "satisfied_criteria": 0,
            "rejected_criteria": 0,
            "pending_criteria": 0,
            "deferred_criteria": 0,
            "acceptance_pass_rate": None,
        },
    )
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:sample_criteria"


def test_non_list_sample_acceptance_criteria_is_rejected() -> None:
    fixture = _synthetic_fixture()
    fixture.case_json["input"]["sample_acceptance_criteria"] = "not a list"  # type: ignore[index]
    fixture.raw_json["input"]["sample_acceptance_criteria"] = "not a list"  # type: ignore[index]
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:sample_criteria"


def test_duplicate_criterion_id_within_fixture_is_rejected() -> None:
    rows = _sample_criteria(satisfied=2)
    rows[1]["criterion_id"] = rows[0]["criterion_id"]  # force collision
    fixture = _synthetic_fixture(sample_criteria=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:duplicate_criterion_id"


def test_duplicate_criterion_id_across_fixtures_is_rejected() -> None:
    """Plan v2 §6 #1 / batch 5e F-PR32-R3-001 carry-over."""

    shared = _uuid_for("cross-fixture-shared")

    def _build(fid: str) -> Fixture:
        return _synthetic_fixture(
            fixture_id=fid,
            sample_criteria=[
                {
                    "criterion_id": shared,
                    "tenant_id": 1,
                    "project_id": _DEFAULT_PROJECT_ID,
                    "ticket_id": _DEFAULT_TICKET_ID,
                    "status": "satisfied",
                }
            ],
            expected_aggregate={
                "total_criteria": 1,
                "evaluated_criteria": 1,
                "satisfied_criteria": 1,
                "rejected_criteria": 0,
                "pending_criteria": 0,
                "deferred_criteria": 0,
                "acceptance_pass_rate": 1.0,
            },
        )

    fixture_a = _build("AC-KPI-01_v2026.05.17-synthetic_dup_a")
    fixture_b = _build("AC-KPI-01_v2026.05.17-synthetic_dup_b")
    result = evaluate_acceptance_pass_rate(_synthetic_corpus([fixture_a, fixture_b]))
    assert result.per_fixture[0].spec_violation_reason is None
    assert (
        result.per_fixture[1].spec_violation_reason
        == "spec_violation:duplicate_criterion_id_across_fixtures"
    )
    # Only fixture A contributes to the corpus totals.
    assert result.satisfied_criteria_across_corpus == 1
    assert result.evaluated_criteria_across_corpus == 1


@pytest.mark.parametrize(
    "id_field",
    ["criterion_id", "project_id", "ticket_id"],
)
def test_invalid_uuid_format_is_rejected(id_field: str) -> None:
    rows = _sample_criteria(satisfied=1, prefix=f"bad-{id_field}")
    rows[0][id_field] = "NOT-A-VALID-UUID-AT-ALL"  # type: ignore[index]
    fixture = _synthetic_fixture(sample_criteria=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == f"spec_violation:{id_field}"


@pytest.mark.parametrize(
    "raw_value",
    [None, True, "1", -1, 0],
)
def test_invalid_tenant_id_is_rejected(raw_value: object) -> None:
    rows = _sample_criteria(satisfied=1, prefix="bad-tenant")
    rows[0]["tenant_id"] = raw_value
    fixture = _synthetic_fixture(sample_criteria=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:tenant_id"


def test_status_not_in_enum_is_rejected() -> None:
    rows = _sample_criteria(satisfied=1, prefix="bad-status-2")
    rows[0]["status"] = "withdrawn"
    fixture = _synthetic_fixture(sample_criteria=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:status"


def test_envelope_kpi_id_mismatch_is_rejected() -> None:
    fixture = _synthetic_fixture(kpi_id="AC-KPI-99")
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:kpi_id"


def test_envelope_metric_key_mismatch_is_rejected() -> None:
    fixture = _synthetic_fixture(metric_key="something_else")
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:metric_key"


# ---------------------------------------------------------------------------
# expected_aggregate violations (14 tests, plan v2 §7.6 + MEDIUM-004)
# ---------------------------------------------------------------------------


def test_missing_expected_aggregate_is_rejected() -> None:
    fixture = _synthetic_fixture(expected_aggregate=OMIT_EXPECTED_AGGREGATE)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_aggregate_missing"


def test_non_dict_expected_aggregate_is_rejected() -> None:
    fixture = _synthetic_fixture(expected_aggregate="not a dict")
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_aggregate"


def _drift_aggregate_with(field: str, value: object) -> tuple[Fixture, str]:
    rows = _sample_criteria(satisfied=3, rejected=1, pending=1, deferred=0)
    aggregate = _expected_aggregate_for(rows)
    aggregate[field] = value
    fixture = _synthetic_fixture(
        sample_criteria=rows, expected_aggregate=aggregate
    )
    expected_reason_map = {
        "total_criteria": "spec_violation:expected_aggregate_total_drift",
        "evaluated_criteria": "spec_violation:expected_aggregate_evaluated_drift",
        "satisfied_criteria": "spec_violation:expected_aggregate_satisfied_drift",
        "rejected_criteria": "spec_violation:expected_aggregate_rejected_drift",
        "pending_criteria": "spec_violation:expected_aggregate_pending_drift",
        "deferred_criteria": "spec_violation:expected_aggregate_deferred_drift",
    }
    return fixture, expected_reason_map[field]


@pytest.mark.parametrize(
    "field",
    [
        "total_criteria",
        "evaluated_criteria",
        "satisfied_criteria",
        "rejected_criteria",
        "pending_criteria",
        "deferred_criteria",
    ],
)
def test_expected_aggregate_count_drift_is_detected(field: str) -> None:
    fixture, expected_reason = _drift_aggregate_with(field, 999)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == expected_reason


def test_expected_aggregate_closure_violation_is_detected() -> None:
    """Plan v2 §6 #10: total != satisfied + rejected + pending + deferred."""

    rows = _sample_criteria(satisfied=3, rejected=1, pending=1)
    aggregate = _expected_aggregate_for(rows)
    aggregate["total_criteria"] = 100  # 100 != 3+1+1+0=5
    fixture = _synthetic_fixture(sample_criteria=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    # The total drift fires first (5 != 100); without that, the closure
    # check would fire. Verify the total-drift wins on priority.
    assert per.spec_violation_reason == "spec_violation:expected_aggregate_total_drift"


def test_total_drift_wins_over_closure_when_total_disagrees_with_recomputed() -> None:
    """F-PR33-001 adopt: documents that ``total_drift`` is the actual
    spec_violation when the declared total does not match recomputed
    total — the closure check at the aggregator is *defensive dead code*
    in the public API path because the upstream 6 count-drift checks
    cannot all pass while the closure equation also fails (the four
    status buckets exhaustively partition ``recomputed_total_criteria``).

    The closure branch exists as defense-in-depth against future bugs in
    ``_collect_sample_criteria`` (e.g., a fifth status leaking in via
    incomplete enum updates). This test asserts the actual surfaced
    reason — ``expected_aggregate_total_drift`` — rather than the
    unreachable ``expected_aggregate_closure_violation``.
    """

    rows = _sample_criteria(satisfied=3, rejected=1, pending=1)
    aggregate = _expected_aggregate_for(rows)
    # Inflate the declared total to 6 (one phantom row); recomputed = 5.
    # The total-drift check at the aggregator fires first; closure check
    # is unreachable here (and in the public API path generally).
    aggregate["total_criteria"] = 6
    fixture = _synthetic_fixture(sample_criteria=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_aggregate_total_drift"


def test_declared_pass_rate_negative_is_rejected() -> None:
    rows = _sample_criteria(satisfied=3, rejected=1)
    aggregate = _expected_aggregate_for(rows)
    aggregate["acceptance_pass_rate"] = -0.1
    fixture = _synthetic_fixture(sample_criteria=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_aggregate"


def test_declared_pass_rate_above_one_is_rejected() -> None:
    rows = _sample_criteria(satisfied=3, rejected=1)
    aggregate = _expected_aggregate_for(rows)
    aggregate["acceptance_pass_rate"] = 1.5
    fixture = _synthetic_fixture(sample_criteria=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_aggregate"


def test_zero_evaluated_with_nonzero_declared_rate_is_rejected() -> None:
    """Plan v2 §6 #4: when evaluated == 0 the declared rate must be null
    or 0.0; arbitrary non-zero is drift.
    """

    rows = _sample_criteria(pending=2, deferred=1)
    aggregate = _expected_aggregate_for(rows)
    assert aggregate["acceptance_pass_rate"] is None
    aggregate["acceptance_pass_rate"] = 0.999  # lie
    fixture = _synthetic_fixture(sample_criteria=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    assert (
        per.spec_violation_reason == "spec_violation:expected_aggregate_pass_rate_drift"
    )


def test_zero_evaluated_with_null_declared_rate_is_accepted() -> None:
    rows = _sample_criteria(pending=2, deferred=1)
    aggregate = _expected_aggregate_for(rows)
    aggregate["acceptance_pass_rate"] = None
    fixture = _synthetic_fixture(sample_criteria=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason is None


def test_zero_evaluated_with_zero_declared_rate_is_accepted() -> None:
    rows = _sample_criteria(pending=2, deferred=1)
    aggregate = _expected_aggregate_for(rows)
    aggregate["acceptance_pass_rate"] = 0.0
    fixture = _synthetic_fixture(sample_criteria=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason is None


# ---------------------------------------------------------------------------
# Edge cases (7 tests, plan v2 §7.7 + threshold priority MEDIUM-002)
# ---------------------------------------------------------------------------


def test_empty_corpus_yields_no_fixtures_reason() -> None:
    result = evaluate_acceptance_pass_rate(_synthetic_corpus([]))
    assert result.threshold_reason == "no_fixtures"
    assert result.metric_value is None
    assert result.threshold_met is False


def test_all_pending_yields_no_evaluated_criteria_reason() -> None:
    fixture = _synthetic_fixture(sample_criteria=_sample_criteria(pending=5))
    result = evaluate_acceptance_pass_rate(_synthetic_corpus([fixture]))
    assert result.threshold_reason == "no_evaluated_criteria"
    assert result.metric_value is None
    assert result.threshold_met is False


def test_all_deferred_yields_no_evaluated_criteria_reason() -> None:
    """Plan v2 §2.2.2 #1 Anti-Gaming counter-defense: defends against
    flip-to-deferred attack.
    """

    fixture = _synthetic_fixture(sample_criteria=_sample_criteria(deferred=5))
    result = evaluate_acceptance_pass_rate(_synthetic_corpus([fixture]))
    assert result.threshold_reason == "no_evaluated_criteria"
    assert result.metric_value is None
    assert result.threshold_met is False


def test_threshold_at_boundary_passes() -> None:
    """3 satisfied / 5 evaluated = 0.6 exactly → threshold_met=True."""

    rows = _sample_criteria(satisfied=3, rejected=2, prefix="boundary-met")
    fixture = _synthetic_fixture(sample_criteria=rows)
    result = evaluate_acceptance_pass_rate(_synthetic_corpus([fixture]))
    assert result.metric_value == pytest.approx(0.6)
    assert result.threshold_met is True
    assert result.threshold_reason == "threshold_met"


def test_threshold_just_below_boundary_fails() -> None:
    """3 satisfied / 6 evaluated = 0.5 → below_threshold."""

    rows = _sample_criteria(satisfied=3, rejected=3, prefix="below-threshold")
    fixture = _synthetic_fixture(sample_criteria=rows)
    result = evaluate_acceptance_pass_rate(_synthetic_corpus([fixture]))
    assert result.metric_value == pytest.approx(0.5)
    assert result.threshold_met is False
    assert result.threshold_reason == "below_threshold"


def test_envelope_invalid_fixture_does_not_poison_corpus_state() -> None:
    """Plan v2 §6 #9 / batch 5e F-PR32-R6-001 carry-over: invalid fixture
    A's criterion_ids do not leak into the corpus seen-set, and its
    counts do not inflate corpus totals.
    """

    shared = _uuid_for("envelope-invalid-shared")
    fixture_a = _synthetic_fixture(
        fixture_id="AC-KPI-01_v2026.05.17-synthetic_env_a",
        kpi_id="AC-KPI-99",  # envelope violation
        sample_criteria=[
            {
                "criterion_id": shared,
                "tenant_id": 1,
                "project_id": _DEFAULT_PROJECT_ID,
                "ticket_id": _DEFAULT_TICKET_ID,
                "status": "satisfied",
            }
        ],
        expected_aggregate={
            "total_criteria": 1,
            "evaluated_criteria": 1,
            "satisfied_criteria": 1,
            "rejected_criteria": 0,
            "pending_criteria": 0,
            "deferred_criteria": 0,
            "acceptance_pass_rate": 1.0,
        },
    )
    fixture_b = _synthetic_fixture(
        fixture_id="AC-KPI-01_v2026.05.17-synthetic_env_b",
        sample_criteria=[
            {
                "criterion_id": shared,  # would collide if A leaked
                "tenant_id": 1,
                "project_id": _DEFAULT_PROJECT_ID,
                "ticket_id": _DEFAULT_TICKET_ID,
                "status": "satisfied",
            }
        ],
        expected_aggregate={
            "total_criteria": 1,
            "evaluated_criteria": 1,
            "satisfied_criteria": 1,
            "rejected_criteria": 0,
            "pending_criteria": 0,
            "deferred_criteria": 0,
            "acceptance_pass_rate": 1.0,
        },
    )
    result = evaluate_acceptance_pass_rate(
        _synthetic_corpus([fixture_a, fixture_b])
    )
    assert result.per_fixture[0].spec_violation_reason == "spec_violation:kpi_id"
    assert result.per_fixture[1].spec_violation_reason is None
    # Corpus totals reflect only fixture B.
    assert result.satisfied_criteria_across_corpus == 1
    assert result.evaluated_criteria_across_corpus == 1


def test_aggregate_invalid_fixture_does_not_poison_corpus_state() -> None:
    """Plan v2 §6 #9 / batch 5e F-PR32-R6-001 carry-over: same gate at
    expected_aggregate violation layer.
    """

    shared = _uuid_for("aggregate-invalid-shared")
    fixture_a = _synthetic_fixture(
        fixture_id="AC-KPI-01_v2026.05.17-synthetic_agg_a",
        sample_criteria=[
            {
                "criterion_id": shared,
                "tenant_id": 1,
                "project_id": _DEFAULT_PROJECT_ID,
                "ticket_id": _DEFAULT_TICKET_ID,
                "status": "satisfied",
            }
        ],
        # Recompute would yield satisfied=1; declare 999 to trigger drift.
        expected_aggregate={
            "total_criteria": 1,
            "evaluated_criteria": 1,
            "satisfied_criteria": 999,
            "rejected_criteria": 0,
            "pending_criteria": 0,
            "deferred_criteria": 0,
            "acceptance_pass_rate": 1.0,
        },
    )
    fixture_b = _synthetic_fixture(
        fixture_id="AC-KPI-01_v2026.05.17-synthetic_agg_b",
        sample_criteria=[
            {
                "criterion_id": shared,
                "tenant_id": 1,
                "project_id": _DEFAULT_PROJECT_ID,
                "ticket_id": _DEFAULT_TICKET_ID,
                "status": "satisfied",
            }
        ],
        expected_aggregate={
            "total_criteria": 1,
            "evaluated_criteria": 1,
            "satisfied_criteria": 1,
            "rejected_criteria": 0,
            "pending_criteria": 0,
            "deferred_criteria": 0,
            "acceptance_pass_rate": 1.0,
        },
    )
    result = evaluate_acceptance_pass_rate(
        _synthetic_corpus([fixture_a, fixture_b])
    )
    assert (
        result.per_fixture[0].spec_violation_reason
        == "spec_violation:expected_aggregate_satisfied_drift"
    )
    assert result.per_fixture[1].spec_violation_reason is None
    assert result.satisfied_criteria_across_corpus == 1


# ---------------------------------------------------------------------------
# SUT integration (5 tests, plan v2 §7.8)
# ---------------------------------------------------------------------------


def test_sut_results_all_true_passes() -> None:
    fixture = _synthetic_fixture()
    result = evaluate_acceptance_pass_rate(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: True},
    )
    assert result.per_fixture[0].sut_attempted is True
    assert result.per_fixture[0].sut_result is True
    assert result.per_fixture[0].passed is True
    assert result.per_fixture[0].sut_failure_reason is None


def test_sut_results_all_false_marks_failure() -> None:
    fixture = _synthetic_fixture()
    result = evaluate_acceptance_pass_rate(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: False},
    )
    assert result.per_fixture[0].sut_failure_reason == "sut_returned_false"
    assert result.per_fixture[0].passed is False
    assert result.threshold_reason == "sut_failure"


def test_sut_result_missing_marks_failure() -> None:
    fixture = _synthetic_fixture()
    result = evaluate_acceptance_pass_rate(
        _synthetic_corpus([fixture]),
        sut_results={"some_other_fixture_id": True},
    )
    assert result.per_fixture[0].sut_failure_reason == "sut_result_missing"
    assert result.per_fixture[0].sut_attempted is True


@pytest.mark.parametrize(
    "raw_value",
    [None, "true", 1, 0, [], "1"],
)
def test_non_boolean_sut_result_is_rejected(raw_value: object) -> None:
    fixture = _synthetic_fixture()
    result = evaluate_acceptance_pass_rate(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: raw_value},  # type: ignore[dict-item]
    )
    assert (
        result.per_fixture[0].sut_failure_reason == "sut_result_invalid_type"
    )


def test_spec_violation_skips_sut_processing() -> None:
    fixture = _synthetic_fixture(kpi_id="AC-KPI-99")  # envelope violation
    result = evaluate_acceptance_pass_rate(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: True},
    )
    per = result.per_fixture[0]
    assert per.spec_violation_reason == "spec_violation:kpi_id"
    assert per.sut_failure_reason is None
    assert per.sut_attempted is False
    assert per.sut_result is None


# ---------------------------------------------------------------------------
# Overflow / robustness (2 tests, plan v2 §7.9)
# ---------------------------------------------------------------------------


def test_huge_int_in_expected_aggregate_is_handled_gracefully() -> None:
    """Plan v2 §6 #5 / batch 5e F-PR32-R6-002 carry-over: 10**500 must
    not crash; instead surfaces as a per-fixture spec_violation.
    """

    rows = _sample_criteria(satisfied=1)
    aggregate = _expected_aggregate_for(rows)
    aggregate["acceptance_pass_rate"] = 10**500  # Python int that overflows float
    fixture = _synthetic_fixture(
        sample_criteria=rows, expected_aggregate=aggregate
    )
    _, per = _result_for(fixture)
    # _is_finite_number returns False for OverflowError → expected_aggregate
    # is treated as malformed.
    assert per.spec_violation_reason == "spec_violation:expected_aggregate"


def test_sample_criterion_dataclass_is_frozen() -> None:
    criterion = SampleAcceptanceCriterion(
        criterion_id=_uuid_for("frozen-test"),
        tenant_id=1,
        project_id=_DEFAULT_PROJECT_ID,
        ticket_id=_DEFAULT_TICKET_ID,
        status="satisfied",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        criterion.status = "rejected"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# LOG output (1 test, plan v2 §2.2.2 #3 informational warning)
# ---------------------------------------------------------------------------


def test_high_deferred_ratio_emits_warning_log(caplog: pytest.LogCaptureFixture) -> None:
    """Plan v2 §2.2.2 #3: > 50% deferred ratio emits an informational log
    warning. Does NOT affect passed / threshold_met (verified by no
    spec_violation).
    """

    rows = _sample_criteria(satisfied=1, deferred=2, prefix="high-defer")
    fixture = _synthetic_fixture(sample_criteria=rows)
    caplog.set_level(logging.WARNING, logger=acceptance_pass_rate._LOGGER.name)
    result = evaluate_acceptance_pass_rate(_synthetic_corpus([fixture]))
    assert result.per_fixture[0].spec_violation_reason is None
    # The fixture is otherwise valid; the warning is informational.
    matching = [
        r for r in caplog.records if "deferred_ratio" in r.getMessage()
    ]
    assert matching, "Expected at least one deferred_ratio warning"
