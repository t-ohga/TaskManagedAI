from __future__ import annotations

from backend.app.domain.agent_runtime.budget import (
    BudgetCheckResult,
    BudgetExceedReason,
    BudgetLevel,
)
from backend.app.domain.agent_runtime.event_type import (
    ALL_AGENT_RUN_EVENT_TYPES,
    AgentRunEventType,
)
from backend.app.domain.agent_runtime.operation_context import (
    OperationContext,
    RequestedOperation,
    compute_fingerprint,
    compute_payload_hash,
)
from backend.app.domain.agent_runtime.snapshot_kind import (
    ALL_SNAPSHOT_KINDS,
    SnapshotKind,
)
from backend.app.domain.agent_runtime.status import (
    ALL_AGENT_RUN_STATUSES,
    ALL_BLOCKED_REASONS,
    TERMINAL_STATES,
    AgentRunStatus,
    BlockedReason,
)


def __getattr__(name: str) -> object:
    if name == "BudgetGuard":
        from backend.app.services.agent_runtime.budget_guard import BudgetGuard

        return BudgetGuard
    raise AttributeError(name)


__all__ = [
    "ALL_AGENT_RUN_EVENT_TYPES",
    "ALL_AGENT_RUN_STATUSES",
    "ALL_BLOCKED_REASONS",
    "ALL_SNAPSHOT_KINDS",
    "AgentRunEventType",
    "AgentRunStatus",
    "BlockedReason",
    "BudgetCheckResult",
    "BudgetExceedReason",
    "BudgetGuard",
    "BudgetLevel",
    "SnapshotKind",
    "OperationContext",
    "RequestedOperation",
    "TERMINAL_STATES",
    "compute_fingerprint",
    "compute_payload_hash",
]
