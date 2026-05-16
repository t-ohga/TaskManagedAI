"""Tests for the AC-KPI-04 citation_coverage aggregator.

Coverage focuses on five concerns:

* 5+ source enum integrity for the AC-KPI-04 constants (Python ``Final`` /
  ``Literal`` + module ``__all__`` + pytest EXPECTED constants + real manifest +
  real fixture).
* Happy path against the live ``eval/quality/citation_coverage`` corpus.
* Manifest-level drift detection (``kpi_id`` / ``metric`` / ``threshold``).
* Per-fixture spec violations including the Anti-Gaming
  ``expected_aggregate_drift`` invariant.
* SUT result integration (forward-compatibility with BL-0127b / SP-012).
"""

from __future__ import annotations

import copy
import dataclasses
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, Literal

import pytest

from backend.app.db.models.base import JsonDict
from backend.app.db.models.dataset_version import FixtureKind
from backend.app.services.eval.kpis import citation_coverage
from backend.app.services.eval.kpis.citation_coverage import (
    AC_KPI_04_KPI_ID,
    AC_KPI_04_METRIC_KEY,
    AC_KPI_04_THRESHOLD,
    AC_KPI_04_THRESHOLD_OPERATOR,
    CitationCoverageFixtureResult,
    CitationCoverageMetricResult,
    ClaimCoverageEntry,
    evaluate_citation_coverage,
)
from backend.app.services.eval.loader import Fixture, LoadedCorpus, load_fixture_corpus

_REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = _REPO_ROOT / "eval/quality/citation_coverage"
MANIFEST_PATH = BASE_PATH / "manifest.json"

EXPECTED_AC_KPI_04_KPI_ID: Final[Literal["AC-KPI-04"]] = "AC-KPI-04"
EXPECTED_AC_KPI_04_METRIC_KEY: Final[Literal["citation_coverage"]] = "citation_coverage"
EXPECTED_AC_KPI_04_THRESHOLD: Final[float] = 0.9
EXPECTED_AC_KPI_04_THRESHOLD_OPERATOR: Final[Literal[">="]] = ">="
# Existing fixture (``citation_coverage_minimal_five_claims``) declares
# ``total_claims=5`` / ``claims_with_citation=3`` / ``coverage_ratio=0.6``.
EXPECTED_FIXTURE_COUNT: Final[int] = 1
EXPECTED_SAMPLE_TOTAL_CLAIMS: Final[int] = 5
EXPECTED_SAMPLE_CLAIMS_WITH_CITATION: Final[int] = 3
EXPECTED_SAMPLE_COVERAGE_RATIO: Final[float] = 0.6


def _load_corpus() -> LoadedCorpus:
    return load_fixture_corpus(BASE_PATH, dataset_key="citation_coverage")


def _read_json(path: Path) -> JsonDict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sample_claims(
    *,
    total: int,
    with_citation: int,
    prefix: str,
    claim_text: str = "synthetic claim text",
) -> list[JsonDict]:
    """Build a deterministic synthetic ``sample_claims`` payload."""

    claims: list[JsonDict] = []
    for index in range(total):
        number = index + 1
        claims.append(
            {
                "claim_id": f"{prefix}-claim-{number:03d}",
                "claim_text": f"{claim_text} {number}",
                "evidence_ids": [f"{prefix}-ev-{number:03d}"],
                "citation_ids": [f"{prefix}-cit-{number:03d}"] if index < with_citation else [],
            }
        )
    return claims


def _expected_aggregate_for(claims: Sequence[Mapping[str, object]]) -> JsonDict:
    total_claims = len(claims)
    claims_with_citation = sum(
        1
        for claim in claims
        if isinstance(claim.get("citation_ids"), list) and len(claim["citation_ids"]) > 0
    )
    return {
        "total_claims": total_claims,
        "claims_with_citation": claims_with_citation,
        "coverage_ratio": claims_with_citation / total_claims if total_claims else 0.0,
    }


# Sentinel values for synthetic fixture construction.
#
# ``_AUTO`` — default placeholder; the helper computes ``expected_aggregate``
# from the supplied ``sample_claims`` so happy-path tests don't have to
# duplicate the calculation.
# ``OMIT_EXPECTED_AGGREGATE`` — public sentinel that asks the helper to omit
# the ``expected_aggregate`` field entirely (used to verify the
# "missing" spec violation).
_AUTO: Final[object] = object()
OMIT_EXPECTED_AGGREGATE: Final[object] = object()


