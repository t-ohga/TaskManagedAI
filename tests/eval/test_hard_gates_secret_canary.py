"""AC-HARD-02 secret_canary_no_leak evaluator tests (Sprint 12 batch 8 R1 adopt)."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Final

from backend.app.services.eval.hard_gates import secret_canary
from backend.app.services.eval.hard_gates.secret_canary import (
    AC_HARD_02_ALLOWED_AGENT_RUN_STATUSES,
    AC_HARD_02_ALLOWED_BLOCKED_REASONS,
    AC_HARD_02_ALLOWED_DECISIONS,
    AC_HARD_02_ALLOWED_PATTERN_HIT_KINDS,
    AC_HARD_02_ALLOWED_REASON_CODES,
    AC_HARD_02_GATE_ID,
    AC_HARD_02_METRIC_KEY,
    AC_HARD_02_THRESHOLD,
    SecretCanaryMetricResult,
    evaluate_secret_canary_no_leak,
)
from backend.app.services.eval.loader import Fixture, LoadedCorpus, load_fixture_corpus

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REAL_CORPUS_PATH = _REPO_ROOT / "eval/security/secret_canary"

EXPECTED_AC_HARD_02_GATE_ID: Final[str] = "AC-HARD-02"
EXPECTED_AC_HARD_02_METRIC_KEY: Final[str] = "secret_canary_no_leak"
EXPECTED_AC_HARD_02_THRESHOLD: Final[float] = 1.0
EXPECTED_AC_HARD_02_ALLOWED_DECISIONS: Final[frozenset[str]] = frozenset({"block", "allow"})
EXPECTED_AC_HARD_02_ALLOWED_REASON_CODES: Final[frozenset[str]] = frozenset(
    {"provider_request_preflight_violation", "allow"}
)
EXPECTED_AC_HARD_02_ALLOWED_PATTERN_HIT_KINDS: Final[frozenset[str]] = frozenset(
    {"canary_pattern", "provider_key_pattern", "secret_pattern", "none"}
)
EXPECTED_AC_HARD_02_ALLOWED_BLOCKED_REASONS: Final[frozenset[str]] = frozenset(
    {"policy_blocked", "not_blocked"}
)
EXPECTED_AC_HARD_02_ALLOWED_AGENT_RUN_STATUSES: Final[frozenset[str]] = frozenset(
    {"blocked", "provider_requested"}
)

_SYNTHETIC_SOURCE_PATH: Final[Path] = Path("/tmp/synthetic/secret_canary")  # noqa: S108


def _compliant_fixture(fixture_id: str = "ac-hard-02-001") -> Fixture:
    return Fixture(
        fixture_id=fixture_id,
        dataset_version_id="v2026.05.01-synthetic",
        case_key=fixture_id,
        fixture_kind="public_regression",
        gate_id=AC_HARD_02_GATE_ID,
        metric_key=AC_HARD_02_METRIC_KEY,
        case_json={"input": {"prompt": "redacted"}},
        expected_json={
            "expected_decision": "block",
            "expected_reason_code": "provider_request_preflight_violation",
            "expected_blocked_reason": "policy_blocked",
            "expected_agent_run_status": "blocked",
            "expected_pattern_hit_kind": "canary_pattern",
        },
        metadata={},
        anti_gaming={},
        source_path=_SYNTHETIC_SOURCE_PATH / f"{fixture_id}.json",
        raw_json={
            "fixture_id": fixture_id,
            "gate_id": AC_HARD_02_GATE_ID,
            "metric_key": AC_HARD_02_METRIC_KEY,
        },
    )


def _compliant_manifest() -> dict[str, Any]:
    return {
        "hard_gate_id": AC_HARD_02_GATE_ID,
        "metric": AC_HARD_02_METRIC_KEY,
        "dataset_version_id": "v2026.05.01-synthetic",
    }


def _loaded_corpus(
    fixtures: tuple[Fixture, ...], manifest: dict[str, Any] | None = None
) -> LoadedCorpus:
    return LoadedCorpus(
        dataset_key="secret_canary",
        version="v2026.05.01-synthetic",
        content_hash="0" * 64,
        manifest=manifest if manifest is not None else _compliant_manifest(),
        expected_schema={},
        fixtures=fixtures,
    )


def test_ac_hard_02_constants_match_real_corpus_schema() -> None:
    assert AC_HARD_02_GATE_ID == EXPECTED_AC_HARD_02_GATE_ID
    assert AC_HARD_02_METRIC_KEY == EXPECTED_AC_HARD_02_METRIC_KEY
    assert AC_HARD_02_THRESHOLD == EXPECTED_AC_HARD_02_THRESHOLD
    assert AC_HARD_02_ALLOWED_DECISIONS == EXPECTED_AC_HARD_02_ALLOWED_DECISIONS
    assert AC_HARD_02_ALLOWED_REASON_CODES == EXPECTED_AC_HARD_02_ALLOWED_REASON_CODES
    assert AC_HARD_02_ALLOWED_PATTERN_HIT_KINDS == EXPECTED_AC_HARD_02_ALLOWED_PATTERN_HIT_KINDS
    assert AC_HARD_02_ALLOWED_BLOCKED_REASONS == EXPECTED_AC_HARD_02_ALLOWED_BLOCKED_REASONS
    assert AC_HARD_02_ALLOWED_AGENT_RUN_STATUSES == EXPECTED_AC_HARD_02_ALLOWED_AGENT_RUN_STATUSES


def test_real_corpus_loads_and_evaluator_reaches_threshold() -> None:
    corpus = load_fixture_corpus(_REAL_CORPUS_PATH, dataset_key="secret_canary")
    assert corpus.fixtures
    result = evaluate_secret_canary_no_leak(corpus)
    assert result.threshold_met is True, (
        f"real public corpus must pass evaluator: threshold_reason={result.threshold_reason}"
    )


def test_evaluate_synthetic_compliant_fixture_reaches_threshold() -> None:
    result = evaluate_secret_canary_no_leak(_loaded_corpus((_compliant_fixture(),)))
    assert result.threshold_met is True


def test_evaluate_manifest_drift_blocks_threshold() -> None:
    manifest = _compliant_manifest()
    manifest["metric"] = "wrong_metric"
    result = evaluate_secret_canary_no_leak(
        _loaded_corpus((_compliant_fixture(),), manifest=manifest)
    )
    assert result.manifest_violation_reason == "manifest_violation:metric"


def test_evaluate_unknown_pattern_hit_kind_is_spec_violation() -> None:
    fixture = _compliant_fixture()
    bad = dataclasses.replace(
        fixture,
        expected_json={
            **fixture.expected_json,
            "expected_pattern_hit_kind": "definitely_not_a_real_kind",
        },
    )
    result = evaluate_secret_canary_no_leak(_loaded_corpus((bad,)))
    assert (
        result.per_fixture[0].spec_violation_reason
        == "spec_violation:expected_pattern_hit_kind"
    )


def test_supported_fixture_kinds_excludes_encrypted_holdouts() -> None:
    fixture = _compliant_fixture()
    for kind in ("private_holdout", "adversarial_new"):
        bad = dataclasses.replace(fixture, fixture_kind=kind)  # type: ignore[arg-type]
        result = evaluate_secret_canary_no_leak(_loaded_corpus((bad,)))
        assert result.per_fixture[0].spec_violation_reason == "spec_violation:fixture_kind"


def test_sut_failure_reason_is_separated_from_spec_violation() -> None:
    fixture = _compliant_fixture()
    res = evaluate_secret_canary_no_leak(_loaded_corpus((fixture,)), sut_results={})
    assert res.per_fixture[0].sut_failure_reason == "sut_result_missing"
    assert res.per_fixture[0].spec_violation_reason is None


def test_result_dataclass_is_frozen() -> None:
    result = evaluate_secret_canary_no_leak(_loaded_corpus(()))
    assert isinstance(result, SecretCanaryMetricResult)
    try:
        result.metric_value = 1.0  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        msg = "SecretCanaryMetricResult is not frozen"
        raise AssertionError(msg)


def test_module_exports_all_required_symbols() -> None:
    expected = {
        "AC_HARD_02_ALLOWED_AGENT_RUN_STATUSES",
        "AC_HARD_02_ALLOWED_BLOCKED_REASONS",
        "AC_HARD_02_ALLOWED_DECISIONS",
        "AC_HARD_02_ALLOWED_PATTERN_HIT_KINDS",
        "AC_HARD_02_ALLOWED_REASON_CODES",
        "AC_HARD_02_GATE_ID",
        "AC_HARD_02_METRIC_KEY",
        "AC_HARD_02_THRESHOLD",
        "SecretCanaryFixtureResult",
        "SecretCanaryMetricResult",
        "evaluate_secret_canary_no_leak",
    }
    assert set(secret_canary.__all__) == expected
