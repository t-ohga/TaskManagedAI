from __future__ import annotations

import pytest

from backend.app.domain.agent_runtime.status import AgentRunStatus
from backend.app.services.agent_runtime.state_machine import (
    ALLOWED_TRANSITIONS,
    EVENT_TYPE_FOR_TRANSITION,
    validate_event_type_for_transition,
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

    # `zip(seq, seq[1:], strict=True)` は数学的に必ず fail する (seq[1:] は seq より 1 短い)。
    # 隣接ペアの iterate には strict=True 不可、strict=False を明示 (B905) で意図を明確化。
    # 2026-05-10 fix (Sprint 4 commit 88dece3 由来の test bug)。
    for from_state, to_state in zip(standard_path, standard_path[1:], strict=False):
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


# ---------------------------------------------------------------------------
# Sprint 5.5 additions (BL-0064 / SP55-B1-R2-F-001): the validation_failed ->
# repair_exhausted transition MUST be witnessed by the dedicated
# ``repair_exhausted`` event_type, not ``validation_failed`` / ``run_failed``.
# ---------------------------------------------------------------------------


def test_validation_failed_to_repair_exhausted_only_accepts_repair_exhausted_event() -> None:
    """ADR-00004 §Sprint 5.5 update event #23 — terminal repair-exhaustion is
    audited by its own event_type, not folded into validation_failed / run_failed.
    """

    assert EVENT_TYPE_FOR_TRANSITION[
        ("validation_failed", "repair_exhausted")
    ] == frozenset({"repair_exhausted"})


def test_validate_event_type_for_repair_exhausted_transition_accepts_dedicated_event() -> None:
    validate_event_type_for_transition(
        "validation_failed", "repair_exhausted", "repair_exhausted"
    )


@pytest.mark.parametrize(
    "forbidden_event",
    ["validation_failed", "run_failed", "repair_retry_scheduled", "policy_blocked"],
)
def test_validate_event_type_for_repair_exhausted_rejects_other_events(
    forbidden_event: str,
) -> None:
    with pytest.raises(ValueError, match="not allowed for transition"):
        validate_event_type_for_transition(
            "validation_failed",
            "repair_exhausted",
            forbidden_event,  # type: ignore[arg-type]
        )