def _synthetic_raw_json(
    *,
    fixture_id: str,
    kpi_id: str,
    metric_key: str,
    fixture_kind: FixtureKind,
    case_key: str,
    sample_claims: list[JsonDict] | None,
    expected_aggregate: object,
    threshold_value: float = 0.9,
) -> JsonDict:
    payload: JsonDict = {
        "fixture_id": fixture_id,
        "dataset_version_id": "v2026.05.09-synthetic",
        "fixture_kind": fixture_kind,
        "kpi_id": kpi_id,
        "metric_key": metric_key,
        "case_key": case_key,
        "input": {
            "dataset_version": "v2026.05.09-synthetic",
            "evidence_set_hash": "synthetic-hash",
            "sample_claims": sample_claims if sample_claims is not None else [],
        },
        "threshold": {"operator": AC_KPI_04_THRESHOLD_OPERATOR, "value": threshold_value},
        "assertions": [
            {
                "name": "synthetic_coverage_assert",
                "expected": "deterministic",
            }
        ],
        "anti_gaming": {
            "private_expectation_visible_to_policy_author": False,
            "append_only_refresh": True,
            "separate_fixture_and_policy_commits": True,
        },
        "metadata": {"rls_ready": True, "synthetic": True},
    }
    if expected_aggregate is not OMIT_EXPECTED_AGGREGATE:
        payload["expected_aggregate"] = expected_aggregate  # type: ignore[assignment]
    return payload


def _synthetic_fixture(
    *,
    fixture_id: str = "AC-KPI-04_v2026.05.09-synthetic_default",
    kpi_id: str = "AC-KPI-04",
    metric_key: str = "citation_coverage",
    fixture_kind: FixtureKind = "public_regression",
    case_key: str = "synthetic_case",
    sample_claims: list[JsonDict] | None = None,
    expected_aggregate: object = _AUTO,
    threshold_value: float = 0.9,
) -> Fixture:
    if sample_claims is None:
        sample_claims = _sample_claims(total=5, with_citation=3, prefix=case_key)
    if expected_aggregate is _AUTO:
        expected_aggregate = _expected_aggregate_for(sample_claims)

    raw_json = _synthetic_raw_json(
        fixture_id=fixture_id,
        kpi_id=kpi_id,
        metric_key=metric_key,
        fixture_kind=fixture_kind,
        case_key=case_key,
        sample_claims=sample_claims,
        expected_aggregate=expected_aggregate,
        threshold_value=threshold_value,
    )

    # Mirror the generic loader's split semantics: expectation-style keys go to
    # ``expected_json``, everything else stays in ``case_json``.
    expectation_keys = {"expected_aggregate", "threshold", "assertions"}
    expected_json: JsonDict = {
        key: raw_json[key] for key in expectation_keys if key in raw_json
    }
    case_json: JsonDict = {key: value for key, value in raw_json.items() if key not in expectation_keys}

    return Fixture(
        fixture_id=fixture_id,
        dataset_version_id="v2026.05.09-synthetic",
        fixture_kind=fixture_kind,
        gate_id=None,
        metric_key=metric_key,
        case_key=case_key,
        case_json=case_json,
        expected_json=expected_json,
        metadata={"rls_ready": True, "synthetic": True},
        anti_gaming=raw_json["anti_gaming"],
        source_path=Path("synthetic/citation_coverage_fixture.json"),
        raw_json=raw_json,
        kpi_id=kpi_id,
    )


_VALID_MANIFEST: Final[JsonDict] = {
    "kpi_id": EXPECTED_AC_KPI_04_KPI_ID,
    "metric": EXPECTED_AC_KPI_04_METRIC_KEY,
    "threshold": {
        "operator": EXPECTED_AC_KPI_04_THRESHOLD_OPERATOR,
        "value": EXPECTED_AC_KPI_04_THRESHOLD,
    },
}


def _synthetic_corpus(
    fixtures: Sequence[Fixture],
    *,
    manifest: JsonDict | None = None,
) -> LoadedCorpus:
    return LoadedCorpus(
        dataset_key="citation_coverage",
        version="v2026.05.09-synthetic",
        content_hash="0" * 64,
        manifest=manifest if manifest is not None else dict(_VALID_MANIFEST),
        expected_schema={},
        fixtures=tuple(fixtures),
    )


# ---------------------------------------------------------------------------
# 5+ source enum integrity
# ---------------------------------------------------------------------------


