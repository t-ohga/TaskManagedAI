from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

StarterMode = Literal["research_only", "plan_only", "draft_pr_requires_approval"]
RequestedActionClass = Literal["read_only", "task_write", "repo_write", "pr_open"]
EffectiveActionClass = RequestedActionClass
RiskLevel = Literal["low", "medium", "high"]
SafeRoute = Literal["/settings", "/today", "/timeline", "/approvals", "/runs"]


class OnboardingDryRunPlanRequest(BaseModel):
    """First-run guided intake request.

    The request deliberately excludes server-owned policy/profile fields and all
    execution identifiers. F2 is a response-only dry run, not an execution start.
    """

    model_config = ConfigDict(extra="forbid")

    purpose: str = Field(min_length=1, max_length=4000)
    target_repo_ref: str | None = Field(default=None, max_length=500)
    expected_artifact: str = Field(min_length=1, max_length=1000)
    allowed_action_class: RequestedActionClass
    budget_cap: str | None = Field(default=None, max_length=100)
    due_at: datetime | None = None
    reviewer_actor_id: UUID | None = None
    starter_mode: StarterMode

    @field_validator("purpose", "target_repo_ref", "expected_artifact", "budget_cap")
    @classmethod
    def _strip_and_reject_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class OnboardingDryRunWouldCreate(BaseModel):
    """Mutation ledger for the response-only onboarding dry run."""

    model_config = ConfigDict(extra="forbid")

    ticket: Literal[False] = False
    agent_run: Literal[False] = False
    approval: Literal[False] = False
    notification: Literal[False] = False
    audit_event: Literal[False] = False
    repository_operation: Literal[False] = False
    provider_call: Literal[False] = False


class OnboardingDryRunPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starter_mode: StarterMode
    requested_action_class: RequestedActionClass
    effective_action_class: EffectiveActionClass
    policy_effect: Literal["allow", "deny", "require_approval"]
    approval_required: bool
    risk_level: RiskLevel
    estimated_cost: str
    rollback_plan: str
    test_plan: list[str]
    blocked_reasons: list[str]
    next_safe_routes: list[SafeRoute]
    would_create: OnboardingDryRunWouldCreate


class OnboardingDryRunPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run_plan: OnboardingDryRunPlan


__all__ = [
    "EffectiveActionClass",
    "OnboardingDryRunPlan",
    "OnboardingDryRunPlanRequest",
    "OnboardingDryRunPlanResponse",
    "OnboardingDryRunWouldCreate",
    "RequestedActionClass",
    "RiskLevel",
    "SafeRoute",
    "StarterMode",
]
