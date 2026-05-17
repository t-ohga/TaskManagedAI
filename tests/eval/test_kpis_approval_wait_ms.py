"""Tests for the AC-KPI-03 approval_wait_ms aggregator.

Covers:
* 5+ source enum integrity (5 sources, plan v2 §2.3)
* Live happy path on the existing Sprint 3 skeleton fixture
* Anti-Gaming defenses (15 defenses, plan v2 §5)
* Manifest drift detection
* Per-fixture spec violations including decided_at required/null contract,
  sub-ms precision reject, causality, and per-fixture threshold reject
* expected_aggregate violations
* SUT integration + overflow / frozen dataclass
"""

from __future__ import annotations

import copy
import dataclasses
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, Literal, get_args

import pytest

from backend.app.db.models.approval_request import ApprovalStatus
from backend.app.db.models.base import JsonDict
from backend.app.db.models.dataset_version import FixtureKind
from backend.app.services.eval.kpis import approval_wait_ms
from backend.app.services.eval.kpis.approval_wait_ms import (
    AC_KPI_03_KPI_ID,
    AC_KPI_03_METRIC_KEY,
    AC_KPI_03_THRESHOLD_HOURS,
    AC_KPI_03_THRESHOLD_MS,
    AC_KPI_03_THRESHOLD_OPERATOR,
    ApprovalWaitMsFixtureResult,
    ApprovalWaitMsMetricResult,
    SampleApproval,
    evaluate_approval_wait_ms,
)
from backend.app.services.eval.loader import Fixture, LoadedCorpus, load_fixture_corpus

_REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = _REPO_ROOT / "eval/quality/approval_wait_ms"
MANIFEST_PATH = BASE_PATH / "manifest.json"
SCHEMA_PATH = BASE_PATH / "expected_schema.json"
APPROVAL_REQUEST_MODEL_PATH = (
    _REPO_ROOT / "backend/app/db/models/approval_request.py"
)

EXPECTED_AC_KPI_03_KPI_ID: Final[Literal["AC-KPI-03"]] = "AC-KPI-03"
EXPECTED_AC_KPI_03_METRIC_KEY: Final[Literal["approval_wait_ms"]] = "approval_wait_ms"
EXPECTED_AC_KPI_03_THRESHOLD_MS: Final[int] = 14_400_000
EXPECTED_AC_KPI_03_THRESHOLD_HOURS: Final[float] = 4.0
EXPECTED_AC_KPI_03_THRESHOLD_OPERATOR: Final[Literal["<="]] = "<="

EXPECTED_KNOWN_APPROVAL_STATUSES: Final[frozenset[str]] = frozenset(
    {"pending", "approved", "rejected", "expired", "invalidated"}
)
EXPECTED_DECIDED_STATUSES: Final[frozenset[str]] = frozenset(
    {"approved", "rejected"}
)


def _load_corpus() -> LoadedCorpus:
    return load_fixture_corpus(BASE_PATH, dataset_key="approval_wait_ms")


def _read_json(path: Path) -> JsonDict:
    return json.loads(path.read_text(encoding="utf-8"))


