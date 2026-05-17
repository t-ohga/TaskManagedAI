"""Tests for the AC-KPI-02 time_to_merge aggregator.

Covers the same six concerns as the batch 5d/5e/5f suites:

* 4+ source enum integrity (Python Literal / aggregator frozenset /
  fixture schema enum + partition invariant; live DB CHECK is SP-012).
* Live happy path + pooled (un-weighted) corpus median.
* Anti-Gaming guards (open / draft / closed_without_merge exclusion,
  status enum, drift oracle, causality, cross-fixture uniqueness,
  late-commit gate, counter-defense logs).
* Manifest drift detection.
* Per-fixture spec violations + expected_aggregate violations.
* SUT integration + spec/sut isolation.

Plus the AC-KPI-02-specific Anti-Gaming invariant that **only PRs with
status="merged" contribute** to the median, with strict
`merged_at >= ticket_created_at` causality (boundary equality valid).
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, Literal
from unittest import mock

import pytest

from backend.app.db.models.base import JsonDict
from backend.app.db.models.dataset_version import FixtureKind
from backend.app.services.eval.kpis import time_to_merge
from backend.app.services.eval.kpis.time_to_merge import (
    AC_KPI_02_KPI_ID,
    AC_KPI_02_METRIC_KEY,
    AC_KPI_02_THRESHOLD_HOURS,
    AC_KPI_02_THRESHOLD_MS,
    AC_KPI_02_THRESHOLD_OPERATOR,
    SamplePullRequest,
    TimeToMergeFixtureResult,
    TimeToMergeMetricResult,
    evaluate_time_to_merge,
)
from backend.app.services.eval.loader import Fixture, LoadedCorpus, load_fixture_corpus

_REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = _REPO_ROOT / "eval/quality/time_to_merge"
MANIFEST_PATH = BASE_PATH / "manifest.json"
SCHEMA_PATH = BASE_PATH / "expected_schema.json"

EXPECTED_AC_KPI_02_KPI_ID: Final[Literal["AC-KPI-02"]] = "AC-KPI-02"
EXPECTED_AC_KPI_02_METRIC_KEY: Final[Literal["time_to_merge"]] = "time_to_merge"
EXPECTED_AC_KPI_02_THRESHOLD_HOURS: Final[float] = 2.0
EXPECTED_AC_KPI_02_THRESHOLD_MS: Final[int] = 7_200_000
EXPECTED_AC_KPI_02_THRESHOLD_OPERATOR: Final[Literal["<="]] = "<="

EXPECTED_KNOWN_PR_STATUSES: Final[frozenset[str]] = frozenset(
    {"open", "draft", "merged", "closed_without_merge"}
)
EXPECTED_MERGED_STATUS: Final[Literal["merged"]] = "merged"

# Live skeleton fixture: 5 PRs (3 merged @ 30m/60m/90m → median 1.0h, 1 open, 1 closed)
EXPECTED_FIXTURE_COUNT: Final[int] = 1
EXPECTED_LIVE_PULLS: Final[int] = 5
EXPECTED_LIVE_MERGED: Final[int] = 3
EXPECTED_LIVE_OPEN: Final[int] = 1
EXPECTED_LIVE_CLOSED: Final[int] = 1
EXPECTED_LIVE_MEDIAN_HOURS: Final[float] = 1.0


def _load_corpus() -> LoadedCorpus:
    return load_fixture_corpus(BASE_PATH, dataset_key="time_to_merge")


def _read_json(path: Path) -> JsonDict:
    return json.loads(path.read_text(encoding="utf-8"))


def _uuid_for(seed: str) -> str:
    """Deterministic UUID-shaped string from a seed."""

    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return (
        f"{digest[0:8]}-{digest[8:12]}-4{digest[13:16]}"
        f"-8{digest[17:20]}-{digest[20:32]}"
    )


_DEFAULT_PROJECT_ID: Final[str] = _uuid_for("synthetic-project-001")
_DEFAULT_REPOSITORY_ID: Final[str] = _uuid_for("synthetic-repository-001")


def _iso(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> str:
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:00+00:00"


def _sample_pulls(
    *,
    merged_durations_min: Sequence[int] = (),
    open_count: int = 0,
    draft_count: int = 0,
    closed_without_merge_count: int = 0,
    extra: Sequence[Mapping[str, object]] = (),
    prefix: str = "synth",
) -> list[JsonDict]:
    """Build a deterministic ``sample_pull_requests`` payload."""

    rows: list[JsonDict] = []
    base_year = 2026
    base_month = 5
    base_day = 1

    def _base_created(idx: int) -> str:
        # 1 hour apart for each ticket so all start at distinct times
        hour = idx % 23
        day = base_day + (idx // 23)
        return _iso(base_year, base_month, day, hour, 0)

    counter = 0
    for duration_min in merged_durations_min:
        created = _base_created(counter)
        merged = _iso(
            base_year, base_month, base_day + (counter // 23),
            counter % 23, duration_min % 60,
        )
        # For >60 min, increment hour
        if duration_min >= 60:
            extra_h = duration_min // 60
            new_hour = (counter % 23) + extra_h
            merged = _iso(
                base_year, base_month, base_day + (counter // 23),
                new_hour, duration_min % 60,
            )
        rows.append(
            {
                "ticket_id": _uuid_for(f"{prefix}-merged-{counter:03d}"),
                "tenant_id": 1,
                "project_id": _DEFAULT_PROJECT_ID,
                "repository_id": _DEFAULT_REPOSITORY_ID,
                "status": "merged",
                "ticket_created_at": created,
                "merged_at": merged,
            }
        )
        counter += 1

    for i in range(open_count):
        rows.append(
            {
                "ticket_id": _uuid_for(f"{prefix}-open-{i:03d}"),
                "tenant_id": 1,
                "project_id": _DEFAULT_PROJECT_ID,
                "repository_id": None,
                "status": "open",
                "ticket_created_at": _base_created(counter),
                "merged_at": None,
            }
        )
        counter += 1
    for i in range(draft_count):
        rows.append(
            {
                "ticket_id": _uuid_for(f"{prefix}-draft-{i:03d}"),
                "tenant_id": 1,
                "project_id": _DEFAULT_PROJECT_ID,
                "repository_id": None,
                "status": "draft",
                "ticket_created_at": _base_created(counter),
                "merged_at": None,
            }
        )
        counter += 1
    for i in range(closed_without_merge_count):
        rows.append(
            {
                "ticket_id": _uuid_for(f"{prefix}-closed-{i:03d}"),
                "tenant_id": 1,
                "project_id": _DEFAULT_PROJECT_ID,
                "repository_id": _DEFAULT_REPOSITORY_ID,
                "status": "closed_without_merge",
                "ticket_created_at": _base_created(counter),
                "merged_at": None,
            }
        )
        counter += 1
    for entry in extra:
        rows.append(dict(entry))
    return rows


_AUTO: Final[object] = object()
OMIT_EXPECTED_AGGREGATE: Final[object] = object()
OMIT_THRESHOLD: Final[object] = object()
_DEFAULT_THRESHOLD: Final[JsonDict] = {
    "operator": "<=",
    "value": 2.0,
    "unit": "hours",
}


def _expected_aggregate_for(rows: Sequence[Mapping[str, object]]) -> JsonDict:
    """Compute the expected aggregate from raw rows (for synthetic helpers)."""

    import datetime as _dt
    import statistics

    merged = [r for r in rows if r.get("status") == "merged"]
    open_count = sum(1 for r in rows if r.get("status") == "open")
    draft_count = sum(1 for r in rows if r.get("status") == "draft")
    closed_count = sum(1 for r in rows if r.get("status") == "closed_without_merge")
    durations_hours: list[float] = []
    for r in merged:
        created_str = r.get("ticket_created_at")
        merged_str = r.get("merged_at")
        if not isinstance(created_str, str) or not isinstance(merged_str, str):
            continue
        created_norm = created_str.replace("Z", "+00:00") if created_str.endswith("Z") else created_str
        merged_norm = merged_str.replace("Z", "+00:00") if merged_str.endswith("Z") else merged_str
        try:
            created_dt = _dt.datetime.fromisoformat(created_norm)
            merged_dt = _dt.datetime.fromisoformat(merged_norm)
        except ValueError:
            continue
        # When either side is naive (test fixture pathological case), the
        # aggregator will reject upstream; the helper just skips so it
        # doesn't raise TypeError on naive/aware subtraction.
        if created_dt.tzinfo is None or merged_dt.tzinfo is None:
            continue
        duration_ms = int(
            (merged_dt - created_dt).total_seconds() * 1000
        )
        durations_hours.append(duration_ms / 3_600_000.0)
    median_hours: float | None = (
        statistics.median(durations_hours) if durations_hours else None
    )
    return {
        "pulls_count": len(rows),
        "merged_count": len(merged),
        "open_count": open_count,
        "draft_count": draft_count,
        "closed_without_merge_count": closed_count,
        "median_hours": median_hours,
    }


def _synthetic_raw_json(
    *,
    fixture_id: str,
    kpi_id: str,
    metric_key: str,
    fixture_kind: FixtureKind,
    case_key: str,
    sample_pulls: Sequence[JsonDict] | None,
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
            "sample_pull_requests": list(sample_pulls)
            if sample_pulls is not None
            else [],
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
    fixture_id: str = "AC-KPI-02_v2026.05.17-synthetic_default",
    kpi_id: str = "AC-KPI-02",
    metric_key: str = "time_to_merge",
    fixture_kind: FixtureKind = "public_regression",
    case_key: str = "synthetic_case",
    sample_pulls: Sequence[JsonDict] | None = None,
    expected_aggregate: object = _AUTO,
    threshold: object = _AUTO,
) -> Fixture:
    if sample_pulls is None:
        sample_pulls = _sample_pulls(
            merged_durations_min=[30, 60, 90],
            open_count=1,
            closed_without_merge_count=1,
        )
    if expected_aggregate is _AUTO:
        expected_aggregate = _expected_aggregate_for(sample_pulls)
    if threshold is _AUTO:
        threshold = dict(_DEFAULT_THRESHOLD)

    raw_json = _synthetic_raw_json(
        fixture_id=fixture_id,
        kpi_id=kpi_id,
        metric_key=metric_key,
        fixture_kind=fixture_kind,
        case_key=case_key,
        sample_pulls=sample_pulls,
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
        source_path=Path("synthetic/time_to_merge.json"),
        raw_json=raw_json,
        kpi_id=kpi_id,
    )


_VALID_MANIFEST: Final[JsonDict] = {
    "kpi_id": EXPECTED_AC_KPI_02_KPI_ID,
    "metric": EXPECTED_AC_KPI_02_METRIC_KEY,
    "threshold": {
        "operator": EXPECTED_AC_KPI_02_THRESHOLD_OPERATOR,
        "value": EXPECTED_AC_KPI_02_THRESHOLD_HOURS,
        "unit": "hours",
    },
}


def _synthetic_corpus(
    fixtures: Sequence[Fixture],
    *,
    manifest: JsonDict | None = None,
) -> LoadedCorpus:
    return LoadedCorpus(
        dataset_key="time_to_merge",
        version="v2026.05.17-synthetic",
        content_hash="0" * 64,
        manifest=manifest if manifest is not None else dict(_VALID_MANIFEST),
        expected_schema={},
        fixtures=tuple(fixtures),
    )


def _result_for(
    fixture: Fixture,
) -> tuple[TimeToMergeMetricResult, TimeToMergeFixtureResult]:
    corpus = _synthetic_corpus([fixture])
    result = evaluate_time_to_merge(corpus)
    assert result.fixture_count == 1
    return result, result.per_fixture[0]


# ---------------------------------------------------------------------------
# 4+ source enum integrity (4 tests, plan v2 §7.1)
# ---------------------------------------------------------------------------


def test_ac_kpi_02_constants_match_test_layer_expected_constants() -> None:
    assert AC_KPI_02_KPI_ID == EXPECTED_AC_KPI_02_KPI_ID
    assert AC_KPI_02_METRIC_KEY == EXPECTED_AC_KPI_02_METRIC_KEY
    assert AC_KPI_02_THRESHOLD_HOURS == EXPECTED_AC_KPI_02_THRESHOLD_HOURS
    assert AC_KPI_02_THRESHOLD_MS == EXPECTED_AC_KPI_02_THRESHOLD_MS
    assert AC_KPI_02_THRESHOLD_OPERATOR == EXPECTED_AC_KPI_02_THRESHOLD_OPERATOR


def test_ac_kpi_02_constants_are_exported_from_module_all() -> None:
    expected = {
        "AC_KPI_02_KPI_ID",
        "AC_KPI_02_METRIC_KEY",
        "AC_KPI_02_THRESHOLD_HOURS",
        "AC_KPI_02_THRESHOLD_MS",
        "AC_KPI_02_THRESHOLD_OPERATOR",
        "SamplePullRequest",
        "TimeToMergeFixtureResult",
        "TimeToMergeMetricResult",
        "evaluate_time_to_merge",
    }
    assert expected <= set(time_to_merge.__all__)


def test_fixture_schema_pr_status_enum_matches_known_set() -> None:
    schema = _read_json(SCHEMA_PATH)
    schema_enum = schema["properties"]["input"]["properties"][
        "sample_pull_requests"
    ]["items"]["properties"]["status"]["enum"]
    assert frozenset(schema_enum) == EXPECTED_KNOWN_PR_STATUSES


def test_merged_status_is_within_known_set() -> None:
    assert (
        time_to_merge._MERGED_STATUS in time_to_merge._KNOWN_PR_STATUSES
    )
    assert (
        time_to_merge._KNOWN_PR_STATUSES == EXPECTED_KNOWN_PR_STATUSES
    )


# ---------------------------------------------------------------------------
# Live happy path (2 tests, plan v2 §7.2)
# ---------------------------------------------------------------------------


def test_live_skeleton_fixture_passes_threshold() -> None:
    corpus = _load_corpus()
    result = evaluate_time_to_merge(corpus)
    assert result.fixture_count == EXPECTED_FIXTURE_COUNT
    assert result.manifest_violation_reason is None
    assert result.total_pulls_across_corpus == EXPECTED_LIVE_PULLS
    assert result.merged_count_across_corpus == EXPECTED_LIVE_MERGED
    assert result.metric_value == pytest.approx(EXPECTED_LIVE_MEDIAN_HOURS)
    assert result.threshold_met is True
    assert result.threshold_reason == "threshold_met"
    per = result.per_fixture[0]
    assert per.spec_violation_reason is None
    assert per.passed is True
    assert per.merged_count == EXPECTED_LIVE_MERGED
    assert per.open_count == EXPECTED_LIVE_OPEN
    assert per.closed_without_merge_count == EXPECTED_LIVE_CLOSED


def test_pooled_corpus_median_across_two_synthetic_fixtures() -> None:
    """Plan v2 §4.2.1: pooled (un-weighted) median across all merged
    durations corpus-wide. Two fixtures contribute durations [1.0, 2.5]
    and [0.5, 3.0] hours → pooled median([0.5, 1.0, 2.5, 3.0]) = 1.75h.
    """

    fixture_a = _synthetic_fixture(
        fixture_id="AC-KPI-02_v2026.05.17-synthetic_corpus_a",
        sample_pulls=_sample_pulls(
            merged_durations_min=[60, 150],  # 1.0h, 2.5h
            prefix="corpus-a",
        ),
    )
    fixture_b = _synthetic_fixture(
        fixture_id="AC-KPI-02_v2026.05.17-synthetic_corpus_b",
        sample_pulls=_sample_pulls(
            merged_durations_min=[30, 180],  # 0.5h, 3.0h
            prefix="corpus-b",
        ),
    )
    result = evaluate_time_to_merge(_synthetic_corpus([fixture_a, fixture_b]))
    # pooled median([0.5, 1.0, 2.5, 3.0]) = (1.0 + 2.5) / 2 = 1.75
    assert result.metric_value == pytest.approx(1.75)
    assert result.merged_count_across_corpus == 4


# ---------------------------------------------------------------------------
# Anti-Gaming (5 tests, plan v2 §7.3)
# ---------------------------------------------------------------------------


def test_open_excluded_from_median_numerator() -> None:
    rows = _sample_pulls(
        merged_durations_min=[60, 120], open_count=2, prefix="open-test"
    )
    fixture = _synthetic_fixture(sample_pulls=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason is None
    assert per.recomputed_median_hours == pytest.approx(1.5)  # median([1.0, 2.0])
    assert per.merged_count == 2
    assert per.open_count == 2


def test_draft_excluded_from_median_numerator() -> None:
    rows = _sample_pulls(
        merged_durations_min=[60, 120], draft_count=2, prefix="draft-test"
    )
    fixture = _synthetic_fixture(sample_pulls=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason is None
    assert per.recomputed_median_hours == pytest.approx(1.5)
    assert per.draft_count == 2


def test_closed_without_merge_excluded_from_median_numerator() -> None:
    rows = _sample_pulls(
        merged_durations_min=[60, 120],
        closed_without_merge_count=2,
        prefix="closed-test",
    )
    fixture = _synthetic_fixture(sample_pulls=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason is None
    assert per.recomputed_median_hours == pytest.approx(1.5)
    assert per.closed_without_merge_count == 2


def test_unknown_status_is_rejected() -> None:
    rows = _sample_pulls(merged_durations_min=[60])
    rows.append(
        {
            "ticket_id": _uuid_for("bad-status-extra"),
            "tenant_id": 1,
            "project_id": _DEFAULT_PROJECT_ID,
            "repository_id": _DEFAULT_REPOSITORY_ID,
            "status": "reopened",  # unknown
            "ticket_created_at": _iso(2026, 5, 1, 12, 0),
            "merged_at": None,
        }
    )
    fixture = _synthetic_fixture(sample_pulls=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:status"


def test_expected_aggregate_median_drift_detected() -> None:
    rows = _sample_pulls(merged_durations_min=[60, 120])
    aggregate = _expected_aggregate_for(rows)
    aggregate["median_hours"] = 5.0  # lie (recomputed = 1.5)
    fixture = _synthetic_fixture(sample_pulls=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_aggregate_median_drift"


# ---------------------------------------------------------------------------
# Manifest drift (4 parametrize, plan v2 §7.4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mutation_key", "mutation_value", "expected_reason"),
    [
        ("kpi_id", "AC-KPI-99", "manifest_violation:kpi_id"),
        ("metric", "something_else", "manifest_violation:metric"),
        ("threshold_operator", ">", "manifest_violation:threshold_operator"),
        ("threshold_value", 5.0, "manifest_violation:threshold_value"),
    ],
)
def test_manifest_violations_are_detected(
    mutation_key: str, mutation_value: object, expected_reason: str
) -> None:
    manifest = copy.deepcopy(_VALID_MANIFEST)
    if mutation_key == "threshold_operator":
        manifest["threshold"]["operator"] = mutation_value
    elif mutation_key == "threshold_value":
        manifest["threshold"]["value"] = mutation_value
    else:
        manifest[mutation_key] = mutation_value
    fixture = _synthetic_fixture()
    result = evaluate_time_to_merge(_synthetic_corpus([fixture], manifest=manifest))
    assert result.manifest_violation_reason == expected_reason
    assert result.threshold_reason == "manifest_violation"


# ---------------------------------------------------------------------------
# Per-fixture spec violations (18 tests, plan v2 §7.5)
# ---------------------------------------------------------------------------


def test_empty_sample_pull_requests_is_rejected() -> None:
    fixture = _synthetic_fixture(
        sample_pulls=[],
        expected_aggregate={
            "pulls_count": 0,
            "merged_count": 0,
            "open_count": 0,
            "draft_count": 0,
            "closed_without_merge_count": 0,
            "median_hours": None,
        },
    )
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:sample_pull_requests"


def test_non_list_sample_pull_requests_is_rejected() -> None:
    fixture = _synthetic_fixture()
    fixture.case_json["input"]["sample_pull_requests"] = "not a list"  # type: ignore[index]
    fixture.raw_json["input"]["sample_pull_requests"] = "not a list"  # type: ignore[index]
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:sample_pull_requests"


def test_duplicate_pr_key_within_fixture_is_rejected() -> None:
    rows = _sample_pulls(merged_durations_min=[60, 120])
    # Force same (ticket_id, repository_id) on both rows
    rows[1]["ticket_id"] = rows[0]["ticket_id"]
    rows[1]["repository_id"] = rows[0]["repository_id"]
    fixture = _synthetic_fixture(sample_pulls=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:duplicate_pr_key"


def test_duplicate_pr_key_across_fixtures_is_rejected() -> None:
    shared_ticket = _uuid_for("cross-fixture-shared-ticket")
    shared_repo = _DEFAULT_REPOSITORY_ID

    def _build(fid: str) -> Fixture:
        rows: list[JsonDict] = [
            {
                "ticket_id": shared_ticket,
                "tenant_id": 1,
                "project_id": _DEFAULT_PROJECT_ID,
                "repository_id": shared_repo,
                "status": "merged",
                "ticket_created_at": _iso(2026, 5, 1, 10, 0),
                "merged_at": _iso(2026, 5, 1, 11, 0),
            }
        ]
        return _synthetic_fixture(
            fixture_id=fid,
            sample_pulls=rows,
            expected_aggregate={
                "pulls_count": 1,
                "merged_count": 1,
                "open_count": 0,
                "draft_count": 0,
                "closed_without_merge_count": 0,
                "median_hours": 1.0,
            },
        )

    fixture_a = _build("AC-KPI-02_v2026.05.17-synthetic_dup_a")
    fixture_b = _build("AC-KPI-02_v2026.05.17-synthetic_dup_b")
    result = evaluate_time_to_merge(_synthetic_corpus([fixture_a, fixture_b]))
    assert result.per_fixture[0].spec_violation_reason is None
    assert (
        result.per_fixture[1].spec_violation_reason
        == "spec_violation:duplicate_pr_key_across_fixtures"
    )
    assert result.merged_count_across_corpus == 1


@pytest.mark.parametrize("id_field", ["ticket_id", "project_id"])
def test_invalid_required_uuid_is_rejected(id_field: str) -> None:
    rows = _sample_pulls(merged_durations_min=[60], prefix=f"bad-{id_field}")
    rows[0][id_field] = "NOT-A-VALID-UUID"  # type: ignore[index]
    fixture = _synthetic_fixture(sample_pulls=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == f"spec_violation:{id_field}"


def test_invalid_repository_id_uuid_is_rejected() -> None:
    rows = _sample_pulls(merged_durations_min=[60], prefix="bad-repo")
    rows[0]["repository_id"] = "NOT-A-VALID-UUID"  # type: ignore[index]
    fixture = _synthetic_fixture(sample_pulls=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:repository_id"


@pytest.mark.parametrize("raw_value", [None, True, "1", -1, 0])
def test_invalid_tenant_id_is_rejected(raw_value: object) -> None:
    rows = _sample_pulls(merged_durations_min=[60], prefix="bad-tenant")
    rows[0]["tenant_id"] = raw_value
    fixture = _synthetic_fixture(sample_pulls=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:tenant_id"


def test_envelope_kpi_id_mismatch_is_rejected() -> None:
    fixture = _synthetic_fixture(kpi_id="AC-KPI-99")
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:kpi_id"


def test_envelope_metric_key_mismatch_is_rejected() -> None:
    fixture = _synthetic_fixture(metric_key="other_metric")
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:metric_key"


def test_unparseable_timestamp_is_rejected() -> None:
    rows = _sample_pulls(merged_durations_min=[60])
    rows[0]["ticket_created_at"] = "not a real date"
    fixture = _synthetic_fixture(sample_pulls=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:ticket_created_at"


def test_naive_datetime_is_rejected() -> None:
    """Plan v2 §2.3 / LOW-003: ISO-8601 without timezone offset is
    rejected by ``_parse_timestamp_ms``.
    """

    rows = _sample_pulls(merged_durations_min=[60])
    rows[0]["ticket_created_at"] = "2026-05-01T10:00:00"  # no tz
    fixture = _synthetic_fixture(sample_pulls=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:ticket_created_at"


def test_non_utc_offset_is_accepted_and_normalized() -> None:
    """Plan v2 §2.3 / LOW-003: non-UTC offset is accepted then
    normalized to UTC for the epoch_ms canonical representation.
    """

    rows: list[JsonDict] = [
        {
            "ticket_id": _uuid_for("non-utc-001"),
            "tenant_id": 1,
            "project_id": _DEFAULT_PROJECT_ID,
            "repository_id": _DEFAULT_REPOSITORY_ID,
            "status": "merged",
            # 10:00+09:00 = 01:00 UTC; merged 11:00+09:00 = 02:00 UTC; delta = 1h
            "ticket_created_at": "2026-05-01T10:00:00+09:00",
            "merged_at": "2026-05-01T11:00:00+09:00",
        }
    ]
    fixture = _synthetic_fixture(
        sample_pulls=rows,
        expected_aggregate={
            "pulls_count": 1,
            "merged_count": 1,
            "open_count": 0,
            "draft_count": 0,
            "closed_without_merge_count": 0,
            "median_hours": 1.0,
        },
    )
    _, per = _result_for(fixture)
    assert per.spec_violation_reason is None
    assert per.recomputed_median_hours == pytest.approx(1.0)


def test_z_suffix_is_accepted_and_normalized() -> None:
    """Plan v2 §2.3 / LOW-003: trailing ``Z`` (RFC 3339) is normalized
    to ``+00:00``.
    """

    rows: list[JsonDict] = [
        {
            "ticket_id": _uuid_for("z-suffix-001"),
            "tenant_id": 1,
            "project_id": _DEFAULT_PROJECT_ID,
            "repository_id": _DEFAULT_REPOSITORY_ID,
            "status": "merged",
            "ticket_created_at": "2026-05-01T10:00:00Z",
            "merged_at": "2026-05-01T11:00:00Z",
        }
    ]
    fixture = _synthetic_fixture(
        sample_pulls=rows,
        expected_aggregate={
            "pulls_count": 1,
            "merged_count": 1,
            "open_count": 0,
            "draft_count": 0,
            "closed_without_merge_count": 0,
            "median_hours": 1.0,
        },
    )
    _, per = _result_for(fixture)
    assert per.spec_violation_reason is None


def test_merged_at_causality_violation_is_rejected() -> None:
    """Plan v2 §6 #12 / HIGH-001: ``merged_at < ticket_created_at`` is
    rejected at parse time as ``spec_violation:merged_at_causality``.
    """

    rows: list[JsonDict] = [
        {
            "ticket_id": _uuid_for("causality-001"),
            "tenant_id": 1,
            "project_id": _DEFAULT_PROJECT_ID,
            "repository_id": _DEFAULT_REPOSITORY_ID,
            "status": "merged",
            "ticket_created_at": "2026-05-01T11:00:00+00:00",
            "merged_at": "2026-05-01T10:00:00+00:00",  # before ticket creation
        }
    ]
    fixture = _synthetic_fixture(sample_pulls=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:merged_at_causality"


def test_merged_status_without_merged_at_is_rejected() -> None:
    """Plan v2 §6 #12: ``status="merged"`` requires non-null
    ``merged_at``.
    """

    rows: list[JsonDict] = [
        {
            "ticket_id": _uuid_for("null-merged-at"),
            "tenant_id": 1,
            "project_id": _DEFAULT_PROJECT_ID,
            "repository_id": _DEFAULT_REPOSITORY_ID,
            "status": "merged",
            "ticket_created_at": "2026-05-01T10:00:00+00:00",
            "merged_at": None,
        }
    ]
    fixture = _synthetic_fixture(sample_pulls=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:merged_at_required"


def test_non_merged_status_with_merged_at_is_rejected() -> None:
    """Plan v2 §7.5: status != merged with non-null merged_at must be
    rejected (cleanliness check).
    """

    rows: list[JsonDict] = [
        {
            "ticket_id": _uuid_for("unexpected-merged-at"),
            "tenant_id": 1,
            "project_id": _DEFAULT_PROJECT_ID,
            "repository_id": _DEFAULT_REPOSITORY_ID,
            "status": "open",
            "ticket_created_at": "2026-05-01T10:00:00+00:00",
            "merged_at": "2026-05-01T11:00:00+00:00",
        }
    ]
    fixture = _synthetic_fixture(sample_pulls=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:merged_at_unexpected"


def test_merged_status_with_null_repository_id_is_rejected() -> None:
    """LOW-R2-001 adopt: merged PR must have non-null repository_id."""

    rows: list[JsonDict] = [
        {
            "ticket_id": _uuid_for("null-repo-merged"),
            "tenant_id": 1,
            "project_id": _DEFAULT_PROJECT_ID,
            "repository_id": None,
            "status": "merged",
            "ticket_created_at": "2026-05-01T10:00:00+00:00",
            "merged_at": "2026-05-01T11:00:00+00:00",
        }
    ]
    fixture = _synthetic_fixture(sample_pulls=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:repository_id"


# ---------------------------------------------------------------------------
# expected_aggregate violations (10 tests, plan v2 §7.6)
# ---------------------------------------------------------------------------


def test_missing_expected_aggregate_is_rejected() -> None:
    fixture = _synthetic_fixture(expected_aggregate=OMIT_EXPECTED_AGGREGATE)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_aggregate_missing"


def test_non_dict_expected_aggregate_is_rejected() -> None:
    fixture = _synthetic_fixture(expected_aggregate="not a dict")
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_aggregate"


@pytest.mark.parametrize(
    ("field", "expected_reason"),
    [
        ("pulls_count", "spec_violation:expected_aggregate_pulls_drift"),
        ("merged_count", "spec_violation:expected_aggregate_merged_drift"),
        ("open_count", "spec_violation:expected_aggregate_open_drift"),
        ("draft_count", "spec_violation:expected_aggregate_draft_drift"),
        (
            "closed_without_merge_count",
            "spec_violation:expected_aggregate_closed_drift",
        ),
    ],
)
def test_expected_aggregate_count_drift_is_detected(
    field: str, expected_reason: str
) -> None:
    rows = _sample_pulls(merged_durations_min=[60], open_count=1)
    aggregate = _expected_aggregate_for(rows)
    aggregate[field] = 999
    fixture = _synthetic_fixture(sample_pulls=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == expected_reason


def test_declared_median_negative_is_rejected() -> None:
    rows = _sample_pulls(merged_durations_min=[60])
    aggregate = _expected_aggregate_for(rows)
    aggregate["median_hours"] = -0.5
    fixture = _synthetic_fixture(sample_pulls=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_aggregate"


def test_zero_merged_with_null_declared_median_is_accepted() -> None:
    rows = _sample_pulls(open_count=3)
    aggregate = _expected_aggregate_for(rows)
    aggregate["median_hours"] = None
    fixture = _synthetic_fixture(sample_pulls=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason is None


def test_zero_merged_with_zero_declared_median_is_accepted() -> None:
    rows = _sample_pulls(open_count=3)
    aggregate = _expected_aggregate_for(rows)
    aggregate["median_hours"] = 0.0
    fixture = _synthetic_fixture(sample_pulls=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason is None


def test_zero_merged_with_nonzero_declared_median_is_rejected() -> None:
    rows = _sample_pulls(open_count=3)
    aggregate = _expected_aggregate_for(rows)
    aggregate["median_hours"] = 0.5
    fixture = _synthetic_fixture(sample_pulls=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_aggregate_median_drift"


# ---------------------------------------------------------------------------
# Edge cases (7 tests, plan v2 §7.7 priority order HIGH-002)
# ---------------------------------------------------------------------------


def test_empty_corpus_yields_no_fixtures_reason() -> None:
    result = evaluate_time_to_merge(_synthetic_corpus([]))
    assert result.threshold_reason == "no_fixtures"
    assert result.threshold_met is False
    assert result.metric_value is None


def test_all_open_yields_no_merged_pulls_reason() -> None:
    fixture = _synthetic_fixture(sample_pulls=_sample_pulls(open_count=5))
    result = evaluate_time_to_merge(_synthetic_corpus([fixture]))
    assert result.threshold_reason == "no_merged_pulls"
    assert result.threshold_met is False
    assert result.metric_value is None


def test_all_closed_without_merge_yields_no_merged_pulls_reason() -> None:
    fixture = _synthetic_fixture(
        sample_pulls=_sample_pulls(closed_without_merge_count=5)
    )
    result = evaluate_time_to_merge(_synthetic_corpus([fixture]))
    assert result.threshold_reason == "no_merged_pulls"
    assert result.threshold_met is False


def test_threshold_at_boundary_passes() -> None:
    """median exactly 2.0h → threshold_met=True (boundary inclusive)."""

    rows = _sample_pulls(merged_durations_min=[120], prefix="boundary-met")
    fixture = _synthetic_fixture(sample_pulls=rows)
    result = evaluate_time_to_merge(_synthetic_corpus([fixture]))
    assert result.metric_value == pytest.approx(2.0)
    assert result.threshold_met is True
    assert result.threshold_reason == "threshold_met"


def test_threshold_just_above_boundary_fails() -> None:
    """median just above 2.0h (2.5h via duration 150min) → above_threshold."""

    rows = _sample_pulls(merged_durations_min=[150], prefix="boundary-above")
    fixture = _synthetic_fixture(sample_pulls=rows)
    result = evaluate_time_to_merge(_synthetic_corpus([fixture]))
    assert result.metric_value == pytest.approx(2.5)
    assert result.threshold_met is False
    assert result.threshold_reason == "above_threshold"


def test_threshold_within_ms_tolerance_passes() -> None:
    """F-PR34-005 adopt: a fixture with a recomputed median of
    ``2.0h + 1ms`` is within the ms-precision tolerance band
    (``_THRESHOLD_HOURS_ABS_TOL = 1/3_600_000``). The aggregator must
    report ``threshold_met=True`` even though the un-rounded float
    metric_value is fractionally greater than 2.0.

    This locks the inclusive boundary semantic at the tolerance edge.
    A future regression that changes ``<=`` to ``<`` or removes
    ``_THRESHOLD_HOURS_ABS_TOL`` would surface immediately here.
    """

    # 2 hours and 1 millisecond = 7_200_001 ms = 2:00:00.001
    rows: list[JsonDict] = [
        {
            "ticket_id": _uuid_for("ms-tol-001"),
            "tenant_id": 1,
            "project_id": _DEFAULT_PROJECT_ID,
            "repository_id": _DEFAULT_REPOSITORY_ID,
            "status": "merged",
            "ticket_created_at": "2026-05-01T10:00:00+00:00",
            "merged_at": "2026-05-01T12:00:00.001+00:00",
        }
    ]
    fixture = _synthetic_fixture(
        sample_pulls=rows,
        expected_aggregate={
            "pulls_count": 1,
            "merged_count": 1,
            "open_count": 0,
            "draft_count": 0,
            "closed_without_merge_count": 0,
            "median_hours": 7_200_001 / 3_600_000.0,
        },
    )
    result = evaluate_time_to_merge(_synthetic_corpus([fixture]))
    # 2.0 + 1/3_600_000 ≈ 2.000000278 hours — within abs_tol.
    assert result.metric_value == pytest.approx(7_200_001 / 3_600_000.0)
    assert result.threshold_met is True
    assert result.threshold_reason == "threshold_met"


def test_threshold_outside_ms_tolerance_fails() -> None:
    """F-PR34-005 adopt: a fixture with median ``2.0h + 100ms`` is
    well outside the 1 ms tolerance band and must report
    ``above_threshold``.
    """

    rows: list[JsonDict] = [
        {
            "ticket_id": _uuid_for("ms-out-of-tol-001"),
            "tenant_id": 1,
            "project_id": _DEFAULT_PROJECT_ID,
            "repository_id": _DEFAULT_REPOSITORY_ID,
            "status": "merged",
            "ticket_created_at": "2026-05-01T10:00:00+00:00",
            "merged_at": "2026-05-01T12:00:00.100+00:00",
        }
    ]
    fixture = _synthetic_fixture(
        sample_pulls=rows,
        expected_aggregate={
            "pulls_count": 1,
            "merged_count": 1,
            "open_count": 0,
            "draft_count": 0,
            "closed_without_merge_count": 0,
            "median_hours": 7_200_100 / 3_600_000.0,
        },
    )
    result = evaluate_time_to_merge(_synthetic_corpus([fixture]))
    assert result.threshold_met is False
    assert result.threshold_reason == "above_threshold"


def test_envelope_invalid_fixture_does_not_poison_corpus_state() -> None:
    """Plan v2 §6 #9 / batch 5e F-PR32-R6-001 carry-over."""

    shared_ticket = _uuid_for("envelope-invalid-shared")
    shared_repo = _DEFAULT_REPOSITORY_ID

    fixture_a = _synthetic_fixture(
        fixture_id="AC-KPI-02_v2026.05.17-synthetic_env_a",
        kpi_id="AC-KPI-99",  # envelope violation
        sample_pulls=[
            {
                "ticket_id": shared_ticket,
                "tenant_id": 1,
                "project_id": _DEFAULT_PROJECT_ID,
                "repository_id": shared_repo,
                "status": "merged",
                "ticket_created_at": "2026-05-01T10:00:00+00:00",
                "merged_at": "2026-05-01T11:00:00+00:00",
            }
        ],
        expected_aggregate={
            "pulls_count": 1,
            "merged_count": 1,
            "open_count": 0,
            "draft_count": 0,
            "closed_without_merge_count": 0,
            "median_hours": 1.0,
        },
    )
    fixture_b = _synthetic_fixture(
        fixture_id="AC-KPI-02_v2026.05.17-synthetic_env_b",
        sample_pulls=[
            {
                "ticket_id": shared_ticket,
                "tenant_id": 1,
                "project_id": _DEFAULT_PROJECT_ID,
                "repository_id": shared_repo,
                "status": "merged",
                "ticket_created_at": "2026-05-01T10:00:00+00:00",
                "merged_at": "2026-05-01T11:00:00+00:00",
            }
        ],
        expected_aggregate={
            "pulls_count": 1,
            "merged_count": 1,
            "open_count": 0,
            "draft_count": 0,
            "closed_without_merge_count": 0,
            "median_hours": 1.0,
        },
    )
    result = evaluate_time_to_merge(_synthetic_corpus([fixture_a, fixture_b]))
    assert result.per_fixture[0].spec_violation_reason == "spec_violation:kpi_id"
    assert result.per_fixture[1].spec_violation_reason is None
    assert result.merged_count_across_corpus == 1
    assert result.metric_value == pytest.approx(1.0)


