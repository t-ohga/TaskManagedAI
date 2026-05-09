from __future__ import annotations

from typing import Literal

AgentRunStatus = Literal[
    "queued",
    "gathering_context",
    "running",
    "generated_artifact",
    "schema_validated",
    "policy_linted",
    "diff_ready",
    "waiting_approval",
    "blocked",
    "provider_refused",
    "provider_incomplete",
    "validation_failed",
    "repair_exhausted",
    "completed",
    "failed",
    "cancelled",
]

ALL_AGENT_RUN_STATUSES: tuple[AgentRunStatus, ...] = (
    "queued",
    "gathering_context",
    "running",
    "generated_artifact",
    "schema_validated",
    "policy_linted",
    "diff_ready",
    "waiting_approval",
    "blocked",
    "provider_refused",
    "provider_incomplete",
    "validation_failed",
    "repair_exhausted",
    "completed",
    "failed",
    "cancelled",
)

TERMINAL_STATES: frozenset[AgentRunStatus] = frozenset(
    {
        "completed",
        "failed",
        "cancelled",
        "provider_refused",
        "repair_exhausted",
    }
)

BlockedReason = Literal["policy_blocked", "budget_blocked", "runtime_blocked"]

ALL_BLOCKED_REASONS: tuple[BlockedReason, ...] = (
    "policy_blocked",
    "budget_blocked",
    "runtime_blocked",
)

__all__ = [
    "ALL_AGENT_RUN_STATUSES",
    "ALL_BLOCKED_REASONS",
    "BlockedReason",
    "AgentRunStatus",
    "TERMINAL_STATES",
]