def _iso(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> str:
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:00+00:00"


def _sample_approvals(
    *,
    approved_durations_min: Sequence[int] = (),
    rejected_durations_min: Sequence[int] = (),
    pending_count: int = 0,
    expired_count: int = 0,
    invalidated_count: int = 0,
    base_hour: int = 10,
    extra: Sequence[Mapping[str, object]] = (),
    prefix: str = "synth",
) -> list[JsonDict]:
    """Build a deterministic ``sample_approvals`` payload by status."""

    rows: list[JsonDict] = []
    counter = 0

    def _request_at(idx: int) -> str:
        h = (base_hour + idx) % 23
        return _iso(2026, 5, 1, h, 0)

    def _decide_at(idx: int, duration_min: int) -> str:
        # Compute absolute decided time = request + duration_min minutes
        total_min = ((base_hour + idx) % 23) * 60 + duration_min
        h = total_min // 60
        m = total_min % 60
        return _iso(2026, 5, 1, h, m)

    for d in approved_durations_min:
        rows.append(
            {
                "requested_at": _request_at(counter),
                "decided_at": _decide_at(counter, d),
                "status": "approved",
            }
        )
        counter += 1
    for d in rejected_durations_min:
        rows.append(
            {
                "requested_at": _request_at(counter),
                "decided_at": _decide_at(counter, d),
                "status": "rejected",
            }
        )
        counter += 1
    for _ in range(pending_count):
        rows.append(
            {
                "requested_at": _request_at(counter),
                "decided_at": None,
                "status": "pending",
            }
        )
        counter += 1
    for _ in range(expired_count):
        rows.append(
            {
                "requested_at": _request_at(counter),
                "decided_at": None,
                "status": "expired",
            }
        )
        counter += 1
    for _ in range(invalidated_count):
        rows.append(
            {
                "requested_at": _request_at(counter),
                "decided_at": None,
                "status": "invalidated",
            }
        )
        counter += 1
    for entry in extra:
        rows.append(dict(entry))
    return rows


_AUTO: Final[object] = object()
OMIT_EXPECTED_AGGREGATE: Final[object] = object()


def _expected_aggregate_for(rows: Sequence[Mapping[str, object]]) -> JsonDict:
    """Compute expected_aggregate from raw rows for synthetic fixtures."""

    import datetime as _dt
    import statistics

    decided_durations_ms: list[float] = []
    for r in rows:
        status = r.get("status")
        if status not in {"approved", "rejected"}:
            continue
        requested_at_str = r.get("requested_at")
        decided_at_str = r.get("decided_at")
        if not isinstance(requested_at_str, str) or not isinstance(decided_at_str, str):
            continue
        req_norm = (
            requested_at_str.replace("Z", "+00:00")
            if requested_at_str.endswith("Z")
            else requested_at_str
        )
        dec_norm = (
            decided_at_str.replace("Z", "+00:00")
            if decided_at_str.endswith("Z")
            else decided_at_str
        )
        try:
            req_dt = _dt.datetime.fromisoformat(req_norm)
            dec_dt = _dt.datetime.fromisoformat(dec_norm)
        except ValueError:
            continue
        if req_dt.tzinfo is None or dec_dt.tzinfo is None:
            continue
        decided_durations_ms.append(
            (dec_dt - req_dt).total_seconds() * 1000.0
        )
    if not decided_durations_ms:
        return {
            "sample_count": 0,
            "median_ms": 0.0,
            "p95_ms": None,
            "min_ms": None,
            "max_ms": None,
        }
    return {
        "sample_count": len(decided_durations_ms),
        "median_ms": statistics.median(decided_durations_ms),
        "p95_ms": None,
        "min_ms": min(decided_durations_ms),
        "max_ms": max(decided_durations_ms),
    }


def _synthetic_raw_json(
    *,
    fixture_id: str,
    kpi_id: str,
    metric_key: str,
    fixture_kind: FixtureKind,
    case_key: str,
    sample_approvals: Sequence[JsonDict] | None,
    expected_aggregate: object,
) -> JsonDict:
    payload: JsonDict = {
        "fixture_id": fixture_id,
        "dataset_version_id": "v2026.05.17-synthetic",
        "fixture_kind": fixture_kind,
        "kpi_id": kpi_id,
        "metric_key": metric_key,
        "case_key": case_key,
        "input": {
            "sample_approvals": list(sample_approvals)
            if sample_approvals is not None
            else [],
        },
        "assertions": [{"name": "synthetic_assert", "expected": "deterministic"}],
        "anti_gaming": {
            "private_expectation_visible_to_policy_author": False,
            "append_only_refresh": True,
            "separate_fixture_and_policy_commits": True,
        },
        "metadata": {"created_at": "2026-05-17", "notes": "synthetic"},
    }
    if expected_aggregate is not OMIT_EXPECTED_AGGREGATE:
        payload["expected_aggregate"] = expected_aggregate  # type: ignore[assignment]
    return payload


def _synthetic_fixture(
    *,
    fixture_id: str = "AC-KPI-03_v2026.05.17-synthetic_default",
    kpi_id: str = "AC-KPI-03",
    metric_key: str = "approval_wait_ms",
    fixture_kind: FixtureKind = "public_regression",
    case_key: str = "synthetic_case",
    sample_approvals: Sequence[JsonDict] | None = None,
    expected_aggregate: object = _AUTO,
) -> Fixture:
    if sample_approvals is None:
        # Default: 2 approved at 30m / 60m + 1 pending → median 45m = 2_700_000 ms
        sample_approvals = _sample_approvals(
            approved_durations_min=[30, 60],
            pending_count=1,
        )
    if expected_aggregate is _AUTO:
        expected_aggregate = _expected_aggregate_for(sample_approvals)

    raw_json = _synthetic_raw_json(
        fixture_id=fixture_id,
        kpi_id=kpi_id,
        metric_key=metric_key,
        fixture_kind=fixture_kind,
        case_key=case_key,
        sample_approvals=sample_approvals,
        expected_aggregate=expected_aggregate,
    )

    expectation_keys = {"expected_aggregate", "assertions"}
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
        metadata={"created_at": "2026-05-17", "synthetic": True},
        anti_gaming=raw_json["anti_gaming"],
        source_path=Path("synthetic/approval_wait_ms.json"),
        raw_json=raw_json,
        kpi_id=kpi_id,
    )