def test_ac_kpi_04_constants_match_test_layer_expected_constants() -> None:
    assert AC_KPI_04_KPI_ID == EXPECTED_AC_KPI_04_KPI_ID
    assert AC_KPI_04_METRIC_KEY == EXPECTED_AC_KPI_04_METRIC_KEY
    assert AC_KPI_04_THRESHOLD_OPERATOR == EXPECTED_AC_KPI_04_THRESHOLD_OPERATOR
    assert AC_KPI_04_THRESHOLD == EXPECTED_AC_KPI_04_THRESHOLD


def test_ac_kpi_04_constants_are_exported_from_module_all() -> None:
    exported = set(citation_coverage.__all__)
    assert {
        "AC_KPI_04_KPI_ID",
        "AC_KPI_04_METRIC_KEY",
        "AC_KPI_04_THRESHOLD",
        "AC_KPI_04_THRESHOLD_OPERATOR",
        "CitationCoverageFixtureResult",
        "CitationCoverageMetricResult",
        "ClaimCoverageEntry",
        "evaluate_citation_coverage",
    } <= exported


def test_ac_kpi_04_constants_match_live_manifest_values() -> None:
    manifest = _read_json(MANIFEST_PATH)
    assert manifest["kpi_id"] == AC_KPI_04_KPI_ID
    assert manifest["metric"] == AC_KPI_04_METRIC_KEY
    threshold = manifest["threshold"]
    assert isinstance(threshold, dict)
    assert threshold["operator"] == AC_KPI_04_THRESHOLD_OPERATOR
    assert threshold["value"] == pytest.approx(AC_KPI_04_THRESHOLD)


def test_live_fixture_envelope_uses_expected_constants() -> None:
    corpus = _load_corpus()
    assert len(corpus.fixtures) == EXPECTED_FIXTURE_COUNT
    fixture = corpus.fixtures[0]
    assert fixture.kpi_id == AC_KPI_04_KPI_ID
    assert fixture.metric_key == AC_KPI_04_METRIC_KEY
    assert fixture.fixture_kind == "public_regression"


# ---------------------------------------------------------------------------
# Happy path against the live corpus
# ---------------------------------------------------------------------------


def test_evaluate_citation_coverage_happy_path_uses_loaded_corpus() -> None:
    corpus = _load_corpus()

    result = evaluate_citation_coverage(corpus)

    assert result.fixture_count == EXPECTED_FIXTURE_COUNT
    assert result.total_claims_across_corpus == EXPECTED_SAMPLE_TOTAL_CLAIMS
    assert result.claims_with_citation_across_corpus == EXPECTED_SAMPLE_CLAIMS_WITH_CITATION
    assert result.metric_value == pytest.approx(EXPECTED_SAMPLE_COVERAGE_RATIO)
    assert result.threshold == AC_KPI_04_THRESHOLD
    assert result.threshold_operator == AC_KPI_04_THRESHOLD_OPERATOR
    assert result.threshold_met is False  # 0.6 < 0.9
    assert result.threshold_reason == "below_threshold"
    assert result.manifest_violation_reason is None
    assert result.pass_count == EXPECTED_FIXTURE_COUNT  # spec-compliant despite below threshold
    assert result.fail_count == 0
    assert all(per_fixture.spec_violation_reason is None for per_fixture in result.per_fixture)


def test_live_fixture_recomputed_ratio_matches_expected_aggregate() -> None:
    corpus = _load_corpus()
    result = evaluate_citation_coverage(corpus)

    per_fixture = result.per_fixture[0]
    assert per_fixture.recomputed_coverage_ratio == pytest.approx(EXPECTED_SAMPLE_COVERAGE_RATIO)
    assert per_fixture.expected_coverage_ratio == pytest.approx(EXPECTED_SAMPLE_COVERAGE_RATIO)
    assert per_fixture.total_claims == EXPECTED_SAMPLE_TOTAL_CLAIMS
    assert per_fixture.claims_with_citation == EXPECTED_SAMPLE_CLAIMS_WITH_CITATION