def test_aggregate_invalid_fixture_does_not_poison_corpus_state() -> None:
    """Plan v2 §6 #9 / batch 5e F-PR32-R6-001 carry-over."""

    shared_ticket = _uuid_for("aggregate-invalid-shared")
    fixture_a = _synthetic_fixture(
        fixture_id="AC-KPI-02_v2026.05.17-synthetic_agg_a",
        sample_pulls=[
            {
                "ticket_id": shared_ticket,
                "tenant_id": 1,
                "project_id": _DEFAULT_PROJECT_ID,
                "repository_id": _DEFAULT_REPOSITORY_ID,
                "status": "merged",
                "ticket_created_at": "2026-05-01T10:00:00+00:00",
                "merged_at": "2026-05-01T11:00:00+00:00",
            }
        ],
        # Declared median drift: 999 vs recomputed 1.0
        expected_aggregate={
            "pulls_count": 1,
            "merged_count": 1,
            "open_count": 0,
            "draft_count": 0,
            "closed_without_merge_count": 0,
            "median_hours": 999.0,
        },
    )
    fixture_b = _synthetic_fixture(
        fixture_id="AC-KPI-02_v2026.05.17-synthetic_agg_b",
        sample_pulls=[
            {
                "ticket_id": shared_ticket,
                "tenant_id": 1,
                "project_id": _DEFAULT_PROJECT_ID,
                "repository_id": _DEFAULT_REPOSITORY_ID,
                "status": "merged",
                "ticket_created_at": "2026-05-01T10:00:00+00:00",
                "merged_at": "2026-05-01T11:00:00+00:00",
            }
        ],
        expected_aggregate={
            "pulls_count": 1,
            "merged_count": 1,
            "open_count": 0,
            "draft_count": 0,
            "closed_without_merge_count": 0,
            "median_hours": 1.0,
        },
    )
    result = evaluate_time_to_merge(_synthetic_corpus([fixture_a, fixture_b]))
    assert (
        result.per_fixture[0].spec_violation_reason
        == "spec_violation:expected_aggregate_median_drift"
    )
    assert result.per_fixture[1].spec_violation_reason is None
    assert result.merged_count_across_corpus == 1


