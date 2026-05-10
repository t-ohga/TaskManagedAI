from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from backend.app.domain.agent_runtime.status import (
    TERMINAL_STATES,
    AgentRunStatus,
    BlockedReason,
)

ProviderResultKind = Literal[
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
]

ALL_PROVIDER_RESULT_KINDS: tuple[ProviderResultKind, ...] = (
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


@dataclass(frozen=True, slots=True)
class AgentRunStatusTransitionTarget:
    status: AgentRunStatus
    blocked_reason: BlockedReason | None = None
    is_terminal: bool = False


_PROVIDER_RESULT_MAPPING: dict[ProviderResultKind, tuple[AgentRunStatus, BlockedReason | None]] = {
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


def map_provider_result_to_status(
    kind: ProviderResultKind,
    *,
    timeout_retryable_as_failed: bool = False,
) -> AgentRunStatusTransitionTarget:
    """Map provider adapter result categories to AgentRun state-machine targets.

    `.claude/rules/agentrun-state-machine.md` §7 allows timeout retryable to map
    to either `provider_incomplete` or `failed`. The default keeps retry/resume
    possible; callers that have exhausted retry budget can set
    `timeout_retryable_as_failed=True`.
    """

    if kind not in ALL_PROVIDER_RESULT_KINDS:
        raise ValueError(f"unknown provider result kind: {kind!r}")

    if kind == "timeout_retryable" and timeout_retryable_as_failed:
        status: AgentRunStatus = "failed"
        blocked_reason: BlockedReason | None = None
    else:
        status, blocked_reason = _PROVIDER_RESULT_MAPPING[cast(ProviderResultKind, kind)]

    return AgentRunStatusTransitionTarget(
        status=status,
        blocked_reason=blocked_reason,
        is_terminal=status in TERMINAL_STATES,
    )


__all__ = [
    "ALL_PROVIDER_RESULT_KINDS",
    "AgentRunStatusTransitionTarget",
    "ProviderResultKind",
    "map_provider_result_to_status",
]

