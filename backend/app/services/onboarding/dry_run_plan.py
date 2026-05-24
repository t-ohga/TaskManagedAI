from __future__ import annotations

from dataclasses import dataclass
from typing import Final, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.domain.policy.action_class import ActionClass, PolicyEffect
from backend.app.domain.policy.autonomy_level import AutonomyLevel
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.schemas.onboarding import (
    EffectiveActionClass,
    OnboardingDryRunPlan,
    OnboardingDryRunPlanRequest,
    OnboardingDryRunPlanResponse,
    OnboardingDryRunWouldCreate,
    RequestedActionClass,
    RiskLevel,
    SafeRoute,
)
from backend.app.services.policy.autonomy_policy_engine import (
    resolve_autonomy_policy_action_effect,
)

_READ_ONLY_ROUTES: Final[list[SafeRoute]] = ["/settings", "/today", "/timeline"]
_MUTATING_REVIEW_ROUTES: Final[list[SafeRoute]] = ["/approvals", "/runs", "/timeline"]


@dataclass(frozen=True)
class OnboardingProjectContext:
    tenant_id: int
    actor_id: UUID
    project_id: UUID
    autonomy_level: AutonomyLevel


async def build_onboarding_dry_run_plan(
    session: AsyncSession,
    *,
    project_context: OnboardingProjectContext,
    request: OnboardingDryRunPlanRequest,
) -> OnboardingDryRunPlanResponse:
    """Build a deterministic first-run plan without creating execution state."""

    assert_onboarding_dry_run_request_has_no_raw_secret(request)
    effective_action_class = _resolve_effective_action_class(request)

    if effective_action_class == "read_only":
        return OnboardingDryRunPlanResponse(
            dry_run_plan=_build_read_only_plan(
                request=request,
                effective_action_class=effective_action_class,
            )
        )

    decision = await resolve_autonomy_policy_action_effect(
        session,
        tenant_id=project_context.tenant_id,
        autonomy_level=project_context.autonomy_level,
        action_class=cast(ActionClass, effective_action_class),
        low_risk_input=None,
        runtime_enabled=False,
    )
    policy_effect: PolicyEffect = decision.decision
    blocked_reasons = ["dry_run_only_no_execution_started", decision.reason_code]
    if policy_effect == "allow":
        policy_effect = "require_approval"
        blocked_reasons.append("runtime_disabled_allow_downgraded_to_require_approval")
    if policy_effect == "require_approval":
        blocked_reasons.append("approval_required_before_execution")
    elif policy_effect == "deny":
        blocked_reasons.append("policy_denied_future_execution_candidate")

    return OnboardingDryRunPlanResponse(
        dry_run_plan=OnboardingDryRunPlan(
            starter_mode=request.starter_mode,
            requested_action_class=request.allowed_action_class,
            effective_action_class=effective_action_class,
            policy_effect=policy_effect,
            approval_required=policy_effect == "require_approval",
            risk_level=_risk_level_for(effective_action_class),
            estimated_cost="0 committed; no provider call was performed by this dry run.",
            rollback_plan="No rollback is required because the dry run creates no persisted state.",
            test_plan=_test_plan_for(effective_action_class),
            blocked_reasons=blocked_reasons,
            next_safe_routes=_MUTATING_REVIEW_ROUTES,
            would_create=OnboardingDryRunWouldCreate(),
        )
    )


def assert_onboarding_dry_run_request_has_no_raw_secret(
    request: OnboardingDryRunPlanRequest,
) -> None:
    assert_no_raw_secret(
        {
            "purpose_text": request.purpose,
            "target_repo_ref_text": request.target_repo_ref,
            "expected_artifact_text": request.expected_artifact,
            "budget_cap_text": request.budget_cap,
        },
        path="$.onboarding_dry_run_request",
    )


def _resolve_effective_action_class(
    request: OnboardingDryRunPlanRequest,
) -> EffectiveActionClass:
    if request.starter_mode in ("research_only", "plan_only"):
        return "read_only"
    return request.allowed_action_class


def _build_read_only_plan(
    *,
    request: OnboardingDryRunPlanRequest,
    effective_action_class: EffectiveActionClass,
) -> OnboardingDryRunPlan:
    blocked_reasons = ["dry_run_only_no_execution_started"]
    if request.starter_mode in ("research_only", "plan_only"):
        blocked_reasons.append("starter_mode_forces_read_only")
    elif request.allowed_action_class == "read_only":
        blocked_reasons.append("requested_upper_bound_read_only")

    return OnboardingDryRunPlan(
        starter_mode=request.starter_mode,
        requested_action_class=request.allowed_action_class,
        effective_action_class=effective_action_class,
        policy_effect="allow",
        approval_required=False,
        risk_level="low",
        estimated_cost="0 committed; no provider call was performed by this dry run.",
        rollback_plan="No rollback is required because the dry run creates no persisted state.",
        test_plan=_test_plan_for(effective_action_class),
        blocked_reasons=blocked_reasons,
        next_safe_routes=_READ_ONLY_ROUTES,
        would_create=OnboardingDryRunWouldCreate(),
    )


def _risk_level_for(action_class: RequestedActionClass) -> RiskLevel:
    if action_class == "read_only":
        return "low"
    if action_class == "task_write":
        return "medium"
    return "high"


def _test_plan_for(action_class: EffectiveActionClass) -> list[str]:
    base_steps = [
        "Review the generated plan before any execution is started.",
        "Confirm the current project and autonomy settings in Settings.",
    ]
    if action_class == "read_only":
        return base_steps + ["Use Timeline or Today as the next read-only inspection surface."]
    return base_steps + [
        "Confirm an approval request would be required before creating execution state.",
        "Verify no ticket, AgentRun, approval, notification, audit, provider, or repository operation was created.",
    ]


__all__ = [
    "OnboardingProjectContext",
    "assert_onboarding_dry_run_request_has_no_raw_secret",
    "build_onboarding_dry_run_plan",
]
