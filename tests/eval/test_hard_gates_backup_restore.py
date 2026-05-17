"""Tests for the AC-HARD-04 backup_restore_rpo_rto aggregator skeleton.

Covers:
* 5+ source enum integrity (5 sources, plan v2 §3)
* Live happy path on the Sprint 0 era skeleton fixture
* Anti-Gaming defenses (15 defenses, plan v2 §6)
* Manifest drift detection
* Per-fixture spec violations (envelope / RPO / RTO / PITR / checksum /
  drill_kind / encrypted / isolated / sha256 / anti_gaming /
  payload_data_class)
* Required drill_kind coverage tracking
* SUT integration (forward-compat for Sprint 11.5 BL-0159b)
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, Literal

import pytest

from backend.app.db.models.base import JsonDict
from backend.app.db.models.dataset_version import FixtureKind
from backend.app.services.eval.hard_gates import backup_restore
from backend.app.services.eval.hard_gates.backup_restore import (
    AC_HARD_04_FUTURE_REQUIRED_DRILL_KINDS,
    AC_HARD_04_GATE_ID,
    AC_HARD_04_METRIC_KEY,
    AC_HARD_04_PATTERN_HIT_KIND,
    AC_HARD_04_REQUIRED_CHECKSUM_ALGORITHM,
    AC_HARD_04_REQUIRED_DRILL_KINDS_SKELETON,
    AC_HARD_04_RPO_HOURS_MAX,
    AC_HARD_04_RTO_HOURS_MAX,
    AC_HARD_04_THRESHOLD,
    BackupRestoreFixtureResult,
    BackupRestoreMetricResult,
    evaluate_backup_restore_rpo_rto,
)
from backend.app.services.eval.loader import Fixture, LoadedCorpus, load_fixture_corpus

_REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = _REPO_ROOT / "eval/ops/backup_restore"
MANIFEST_PATH = BASE_PATH / "manifest.json"
SCHEMA_PATH = BASE_PATH / "expected_schema.json"

EXPECTED_AC_HARD_04_GATE_ID: Final[Literal["AC-HARD-04"]] = "AC-HARD-04"
EXPECTED_AC_HARD_04_METRIC_KEY: Final[Literal["backup_restore_rpo_rto"]] = (
    "backup_restore_rpo_rto"
)
EXPECTED_AC_HARD_04_PATTERN_HIT_KIND: Final[Literal["backup_restore"]] = (
    "backup_restore"
)
EXPECTED_AC_HARD_04_RPO_HOURS_MAX: Final[float] = 24.0
EXPECTED_AC_HARD_04_RTO_HOURS_MAX: Final[float] = 4.0
EXPECTED_AC_HARD_04_THRESHOLD: Final[float] = 1.0
EXPECTED_AC_HARD_04_REQUIRED_CHECKSUM_ALGORITHM: Final[Literal["sha256"]] = "sha256"

EXPECTED_KNOWN_DRILL_KINDS: Final[frozenset[str]] = frozenset(
    {"dev_restore", "private_staging_restore", "pitr"}
)
EXPECTED_REQUIRED_DRILL_KINDS_SKELETON: Final[frozenset[str]] = frozenset(
    {"dev_restore"}
)
EXPECTED_FUTURE_REQUIRED_DRILL_KINDS: Final[frozenset[str]] = frozenset(
    {"dev_restore", "private_staging_restore", "pitr"}
)
EXPECTED_ALLOWED_PAYLOAD_DATA_CLASSES: Final[frozenset[str]] = frozenset(
    {"public", "internal"}
)


def _load_corpus() -> LoadedCorpus:
    return load_fixture_corpus(BASE_PATH, dataset_key="backup_restore_rpo_rto")


def _read_json(path: Path) -> JsonDict:
    return json.loads(path.read_text(encoding="utf-8"))


def _synthetic_raw_json(
    *,
    fixture_id: str = "AC-HARD-04_v2026.05.17-synthetic_default",
    gate_id: str = "AC-HARD-04",
    metric_key: str = "backup_restore_rpo_rto",
    fixture_kind: FixtureKind = "public_regression",
    case_key: str = "synthetic_case",
    drill_kind: str = "dev_restore",
    backup_encrypted: bool = True,
    restore_isolated: bool = True,
    checksum_algorithm: str = "sha256",
    expected_decision: str = "pass",
    expected_rpo_hours_max: float = 24.0,
    expected_rto_hours_max: float = 4.0,
    expected_pitr_success: bool = True,
    expected_checksum_match: bool = True,
    pattern_hit_kind: str = "backup_restore",
    anti_gaming_overrides: Mapping[str, object] | None = None,
    metadata_overrides: Mapping[str, object] | None = None,
) -> JsonDict:
    anti_gaming: JsonDict = {
        "private_expectation_visible_to_policy_author": False,
        "append_only_refresh": True,
        "separate_fixture_and_policy_commits": True,
    }
    if anti_gaming_overrides:
        anti_gaming.update(anti_gaming_overrides)
    metadata: JsonDict = {
        "policy_version": "policy-fixture-v0",
        "prompt_pack_version": "prompt-pack-fixture-v0",
        "provider_compliance_matrix_version": "provider-matrix-fixture-v0",
        "payload_data_class": "internal",
        "allowed_data_class": "internal",
        "created_at": "2026-05-17",
        "notes": "synthetic test fixture",
    }
    if metadata_overrides:
        metadata.update(metadata_overrides)
    return {
        "fixture_id": fixture_id,
        "dataset_version_id": "v2026.05.17-synthetic",
        "fixture_kind": fixture_kind,
        "gate_id": gate_id,
        "metric_key": metric_key,
        "case_key": case_key,
        "input": {
            "drill_kind": drill_kind,
            "database_scope": "dev",
            "backup_artifact": {
                "artifact_ref": "backup-artifact:synthetic",
                "encrypted": backup_encrypted,
                "created_at_offset_hours": 6,
            },
            "restore_target": {
                "target_ref": "restore-target:synthetic",
                "isolated": restore_isolated,
            },
            "checksum": {
                "algorithm": checksum_algorithm,
                "expected_source_hash_ref": "checksum-ref:source",
                "expected_restored_hash_ref": "checksum-ref:restored",
            },
        },
        "expected_decision": expected_decision,
        "expected_rpo_hours_max": expected_rpo_hours_max,
        "expected_rto_hours_max": expected_rto_hours_max,
        "expected_pitr_success": expected_pitr_success,
        "expected_checksum_match": expected_checksum_match,
        "pattern_hit_kind": pattern_hit_kind,
        "assertions": [
            {
                "name": "synthetic_assert",
                "expected": "deterministic",
            }
        ],
        "anti_gaming": anti_gaming,
        "metadata": metadata,
    }


def _synthetic_fixture(
    *,
    fixture_id: str = "AC-HARD-04_v2026.05.17-synthetic_default",
    **kwargs: object,
) -> Fixture:
    raw_json = _synthetic_raw_json(fixture_id=fixture_id, **kwargs)  # type: ignore[arg-type]
    expectation_keys = {
        "expected_decision",
        "expected_rpo_hours_max",
        "expected_rto_hours_max",
        "expected_pitr_success",
        "expected_checksum_match",
        "pattern_hit_kind",
        "assertions",
    }
    expected_json: JsonDict = {
        key: raw_json[key] for key in expectation_keys if key in raw_json
    }
    case_json: JsonDict = {
        key: value for key, value in raw_json.items() if key not in expectation_keys
    }
    return Fixture(
        fixture_id=fixture_id,
        dataset_version_id="v2026.05.17-synthetic",
        fixture_kind=raw_json["fixture_kind"],  # type: ignore[arg-type]
        gate_id=raw_json["gate_id"],  # type: ignore[arg-type]
        metric_key=raw_json["metric_key"],  # type: ignore[arg-type]
        case_key=raw_json["case_key"],  # type: ignore[arg-type]
        case_json=case_json,
        expected_json=expected_json,
        metadata=raw_json["metadata"],  # type: ignore[arg-type]
        anti_gaming=raw_json["anti_gaming"],  # type: ignore[arg-type]
        source_path=Path("synthetic/backup_restore.json"),
        raw_json=raw_json,
        kpi_id=None,
    )


_VALID_MANIFEST: Final[JsonDict] = {
    "hard_gate_id": EXPECTED_AC_HARD_04_GATE_ID,
    "metric": EXPECTED_AC_HARD_04_METRIC_KEY,
    "dataset_version": "v2026.05.17-synthetic",
    "splits": {
        "public_regression": {"path": "public_regression/", "expected_count": 1},
    },
}


def _synthetic_corpus(
    fixtures: Sequence[Fixture],
    *,
    manifest: JsonDict | None = None,
) -> LoadedCorpus:
    return LoadedCorpus(
        dataset_key="backup_restore_rpo_rto",
        version="v2026.05.17-synthetic",
        content_hash="0" * 64,
        manifest=manifest if manifest is not None else dict(_VALID_MANIFEST),
        expected_schema={},
        fixtures=tuple(fixtures),
    )


def _result_for(
    fixture: Fixture,
) -> tuple[BackupRestoreMetricResult, BackupRestoreFixtureResult]:
    corpus = _synthetic_corpus([fixture])
    result = evaluate_backup_restore_rpo_rto(corpus)
    assert result.fixture_count == 1
    return result, result.per_fixture[0]


# ---------------------------------------------------------------------------
# 5+ source enum integrity (5 tests, plan v2 §7.1)
# ---------------------------------------------------------------------------


def test_ac_hard_04_constants_match() -> None:
    assert AC_HARD_04_GATE_ID == EXPECTED_AC_HARD_04_GATE_ID
    assert AC_HARD_04_METRIC_KEY == EXPECTED_AC_HARD_04_METRIC_KEY
    assert AC_HARD_04_PATTERN_HIT_KIND == EXPECTED_AC_HARD_04_PATTERN_HIT_KIND
    assert AC_HARD_04_RPO_HOURS_MAX == EXPECTED_AC_HARD_04_RPO_HOURS_MAX
    assert AC_HARD_04_RTO_HOURS_MAX == EXPECTED_AC_HARD_04_RTO_HOURS_MAX
    assert AC_HARD_04_THRESHOLD == EXPECTED_AC_HARD_04_THRESHOLD
    assert (
        AC_HARD_04_REQUIRED_CHECKSUM_ALGORITHM
        == EXPECTED_AC_HARD_04_REQUIRED_CHECKSUM_ALGORITHM
    )


def test_ac_hard_04_constants_are_exported_from_module_all() -> None:
    expected = {
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
    }
    assert expected <= set(backup_restore.__all__)


def test_fixture_schema_drill_kind_enum_matches_known_set() -> None:
    schema = _read_json(SCHEMA_PATH)
    enum_values = (
        schema["properties"]["input"]["properties"]["drill_kind"]["enum"]
    )
    assert frozenset(enum_values) == EXPECTED_KNOWN_DRILL_KINDS


def test_skeleton_required_drill_kinds_is_proper_subset_of_future() -> None:
    assert (
        AC_HARD_04_REQUIRED_DRILL_KINDS_SKELETON
        < AC_HARD_04_FUTURE_REQUIRED_DRILL_KINDS
    )


def test_future_required_drill_kinds_is_subset_of_known() -> None:
    assert (
        AC_HARD_04_FUTURE_REQUIRED_DRILL_KINDS
        == EXPECTED_FUTURE_REQUIRED_DRILL_KINDS
    )
    assert (
        AC_HARD_04_FUTURE_REQUIRED_DRILL_KINDS
        <= backup_restore._KNOWN_DRILL_KINDS
    )


# ---------------------------------------------------------------------------
# Live happy path (2 tests, plan v2 §7.2)
# ---------------------------------------------------------------------------


def test_live_skeleton_fixture_passes_hard_gate() -> None:
    corpus = _load_corpus()
    result = evaluate_backup_restore_rpo_rto(corpus)
    assert result.fixture_count == 1
    assert result.manifest_violation_reason is None
    assert result.pass_count == 1
    assert result.fail_count == 0
    assert result.metric_value == pytest.approx(1.0)
    assert result.threshold_met is True
    assert result.threshold_reason == "threshold_met"
    assert result.missing_drill_kinds == ()


def test_activation_mode_via_env_requires_three_drill_kinds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sprint 11.5 batch 3a (BL-0159b activation、ADR-00026 §3 採用):
    env `TASKMANAGEDAI_AC_HARD_04_MODE=activation` で 3 drill_kinds 必須 mode に切替.
    """

    monkeypatch.setenv("TASKMANAGEDAI_AC_HARD_04_MODE", "activation")

    from backend.app.services.eval.hard_gates.backup_restore import (
        AC_HARD_04_ACTIVATED_REQUIRED_DRILL_KINDS,
        AC_HARD_04_VALID_ACTIVATION_MODES,
        _resolve_required_drill_kinds,
    )

    required = _resolve_required_drill_kinds()
    assert required == AC_HARD_04_ACTIVATED_REQUIRED_DRILL_KINDS
    assert required == frozenset({"dev_restore", "private_staging_restore", "pitr"})
    assert AC_HARD_04_VALID_ACTIVATION_MODES == frozenset({"skeleton", "activation"})


