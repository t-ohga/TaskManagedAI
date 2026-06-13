"""SP-029 (ADR-00055) shadow mode state machine の run_mode-gated transition test。

設計制約:
- 16 status / base ALLOWED_TRANSITIONS は不変 (run_mode は additive 直交次元)。
- shadow 合法 terminal ``schema_validated -> completed`` は **run_mode='shadow' のみ**
  許可、production は同 edge を使えない (run_mode-gated)。
- event_type は既存 ``run_completed`` を再利用 (新 event_type を増やさない)。
"""

from __future__ import annotations

import pytest

from backend.app.domain.agent_runtime.status import AgentRunStatus
from backend.app.services.agent_runtime.state_machine import (
    EVENT_TYPE_FOR_TRANSITION,
    SHADOW_EXTRA_TRANSITIONS,
    validate_transition,
)

EXPECTED_SHADOW_EXTRA_TRANSITIONS: dict[AgentRunStatus, frozenset[AgentRunStatus]] = {
    "schema_validated": frozenset({"completed"}),
}


def test_shadow_extra_transitions_match_expected() -> None:
    assert SHADOW_EXTRA_TRANSITIONS == EXPECTED_SHADOW_EXTRA_TRANSITIONS


def test_shadow_allows_schema_validated_to_completed() -> None:
    assert (
        validate_transition("schema_validated", "completed", "shadow") == "completed"
    )


def test_production_rejects_schema_validated_to_completed() -> None:
    with pytest.raises(ValueError, match="is not allowed"):
        validate_transition("schema_validated", "completed", "production")


def test_default_run_mode_rejects_shadow_terminal_edge() -> None:
    # run_mode default は production。shadow 専用 edge を使えない。
    with pytest.raises(ValueError, match="is not allowed"):
        validate_transition("schema_validated", "completed")


def test_shadow_terminal_uses_run_completed_event() -> None:
    assert EVENT_TYPE_FOR_TRANSITION[("schema_validated", "completed")] == frozenset(
        {"run_completed"}
    )


def test_shadow_still_honours_base_transitions() -> None:
    # base edge (schema_validated -> policy_linted) は shadow でも許可される
    # (shadow は base + extra の union)。
    assert (
        validate_transition("schema_validated", "policy_linted", "shadow")
        == "policy_linted"
    )


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        ("running", "completed"),  # production の正規 terminal は維持
        ("queued", "gathering_context"),
        ("waiting_approval", "running"),
    ],
)
def test_base_transitions_unchanged_for_both_modes(
    from_state: AgentRunStatus,
    to_state: AgentRunStatus,
) -> None:
    assert validate_transition(from_state, to_state, "production") == to_state
    assert validate_transition(from_state, to_state, "shadow") == to_state


def test_shadow_cannot_invent_new_terminal_from_other_states() -> None:
    # shadow extra edge は schema_validated -> completed のみ。他状態からの
    # 近道 completed は shadow でも不可 (extra を 1 edge に限定)。
    for from_state in ("policy_linted", "diff_ready", "gathering_context"):
        with pytest.raises(ValueError, match="is not allowed"):
            validate_transition(from_state, "completed", "shadow")
