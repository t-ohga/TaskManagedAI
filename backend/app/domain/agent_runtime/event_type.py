from __future__ import annotations

from typing import Literal

AgentRunEventType = Literal[
    "run_queued",
    "context_gathered",
    "provider_requested",
    "provider_responded",
    "artifact_generated",
    "schema_validated",
    "validation_failed",
    "repair_retry_scheduled",
    "policy_linted",
    "policy_blocked",
    "budget_blocked",
    "runtime_blocked",
    "diff_ready",
    "approval_requested",
    "approval_decided",
    "runner_started",
    "runner_completed",
    "runner_blocked",
    "repo_pr_opened",
    "run_completed",
    "run_failed",
    "run_cancelled",
    "repair_exhausted",
    "trust_level_promoted",
    "trust_level_promotion_denied",
]

ALL_AGENT_RUN_EVENT_TYPES: tuple[AgentRunEventType, ...] = (
    "run_queued",
    "context_gathered",
    "provider_requested",
    "provider_responded",
    "artifact_generated",
    "schema_validated",
    "validation_failed",
    "repair_retry_scheduled",
    "policy_linted",
    "policy_blocked",
    "budget_blocked",
    "runtime_blocked",
    "diff_ready",
    "approval_requested",
    "approval_decided",
    "runner_started",
    "runner_completed",
    "runner_blocked",
    "repo_pr_opened",
    "run_completed",
    "run_failed",
    "run_cancelled",
    "repair_exhausted",
    "trust_level_promoted",
    "trust_level_promotion_denied",
)

__all__ = ["ALL_AGENT_RUN_EVENT_TYPES", "AgentRunEventType"]