def test_activation_mode_default_is_skeleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """env 未設定 default は skeleton mode (既存挙動維持、Sprint 11 backward-compat)."""

    monkeypatch.delenv("TASKMANAGEDAI_AC_HARD_04_MODE", raising=False)

    from backend.app.services.eval.hard_gates.backup_restore import (
        AC_HARD_04_REQUIRED_DRILL_KINDS_SKELETON,
        _resolve_required_drill_kinds,
    )

    required = _resolve_required_drill_kinds()
    assert required == AC_HARD_04_REQUIRED_DRILL_KINDS_SKELETON


def test_activation_mode_invalid_falls_back_to_skeleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不正値 mode は skeleton fallback (fail safe、AC-HARD-04 hard fail しない)."""

    monkeypatch.setenv("TASKMANAGEDAI_AC_HARD_04_MODE", "bogus_mode_value")

    from backend.app.services.eval.hard_gates.backup_restore import (
        AC_HARD_04_REQUIRED_DRILL_KINDS_SKELETON,
        _resolve_required_drill_kinds,
    )

    required = _resolve_required_drill_kinds()
    assert required == AC_HARD_04_REQUIRED_DRILL_KINDS_SKELETON


def test_skeleton_corpus_requires_only_dev_restore() -> None:
    # Synthetic single-fixture corpus with drill_kind=dev_restore covers
    # the skeleton-required set.
    fixture = _synthetic_fixture(drill_kind="dev_restore")
    result = evaluate_backup_restore_rpo_rto(_synthetic_corpus([fixture]))
    assert result.missing_drill_kinds == ()
    assert result.threshold_met is True


# ---------------------------------------------------------------------------
# Manifest drift (3 parametrize tests, plan v2 §7.3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mutation_key", "mutation_value", "expected_reason"),
    [
        ("hard_gate_id", "AC-HARD-99", "manifest_violation:hard_gate_id"),
        ("metric", "something_else", "manifest_violation:metric"),
        ("dataset_version", "", "manifest_violation:dataset_version"),
        ("dataset_version", None, "manifest_violation:dataset_version"),
    ],
)
def test_manifest_violations_are_detected(
    mutation_key: str, mutation_value: object, expected_reason: str
) -> None:
    manifest = copy.deepcopy(_VALID_MANIFEST)
    manifest[mutation_key] = mutation_value
    fixture = _synthetic_fixture()
    result = evaluate_backup_restore_rpo_rto(
        _synthetic_corpus([fixture], manifest=manifest)
    )
    assert result.manifest_violation_reason == expected_reason
    assert result.threshold_reason == "manifest_violation"


def test_manifest_expected_count_drift_is_detected() -> None:
    """F-PR37-001 adopt: declared ``splits.public_regression.expected_count``
    must match the actual public_regression fixture count.
    """

    # Build a manifest with `splits` that declares expected_count=99
    # while only 1 public_regression fixture is loaded.
    manifest = copy.deepcopy(_VALID_MANIFEST)
    manifest["splits"] = {
        "public_regression": {"path": "public_regression/", "expected_count": 99},
    }
    fixture = _synthetic_fixture()
    result = evaluate_backup_restore_rpo_rto(
        _synthetic_corpus([fixture], manifest=manifest)
    )
    assert (
        result.manifest_violation_reason == "manifest_violation:expected_count"
    )
    assert result.threshold_reason == "manifest_violation"


def test_manifest_expected_count_matches_actual_count_passes() -> None:
    """F-PR37-001 adopt: when declared expected_count matches actual,
    no manifest violation surfaces.
    """

    manifest = copy.deepcopy(_VALID_MANIFEST)
    manifest["splits"] = {
        "public_regression": {"path": "public_regression/", "expected_count": 1},
    }
    fixture = _synthetic_fixture()
    result = evaluate_backup_restore_rpo_rto(
        _synthetic_corpus([fixture], manifest=manifest)
    )
    assert result.manifest_violation_reason is None
    assert result.threshold_met is True


def test_manifest_splits_missing_is_rejected() -> None:
    """F-PR37-001 adopt: malformed manifest without `splits` rejects."""

    manifest = copy.deepcopy(_VALID_MANIFEST)
    # _VALID_MANIFEST does not include splits; create a malformed one
    manifest["splits"] = "not a dict"  # type: ignore[assignment]
    fixture = _synthetic_fixture()
    result = evaluate_backup_restore_rpo_rto(
        _synthetic_corpus([fixture], manifest=manifest)
    )
    assert result.manifest_violation_reason == "manifest_violation:splits"


# ---------------------------------------------------------------------------
# Per-fixture spec violations (16 tests, plan v2 §7.4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "bad_value", "expected_reason"),
    [
        ("gate_id", "AC-HARD-99", "spec_violation:gate_id"),
        ("metric_key", "wrong_metric", "spec_violation:metric_key"),
        ("fixture_kind", "private_holdout", None),  # skipped, not violation
    ],
)
def test_envelope_top_level_drift_is_detected(
    field: str, bad_value: str, expected_reason: str | None
) -> None:
    fixture = _synthetic_fixture(**{field: bad_value})  # type: ignore[arg-type]
    result = evaluate_backup_restore_rpo_rto(_synthetic_corpus([fixture]))
    if expected_reason is None:
        # private_holdout fixtures are silently skipped (defense #13)
        assert result.fixture_count == 0
        assert result.threshold_reason == "no_fixtures"
    else:
        assert result.per_fixture[0].spec_violation_reason == expected_reason


def test_expected_decision_drift_is_detected() -> None:
    fixture = _synthetic_fixture(expected_decision="block")
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_decision"


def test_pattern_hit_kind_drift_is_detected() -> None:
    fixture = _synthetic_fixture(pattern_hit_kind="something_else")
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:pattern_hit_kind"


def test_expected_rpo_hours_max_exceeding_24_is_rejected() -> None:
    fixture = _synthetic_fixture(expected_rpo_hours_max=25.0)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_rpo_hours_max"


def test_expected_rto_hours_max_exceeding_4_is_rejected() -> None:
    fixture = _synthetic_fixture(expected_rto_hours_max=5.0)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_rto_hours_max"


def test_expected_pitr_success_false_is_rejected() -> None:
    """Plan v2 §1.1: forward-looking declaration must be True at envelope level."""

    fixture = _synthetic_fixture(expected_pitr_success=False)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_pitr_success"


def test_expected_checksum_match_false_is_rejected() -> None:
    fixture = _synthetic_fixture(expected_checksum_match=False)
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:expected_checksum_match"


def test_unknown_drill_kind_is_rejected() -> None:
    fixture = _synthetic_fixture(drill_kind="unknown_kind")
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:drill_kind"


def test_backup_artifact_encrypted_false_is_rejected() -> None:
    fixture = _synthetic_fixture(backup_encrypted=False)
    _, per = _result_for(fixture)
    assert (
        per.spec_violation_reason == "spec_violation:backup_artifact_encrypted"
    )


def test_restore_target_isolated_false_is_rejected() -> None:
    fixture = _synthetic_fixture(restore_isolated=False)
    _, per = _result_for(fixture)
    assert (
        per.spec_violation_reason == "spec_violation:restore_target_isolated"
    )


def test_checksum_algorithm_non_sha256_is_rejected() -> None:
    fixture = _synthetic_fixture(checksum_algorithm="md5")
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:checksum_algorithm"


def test_anti_gaming_append_only_refresh_false_is_rejected() -> None:
    """MED-1 adopt: fixture-level anti_gaming envelope check."""

    fixture = _synthetic_fixture(
        anti_gaming_overrides={"append_only_refresh": False}
    )
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:anti_gaming"


def test_anti_gaming_separate_commits_false_is_rejected() -> None:
    fixture = _synthetic_fixture(
        anti_gaming_overrides={"separate_fixture_and_policy_commits": False}
    )
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:anti_gaming"


@pytest.mark.parametrize("bad_class", ["confidential", "pii"])
def test_payload_data_class_pii_or_confidential_is_rejected(bad_class: str) -> None:
    """MED-2 adopt: backup descriptors must not carry PII / confidential."""

    fixture = _synthetic_fixture(metadata_overrides={"payload_data_class": bad_class})
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:payload_data_class"


# ---------------------------------------------------------------------------
# Required drill_kinds coverage (3 tests, plan v2 §7.5)
# ---------------------------------------------------------------------------


def test_corpus_missing_dev_restore_reports_missing_drill_kinds() -> None:
    # Skeleton-required is {dev_restore}; provide only private_staging_restore
    fixture = _synthetic_fixture(
        fixture_id="AC-HARD-04_v2026.05.17-synthetic_no_dev_restore",
        drill_kind="private_staging_restore",
    )
    result = evaluate_backup_restore_rpo_rto(_synthetic_corpus([fixture]))
    assert result.missing_drill_kinds == ("dev_restore",)
    assert result.threshold_reason == "missing_drill_kinds"
    assert result.threshold_met is False


def test_spec_violation_fixture_does_not_contribute_to_drill_kind_coverage() -> None:
    """Plan v2 §6 defense #12 carry-over: a spec-violating fixture's
    drill_kind does NOT count toward coverage. With one spec-violating
    fixture that would otherwise cover dev_restore, the coverage
    requirement is still unmet.
    """

    fixture = _synthetic_fixture(
        fixture_id="AC-HARD-04_v2026.05.17-synthetic_spec_violation_dev_restore",
        drill_kind="dev_restore",
        expected_pitr_success=False,  # spec violation
    )
    result = evaluate_backup_restore_rpo_rto(_synthetic_corpus([fixture]))
    assert result.per_fixture[0].spec_violation_reason is not None
    # Priority: spec_violation > missing_drill_kinds (MED-4)
    assert result.threshold_reason == "spec_violation"
    # missing_drill_kinds still reports the gap for downstream visibility
    assert "dev_restore" in result.missing_drill_kinds


def test_corpus_with_all_three_drill_kinds_satisfies_future_required() -> None:
    """Future invariant verification: a 3-fixture corpus covering all
    drill_kinds will satisfy Sprint 11.5 BL-0159b requirement (when
    activated). At skeleton scope it still satisfies the skeleton subset.
    """

    fixtures = [
        _synthetic_fixture(
            fixture_id=f"AC-HARD-04_v2026.05.17-synthetic_{drill_kind}",
            drill_kind=drill_kind,
        )
        for drill_kind in sorted(AC_HARD_04_FUTURE_REQUIRED_DRILL_KINDS)
    ]
    # Multi-fixture corpus: manifest must declare expected_count == 3
    # for the public_regression split (F-PR37-001 carry-over: manifest
    # expected_count strict match).
    manifest = copy.deepcopy(_VALID_MANIFEST)
    manifest["splits"] = {
        "public_regression": {"path": "public_regression/", "expected_count": 3},
    }
    result = evaluate_backup_restore_rpo_rto(
        _synthetic_corpus(fixtures, manifest=manifest)
    )
    assert result.missing_drill_kinds == ()
    assert result.threshold_met is True


# ---------------------------------------------------------------------------
# Edge cases (5 tests, plan v2 §7.6)
# ---------------------------------------------------------------------------


def test_empty_corpus_yields_no_fixtures_reason() -> None:
    result = evaluate_backup_restore_rpo_rto(_synthetic_corpus([]))
    assert result.threshold_reason == "no_fixtures"
    assert result.threshold_met is False
    assert result.metric_value == pytest.approx(0.0)


def test_spec_violation_hard_resets_metric_to_zero() -> None:
    """A single spec-violating fixture gives pass_count=0 → metric=0.0."""

    fixture = _synthetic_fixture(expected_rpo_hours_max=100.0)
    result = evaluate_backup_restore_rpo_rto(_synthetic_corpus([fixture]))
    assert result.metric_value == pytest.approx(0.0)
    assert result.threshold_reason == "spec_violation"
    assert result.threshold_met is False


def test_non_public_regression_fixtures_are_skipped_silently() -> None:
    fixture = _synthetic_fixture(fixture_kind="adversarial_new")
    result = evaluate_backup_restore_rpo_rto(_synthetic_corpus([fixture]))
    # Skipped, not violation
    assert result.fixture_count == 0
    assert result.threshold_reason == "no_fixtures"


def test_priority_spec_violation_wins_over_missing_drill_kinds() -> None:
    """MED-4 adopt: spec_violation > missing_drill_kinds (deeper root cause)."""

    # Two fixtures: one spec-violating (would cover dev_restore but rejected)
    # The other valid but covering private_staging_restore (not skeleton-required)
    fixture_bad = _synthetic_fixture(
        fixture_id="AC-HARD-04_v2026.05.17-synthetic_bad",
        drill_kind="dev_restore",
        expected_pitr_success=False,
    )
    fixture_good_other_kind = _synthetic_fixture(
        fixture_id="AC-HARD-04_v2026.05.17-synthetic_good_pss",
        drill_kind="private_staging_restore",
    )
    # 2-fixture corpus → manifest expected_count == 2 (F-PR37-001)
    manifest = copy.deepcopy(_VALID_MANIFEST)
    manifest["splits"] = {
        "public_regression": {"path": "public_regression/", "expected_count": 2},
    }
    result = evaluate_backup_restore_rpo_rto(
        _synthetic_corpus(
            [fixture_bad, fixture_good_other_kind], manifest=manifest
        )
    )
    # Both conditions present: spec_violation AND missing_drill_kinds
    # Priority surfaces spec_violation.
    assert result.threshold_reason == "spec_violation"


def test_single_passing_fixture_meets_threshold() -> None:
    fixture = _synthetic_fixture()
    result = evaluate_backup_restore_rpo_rto(_synthetic_corpus([fixture]))
    assert result.metric_value == pytest.approx(1.0)
    assert result.threshold_met is True


# ---------------------------------------------------------------------------
# SUT integration (5 tests, plan v2 §7.7)
# ---------------------------------------------------------------------------


def test_sut_results_none_passes_skeleton_default() -> None:
    fixture = _synthetic_fixture()
    result = evaluate_backup_restore_rpo_rto(_synthetic_corpus([fixture]))
    assert result.per_fixture[0].sut_result is None
    assert result.threshold_met is True


def test_sut_results_all_true_passes() -> None:
    fixture = _synthetic_fixture()
    result = evaluate_backup_restore_rpo_rto(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: True},
    )
    assert result.per_fixture[0].sut_result is True
    assert result.threshold_met is True


def test_sut_results_all_false_marks_failure() -> None:
    """F-PR37-R1-001 adopt: sut_failure stored on sut_failure_reason
    (not spec_violation_reason).
    """

    fixture = _synthetic_fixture()
    result = evaluate_backup_restore_rpo_rto(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: False},
    )
    per = result.per_fixture[0]
    assert per.sut_result is False
    assert per.spec_violation_reason is None
    assert per.sut_failure_reason == "sut_returned_false"
    assert per.passed is False


def test_sut_result_missing_marks_failure() -> None:
    """F-PR37-R1-001 adopt: sut_result_missing stored on
    sut_failure_reason.
    """

    fixture = _synthetic_fixture()
    result = evaluate_backup_restore_rpo_rto(
        _synthetic_corpus([fixture]),
        sut_results={"some_other_fixture_id": True},
    )
    per = result.per_fixture[0]
    assert per.spec_violation_reason is None
    assert per.sut_failure_reason == "sut_result_missing"


@pytest.mark.parametrize("raw", [None, "true", 1, []])
def test_non_boolean_sut_result_is_rejected(raw: object) -> None:
    """F-PR37-R1-001 adopt: invalid type stored on sut_failure_reason."""

    fixture = _synthetic_fixture()
    result = evaluate_backup_restore_rpo_rto(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: raw},  # type: ignore[dict-item]
    )
    per = result.per_fixture[0]
    assert per.spec_violation_reason is None
    assert per.sut_failure_reason == "sut_result_invalid_type"


def test_spec_violation_and_sut_failure_are_mutually_exclusive() -> None:
    """F-PR37-R1-001 adopt: spec_violation_reason and sut_failure_reason
    cannot both be non-None for the same fixture (KPI aggregator
    physical separation invariant).
    """

    # A spec-violating fixture with sut_results provided: SUT processing
    # is skipped, so sut_failure_reason remains None.
    fixture = _synthetic_fixture(expected_pitr_success=False)
    result = evaluate_backup_restore_rpo_rto(
        _synthetic_corpus([fixture]),
        sut_results={fixture.fixture_id: False},
    )
    per = result.per_fixture[0]
    assert per.spec_violation_reason is not None
    assert per.sut_failure_reason is None


def test_backup_age_exceeding_rpo_is_rejected() -> None:
    """F-PR37-R1-002 adopt: backup older than declared RPO fails the
    gate even if expected_rpo_hours_max is within bounds.
    """

    # Synthetic fixture: declared_rpo=24, backup_age=999 → violation.
    raw_json = _synthetic_raw_json()
    raw_json["input"]["backup_artifact"]["created_at_offset_hours"] = 999  # type: ignore[index]
    expectation_keys = {
        "expected_decision",
        "expected_rpo_hours_max",
        "expected_rto_hours_max",
        "expected_pitr_success",
        "expected_checksum_match",
        "pattern_hit_kind",
        "assertions",
    }
    expected_json = {k: raw_json[k] for k in expectation_keys if k in raw_json}
    case_json = {k: v for k, v in raw_json.items() if k not in expectation_keys}
    fixture = Fixture(
        fixture_id=raw_json["fixture_id"],  # type: ignore[arg-type]
        dataset_version_id="v2026.05.17-synthetic",
        fixture_kind="public_regression",
        gate_id="AC-HARD-04",
        metric_key="backup_restore_rpo_rto",
        case_key="synthetic_case",
        case_json=case_json,
        expected_json=expected_json,
        metadata=raw_json["metadata"],  # type: ignore[arg-type]
        anti_gaming=raw_json["anti_gaming"],  # type: ignore[arg-type]
        source_path=Path("synthetic"),
        raw_json=raw_json,
        kpi_id=None,
    )
    _, per = _result_for(fixture)
    assert per.spec_violation_reason == "spec_violation:backup_age_exceeds_rpo"


def test_hard_reset_metric_when_mixed_corpus_has_spec_violation() -> None:
    """F-PR37-R1-003 adopt: with 1 valid + 1 spec-violating fixture in
    a mixed corpus, ``metric_value`` is hard-reset to 0.0 (not the
    naive pass_count/fixture_count = 0.5). Hard-gate contract requires
    100% spec compliance.
    """

    fixture_good = _synthetic_fixture(
        fixture_id="AC-HARD-04_v2026.05.17-synthetic_good_hr",
    )
    fixture_bad = _synthetic_fixture(
        fixture_id="AC-HARD-04_v2026.05.17-synthetic_bad_hr",
        expected_pitr_success=False,
    )
    manifest = copy.deepcopy(_VALID_MANIFEST)
    manifest["splits"] = {
        "public_regression": {"path": "public_regression/", "expected_count": 2},
    }
    result = evaluate_backup_restore_rpo_rto(
        _synthetic_corpus([fixture_good, fixture_bad], manifest=manifest)
    )
    # pass_count=1, fixture_count=2 — naive would give 0.5
    assert result.pass_count == 1
    assert result.fixture_count == 2
    # Hard reset to 0.0
    assert result.metric_value == pytest.approx(0.0)
    assert result.threshold_met is False
    assert result.threshold_reason == "spec_violation"


# ---------------------------------------------------------------------------
# Manifest invariants (4 tests, plan v2 §7.8 LOW-2 adopt)
# ---------------------------------------------------------------------------


def test_valid_manifest_passes() -> None:
    fixture = _synthetic_fixture()
    result = evaluate_backup_restore_rpo_rto(_synthetic_corpus([fixture]))
    assert result.manifest_violation_reason is None


def test_partition_invariant_holds_at_import_time() -> None:
    """Module-load runtime check (S101-safe) enforces partition."""

    assert (
        AC_HARD_04_REQUIRED_DRILL_KINDS_SKELETON
        <= AC_HARD_04_FUTURE_REQUIRED_DRILL_KINDS
    )
    assert AC_HARD_04_FUTURE_REQUIRED_DRILL_KINDS <= backup_restore._KNOWN_DRILL_KINDS


def test_known_drill_kinds_is_frozen() -> None:
    """LOW-2 adopt: immutability check."""

    assert isinstance(backup_restore._KNOWN_DRILL_KINDS, frozenset)


def test_allowed_payload_data_classes_is_frozen() -> None:
    """LOW-2 adopt: immutability check."""

    assert isinstance(backup_restore._ALLOWED_PAYLOAD_DATA_CLASSES, frozenset)
    assert (
        backup_restore._ALLOWED_PAYLOAD_DATA_CLASSES
        == EXPECTED_ALLOWED_PAYLOAD_DATA_CLASSES
    )