# ---------------------------------------------------------------------------
# SUT integration (5 tests, plan v2 §7.8)
# ---------------------------------------------------------------------------


def test_sut_results_all_true_passes() -> None:
    fixture = _synthetic_fixture()
    result = evaluate_time_to_merge(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: True},
    )
    assert result.per_fixture[0].passed is True
    assert result.per_fixture[0].sut_attempted is True


def test_sut_results_all_false_marks_failure() -> None:
    fixture = _synthetic_fixture()
    result = evaluate_time_to_merge(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: False},
    )
    assert result.per_fixture[0].sut_failure_reason == "sut_returned_false"
    assert result.threshold_reason == "sut_failure"


def test_sut_result_missing_marks_failure() -> None:
    fixture = _synthetic_fixture()
    result = evaluate_time_to_merge(
        _synthetic_corpus([fixture]),
        sut_results={"some_other_fixture_id": True},
    )
    assert result.per_fixture[0].sut_failure_reason == "sut_result_missing"


@pytest.mark.parametrize("raw_value", [None, "true", 1, 0, [], "1"])
def test_non_boolean_sut_result_is_rejected(raw_value: object) -> None:
    fixture = _synthetic_fixture()
    result = evaluate_time_to_merge(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: raw_value},  # type: ignore[dict-item]
    )
    assert (
        result.per_fixture[0].sut_failure_reason == "sut_result_invalid_type"
    )


