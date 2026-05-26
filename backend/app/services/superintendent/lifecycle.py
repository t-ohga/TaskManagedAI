"""Agent lifecycle management by Superintendent.

State machine: registered → starting → running → stopping → stopped
                                    ↘ failed
                          killed (from any state via kill switch)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

AgentState = Literal[
    "registered",
    "starting",
    "running",
    "stopping",
    "stopped",
    "failed",
    "killed",
]

TERMINAL_STATES: frozenset[AgentState] = frozenset({"stopped", "failed", "killed"})


@dataclass
class ManagedAgent:
    agent_id: UUID
    actor_id: UUID
    role_id: str
    state: AgentState
    project_id: UUID
    superintendent_id: UUID
    created_at: datetime
    started_at: datetime | None = None
    stopped_at: datetime | None = None


def can_transition(current: AgentState, target: AgentState) -> bool:
    allowed: dict[AgentState, set[AgentState]] = {
        "registered": {"starting", "killed"},
        "starting": {"running", "failed", "killed"},
        "running": {"stopping", "failed", "killed"},
        "stopping": {"stopped", "failed", "killed"},
        "stopped": set(),
        "failed": set(),
        "killed": set(),
    }
    return target in allowed.get(current, set())
