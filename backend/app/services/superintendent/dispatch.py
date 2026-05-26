"""Workflow dispatch: Superintendent assigns tickets to agents."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from backend.app.services.superintendent.delegation_policy import (
    DelegationPolicy,
    can_auto_approve,
    is_action_allowed,
)


@dataclass(frozen=True, slots=True)
class DispatchRequest:
    superintendent_id: UUID
    agent_id: UUID
    ticket_id: str
    project_id: UUID
    action_class: str
    risk_level: str


@dataclass(frozen=True, slots=True)
class DispatchResult:
    dispatched: bool
    run_id: str | None = None
    deny_reason: str | None = None
    needs_human_approval: bool = False


def evaluate_dispatch(
    request: DispatchRequest,
    policy: DelegationPolicy,
) -> DispatchResult:
    if not is_action_allowed(policy, request.action_class):
        return DispatchResult(
            dispatched=False,
            deny_reason=f"action '{request.action_class}' is forbidden by delegation policy",
        )

    if can_auto_approve(policy, request.risk_level):
        return DispatchResult(
            dispatched=True,
            run_id="pending-creation",
            needs_human_approval=False,
        )

    return DispatchResult(
        dispatched=True,
        run_id="pending-creation",
        needs_human_approval=True,
    )
