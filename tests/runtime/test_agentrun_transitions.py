from __future__ import annotations

import pytest

from backend.app.domain.agent_runtime.status import AgentRunStatus
from backend.app.services.agent_runtime.state_machine import (
    ALLOWED_TRANSITIONS,
    BLOCKED_EVENT_TYPE_REASON_MAPPING,
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
    # SP-PHASE1 B1 (ADR-00048 A-5): emergency-stop resume restores pre_stop_status
    # (policy_linted / diff_ready are new resume targets; waiting_approval / running
    # pre-existed). enum (16 status) unchanged, transition mapping only.
    "blocked": frozenset(
        {
            "waiting_approval",
            "running",
            "policy_linted",
            "diff_ready",
            "failed",
            "cancelled",
        }
    ),
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


# ---------------------------------------------------------------------------
# SP-PHASE1 B1 (ADR-00048 §Amendment A-5 / A-6): emergency-stop block & resume
# transitions are witnessed by dedicated event types (emergency_stop_engaged /
# emergency_stop_resumed). status (16) + blocked_reason (3) enums are unchanged;
# only transition mappings are extended (union, no existing edge/event removed).
# ---------------------------------------------------------------------------

# block source states allowed by ADR-00048 (D)/(H): only valid -> blocked edges.
_EMERGENCY_BLOCK_SOURCES: tuple[AgentRunStatus, ...] = (
    "running",
    "policy_linted",
    "diff_ready",
    "waiting_approval",
)

# pre_stop_status resume targets (B-3 restore table, gate skip 防止).
_EMERGENCY_RESUME_TARGETS: tuple[AgentRunStatus, ...] = (
    "running",
    "policy_linted",
    "diff_ready",
    "waiting_approval",
)


@pytest.mark.parametrize("from_state", _EMERGENCY_BLOCK_SOURCES)
def test_emergency_stop_block_transition_is_allowed(from_state: AgentRunStatus) -> None:
    """Each valid block source -> blocked is allowed and witnessed by the
    dedicated ``emergency_stop_engaged`` event."""

    assert validate_transition(from_state, "blocked") == "blocked"
    assert "emergency_stop_engaged" in EVENT_TYPE_FOR_TRANSITION[(from_state, "blocked")]
    validate_event_type_for_transition(from_state, "blocked", "emergency_stop_engaged")


def test_emergency_stop_engaged_maps_to_runtime_blocked_reason() -> None:
    """A-6: dedicated event keeps blocked_reason enum unchanged (runtime_blocked)."""

    assert BLOCKED_EVENT_TYPE_REASON_MAPPING["emergency_stop_engaged"] == "runtime_blocked"


@pytest.mark.parametrize("to_state", _EMERGENCY_RESUME_TARGETS)
def test_emergency_stop_resume_transition_is_allowed(to_state: AgentRunStatus) -> None:
    """blocked -> pre_stop_status is allowed and witnessed by the dedicated
    ``emergency_stop_resumed`` event."""

    assert validate_transition("blocked", to_state) == to_state
    assert "emergency_stop_resumed" in EVENT_TYPE_FOR_TRANSITION[("blocked", to_state)]
    validate_event_type_for_transition("blocked", to_state, "emergency_stop_resumed")


@pytest.mark.parametrize("pipeline_target", ["policy_linted", "diff_ready"])
def test_emergency_stop_resume_to_pipeline_is_denied_for_shadow(
    pipeline_target: AgentRunStatus,
) -> None:
    """SP-PHASE1 B1 (adversarial MEDIUM fix): the new emergency-stop resume edges
    blocked->policy_linted / blocked->diff_ready are production-only. shadow runs
    cannot reach the side-effect pipeline (SP-029/ADR-00055 primary defense), so
    SHADOW_FORBIDDEN_TRANSITIONS strips these resume edges for run_mode='shadow'.
    Production keeps them (pre_stop_status restore)."""

    # production: allowed (pre_stop_status restore).
    assert validate_transition("blocked", pipeline_target, "production") == pipeline_target
    # shadow: denied (confinement restored).
    with pytest.raises(ValueError, match="not allowed"):
        validate_transition("blocked", pipeline_target, "shadow")


@pytest.mark.parametrize(
    "non_block_source",
    [
        "queued",
        "gathering_context",
        "generated_artifact",
        "schema_validated",
        "validation_failed",
        "provider_incomplete",
    ],
)
def test_emergency_stop_engaged_rejected_from_non_block_source(
    non_block_source: AgentRunStatus,
) -> None:
    """ADR-00048 (D): non block-source states must not be directly transitioned
    to blocked via the emergency-stop event (latch covers new-activity deny
    instead, so no illegal transition history is created).

    For sources that have no (src, blocked) mapping at all the mapping lookup
    raises; for sources whose -> blocked edge is not even allowed the transition
    itself raises. Either way the emergency event is rejected.
    """

    with pytest.raises(ValueError):
        # blocked is not a legal target for these sources, so validate_transition
        # rejects first; even where a (src, blocked) edge existed it would not
        # contain emergency_stop_engaged.
        validate_transition(non_block_source, "blocked")


def test_emergency_stop_engaged_not_allowed_on_non_emergency_block_edges() -> None:
    """The emergency event must not leak into non-emergency block witnessing
    (e.g. the budget-only diff_ready edge previously had no emergency event)."""

    # diff_ready -> blocked legitimately includes policy/budget; ensure the
    # emergency event is additive and the legacy events are still present.
    diff_ready_block = EVENT_TYPE_FOR_TRANSITION[("diff_ready", "blocked")]
    assert {"policy_blocked", "budget_blocked"} <= diff_ready_block
    assert "emergency_stop_engaged" in diff_ready_block


def test_emergency_resumed_not_allowed_on_non_resume_edges() -> None:
    """``emergency_stop_resumed`` must not be accepted for terminal blocked exits
    (blocked -> failed / cancelled) which keep their own dedicated events."""

    for terminal_to in ("failed", "cancelled"):
        allowed = EVENT_TYPE_FOR_TRANSITION[("blocked", terminal_to)]
        assert "emergency_stop_resumed" not in allowed
        with pytest.raises(ValueError, match="not allowed for transition"):
            validate_event_type_for_transition(
                "blocked",
                terminal_to,  # type: ignore[arg-type]
                "emergency_stop_resumed",
            )

