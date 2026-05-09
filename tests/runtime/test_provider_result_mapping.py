from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from backend.app.domain.agent_runtime.status import TERMINAL_STATES
from backend.app.services.agent_runtime.provider_result_mapping import (
    ALL_PROVIDER_RESULT_KINDS,
    AgentRunStatusTransitionTarget,
    ProviderResultKind,
    map_provider_result_to_status,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STATE_MACHINE_RULE_PATH = _REPO_ROOT / ".claude/rules/agentrun-state-machine.md"

_EXPECTED_PROVIDER_RESULT_KINDS: tuple[ProviderResultKind, ...] = (
    "success",
    "refusal",
    "safety_refusal",
    "max_token",
    "incomplete",
    "timeout_retryable",
    "unsupported_schema",
    "schema_mismatch",
    "preflight_deny",
    "data_class_deny",
    "budget_exceeded",
)

_EXPECTED_MAPPING: dict[ProviderResultKind, tuple[str, str | None]] = {
    "success": ("generated_artifact", None),
    "refusal": ("provider_refused", None),
    "safety_refusal": ("provider_refused", None),
    "max_token": ("provider_incomplete", None),
    "incomplete": ("provider_incomplete", None),
    "timeout_retryable": ("provider_incomplete", None),
    "unsupported_schema": ("validation_failed", None),
    "schema_mismatch": ("validation_failed", None),
    "preflight_deny": ("blocked", "policy_blocked"),
    "data_class_deny": ("blocked", "policy_blocked"),
    "budget_exceeded": ("blocked", "budget_blocked"),
}


def test_provider_result_kind_cross_source_has_all_11_values() -> None:
    assert ALL_PROVIDER_RESULT_KINDS == _EXPECTED_PROVIDER_RESULT_KINDS
    assert len(ALL_PROVIDER_RESULT_KINDS) == 11
    assert len(set(ALL_PROVIDER_RESULT_KINDS)) == 11


@pytest.mark.parametrize("kind", _EXPECTED_PROVIDER_RESULT_KINDS)
def test_each_provider_result_kind_maps_to_expected_status(
    kind: ProviderResultKind,
) -> None:
    target = map_provider_result_to_status(kind)
    expected_status, expected_blocked_reason = _EXPECTED_MAPPING[kind]

    assert isinstance(target, AgentRunStatusTransitionTarget)
    assert target.status == expected_status
    assert target.blocked_reason == expected_blocked_reason
    assert target.is_terminal == (target.status in TERMINAL_STATES)


def test_success_maps_to_generated_artifact() -> None:
    target = map_provider_result_to_status("success")

    assert target.status == "generated_artifact"
    assert target.blocked_reason is None
    assert target.is_terminal is False


@pytest.mark.parametrize("kind", ["refusal", "safety_refusal"])
def test_refusal_and_safety_refusal_map_to_provider_refused_terminal(
    kind: ProviderResultKind,
) -> None:
    target = map_provider_result_to_status(kind)

    assert target.status == "provider_refused"
    assert target.blocked_reason is None
    assert target.is_terminal is True


@pytest.mark.parametrize("kind", ["max_token", "incomplete"])
def test_incomplete_results_map_to_provider_incomplete_non_terminal(
    kind: ProviderResultKind,
) -> None:
    target = map_provider_result_to_status(kind)

    assert target.status == "provider_incomplete"
    assert target.blocked_reason is None
    assert target.is_terminal is False


def test_timeout_retryable_defaults_to_provider_incomplete() -> None:
    target = map_provider_result_to_status("timeout_retryable")

    assert target.status == "provider_incomplete"
    assert target.blocked_reason is None
    assert target.is_terminal is False


def test_timeout_retryable_can_map_to_failed_after_retry_exhaustion() -> None:
    target = map_provider_result_to_status(
        "timeout_retryable",
        timeout_retryable_as_failed=True,
    )

    assert target.status == "failed"
    assert target.blocked_reason is None
    assert target.is_terminal is True


@pytest.mark.parametrize("kind", ["unsupported_schema", "schema_mismatch"])
def test_schema_results_map_to_validation_failed(kind: ProviderResultKind) -> None:
    target = map_provider_result_to_status(kind)

    assert target.status == "validation_failed"
    assert target.blocked_reason is None
    assert target.is_terminal is False


@pytest.mark.parametrize("kind", ["preflight_deny", "data_class_deny"])
def test_policy_denies_map_to_blocked_policy_blocked(kind: ProviderResultKind) -> None:
    target = map_provider_result_to_status(kind)

    assert target.status == "blocked"
    assert target.blocked_reason == "policy_blocked"
    assert target.is_terminal is False


def test_budget_exceeded_maps_to_blocked_budget_blocked() -> None:
    target = map_provider_result_to_status("budget_exceeded")

    assert target.status == "blocked"
    assert target.blocked_reason == "budget_blocked"
    assert target.is_terminal is False


def test_invalid_provider_result_kind_rejects_fail_closed() -> None:
    with pytest.raises(ValueError, match="unknown provider result kind"):
        map_provider_result_to_status(cast(Any, "unknown_kind"))


def test_all_blocked_mappings_have_blocked_reason() -> None:
    for kind in ALL_PROVIDER_RESULT_KINDS:
        target = map_provider_result_to_status(kind)
        if target.status == "blocked":
            assert target.blocked_reason in {"policy_blocked", "budget_blocked"}
        else:
            assert target.blocked_reason is None


def test_mapping_matches_agentrun_state_machine_rule_section_7_text() -> None:
    text = _STATE_MACHINE_RULE_PATH.read_text(encoding="utf-8")

    required_fragments = [
        "refusal | `provider_refused`",
        "safety refusal | `provider_refused`",
        "max token / incomplete | `provider_incomplete`",
        "timeout retryable | `provider_incomplete` または `failed`",
        "unsupported schema | `validation_failed`",
        "schema mismatch | `validation_failed`",
        "provider request preflight deny | `blocked` + `policy_blocked`",
        "data class deny | `blocked` + `policy_blocked`",
        "budget exceeded | `blocked` + `budget_blocked`",
        "success structured output | `generated_artifact`",
    ]
    for fragment in required_fragments:
        assert fragment in text


def test_terminal_flags_match_status_contract() -> None:
    for kind in ALL_PROVIDER_RESULT_KINDS:
        target = map_provider_result_to_status(kind)
        assert target.is_terminal == (target.status in TERMINAL_STATES)

    failed_timeout = map_provider_result_to_status(
        "timeout_retryable",
        timeout_retryable_as_failed=True,
    )
    assert failed_timeout.status == "failed"
    assert failed_timeout.is_terminal == ("failed" in TERMINAL_STATES)
