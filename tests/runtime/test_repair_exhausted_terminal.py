"""Sprint 5.5 BL-0070: ``repair_exhausted`` terminal contract test.

Asserts at the state-machine level that every terminal state
(``completed`` / ``failed`` / ``cancelled`` / ``provider_refused`` /
``repair_exhausted``) rejects all 15 alternative target states, with
particular emphasis on ``repair_exhausted`` introduced by ADR-00004
§Sprint 5.5 update (event #23 + terminal #13).

Per Sprint Pack §「max_days 6 day 超過時の defer 順序」 the matrix is
restricted to terminal 5 states (75 pairs) for batch 2; the remaining
11 non-terminal-source invalid transitions are tackled in Sprint 6
worker once the full chain is wired.

Includes negative tests for ``EVENT_TYPE_FOR_TRANSITION``: even when
the source / target pair *would* be allowed by ``ALLOWED_TRANSITIONS``
(``validation_failed -> repair_exhausted``), only the dedicated
``repair_exhausted`` event_type can witness the transition (SP55-B1-R2-F-001
fix).
"""

from __future__ import annotations

import pytest

from backend.app.domain.agent_runtime.event_type import (
    ALL_AGENT_RUN_EVENT_TYPES,
    AgentRunEventType,
)
from backend.app.domain.agent_runtime.status import (
    ALL_AGENT_RUN_STATUSES,
    TERMINAL_STATES,
    AgentRunStatus,
)
from backend.app.services.agent_runtime.state_machine import (
    ALLOWED_TRANSITIONS,
    EVENT_TYPE_FOR_TRANSITION,
    validate_event_type_for_transition,
    validate_transition,
)

# ---------------------------------------------------------------------------
# Terminal contract: any transition from a terminal state must raise.
# ---------------------------------------------------------------------------


_TERMINAL_TARGET_MATRIX: list[tuple[AgentRunStatus, AgentRunStatus]] = [
    (terminal, target)
    for terminal in TERMINAL_STATES
    for target in ALL_AGENT_RUN_STATUSES
    if target != terminal
]


@pytest.mark.parametrize(
    ("terminal_state", "attempted_to_state"),
    _TERMINAL_TARGET_MATRIX,
)
def test_every_terminal_state_rejects_every_alternative_target(
    terminal_state: AgentRunStatus,
    attempted_to_state: AgentRunStatus,
) -> None:
    """5 terminals × 15 alternatives = 75 pairs all reject (75 / 16²)."""

    with pytest.raises(ValueError, match="terminal AgentRun state cannot transition"):
        validate_transition(terminal_state, attempted_to_state)


def test_repair_exhausted_is_one_of_the_five_terminal_states() -> None:
    """ADR-00004 §13 invariant: repair_exhausted is terminal (not in TERMINAL_STATES
    means the contract has drifted)."""

    assert "repair_exhausted" in TERMINAL_STATES
    assert set(TERMINAL_STATES) == {
        "completed",
        "failed",
        "cancelled",
        "provider_refused",
        "repair_exhausted",
    }


def test_repair_exhausted_has_no_outbound_transitions_in_allowlist() -> None:
    """ALLOWED_TRANSITIONS["repair_exhausted"] must be an empty frozenset."""

    assert ALLOWED_TRANSITIONS["repair_exhausted"] == frozenset()


@pytest.mark.parametrize(
    "attempted_to_state",
    [s for s in ALL_AGENT_RUN_STATUSES if s != "repair_exhausted"],
)
def test_repair_exhausted_rejects_resume_to_any_running_or_blocked_state(
    attempted_to_state: AgentRunStatus,
) -> None:
    """The repair-exhaustion terminal explicitly rejects ``running`` /
    ``gathering_context`` / ``blocked`` etc.; no 'retry after repair_exhausted'
    path may sneak in."""

    with pytest.raises(ValueError, match="terminal AgentRun state cannot transition"):
        validate_transition("repair_exhausted", attempted_to_state)


# ---------------------------------------------------------------------------
# event_type contract for validation_failed -> repair_exhausted.
# ---------------------------------------------------------------------------


def test_validation_failed_to_repair_exhausted_allows_only_repair_exhausted_event() -> None:
    """ADR-00004 §Sprint 5.5 update event #23: the dedicated event_type is
    the only one that may witness this terminal transition (SP55-B1-R2-F-001
    fix). ``validation_failed`` / ``run_failed`` are explicitly rejected so
    that audit trails surface repair-exhaustion as its own kind."""

    allowed = EVENT_TYPE_FOR_TRANSITION[("validation_failed", "repair_exhausted")]
    assert allowed == frozenset({"repair_exhausted"})


@pytest.mark.parametrize(
    "forbidden_event",
    [
        et
        for et in ALL_AGENT_RUN_EVENT_TYPES
        if et != "repair_exhausted"
    ],
)
def test_validation_failed_to_repair_exhausted_rejects_other_event_types(
    forbidden_event: AgentRunEventType,
) -> None:
    """Every non-``repair_exhausted`` event_type must be rejected for the
    terminal transition. 24 / 25 forbidden events form an exhaustive sweep."""

    with pytest.raises(ValueError, match="not allowed for transition"):
        validate_event_type_for_transition(
            "validation_failed",
            "repair_exhausted",
            forbidden_event,
        )


def test_validation_failed_to_repair_exhausted_accepts_dedicated_event() -> None:
    """Positive control: the dedicated event_type passes."""

    validate_event_type_for_transition(
        "validation_failed",
        "repair_exhausted",
        "repair_exhausted",
    )


# ---------------------------------------------------------------------------
# AgentRunEventType allowlist integrity (Sprint 5.5 expansion).
# ---------------------------------------------------------------------------


def test_sprint55_event_types_are_present_in_enum() -> None:
    """5+ source integrity sanity: the 3 new event_types added in Sprint 5.5
    (BL-0064/0065 / ADR-00004 §Sprint 5.5 update) must be exposed via the
    Python Literal + ALL tuple."""

    for new_event in ("repair_exhausted", "trust_level_promoted", "trust_level_promotion_denied"):
        assert new_event in ALL_AGENT_RUN_EVENT_TYPES