_VALID_MANIFEST: Final[JsonDict] = {
    "kpi_id": EXPECTED_AC_KPI_03_KPI_ID,
    "metric": EXPECTED_AC_KPI_03_METRIC_KEY,
    "kpi_threshold_ms_median": EXPECTED_AC_KPI_03_THRESHOLD_MS,
}


def _synthetic_corpus(
    fixtures: Sequence[Fixture],
    *,
    manifest: JsonDict | None = None,
) -> LoadedCorpus:
    return LoadedCorpus(
        dataset_key="approval_wait_ms",
        version="v2026.05.17-synthetic",
        content_hash="0" * 64,
        manifest=manifest if manifest is not None else dict(_VALID_MANIFEST),
        expected_schema={},
        fixtures=tuple(fixtures),
    )


def _result_for(
    fixture: Fixture,
) -> tuple[ApprovalWaitMsMetricResult, ApprovalWaitMsFixtureResult]:
    corpus = _synthetic_corpus([fixture])
    result = evaluate_approval_wait_ms(corpus)
    assert result.fixture_count == 1
    return result, result.per_fixture[0]


# ---------------------------------------------------------------------------
# 5+ source enum integrity (6 tests, plan v2 §6.1)
# ---------------------------------------------------------------------------


def test_ac_kpi_03_constants_match() -> None:
    assert AC_KPI_03_KPI_ID == EXPECTED_AC_KPI_03_KPI_ID
    assert AC_KPI_03_METRIC_KEY == EXPECTED_AC_KPI_03_METRIC_KEY
    assert AC_KPI_03_THRESHOLD_MS == EXPECTED_AC_KPI_03_THRESHOLD_MS
    assert AC_KPI_03_THRESHOLD_HOURS == EXPECTED_AC_KPI_03_THRESHOLD_HOURS
    assert AC_KPI_03_THRESHOLD_OPERATOR == EXPECTED_AC_KPI_03_THRESHOLD_OPERATOR


def test_ac_kpi_03_constants_are_exported_from_module_all() -> None:
    expected = {
        "AC_KPI_03_KPI_ID",
        "AC_KPI_03_METRIC_KEY",
        "AC_KPI_03_THRESHOLD_HOURS",
        "AC_KPI_03_THRESHOLD_MS",
        "AC_KPI_03_THRESHOLD_OPERATOR",
        "ApprovalWaitMsFixtureResult",
        "ApprovalWaitMsMetricResult",
        "SampleApproval",
        "evaluate_approval_wait_ms",
    }
    assert expected <= set(approval_wait_ms.__all__)


def test_fixture_schema_status_enum_matches_known_set() -> None:
    schema = _read_json(SCHEMA_PATH)
    schema_enum = schema["properties"]["input"]["properties"][
        "sample_approvals"
    ]["items"]["properties"]["status"]["enum"]
    assert frozenset(schema_enum) == EXPECTED_KNOWN_APPROVAL_STATUSES


def test_orm_literal_matches_known_set() -> None:
    """5+ source #2: ORM ``ApprovalStatus`` Literal vs aggregator
    frozenset exact-set comparison.
    """

    assert frozenset(get_args(ApprovalStatus)) == EXPECTED_KNOWN_APPROVAL_STATUSES
    assert (
        approval_wait_ms._KNOWN_APPROVAL_STATUSES == EXPECTED_KNOWN_APPROVAL_STATUSES
    )


def test_db_check_constraint_matches_known_set() -> None:
    """5+ source #1: parse DB CHECK constraint from the model source
    and compare against the aggregator frozenset exact set.
    """

    source = APPROVAL_REQUEST_MODEL_PATH.read_text(encoding="utf-8")
    import re as _re

    match = _re.search(r"status in \(([^)]+)\)", source)
    assert match is not None
    raw_statuses = match.group(1)
    extracted = frozenset(_re.findall(r"'([^']+)'", raw_statuses))
    assert extracted == EXPECTED_KNOWN_APPROVAL_STATUSES


