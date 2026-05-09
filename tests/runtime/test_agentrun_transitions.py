from __future__ import annotations

import pytest

from backend.app.domain.agent_runtime.status import AgentRunStatus
from backend.app.services.agent_runtime.state_machine import (
    ALLOWED_TRANSITIONS,
    validate_transition,
)

EXPECTED_ALLOWED_TRANSITIONS: dict[AgentRunStatus, frozenset[AgentRunStatus]] = {
    "queued": frozenset({"gathering_context"}),
    "gathering_context": frozenset({"running"}),
    "running": frozenset(
        {
            "generated_artifact",
            "provider_refused",
            "provider_incomplete",
            "blocked",
            "failed",
            "cancelled",
            "completed",
        }
    ),
    "generated_artifact": frozenset({"schema_validated", "validation_failed"}),
    "schema_validated": frozenset({"policy_linted"}),
    "policy_linted": frozenset({"diff_ready", "blocked"}),
    "diff_ready": frozenset({"waiting_approval", "blocked"}),
    "waiting_approval": frozenset({"running", "blocked", "cancelled"}),
    "blocked": frozenset({"waiting_approval", "running", "failed", "cancelled"}),
    "provider_refused": frozenset(),
    "provider_incomplete": frozenset({"running", "failed", "cancelled"}),
    "validation_failed": frozenset({"running", "repair_exhausted"}),
    "repair_exhausted": frozenset(),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


def test_allowed_transitions_match_agentrun_state_machine_rule_section_4() -> None:
    assert ALLOWED_TRANSITIONS == EXPECTED_ALLOWED_TRANSITIONS


def test_standard_transition_path_reaches_completed() -> None:
    standard_path: tuple[AgentRunStatus, ...] = (
        "queued",
        "gathering_context",
        "running",
        "generated_artifact",
        "schema_validated",
        "policy_linted",
        "diff_ready",
        "waiting_approval",
        "running",
        "completed",
    )

    for from_state, to_state in zip(standard_path, standard_path[1:], strict=True):
        assert validate_transition(from_state, to_state) == to_state


@pytest.mark.parametrize(
    "terminal_state",
    ["completed", "failed", "cancelled", "provider_refused", "repair_exhausted"],
)
def test_terminal_states_reject_any_transition(terminal_state: AgentRunStatus) -> None:
    with pytest.raises(ValueError, match="terminal AgentRun state cannot transition"):
        validate_transition(terminal_state, "running")


def test_provider_incomplete_can_resume_to_running() -> None:
    assert validate_transition("provider_incomplete", "running") == "running"


def test_validation_failed_can_repair_retry_to_running() -> None:
    assert validate_transition("validation_failed", "running") == "running"


def test_validation_failed_can_transition_to_repair_exhausted() -> None:
    assert validate_transition("validation_failed", "repair_exhausted") == "repair_exhausted"


@pytest.mark.parametrize("resume_state", ["waiting_approval", "running"])
def test_blocked_can_resume_to_waiting_approval_or_running(
    resume_state: AgentRunStatus,
) -> None:
    assert validate_transition("blocked", resume_state) == resume_state


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        ("queued", "completed"),
        ("generated_artifact", "policy_linted"),
        ("provider_refused", "running"),
        ("repair_exhausted", "running"),
    ],
)
def test_unknown_or_disallowed_transitions_raise_value_error(
    from_state: AgentRunStatus,
    to_state: AgentRunStatus,
) -> None:
    with pytest.raises(ValueError):
        validate_transition(from_state, to_state)