# ---------------------------------------------------------------------------
# Manifest-level drift detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("override", "expected_reason"),
    (
        ({"kpi_id": "AC-KPI-99"}, "manifest_violation:kpi_id"),
        ({"metric": "wrong_metric"}, "manifest_violation:metric"),
        ({"threshold": "not-a-dict"}, "manifest_violation:threshold"),
        (
            {"threshold": {"operator": "<", "value": EXPECTED_AC_KPI_04_THRESHOLD}},
            "manifest_violation:threshold_operator",
        ),
        (
            {"threshold": {"operator": ">=", "value": "nine-tenths"}},
            "manifest_violation:threshold_value",
        ),
        (
            {"threshold": {"operator": ">=", "value": 0.5}},
            "manifest_violation:threshold_value",
        ),
    ),
)
def test_manifest_drift_breaks_the_gate(override: JsonDict, expected_reason: str) -> None:
    manifest = dict(_VALID_MANIFEST)
    manifest.update(override)
    corpus = _synthetic_corpus(
        fixtures=[_synthetic_fixture()],
        manifest=manifest,
    )

    result = evaluate_citation_coverage(corpus)

    assert result.threshold_met is False
    assert result.threshold_reason == "manifest_violation"
    assert result.manifest_violation_reason == expected_reason


# ---------------------------------------------------------------------------
# Per-fixture spec violations
# ---------------------------------------------------------------------------


def _result_for(fixture: Fixture) -> tuple[CitationCoverageMetricResult, CitationCoverageFixtureResult]:
    corpus = _synthetic_corpus([fixture])
    result = evaluate_citation_coverage(corpus)
    assert result.fixture_count == 1
    return result, result.per_fixture[0]


def test_envelope_violation_kpi_id_is_detected() -> None:
    result, per_fixture = _result_for(_synthetic_fixture(kpi_id="AC-KPI-99"))
    assert per_fixture.spec_violation_reason == "spec_violation:kpi_id"
    assert result.threshold_reason == "spec_violation"


def test_envelope_violation_metric_key_is_detected() -> None:
    result, per_fixture = _result_for(_synthetic_fixture(metric_key="wrong_metric"))
    assert per_fixture.spec_violation_reason == "spec_violation:metric_key"
    assert result.threshold_reason == "spec_violation"


def test_non_public_fixture_kind_is_skipped() -> None:
    """Redacted splits are deferred to SP-022+, so they must be skipped.

    The aggregator scope for batch 5d is ``public_regression`` only; the
    encrypted-holdout decryption path is BL-0127b / SP-022+ work. Skipped
    fixtures contribute neither pass nor fail counts.
    """

    corpus = _synthetic_corpus([_synthetic_fixture(fixture_kind="private_holdout")])
    result = evaluate_citation_coverage(corpus)

    assert result.fixture_count == 0
    assert result.pass_count == 0
    assert result.fail_count == 0
    assert result.per_fixture == ()
    assert result.threshold_reason == "no_fixtures"


def test_expected_aggregate_missing_is_detected() -> None:
    fixture = _synthetic_fixture(expected_aggregate=OMIT_EXPECTED_AGGREGATE)
    result, per_fixture = _result_for(fixture)
    assert per_fixture.spec_violation_reason == "spec_violation:expected_aggregate_missing"
    assert result.threshold_reason == "spec_violation"


def test_expected_aggregate_malformed_is_detected() -> None:
    fixture = _synthetic_fixture(expected_aggregate="not-a-dict")
    result, per_fixture = _result_for(fixture)
    assert per_fixture.spec_violation_reason == "spec_violation:expected_aggregate"
    assert result.threshold_reason == "spec_violation"


def test_expected_aggregate_drift_is_detected() -> None:
    sample_claims = _sample_claims(total=5, with_citation=3, prefix="drift")
    # Real ratio = 0.6, but the fixture declares 0.8 → drift.
    fixture = _synthetic_fixture(
        sample_claims=sample_claims,
        expected_aggregate={
            "total_claims": 5,
            "claims_with_citation": 3,
            "coverage_ratio": 0.8,
        },
    )
    result, per_fixture = _result_for(fixture)
    assert per_fixture.spec_violation_reason == "spec_violation:expected_aggregate_drift"
    assert per_fixture.recomputed_coverage_ratio == pytest.approx(0.6)
    assert per_fixture.expected_coverage_ratio == pytest.approx(0.8)
    assert result.threshold_reason == "spec_violation"


def test_no_claims_is_detected() -> None:
    fixture = _synthetic_fixture(sample_claims=[], expected_aggregate={"coverage_ratio": 0.0})
    result, per_fixture = _result_for(fixture)
    assert per_fixture.spec_violation_reason == "spec_violation:no_claims"
    assert per_fixture.total_claims == 0
    assert result.threshold_reason == "spec_violation"