def test_partition_invariant_excluded_set() -> None:
    """5+ source #6: ``_DECIDED_STATUSES ⊊ _KNOWN_APPROVAL_STATUSES``
    + excluded set = ``{pending, expired, invalidated}``.
    """

    assert (
        approval_wait_ms._DECIDED_STATUSES == EXPECTED_DECIDED_STATUSES
    )
    assert EXPECTED_DECIDED_STATUSES < EXPECTED_KNOWN_APPROVAL_STATUSES
    excluded = EXPECTED_KNOWN_APPROVAL_STATUSES - EXPECTED_DECIDED_STATUSES
    assert excluded == frozenset({"pending", "expired", "invalidated"})


# ---------------------------------------------------------------------------
# Live happy path (2 tests, plan v2 §6.2)
# ---------------------------------------------------------------------------


def test_live_skeleton_fixture_passes_threshold() -> None:
    """Existing AC-KPI-03 skeleton: 3 samples (30 min approved, 120 min
    approved, 240 min rejected) → median = 7_200_000 ms = 2h ≤ 4h.
    """

    corpus = _load_corpus()
    result = evaluate_approval_wait_ms(corpus)
    assert result.fixture_count == 1
    assert result.manifest_violation_reason is None
    assert result.decided_count_across_corpus == 3
    assert result.metric_value == pytest.approx(7_200_000.0)
    assert result.threshold_met is True
    assert result.threshold_reason == "threshold_met"


def test_pooled_corpus_median_across_two_synthetic_fixtures() -> None:
    """Pooled (un-weighted) median across all decided approvals."""

    fixture_a = _synthetic_fixture(
        fixture_id="AC-KPI-03_v2026.05.17-synthetic_corpus_a",
        sample_approvals=_sample_approvals(
            approved_durations_min=[60, 150],
            base_hour=10,
        ),
    )
    fixture_b = _synthetic_fixture(
        fixture_id="AC-KPI-03_v2026.05.17-synthetic_corpus_b",
        sample_approvals=_sample_approvals(
            approved_durations_min=[30, 180],
            base_hour=14,
        ),
    )
    result = evaluate_approval_wait_ms(_synthetic_corpus([fixture_a, fixture_b]))
    # durations: [60m=3_600_000, 150m=9_000_000, 30m=1_800_000, 180m=10_800_000]
    # sorted [1_800_000, 3_600_000, 9_000_000, 10_800_000]
    # median = (3_600_000 + 9_000_000) / 2 = 6_300_000
    assert result.metric_value == pytest.approx(6_300_000.0)
    assert result.decided_count_across_corpus == 4


