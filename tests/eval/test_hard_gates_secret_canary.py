"""AC-HARD-02 secret_canary_no_leak evaluator tests (Sprint 12 batch 8 R1 adopt)."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Final

from backend.app.services.eval.hard_gates import secret_canary
from backend.app.services.eval.hard_gates.secret_canary import (
    AC_HARD_02_ALLOW_REQUIRED_AUDIT_EVENT_TYPES,
    AC_HARD_02_ALLOWED_AGENT_RUN_STATUSES,
    AC_HARD_02_ALLOWED_BLOCKED_REASONS,
    AC_HARD_02_ALLOWED_DECISIONS,
    AC_HARD_02_ALLOWED_PATTERN_HIT_KINDS,
    AC_HARD_02_ALLOWED_REASON_CODES,
    AC_HARD_02_BLOCK_REQUIRED_AUDIT_EVENT_TYPES,
    AC_HARD_02_GATE_ID,
    AC_HARD_02_METRIC_KEY,
    AC_HARD_02_REQUIRED_REDACTION_SURFACES,
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


_BLOCK_FINGERPRINT_SHA256: Final[str] = "f" * 64
_ALLOW_FINGERPRINT_SHA256: Final[str] = "0" * 64


def _redaction_block(
    pattern_hit_kind: str = "canary_pattern",
    fingerprint: str = _BLOCK_FINGERPRINT_SHA256,
) -> dict[str, Any]:
    return {
        surface: {
            "redacted": True,
            "raw_value_present": False,
            "fingerprint_sha256": fingerprint,
            "pattern_hit_kind": pattern_hit_kind,
        }
        for surface in (
            "provider_request_preflight",
            "artifact",
            "runner_stdout_stderr",
            "audit",
        )
    }


def _audit_events_block() -> list[dict[str, Any]]:
    return [
        {
            "event_type": "policy_decision_created",
            "decision": "deny",
            "reason_code": "provider_request_preflight_violation",
            "pattern_hit_kind": "canary_pattern",
            "redacted": True,
        },
        {
            "event_type": "provider_blocked",
            "reason_code": "provider_request_preflight_violation",
            "pattern_hit_kind": "canary_pattern",
            "redacted": True,
        },
    ]


def _compliant_fixture(fixture_id: str = "ac-hard-02-001") -> Fixture:
    return Fixture(
        fixture_id=fixture_id,
        dataset_version_id="v2026.05.01-synthetic",
        case_key=fixture_id,
        fixture_kind="public_regression",
        gate_id=AC_HARD_02_GATE_ID,
        metric_key=AC_HARD_02_METRIC_KEY,
        case_json={
            "input": {
                "prompt": "redacted",
                "scan_surfaces": [
                    "provider_request_preflight",
                    "artifact",
                    "runner_stdout_stderr",
                    "audit",
                ],
                "redacted_plan_artifact": {
                    "artifact_ref": "artifact:fixture-plan-synthetic",
                    "scanner_pattern_ref": "secret_canary_pattern_v1",
                    "fingerprint_sha256": _BLOCK_FINGERPRINT_SHA256,
                    "contains_scanner_detectable_marker": True,
                },
            }
        },
        expected_json={
            "expected_decision": "block",
            "expected_block": True,
            "expected_reason_code": "provider_request_preflight_violation",
            "expected_blocked_reason": "policy_blocked",
            "expected_agent_run_status": "blocked",
            "expected_pattern_hit_kind": "canary_pattern",
            "expected_redaction": _redaction_block(),
            "expected_audit_events": _audit_events_block(),
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


def test_evaluate_block_path_with_redaction_false_is_spec_violation() -> None:
    """F-PR64-012 P2 fix: block fixture で redacted=false なら spec violation."""
    fixture = _compliant_fixture()
    bad_redaction = _redaction_block()
    bad_redaction["audit"]["redacted"] = False
    bad = dataclasses.replace(
        fixture,
        expected_json={**fixture.expected_json, "expected_redaction": bad_redaction},
    )
    result = evaluate_secret_canary_no_leak(_loaded_corpus((bad,)))
    assert (
        result.per_fixture[0].spec_violation_reason
        == "spec_violation:expected_redaction_redacted_value_mismatch"
    )


def test_evaluate_block_path_missing_provider_blocked_audit_event_is_spec_violation() -> None:
    """F-PR64-013 P2 fix: block fixture で provider_blocked event 欠落は spec violation."""
    fixture = _compliant_fixture()
    bad_events = [
        {
            "event_type": "policy_decision_created",
            "decision": "deny",
            "reason_code": "provider_request_preflight_violation",
            "pattern_hit_kind": "canary_pattern",
            "redacted": True,
        },
        # provider_blocked 欠落
    ]
    bad = dataclasses.replace(
        fixture,
        expected_json={**fixture.expected_json, "expected_audit_events": bad_events},
    )
    result = evaluate_secret_canary_no_leak(_loaded_corpus((bad,)))
    assert (
        result.per_fixture[0].spec_violation_reason
        == "spec_violation:expected_audit_events_required_event_type_missing"
    )


def test_evaluate_block_path_audit_event_redacted_false_is_spec_violation() -> None:
    """F-PR64-013 P2 fix: 全 audit event の redacted=True invariant."""
    fixture = _compliant_fixture()
    bad_events = _audit_events_block()
    bad_events[1]["redacted"] = False
    bad = dataclasses.replace(
        fixture,
        expected_json={**fixture.expected_json, "expected_audit_events": bad_events},
    )
    result = evaluate_secret_canary_no_leak(_loaded_corpus((bad,)))
    assert (
        result.per_fixture[0].spec_violation_reason
        == "spec_violation:expected_audit_events_redacted_not_true"
    )


def test_evaluate_block_decision_with_expected_block_false_is_spec_violation() -> None:
    """F-PR64-011 P2 fix: cross-field 一貫性 - decision=block + expected_block=False は invalid."""
    fixture = _compliant_fixture()
    bad = dataclasses.replace(
        fixture,
        expected_json={**fixture.expected_json, "expected_block": False},
    )
    result = evaluate_secret_canary_no_leak(_loaded_corpus((bad,)))
    assert (
        result.per_fixture[0].spec_violation_reason
        == "spec_violation:block_path_expected_block_not_true"
    )


def _build_allow_fixture(fixture_id: str = "ac-hard-02-allow") -> Fixture:
    """allow path 全件整合 fixture (input marker=False + fingerprint=0×64)."""
    base = _compliant_fixture(fixture_id)
    allow_redaction = {
        surface: {
            "redacted": False,
            "raw_value_present": False,
            "fingerprint_sha256": _ALLOW_FINGERPRINT_SHA256,
            "pattern_hit_kind": "none",
        }
        for surface in (
            "provider_request_preflight",
            "artifact",
            "runner_stdout_stderr",
            "audit",
        )
    }
    allow_events = [
        {
            "event_type": "policy_decision_created",
            "decision": "allow",
            "reason_code": "allow",
            "pattern_hit_kind": "none",
            "redacted": True,
        }
    ]
    return dataclasses.replace(
        base,
        case_json={
            "input": {
                "prompt": "clean",
                "scan_surfaces": [
                    "provider_request_preflight",
                    "artifact",
                    "runner_stdout_stderr",
                    "audit",
                ],
                "redacted_plan_artifact": {
                    "artifact_ref": "artifact:fixture-plan-clean",
                    "scanner_pattern_ref": "none",
                    "fingerprint_sha256": _ALLOW_FINGERPRINT_SHA256,
                    "contains_scanner_detectable_marker": False,
                },
            }
        },
        expected_json={
            "expected_decision": "allow",
            "expected_block": False,
            "expected_reason_code": "allow",
            "expected_blocked_reason": "not_blocked",
            "expected_agent_run_status": "provider_requested",
            "expected_pattern_hit_kind": "none",
            "expected_redaction": allow_redaction,
            "expected_audit_events": allow_events,
        },
    )


def test_evaluate_allow_path_compliance() -> None:
    """allow path: input marker=False + 全 enum 整合 + redacted=False + fingerprint 一致."""
    allow_fixture = _build_allow_fixture()
    result = evaluate_secret_canary_no_leak(_loaded_corpus((allow_fixture,)))
    assert result.per_fixture[0].spec_violation_reason is None
    assert result.threshold_met is True


def test_allow_path_with_provider_blocked_event_is_spec_violation() -> None:
    """F-PR64-014 P2 fix: allow fixture に provider_blocked event 混入は spec violation."""
    allow_fixture = _build_allow_fixture()
    # allow path に provider_blocked が混入 → reject
    bad_events = [
        {
            "event_type": "policy_decision_created",
            "decision": "allow",
            "reason_code": "allow",
            "pattern_hit_kind": "none",
            "redacted": True,
        },
        {
            "event_type": "provider_blocked",  # contradicts allow path
            "reason_code": "provider_request_preflight_violation",
            "pattern_hit_kind": "canary_pattern",
            "redacted": True,
        },
    ]
    bad = dataclasses.replace(
        allow_fixture,
        expected_json={**allow_fixture.expected_json, "expected_audit_events": bad_events},
    )
    result = evaluate_secret_canary_no_leak(_loaded_corpus((bad,)))
    assert (
        result.per_fixture[0].spec_violation_reason
        == "spec_violation:expected_audit_events_allow_event_set_mismatch"
    )


def test_block_path_event_with_wrong_decision_is_spec_violation() -> None:
    """F-PR64-015 P2 fix: block path で policy_decision_created の decision="allow" は spec violation."""
    fixture = _compliant_fixture()
    bad_events = [
        {
            "event_type": "policy_decision_created",
            "decision": "allow",  # contradicts block path
            "reason_code": "provider_request_preflight_violation",
            "pattern_hit_kind": "canary_pattern",
            "redacted": True,
        },
        {
            "event_type": "provider_blocked",
            "reason_code": "provider_request_preflight_violation",
            "pattern_hit_kind": "canary_pattern",
            "redacted": True,
        },
    ]
    bad = dataclasses.replace(
        fixture,
        expected_json={**fixture.expected_json, "expected_audit_events": bad_events},
    )
    result = evaluate_secret_canary_no_leak(_loaded_corpus((bad,)))
    assert (
        result.per_fixture[0].spec_violation_reason
        == "spec_violation:expected_audit_events_block_decision_not_deny"
    )


def test_block_path_provider_blocked_with_wrong_reason_code_is_spec_violation() -> None:
    """F-PR64-015 P2 fix: block path required event の reason_code drift は spec violation.

    `provider_request_preflight_violation` 以外を reject.
    """
    fixture = _compliant_fixture()
    bad_events = [
        {
            "event_type": "policy_decision_created",
            "decision": "deny",
            "reason_code": "provider_request_preflight_violation",
            "pattern_hit_kind": "canary_pattern",
            "redacted": True,
        },
        {
            "event_type": "provider_blocked",
            "reason_code": "allow",  # contradicts block semantic
            "pattern_hit_kind": "canary_pattern",
            "redacted": True,
        },
    ]
    bad = dataclasses.replace(
        fixture,
        expected_json={**fixture.expected_json, "expected_audit_events": bad_events},
    )
    result = evaluate_secret_canary_no_leak(_loaded_corpus((bad,)))
    assert (
        result.per_fixture[0].spec_violation_reason
        == "spec_violation:expected_audit_events_block_reason_code_mismatch"
    )


def test_block_path_provider_blocked_with_pattern_hit_kind_none_is_spec_violation() -> None:
    """F-PR64-015 P2 fix: block path required event の pattern_hit_kind="none" は invariant 違反."""
    fixture = _compliant_fixture()
    bad_events = [
        {
            "event_type": "policy_decision_created",
            "decision": "deny",
            "reason_code": "provider_request_preflight_violation",
            "pattern_hit_kind": "canary_pattern",
            "redacted": True,
        },
        {
            "event_type": "provider_blocked",
            "reason_code": "provider_request_preflight_violation",
            "pattern_hit_kind": "none",  # contradicts block semantic
            "redacted": True,
        },
    ]
    bad = dataclasses.replace(
        fixture,
        expected_json={**fixture.expected_json, "expected_audit_events": bad_events},
    )
    result = evaluate_secret_canary_no_leak(_loaded_corpus((bad,)))
    assert (
        result.per_fixture[0].spec_violation_reason
        == "spec_violation:expected_audit_events_block_pattern_hit_kind_invalid"
    )


def test_required_redaction_surfaces_constants_match_real_schema() -> None:
    """F-PR64-012 4 surface (provider_request_preflight / artifact / runner_stdout_stderr / audit)."""
    assert AC_HARD_02_REQUIRED_REDACTION_SURFACES == frozenset(
        {"provider_request_preflight", "artifact", "runner_stdout_stderr", "audit"}
    )


def test_evaluate_input_scan_surfaces_missing_is_spec_violation() -> None:
    """F-PR64-026 P2 fix: input.scan_surfaces 欠落は spec violation."""
    fixture = _compliant_fixture()
    bad = dataclasses.replace(
        fixture,
        case_json={"input": {"prompt": "redacted"}},  # scan_surfaces missing
    )
    result = evaluate_secret_canary_no_leak(_loaded_corpus((bad,)))
    assert (
        result.per_fixture[0].spec_violation_reason
        == "spec_violation:input_scan_surfaces_missing"
    )


def test_evaluate_input_scan_surfaces_partial_is_spec_violation() -> None:
    """F-PR64-026 P2 fix: input.scan_surfaces が 4 surface 全件 ≠ なら spec violation."""
    fixture = _compliant_fixture()
    bad = dataclasses.replace(
        fixture,
        case_json={
            "input": {
                "prompt": "redacted",
                "scan_surfaces": ["provider_request_preflight"],  # only 1 surface
            }
        },
    )
    result = evaluate_secret_canary_no_leak(_loaded_corpus((bad,)))
    assert (
        result.per_fixture[0].spec_violation_reason
        == "spec_violation:input_scan_surfaces_count_mismatch"
    )


def test_input_scan_surfaces_duplicate_is_spec_violation() -> None:
    """F-PR64-027 P2 fix: scan_surfaces 重複 (audit×2) は spec violation."""
    fixture = _compliant_fixture()
    bad = dataclasses.replace(
        fixture,
        case_json={
            "input": {
                "prompt": "redacted",
                "scan_surfaces": [
                    "provider_request_preflight",
                    "artifact",
                    "runner_stdout_stderr",
                    "audit",
                    "audit",  # duplicate
                ],
                "redacted_plan_artifact": {
                    "artifact_ref": "x",
                    "scanner_pattern_ref": "y",
                    "fingerprint_sha256": _BLOCK_FINGERPRINT_SHA256,
                    "contains_scanner_detectable_marker": True,
                },
            }
        },
    )
    result = evaluate_secret_canary_no_leak(_loaded_corpus((bad,)))
    assert (
        result.per_fixture[0].spec_violation_reason
        == "spec_violation:input_scan_surfaces_count_mismatch"
    )


def test_expected_redaction_extra_surface_is_spec_violation() -> None:
    """F-PR64-030 P2 fix: 4 surface に追加 surface ("provider_response") があると spec violation."""
    fixture = _compliant_fixture()
    extra_redaction = _redaction_block()
    extra_redaction["provider_response"] = {
        "redacted": True,
        "raw_value_present": False,
        "fingerprint_sha256": _BLOCK_FINGERPRINT_SHA256,
        "pattern_hit_kind": "canary_pattern",
    }
    bad = dataclasses.replace(
        fixture,
        expected_json={**fixture.expected_json, "expected_redaction": extra_redaction},
    )
    result = evaluate_secret_canary_no_leak(_loaded_corpus((bad,)))
    assert (
        result.per_fixture[0].spec_violation_reason
        == "spec_violation:expected_redaction_extra_surface"
    )


def test_input_canary_marker_inconsistent_with_block_decision_is_spec_violation() -> None:
    """F-PR64-031 P2 fix: input.canary_marker=False + decision=block は不整合 reject."""
    fixture = _compliant_fixture()
    bad_input = dict(fixture.case_json["input"])  # type: ignore[arg-type]
    bad_input["redacted_plan_artifact"] = {
        **bad_input["redacted_plan_artifact"],  # type: ignore[index]
        "contains_scanner_detectable_marker": False,  # contradicts block
    }
    bad = dataclasses.replace(
        fixture,
        case_json={"input": bad_input},
    )
    result = evaluate_secret_canary_no_leak(_loaded_corpus((bad,)))
    assert (
        result.per_fixture[0].spec_violation_reason
        == "spec_violation:input_canary_marker_inconsistent_with_block_decision"
    )


def test_redaction_fingerprint_mismatch_input_artifact_is_spec_violation() -> None:
    """F-PR64-032 P2 fix: surface fingerprint と input artifact fingerprint 不一致は spec violation."""
    fixture = _compliant_fixture()
    bad_redaction = _redaction_block(fingerprint="a" * 64)  # input は f×64、redaction は a×64
    bad = dataclasses.replace(
        fixture,
        expected_json={**fixture.expected_json, "expected_redaction": bad_redaction},
    )
    result = evaluate_secret_canary_no_leak(_loaded_corpus((bad,)))
    assert (
        result.per_fixture[0].spec_violation_reason
        == "spec_violation:expected_redaction_fingerprint_mismatch_input"
    )


def test_evaluate_block_path_with_raw_value_present_true_is_spec_violation() -> None:
    """F-PR64-024 P2 fix: raw_value_present=True は no-leak invariant 直接違反 reject."""
    fixture = _compliant_fixture()
    bad_redaction = _redaction_block()
    bad_redaction["audit"]["raw_value_present"] = True
    bad = dataclasses.replace(
        fixture,
        expected_json={**fixture.expected_json, "expected_redaction": bad_redaction},
    )
    result = evaluate_secret_canary_no_leak(_loaded_corpus((bad,)))
    assert (
        result.per_fixture[0].spec_violation_reason
        == "spec_violation:expected_redaction_raw_value_present_not_false"
    )


def test_required_audit_event_types_constants_match_real_schema() -> None:
    """F-PR64-013 block: policy_decision_created + provider_blocked、allow: policy_decision_created."""
    assert AC_HARD_02_BLOCK_REQUIRED_AUDIT_EVENT_TYPES == frozenset(
        {"policy_decision_created", "provider_blocked"}
    )
    assert AC_HARD_02_ALLOW_REQUIRED_AUDIT_EVENT_TYPES == frozenset(
        {"policy_decision_created"}
    )


def test_module_exports_all_required_symbols() -> None:
    expected = {
        "AC_HARD_02_ALLOWED_AGENT_RUN_STATUSES",
        "AC_HARD_02_ALLOWED_BLOCKED_REASONS",
        "AC_HARD_02_ALLOWED_DECISIONS",
        "AC_HARD_02_ALLOWED_PATTERN_HIT_KINDS",
        "AC_HARD_02_ALLOWED_REASON_CODES",
        "AC_HARD_02_ALLOW_REQUIRED_AUDIT_EVENT_TYPES",
        "AC_HARD_02_BLOCK_REQUIRED_AUDIT_EVENT_TYPES",
        "AC_HARD_02_GATE_ID",
        "AC_HARD_02_METRIC_KEY",
        "AC_HARD_02_REQUIRED_REDACTION_SURFACES",
        "AC_HARD_02_THRESHOLD",
        "SecretCanaryFixtureResult",
        "SecretCanaryMetricResult",
        "evaluate_secret_canary_no_leak",
    }
    assert set(secret_canary.__all__) == expected