def test_spec_violation_skips_sut_processing() -> None:
    fixture = _synthetic_fixture(kpi_id="AC-KPI-99")
    result = evaluate_time_to_merge(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: True},
    )
    per = result.per_fixture[0]
    assert per.spec_violation_reason == "spec_violation:kpi_id"
    assert per.sut_attempted is False
    assert per.sut_result is None


# ---------------------------------------------------------------------------
# Overflow / robustness (2 tests, plan v2 §7.9)
# ---------------------------------------------------------------------------


def test_huge_int_in_expected_aggregate_is_handled_gracefully() -> None:
    rows = _sample_pulls(merged_durations_min=[60])
    aggregate = _expected_aggregate_for(rows)
    aggregate["median_hours"] = 10**500
    fixture = _synthetic_fixture(sample_pulls=rows, expected_aggregate=aggregate)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_aggregate"


def test_sample_pull_request_dataclass_is_frozen() -> None:
    pr = SamplePullRequest(
        ticket_id=_uuid_for("frozen-test"),
        tenant_id=1,
        project_id=_DEFAULT_PROJECT_ID,
        repository_id=_DEFAULT_REPOSITORY_ID,
        status="merged",
        ticket_created_at_ms=1746091200000,
        merged_at_ms=1746094800000,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        pr.status = "open"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Anti-Gaming counter-defense logs (2 tests, plan v2 §7.10)
# ---------------------------------------------------------------------------


def test_high_closed_without_merge_ratio_emits_warning_log() -> None:
    """Plan v2 §2.2 + §7.10: >50% closed_without_merge → warn, but does
    NOT reject. Uses mock.patch.object for CI determinism (batch 5f
    lesson carry-over).
    """

    rows = _sample_pulls(
        merged_durations_min=[60],
        closed_without_merge_count=3,
        prefix="high-reject",
    )
    fixture = _synthetic_fixture(sample_pulls=rows)
    with mock.patch.object(
        time_to_merge._LOGGER, "warning", wraps=time_to_merge._LOGGER.warning
    ) as mock_warning:
        result = evaluate_time_to_merge(_synthetic_corpus([fixture]))
    assert result.per_fixture[0].spec_violation_reason is None
    matching = [
        call for call in mock_warning.call_args_list
        if call.args and "closed_without_merge_ratio" in str(call.args[0])
    ]
    assert matching, (
        f"Expected closed_without_merge_ratio warning. "
        f"Got {mock_warning.call_args_list}"
    )


def test_sub_millisecond_timestamp_is_rejected() -> None:
    """F-PR34-R2-001 P2 adopt: sub-millisecond precision (microseconds
    not divisible by 1000) is rejected. Otherwise two timestamps that
    differ in the microsecond range collapse to the same ms after
    truncation, hiding a negative duration from the causality check.
    """

    rows: list[JsonDict] = [
        {
            "ticket_id": _uuid_for("submillisecond"),
            "tenant_id": 1,
            "project_id": _DEFAULT_PROJECT_ID,
            "repository_id": _DEFAULT_REPOSITORY_ID,
            "status": "merged",
            # 999.9 microseconds < 1 ms — sub-millisecond precision.
            "ticket_created_at": "2026-05-01T10:00:00.999999+00:00",
            "merged_at": "2026-05-01T10:00:00.999900+00:00",
        }
    ]
    fixture = _synthetic_fixture(sample_pulls=rows)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:ticket_created_at"


def test_fixture_threshold_relaxed_value_is_rejected() -> None:
    """F-PR34-R2-002 P2 adopt: per-fixture threshold with a relaxed
    ``value`` (e.g., 999.0 to silently mark "passed") is rejected as
    ``spec_violation:threshold_value`` before any downstream validation.
    """

    rows = _sample_pulls(merged_durations_min=[60])
    fixture = _synthetic_fixture(
        sample_pulls=rows,
        threshold={"operator": "<=", "value": 999.0, "unit": "hours"},
    )
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:threshold_value"


def test_fixture_threshold_wrong_unit_is_rejected() -> None:
    """F-PR34-R2-002 P2 adopt: ``unit != "hours"`` rejected."""

    rows = _sample_pulls(merged_durations_min=[60])
    fixture = _synthetic_fixture(
        sample_pulls=rows,
        threshold={"operator": "<=", "value": 2.0, "unit": "minutes"},
    )
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:threshold_unit"


def test_fixture_threshold_wrong_operator_is_rejected() -> None:
    """F-PR34-R2-002 P2 adopt: ``operator != "<="`` rejected."""

    rows = _sample_pulls(merged_durations_min=[60])
    fixture = _synthetic_fixture(
        sample_pulls=rows,
        threshold={"operator": ">=", "value": 2.0, "unit": "hours"},
    )
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:threshold_operator"


def test_fixture_threshold_null_is_accepted() -> None:
    """F-PR34-R2-002 P2 adopt: a fixture with ``threshold: null`` falls
    through to manifest-canonical threshold (no fixture-level violation).
    """

    rows = _sample_pulls(merged_durations_min=[60])
    fixture = _synthetic_fixture(sample_pulls=rows, threshold=None)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason is None


def test_all_zero_duration_emits_warning_log_but_does_not_reject() -> None:
    """Plan v2 §2.2 + §7.10: 5+ merged PRs all with duration=0 → warn,
    boundary `merged_at == ticket_created_at` is valid per MED-003.
    """

    rows: list[JsonDict] = []
    for i in range(5):
        rows.append(
            {
                "ticket_id": _uuid_for(f"zero-duration-{i:03d}"),
                "tenant_id": 1,
                "project_id": _DEFAULT_PROJECT_ID,
                "repository_id": _DEFAULT_REPOSITORY_ID,
                "status": "merged",
                "ticket_created_at": f"2026-05-01T{i + 10:02d}:00:00+00:00",
                "merged_at": f"2026-05-01T{i + 10:02d}:00:00+00:00",
            }
        )
    fixture = _synthetic_fixture(sample_pulls=rows)
    with mock.patch.object(
        time_to_merge._LOGGER, "warning", wraps=time_to_merge._LOGGER.warning
    ) as mock_warning:
        result = evaluate_time_to_merge(_synthetic_corpus([fixture]))
    # Boundary valid; no spec_violation. metric_value = median of 5 zeros = 0.0
    assert result.per_fixture[0].spec_violation_reason is None
    assert result.metric_value == pytest.approx(0.0)
    assert result.threshold_met is True  # 0.0 <= 2.0
    matching = [
        call for call in mock_warning.call_args_list
        if call.args and "all-zero-duration" in str(call.args[0])
    ]
    assert matching, (
        f"Expected all-zero-duration warning. "
        f"Got {mock_warning.call_args_list}"
    )