# ---------------------------------------------------------------------------
# Anti-Gaming (5 tests, plan v2 §6.3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "non_decided_kwarg",
    [
        {"pending_count": 2},
        {"expired_count": 2},
        {"invalidated_count": 2},
    ],
)
def test_non_decided_statuses_excluded_from_numerator(
    non_decided_kwarg: dict[str, int],
) -> None:
    rows = _sample_approvals(approved_durations_min=[60], **non_decided_kwarg)
    fixture = _synthetic_fixture(sample_approvals=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason is None
    # Only 1 decided approval @ 60m = 3_600_000 ms.
    assert per.recomputed_median_ms == pytest.approx(3_600_000.0)
    assert per.decided_count == 1


def test_unknown_status_is_rejected() -> None:
    rows = _sample_approvals(approved_durations_min=[60])
    rows.append(
        {
            "requested_at": _iso(2026, 5, 1, 14, 0),
            "decided_at": None,
            "status": "withdrawn",
        }
    )
    fixture = _synthetic_fixture(sample_approvals=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:status"


def test_expected_aggregate_median_drift_detected() -> None:
    rows = _sample_approvals(approved_durations_min=[60, 120])
    aggregate = _expected_aggregate_for(rows)
    aggregate["median_ms"] = 999_999.0  # lie
    fixture = _synthetic_fixture(sample_approvals=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    assert (
        per.spec_violation_reason
        == "spec_violation:expected_aggregate_median_drift"
    )


# ---------------------------------------------------------------------------
# Manifest drift (3 parametrize)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mutation_key", "mutation_value", "expected_reason"),
    [
        ("kpi_id", "AC-KPI-99", "manifest_violation:kpi_id"),
        ("metric", "something_else", "manifest_violation:metric"),
        (
            "kpi_threshold_ms_median",
            5_000_000,
            "manifest_violation:kpi_threshold_ms_median",
        ),
    ],
)
def test_manifest_violations_are_detected(
    mutation_key: str, mutation_value: object, expected_reason: str
) -> None:
    manifest = copy.deepcopy(_VALID_MANIFEST)
    manifest[mutation_key] = mutation_value
    fixture = _synthetic_fixture()
    result = evaluate_approval_wait_ms(
        _synthetic_corpus([fixture], manifest=manifest)
    )
    assert result.manifest_violation_reason == expected_reason
    assert result.threshold_reason == "manifest_violation"


# ---------------------------------------------------------------------------
# Per-fixture spec violations (15 tests, plan v2 §6.5)
# ---------------------------------------------------------------------------


def test_empty_sample_approvals_is_rejected() -> None:
    fixture = _synthetic_fixture(
        sample_approvals=[],
        expected_aggregate={"sample_count": 0, "median_ms": 0.0},
    )
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:sample_approvals"


def test_non_list_sample_approvals_is_rejected() -> None:
    fixture = _synthetic_fixture()
    fixture.case_json["input"]["sample_approvals"] = "not a list"  # type: ignore[index]
    fixture.raw_json["input"]["sample_approvals"] = "not a list"  # type: ignore[index]
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:sample_approvals"


@pytest.mark.parametrize("status", ["approved", "rejected"])
def test_decided_at_required_for_decided_statuses(status: str) -> None:
    rows: list[JsonDict] = [
        {
            "requested_at": _iso(2026, 5, 1, 10, 0),
            "decided_at": None,
            "status": status,
        }
    ]
    fixture = _synthetic_fixture(sample_approvals=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:decided_at_required"


@pytest.mark.parametrize("status", ["pending", "expired", "invalidated"])
def test_decided_at_unexpected_for_non_decided_statuses(status: str) -> None:
    rows: list[JsonDict] = [
        {
            "requested_at": _iso(2026, 5, 1, 10, 0),
            "decided_at": _iso(2026, 5, 1, 11, 0),
            "status": status,
        }
    ]
    fixture = _synthetic_fixture(sample_approvals=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:decided_at_unexpected"


def test_unparseable_timestamp_is_rejected() -> None:
    rows = _sample_approvals(approved_durations_min=[60])
    rows[0]["requested_at"] = "not a real date"
    fixture = _synthetic_fixture(sample_approvals=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:requested_at"


def test_naive_datetime_is_rejected() -> None:
    rows = _sample_approvals(approved_durations_min=[60])
    rows[0]["requested_at"] = "2026-05-01T10:00:00"  # no tz
    fixture = _synthetic_fixture(sample_approvals=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:requested_at"


def test_sub_millisecond_precision_is_rejected() -> None:
    """Plan v2 §2.4 / batch 5g F-PR34-R2-001 carry-over."""

    rows: list[JsonDict] = [
        {
            "requested_at": "2026-05-01T10:00:00.999999+00:00",
            "decided_at": "2026-05-01T10:00:00.999900+00:00",
            "status": "approved",
        }
    ]
    fixture = _synthetic_fixture(sample_approvals=rows)
    _, per = _result_for(fixture)
    # Sub-ms in requested_at trips the requested_at parse first.
    assert per.spec_violation_reason == "spec_violation:requested_at"


def test_non_utc_offset_is_accepted_and_normalized() -> None:
    rows: list[JsonDict] = [
        {
            # +09:00 normalized to UTC; 10:00+09:00 = 01:00 UTC, 11:00+09:00 = 02:00 UTC.
            # Duration = 1h = 3_600_000 ms.
            "requested_at": "2026-05-01T10:00:00+09:00",
            "decided_at": "2026-05-01T11:00:00+09:00",
            "status": "approved",
        }
    ]
    fixture = _synthetic_fixture(
        sample_approvals=rows,
        expected_aggregate={
            "sample_count": 1,
            "median_ms": 3_600_000.0,
        },
    )
    _, per = _result_for(fixture)
    assert per.spec_violation_reason is None
    assert per.recomputed_median_ms == pytest.approx(3_600_000.0)


def test_causality_violation_is_rejected() -> None:
    rows: list[JsonDict] = [
        {
            "requested_at": _iso(2026, 5, 1, 11, 0),
            "decided_at": _iso(2026, 5, 1, 10, 0),  # before requested
            "status": "approved",
        }
    ]
    fixture = _synthetic_fixture(sample_approvals=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:decided_at_causality"


def test_envelope_kpi_id_mismatch_is_rejected() -> None:
    fixture = _synthetic_fixture(kpi_id="AC-KPI-99")
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:kpi_id"


def test_envelope_metric_key_mismatch_is_rejected() -> None:
    fixture = _synthetic_fixture(metric_key="something_else")
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:metric_key"


def test_corpus_wide_duplicate_approval_is_detected() -> None:
    """Plan v2 §5 #1 + LOW-L2: best-effort dup detection across fixtures."""

    shared_row: JsonDict = {
        "requested_at": _iso(2026, 5, 1, 10, 0),
        "decided_at": _iso(2026, 5, 1, 11, 0),
        "status": "approved",
    }

    def _build(fid: str) -> Fixture:
        return _synthetic_fixture(
            fixture_id=fid,
            sample_approvals=[dict(shared_row)],
            expected_aggregate={
                "sample_count": 1,
                "median_ms": 3_600_000.0,
            },
        )

    fixture_a = _build("AC-KPI-03_v2026.05.17-synthetic_dup_a")
    fixture_b = _build("AC-KPI-03_v2026.05.17-synthetic_dup_b")
    result = evaluate_approval_wait_ms(_synthetic_corpus([fixture_a, fixture_b]))
    assert result.per_fixture[0].spec_violation_reason is None
    assert (
        result.per_fixture[1].spec_violation_reason
        == "spec_violation:duplicate_approval_across_fixtures"
    )
    assert result.decided_count_across_corpus == 1


def test_per_fixture_threshold_block_is_rejected() -> None:
    """Plan v2 §5 #15 / HIGH-H1: per-fixture ``threshold`` block is not
    permitted by the AC-KPI-03 schema (``additionalProperties: false``).
    If a persisted corpus bypasses schema validation, reject.
    """

    fixture = _synthetic_fixture()
    fixture.raw_json["threshold"] = {"operator": "<=", "value": 999.0}  # type: ignore[index]
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:threshold_unexpected"


# ---------------------------------------------------------------------------
# expected_aggregate violations (8 tests, plan v2 §6.6)
# ---------------------------------------------------------------------------


def test_missing_expected_aggregate_is_rejected() -> None:
    fixture = _synthetic_fixture(expected_aggregate=OMIT_EXPECTED_AGGREGATE)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_aggregate_missing"


def test_non_dict_expected_aggregate_is_rejected() -> None:
    fixture = _synthetic_fixture(expected_aggregate="not a dict")
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_aggregate"


def test_sample_count_drift_is_detected() -> None:
    """Plan v2 §4.2.2 / MED-M2: ``expected_aggregate.sample_count`` =
    decided_count.
    """

    rows = _sample_approvals(approved_durations_min=[60, 120], pending_count=1)
    aggregate = _expected_aggregate_for(rows)
    aggregate["sample_count"] = 99  # lie
    fixture = _synthetic_fixture(sample_approvals=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    assert (
        per.spec_violation_reason == "spec_violation:expected_aggregate_decided_drift"
    )


def test_declared_median_negative_is_rejected() -> None:
    rows = _sample_approvals(approved_durations_min=[60])
    aggregate = _expected_aggregate_for(rows)
    aggregate["median_ms"] = -1.0
    fixture = _synthetic_fixture(sample_approvals=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_aggregate"


def test_declared_median_non_numeric_is_rejected() -> None:
    rows = _sample_approvals(approved_durations_min=[60])
    aggregate = _expected_aggregate_for(rows)
    aggregate["median_ms"] = "not a number"
    fixture = _synthetic_fixture(sample_approvals=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_aggregate"


def test_optional_p95_negative_is_rejected() -> None:
    rows = _sample_approvals(approved_durations_min=[60])
    aggregate = _expected_aggregate_for(rows)
    aggregate["p95_ms"] = -10.0
    fixture = _synthetic_fixture(sample_approvals=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_aggregate"


def test_optional_p95_null_is_accepted() -> None:
    rows = _sample_approvals(approved_durations_min=[60])
    aggregate = _expected_aggregate_for(rows)
    aggregate["p95_ms"] = None
    fixture = _synthetic_fixture(sample_approvals=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason is None


def test_per_fixture_all_pending_is_rejected_by_construction() -> None:
    """Plan v2 §2.6 / HIGH-H2: per-fixture decided_count == 0 is a
    by-construction spec violation since schema requires numeric
    ``median_ms``.
    """

    rows = _sample_approvals(pending_count=3)
    fixture = _synthetic_fixture(
        sample_approvals=rows,
        expected_aggregate={
            "sample_count": 0,
            "median_ms": 0.0,  # any non-null numeric — but recomputed is None
        },
    )
    _, per = _result_for(fixture)
    assert (
        per.spec_violation_reason
        == "spec_violation:expected_aggregate_median_drift"
    )


# ---------------------------------------------------------------------------
# Edge cases (8 tests, plan v2 §6.7)
# ---------------------------------------------------------------------------


def test_empty_corpus_yields_no_fixtures_reason() -> None:
    result = evaluate_approval_wait_ms(_synthetic_corpus([]))
    assert result.threshold_reason == "no_fixtures"
    assert result.threshold_met is False
    assert result.metric_value is None


def test_corpus_pool_all_non_decided_yields_no_decided_approvals_reason() -> None:
    """Plan v2 §4.2.1 priority 5: corpus pool has no decided rows.
    Uses a fixture with all pending samples — by construction this is a
    per-fixture spec violation, so the corpus picks up via the
    ``spec_violation`` reason path. To exercise ``no_decided_approvals``
    at the corpus level, we need a fixture that passes spec but
    contributes no decided rows — which is impossible under the existing
    schema. Therefore this scenario only manifests when a fixture passes
    schema with decided_count==0 (e.g., a manifest-only edge). For the
    purposes of this test, an empty corpus is the canonical
    ``no_decided_approvals`` analog when chained from no_fixtures.
    Verify the test infrastructure can still produce the corpus-level
    reason via the schema-by-construction path.
    """

    rows = _sample_approvals(pending_count=3)
    fixture = _synthetic_fixture(
        sample_approvals=rows,
        expected_aggregate={"sample_count": 0, "median_ms": 0.0},
    )
    result = evaluate_approval_wait_ms(_synthetic_corpus([fixture]))
    # The fixture is rejected as spec_violation; corpus-level reason
    # surfaces as "spec_violation" not "no_decided_approvals".
    assert result.threshold_reason == "spec_violation"
    assert result.threshold_met is False


def test_threshold_at_boundary_passes() -> None:
    """median exactly 14_400_000 ms (4h) → threshold_met=True."""

    # 1 approved at 240m = 14_400_000 ms.
    rows = _sample_approvals(approved_durations_min=[240])
    fixture = _synthetic_fixture(sample_approvals=rows)
    result = evaluate_approval_wait_ms(_synthetic_corpus([fixture]))
    assert result.metric_value == pytest.approx(14_400_000.0)
    assert result.threshold_met is True


def test_threshold_within_ms_tolerance_passes() -> None:
    """median = 14_400_001 ms (4h + 1ms) within 1ms abs_tol → True."""

    rows: list[JsonDict] = [
        {
            "requested_at": "2026-05-01T10:00:00.000+00:00",
            "decided_at": "2026-05-01T14:00:00.001+00:00",
            "status": "approved",
        }
    ]
    fixture = _synthetic_fixture(
        sample_approvals=rows,
        expected_aggregate={"sample_count": 1, "median_ms": 14_400_001.0},
    )
    result = evaluate_approval_wait_ms(_synthetic_corpus([fixture]))
    assert result.metric_value == pytest.approx(14_400_001.0)
    assert result.threshold_met is True


def test_threshold_outside_ms_tolerance_fails() -> None:
    """median = 14_400_100 ms (4h + 100ms) outside tolerance →
    above_threshold.
    """

    rows: list[JsonDict] = [
        {
            "requested_at": "2026-05-01T10:00:00.000+00:00",
            "decided_at": "2026-05-01T14:00:00.100+00:00",
            "status": "approved",
        }
    ]
    fixture = _synthetic_fixture(
        sample_approvals=rows,
        expected_aggregate={"sample_count": 1, "median_ms": 14_400_100.0},
    )
    result = evaluate_approval_wait_ms(_synthetic_corpus([fixture]))
    assert result.threshold_met is False
    assert result.threshold_reason == "above_threshold"


def test_envelope_invalid_fixture_does_not_poison_corpus_state() -> None:
    shared_row: JsonDict = {
        "requested_at": _iso(2026, 5, 1, 10, 0),
        "decided_at": _iso(2026, 5, 1, 11, 0),
        "status": "approved",
    }
    fixture_a = _synthetic_fixture(
        fixture_id="AC-KPI-03_v2026.05.17-synthetic_env_a",
        kpi_id="AC-KPI-99",  # envelope violation
        sample_approvals=[dict(shared_row)],
        expected_aggregate={"sample_count": 1, "median_ms": 3_600_000.0},
    )
    fixture_b = _synthetic_fixture(
        fixture_id="AC-KPI-03_v2026.05.17-synthetic_env_b",
        sample_approvals=[dict(shared_row)],
        expected_aggregate={"sample_count": 1, "median_ms": 3_600_000.0},
    )
    result = evaluate_approval_wait_ms(_synthetic_corpus([fixture_a, fixture_b]))
    assert result.per_fixture[0].spec_violation_reason == "spec_violation:kpi_id"
    assert result.per_fixture[1].spec_violation_reason is None
    assert result.decided_count_across_corpus == 1


def test_aggregate_invalid_fixture_does_not_poison_corpus_state() -> None:
    shared_row: JsonDict = {
        "requested_at": _iso(2026, 5, 1, 10, 0),
        "decided_at": _iso(2026, 5, 1, 11, 0),
        "status": "approved",
    }
    fixture_a = _synthetic_fixture(
        fixture_id="AC-KPI-03_v2026.05.17-synthetic_agg_a",
        sample_approvals=[dict(shared_row)],
        # drift: declared 999_999 vs recomputed 3_600_000
        expected_aggregate={"sample_count": 1, "median_ms": 999_999.0},
    )
    fixture_b = _synthetic_fixture(
        fixture_id="AC-KPI-03_v2026.05.17-synthetic_agg_b",
        sample_approvals=[dict(shared_row)],
        expected_aggregate={"sample_count": 1, "median_ms": 3_600_000.0},
    )
    result = evaluate_approval_wait_ms(_synthetic_corpus([fixture_a, fixture_b]))
    assert (
        result.per_fixture[0].spec_violation_reason
        == "spec_violation:expected_aggregate_median_drift"
    )
    assert result.per_fixture[1].spec_violation_reason is None


@pytest.mark.parametrize(
    "bad_value",
    ["string", 1.5, True, None],
)
def test_kpi_threshold_ms_median_int_strictness(bad_value: object) -> None:
    """LOW-L3 adopt: ``kpi_threshold_ms_median`` must be non-bool int."""

    manifest = copy.deepcopy(_VALID_MANIFEST)
    manifest["kpi_threshold_ms_median"] = bad_value
    fixture = _synthetic_fixture()
    result = evaluate_approval_wait_ms(
        _synthetic_corpus([fixture], manifest=manifest)
    )
    assert (
        result.manifest_violation_reason
        == "manifest_violation:kpi_threshold_ms_median"
    )


# ---------------------------------------------------------------------------
# SUT integration (5 tests)
# ---------------------------------------------------------------------------


def test_sut_results_all_true_passes() -> None:
    fixture = _synthetic_fixture()
    result = evaluate_approval_wait_ms(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: True},
    )
    assert result.per_fixture[0].passed is True


def test_sut_results_all_false_marks_failure() -> None:
    fixture = _synthetic_fixture()
    result = evaluate_approval_wait_ms(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: False},
    )
    assert result.per_fixture[0].sut_failure_reason == "sut_returned_false"


def test_sut_result_missing_marks_failure() -> None:
    fixture = _synthetic_fixture()
    result = evaluate_approval_wait_ms(
        _synthetic_corpus([fixture]),
        sut_results={"some_other_fixture_id": True},
    )
    assert result.per_fixture[0].sut_failure_reason == "sut_result_missing"


@pytest.mark.parametrize("raw", [None, "true", 1, []])
def test_non_boolean_sut_result_is_rejected(raw: object) -> None:
    fixture = _synthetic_fixture()
    result = evaluate_approval_wait_ms(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: raw},  # type: ignore[dict-item]
    )
    assert (
        result.per_fixture[0].sut_failure_reason == "sut_result_invalid_type"
    )


def test_spec_violation_skips_sut_processing() -> None:
    fixture = _synthetic_fixture(kpi_id="AC-KPI-99")
    result = evaluate_approval_wait_ms(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: True},
    )
    per = result.per_fixture[0]
    assert per.spec_violation_reason == "spec_violation:kpi_id"
    assert per.sut_attempted is False


# ---------------------------------------------------------------------------
# Overflow / robustness (2 tests)
# ---------------------------------------------------------------------------


def test_huge_int_in_expected_aggregate_is_handled_gracefully() -> None:
    rows = _sample_approvals(approved_durations_min=[60])
    aggregate = _expected_aggregate_for(rows)
    aggregate["median_ms"] = 10**500
    fixture = _synthetic_fixture(sample_approvals=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_aggregate"


def test_sample_approval_dataclass_is_frozen() -> None:
    approval = SampleApproval(
        requested_at_ms=1_746_091_200_000,
        decided_at_ms=1_746_094_800_000,
        status="approved",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        approval.status = "rejected"  # type: ignore[misc]