def test_duplicate_claim_id_is_detected() -> None:
    claims = _sample_claims(total=3, with_citation=2, prefix="dup")
    claims[1]["claim_id"] = claims[0]["claim_id"]
    fixture = _synthetic_fixture(sample_claims=claims)
    _, per_fixture = _result_for(fixture)
    assert per_fixture.spec_violation_reason == "spec_violation:duplicate_claim_id"


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    (
        ({"sample_claims": "not-a-list"}, "spec_violation:sample_claims"),
        ({"sample_claims": ["not-a-dict"]}, "spec_violation:sample_claims"),
    ),
)
def test_malformed_sample_claims_payload_is_detected(
    mutation: JsonDict, expected_reason: str
) -> None:
    fixture = _synthetic_fixture()
    raw_input: dict[str, Any] = dict(fixture.case_json["input"])  # type: ignore[arg-type]
    raw_input.update(mutation)
    mutated_case_json = dict(fixture.case_json)
    mutated_case_json["input"] = raw_input
    mutated_raw_json = dict(fixture.raw_json)
    mutated_raw_json["input"] = raw_input
    rebuilt = Fixture(
        fixture_id=fixture.fixture_id,
        dataset_version_id=fixture.dataset_version_id,
        fixture_kind=fixture.fixture_kind,
        gate_id=fixture.gate_id,
        metric_key=fixture.metric_key,
        case_key=fixture.case_key,
        case_json=mutated_case_json,
        expected_json=fixture.expected_json,
        metadata=fixture.metadata,
        anti_gaming=fixture.anti_gaming,
        source_path=fixture.source_path,
        raw_json=mutated_raw_json,
        kpi_id=fixture.kpi_id,
    )
    _, per_fixture = _result_for(rebuilt)
    assert per_fixture.spec_violation_reason == expected_reason


def test_malformed_claim_id_is_detected() -> None:
    claims = _sample_claims(total=2, with_citation=1, prefix="bad")
    claims[0]["claim_id"] = ""
    fixture = _synthetic_fixture(sample_claims=claims)
    _, per_fixture = _result_for(fixture)
    assert per_fixture.spec_violation_reason == "spec_violation:claim_id"


def test_malformed_citation_ids_is_detected() -> None:
    claims = _sample_claims(total=2, with_citation=1, prefix="bad")
    claims[0]["citation_ids"] = ["", None]  # type: ignore[list-item]
    fixture = _synthetic_fixture(sample_claims=claims)
    _, per_fixture = _result_for(fixture)
    assert per_fixture.spec_violation_reason == "spec_violation:citation_ids"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_corpus_yields_no_fixtures_reason() -> None:
    result = evaluate_citation_coverage(_synthetic_corpus([]))
    assert result.fixture_count == 0
    assert result.metric_value == 0.0
    assert result.threshold_met is False
    assert result.threshold_reason == "no_fixtures"


def test_weighted_average_across_two_fixtures() -> None:
    fixture_small = _synthetic_fixture(
        fixture_id="AC-KPI-04_synthetic_small",
        case_key="small",
        sample_claims=_sample_claims(total=5, with_citation=3, prefix="small"),
    )
    fixture_large = _synthetic_fixture(
        fixture_id="AC-KPI-04_synthetic_large",
        case_key="large",
        sample_claims=_sample_claims(total=10, with_citation=9, prefix="large"),
    )

    result = evaluate_citation_coverage(_synthetic_corpus([fixture_small, fixture_large]))

    assert result.fixture_count == 2
    assert result.total_claims_across_corpus == 15
    assert result.claims_with_citation_across_corpus == 12
    # Weighted average = 12 / 15 = 0.8, NOT (0.6 + 0.9) / 2 = 0.75.
    assert result.metric_value == pytest.approx(12 / 15)
    assert result.threshold_met is False  # 0.8 < 0.9


def test_threshold_met_when_metric_at_or_above_threshold() -> None:
    fixture = _synthetic_fixture(
        sample_claims=_sample_claims(total=10, with_citation=10, prefix="full"),
    )
    result = evaluate_citation_coverage(_synthetic_corpus([fixture]))
    assert result.metric_value == pytest.approx(1.0)
    assert result.threshold_met is True
    assert result.threshold_reason == "threshold_met"


# ---------------------------------------------------------------------------
# SUT result integration (forward-compat for BL-0127b / SP-012)
# ---------------------------------------------------------------------------


def test_sut_results_all_true_passes() -> None:
    fixture = _synthetic_fixture()
    result = evaluate_citation_coverage(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: True},
    )
    per_fixture = result.per_fixture[0]
    assert per_fixture.passed is True
    assert per_fixture.sut_result is True
    assert per_fixture.spec_violation_reason is None


