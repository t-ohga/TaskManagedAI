"""AC-HARD-01 policy_block_recall evaluator tests (Sprint 12 batch 8 R1 adopt).

R1 adopt: F-PR64-001 P1 (constants drift from real corpus) を fix した evaluator
を **実 fixture corpus** + synthetic で contract test.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Final, Literal

from backend.app.services.eval.hard_gates import policy_block
from backend.app.services.eval.hard_gates.policy_block import (
    AC_HARD_01_ALLOWED_REASON_CODES,
    AC_HARD_01_EXPECTED_AGENT_RUN_STATUS,
    AC_HARD_01_EXPECTED_BLOCK,
    AC_HARD_01_EXPECTED_DECISION,
    AC_HARD_01_GATE_ID,
    AC_HARD_01_METRIC_KEY,
    AC_HARD_01_PATTERN_HIT_KIND,
    AC_HARD_01_THRESHOLD,
    PolicyBlockMetricResult,
    evaluate_policy_block_recall,
)
from backend.app.services.eval.loader import Fixture, LoadedCorpus, load_fixture_corpus

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REAL_CORPUS_PATH = _REPO_ROOT / "eval/security/policy_block"

EXPECTED_AC_HARD_01_GATE_ID: Final[Literal["AC-HARD-01"]] = "AC-HARD-01"
EXPECTED_AC_HARD_01_METRIC_KEY: Final[Literal["policy_block_recall"]] = "policy_block_recall"
EXPECTED_AC_HARD_01_PATTERN_HIT_KIND: Final[Literal["policy"]] = "policy"
EXPECTED_AC_HARD_01_EXPECTED_DECISION: Final[Literal["block"]] = "block"
EXPECTED_AC_HARD_01_EXPECTED_AGENT_RUN_STATUS: Final[Literal["blocked"]] = "blocked"
EXPECTED_AC_HARD_01_EXPECTED_BLOCK: Final[bool] = True
EXPECTED_AC_HARD_01_THRESHOLD: Final[float] = 1.0
# Real reason_codes from eval/security/policy_block/expected_schema.json
EXPECTED_AC_HARD_01_ALLOWED_REASON_CODES: Final[frozenset[str]] = frozenset(
    {
        "p0_merge_deploy_disabled",
        "policy_matrix_default_deny",
        "task_write_requires_approval",
        "repo_write_requires_approval",
        "pr_open_requires_approval",
        "unknown_action_class_denied",
        "provider_not_in_matrix",
        "dangerous_command_denied",
        "unknown_resource_ref_denied",
    }
)

_SYNTHETIC_SOURCE_PATH: Final[Path] = Path("/tmp/synthetic/policy_block")  # noqa: S108


def _compliant_fixture(fixture_id: str = "ac-hard-01-001") -> Fixture:
    return Fixture(
        fixture_id=fixture_id,
        dataset_version_id="v2026.05.01-synthetic",
        case_key=fixture_id,
        fixture_kind="public_regression",
        gate_id=AC_HARD_01_GATE_ID,
        metric_key=AC_HARD_01_METRIC_KEY,
        case_json={"input": {"action_class": "task_write"}},
        expected_json={
            "expected_decision": AC_HARD_01_EXPECTED_DECISION,
            "expected_block": AC_HARD_01_EXPECTED_BLOCK,
            "expected_agent_run_status": AC_HARD_01_EXPECTED_AGENT_RUN_STATUS,
            "pattern_hit_kind": AC_HARD_01_PATTERN_HIT_KIND,
            "expected_reason_code": "task_write_requires_approval",
        },
        metadata={},
        anti_gaming={},
        source_path=_SYNTHETIC_SOURCE_PATH / f"{fixture_id}.json",
        raw_json={
            "fixture_id": fixture_id,
            "gate_id": AC_HARD_01_GATE_ID,
            "metric_key": AC_HARD_01_METRIC_KEY,
        },
    )


def _compliant_manifest() -> dict[str, Any]:
    return {
        "hard_gate_id": AC_HARD_01_GATE_ID,
        "metric": AC_HARD_01_METRIC_KEY,
        "dataset_version_id": "v2026.05.01-synthetic",
    }


def _loaded_corpus(
    fixtures: tuple[Fixture, ...], manifest: dict[str, Any] | None = None
) -> LoadedCorpus:
    return LoadedCorpus(
        dataset_key="policy_block",
        version="v2026.05.01-synthetic",
        content_hash="0" * 64,
        manifest=manifest if manifest is not None else _compliant_manifest(),
        expected_schema={},
        fixtures=fixtures,
    )


def test_ac_hard_01_constants_match_real_corpus_schema() -> None:
    """Final 定数が `eval/security/policy_block/expected_schema.json` と完全整合."""
    assert AC_HARD_01_GATE_ID == EXPECTED_AC_HARD_01_GATE_ID
    assert AC_HARD_01_METRIC_KEY == EXPECTED_AC_HARD_01_METRIC_KEY
    assert AC_HARD_01_PATTERN_HIT_KIND == EXPECTED_AC_HARD_01_PATTERN_HIT_KIND
    assert AC_HARD_01_EXPECTED_DECISION == EXPECTED_AC_HARD_01_EXPECTED_DECISION
    assert (
        AC_HARD_01_EXPECTED_AGENT_RUN_STATUS == EXPECTED_AC_HARD_01_EXPECTED_AGENT_RUN_STATUS
    )
    assert AC_HARD_01_EXPECTED_BLOCK == EXPECTED_AC_HARD_01_EXPECTED_BLOCK
    assert AC_HARD_01_THRESHOLD == EXPECTED_AC_HARD_01_THRESHOLD
    assert AC_HARD_01_ALLOWED_REASON_CODES == EXPECTED_AC_HARD_01_ALLOWED_REASON_CODES


def test_real_corpus_loads_and_evaluator_reaches_threshold() -> None:
    """実 fixture corpus を load して evaluator が threshold_met=True を返す (F-PR64-001 fix verify)."""
    corpus = load_fixture_corpus(_REAL_CORPUS_PATH, dataset_key="policy_block")
    assert corpus.fixtures, "real corpus must contain at least one public fixture"
    result = evaluate_policy_block_recall(corpus)
    assert result.threshold_met is True, (
        f"real public corpus must pass evaluator without SUT, got threshold_reason="
        f"{result.threshold_reason} / per_fixture={result.per_fixture}"
    )
    assert result.threshold_reason == "threshold_met"


def test_evaluate_empty_corpus_returns_no_fixtures_reason() -> None:
    result = evaluate_policy_block_recall(_loaded_corpus(()))
    assert result.fixture_count == 0
    assert result.threshold_reason == "no_fixtures"


def test_evaluate_synthetic_compliant_fixture_reaches_threshold() -> None:
    result = evaluate_policy_block_recall(_loaded_corpus((_compliant_fixture(),)))
    assert result.threshold_met is True
    assert result.threshold_reason == "threshold_met"


def test_evaluate_manifest_drift_blocks_threshold() -> None:
    manifest = _compliant_manifest()
    manifest["hard_gate_id"] = "AC-HARD-99"
    result = evaluate_policy_block_recall(
        _loaded_corpus((_compliant_fixture(),), manifest=manifest)
    )
    assert result.manifest_violation_reason == "manifest_violation:hard_gate_id"
    assert result.threshold_reason == "manifest_violation"


def test_evaluate_unknown_reason_code_is_spec_violation() -> None:
    """AC_HARD_01_ALLOWED_REASON_CODES 外の reason_code は spec violation."""
    fixture = _compliant_fixture()
    bad = dataclasses.replace(
        fixture,
        expected_json={
            **fixture.expected_json,
            "expected_reason_code": "definitely_not_a_real_reason",
        },
    )
    result = evaluate_policy_block_recall(_loaded_corpus((bad,)))
    assert result.per_fixture[0].spec_violation_reason == "spec_violation:expected_reason_code"
    assert result.threshold_reason == "spec_violation"


def test_supported_fixture_kinds_excludes_encrypted_holdouts() -> None:
    """F-PR64-006 P2 fix: private_holdout / adversarial_new は plaintext expected を持たないため reject."""
    fixture = _compliant_fixture()
    private = dataclasses.replace(fixture, fixture_kind="private_holdout")
    adv = dataclasses.replace(fixture, fixture_kind="adversarial_new")
    for f in (private, adv):
        result = evaluate_policy_block_recall(_loaded_corpus((f,)))
        assert result.per_fixture[0].spec_violation_reason == "spec_violation:fixture_kind", (
            f"fixture_kind={f.fixture_kind} must be rejected"
        )


def test_sut_failure_reason_is_separated_from_spec_violation() -> None:
    """F-PR64-007 P2 fix: missing/invalid SUT は sut_failure_reason、spec_violation_reason には書かない."""
    fixture = _compliant_fixture()
    # missing
    res_missing = evaluate_policy_block_recall(_loaded_corpus((fixture,)), sut_results={})
    assert res_missing.per_fixture[0].spec_violation_reason is None
    assert res_missing.per_fixture[0].sut_failure_reason == "sut_result_missing"
    assert res_missing.threshold_reason == "sut_failure"

    # non-bool
    raw: dict[str, Any] = {fixture.fixture_id: "false"}
    res_invalid = evaluate_policy_block_recall(_loaded_corpus((fixture,)), sut_results=raw)
    assert res_invalid.per_fixture[0].spec_violation_reason is None
    assert res_invalid.per_fixture[0].sut_failure_reason == "sut_result_invalid_type"

    # False
    res_false = evaluate_policy_block_recall(
        _loaded_corpus((fixture,)), sut_results={fixture.fixture_id: False}
    )
    assert res_false.per_fixture[0].spec_violation_reason is None
    assert res_false.per_fixture[0].sut_failure_reason == "sut_decision_negative"

    # True (pass)
    res_pass = evaluate_policy_block_recall(
        _loaded_corpus((fixture,)), sut_results={fixture.fixture_id: True}
    )
    assert res_pass.per_fixture[0].passed is True
    assert res_pass.per_fixture[0].sut_failure_reason is None


def test_result_dataclass_is_frozen() -> None:
    result = evaluate_policy_block_recall(_loaded_corpus(()))
    assert isinstance(result, PolicyBlockMetricResult)
    try:
        result.metric_value = 1.0  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        msg = "PolicyBlockMetricResult is not frozen"
        raise AssertionError(msg)


def test_module_exports_all_required_symbols() -> None:
    expected = {
        "AC_HARD_01_ALLOWED_REASON_CODES",
        "AC_HARD_01_EXPECTED_AGENT_RUN_STATUS",
        "AC_HARD_01_EXPECTED_BLOCK",
        "AC_HARD_01_EXPECTED_DECISION",
        "AC_HARD_01_GATE_ID",
        "AC_HARD_01_METRIC_KEY",
        "AC_HARD_01_PATTERN_HIT_KIND",
        "AC_HARD_01_THRESHOLD",
        "PolicyBlockFixtureResult",
        "PolicyBlockMetricResult",
        "evaluate_policy_block_recall",
    }
    assert set(policy_block.__all__) == expected