def test_sut_results_all_false_marks_failure() -> None:
    fixture = _synthetic_fixture()
    result = evaluate_citation_coverage(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: False},
    )
    per_fixture = result.per_fixture[0]
    assert per_fixture.passed is False
    assert per_fixture.sut_result is False
    # ``spec_violation_reason`` stays ``None`` because the spec is satisfied;
    # the failure source is the SUT result itself.
    assert per_fixture.spec_violation_reason is None
    assert result.fail_count == 1


def test_sut_results_missing_fixture_id_marks_failure() -> None:
    fixture = _synthetic_fixture()
    result = evaluate_citation_coverage(
        _synthetic_corpus([fixture]),
        sut_results={},
    )
    per_fixture = result.per_fixture[0]
    assert per_fixture.passed is False
    assert per_fixture.sut_result is None
    assert per_fixture.spec_violation_reason == "sut_result_missing"


@pytest.mark.parametrize(
    "raw_sut_value",
    ("true", 1, 0, [], {"value": True}, None),
)
def test_non_boolean_sut_result_is_rejected(raw_sut_value: object) -> None:
    fixture = _synthetic_fixture()
    result = evaluate_citation_coverage(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: raw_sut_value},  # type: ignore[dict-item]
    )
    per_fixture = result.per_fixture[0]
    assert per_fixture.passed is False
    assert per_fixture.sut_result is None
    assert per_fixture.spec_violation_reason == "sut_result_invalid_type"


# ---------------------------------------------------------------------------
# Anti-Gaming raw-content non-leakage
# ---------------------------------------------------------------------------


def test_spec_violation_reason_does_not_embed_claim_text() -> None:
    sensitive = "anti-gaming-canary-must-not-leak"
    fixture = _synthetic_fixture(
        sample_claims=_sample_claims(
            total=3,
            with_citation=2,
            prefix="leak",
            claim_text=sensitive,
        ),
        expected_aggregate={
            "total_claims": 3,
            "claims_with_citation": 2,
            "coverage_ratio": 0.99,  # forces drift
        },
    )
    result, per_fixture = _result_for(fixture)
    assert per_fixture.spec_violation_reason == "spec_violation:expected_aggregate_drift"
    assert per_fixture.spec_violation_reason is not None
    assert sensitive not in per_fixture.spec_violation_reason
    # Also verify the dataclass repr does not leak the marker.
    assert sensitive not in repr(result)


def test_claim_coverage_entry_dataclass_is_frozen() -> None:
    """``ClaimCoverageEntry`` is a frozen dataclass — mutation must fail."""

    entry = ClaimCoverageEntry(claim_id="c-001", has_citation=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.claim_id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Live regression: synthetic corpus + live corpus mix
# ---------------------------------------------------------------------------


def test_live_corpus_round_trip_via_recomputation_matches_loader_classification() -> None:
    """Recompute coverage from raw_json directly to assert loader fidelity."""

    corpus = _load_corpus()
    fixture = corpus.fixtures[0]
    raw_input = fixture.raw_json["input"]
    assert isinstance(raw_input, dict)
    sample_claims = raw_input["sample_claims"]
    assert isinstance(sample_claims, list)
    aggregator_result = evaluate_citation_coverage(corpus)
    naive_recompute = sum(
        1 for claim in sample_claims if isinstance(claim, dict) and len(claim.get("citation_ids") or []) > 0
    ) / max(len(sample_claims), 1)
    assert aggregator_result.metric_value == pytest.approx(naive_recompute)


def test_live_corpus_immutable_against_synthetic_mutation(tmp_path: Path) -> None:
    """Mutating a copy of the fixture should never affect the live load.

    Anti-Gaming defense: the loader's tamper detection should keep the live
    corpus deterministic across runs. This test mutates a *copy* and confirms
    the live ``_load_corpus()`` continues to produce the same metric.
    """

    corpus = _load_corpus()
    snapshot_metric = evaluate_citation_coverage(corpus).metric_value

    fixture = corpus.fixtures[0]
    mutated_raw = copy.deepcopy(fixture.raw_json)
    mutated_raw["expected_aggregate"]["coverage_ratio"] = 0.99  # type: ignore[index]
    # Write the mutated copy to a temporary location to assert no shared state.
    (tmp_path / "mutated_fixture.json").write_text(json.dumps(mutated_raw), encoding="utf-8")

    refreshed = evaluate_citation_coverage(_load_corpus())
    assert refreshed.metric_value == pytest.approx(snapshot_metric)
