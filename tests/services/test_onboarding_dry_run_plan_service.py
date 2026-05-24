from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.domain.policy.action_class import ActionClass, PolicyEffect
from backend.app.schemas.onboarding import OnboardingDryRunPlanRequest
from backend.app.services.onboarding import dry_run_plan
from backend.app.services.onboarding.dry_run_plan import (
    OnboardingProjectContext,
    build_onboarding_dry_run_plan,
)
from backend.app.services.policy.autonomy_policy_engine import (
    AutonomyPolicyEngineDecision,
)

_ACTOR_ID = UUID("00000000-0000-4000-8000-000000009501")
_PROJECT_ID = UUID("00000000-0000-4000-8000-000000009502")


class _NoMutationSession:
    def add(self, *_: object, **__: object) -> None:
        raise AssertionError("dry-run service must not add ORM objects")

    async def flush(self, *_: object, **__: object) -> None:
        raise AssertionError("dry-run service must not flush")

    async def commit(self) -> None:
        raise AssertionError("dry-run service must not commit")

    async def execute(self, *_: object, **__: object) -> object:
        raise AssertionError("dry-run service must not query for read-only plans")


def _request(**overrides: object) -> OnboardingDryRunPlanRequest:
    values: dict[str, object] = {
        "purpose": "Summarize the current sprint readiness.",
        "target_repo_ref": "t-ohga/TaskManagedAI",
        "expected_artifact": "A reviewed implementation plan.",
        "allowed_action_class": "read_only",
        "budget_cap": "0 USD committed",
        "starter_mode": "research_only",
    }
    values.update(overrides)
    return OnboardingDryRunPlanRequest(**values)  # type: ignore[arg-type]


def _context() -> OnboardingProjectContext:
    return OnboardingProjectContext(
        tenant_id=1,
        actor_id=_ACTOR_ID,
        project_id=_PROJECT_ID,
        autonomy_level="L3",
    )


def _decision(
    *,
    action_class: ActionClass,
    decision: PolicyEffect,
    reason_code: str = "autonomy_runtime_disabled_fallback",
) -> AutonomyPolicyEngineDecision:
    return AutonomyPolicyEngineDecision(
        autonomy_level="L3",
        policy_profile="default",
        action_class=action_class,
        decision=decision,
        profile_resolved_effect="allow",
        require_review_artifact=False,
        reason_code=reason_code,  # type: ignore[arg-type]
        profile_reason_code="policy_profile_action_effect_resolved",
        low_risk_failed_axes=(),
        override_source=None,
    )


def test_schema_rejects_server_owned_or_execution_fields() -> None:
    for forbidden_field in (
        "policy_profile",
        "tenant_id",
        "project_id",
        "actor_id",
        "approval_id",
        "run_id",
        "provider_request",
    ):
        with pytest.raises(ValidationError):
            _request(**{forbidden_field: "caller-supplied"})


@pytest.mark.parametrize("action_class", ["secret_access", "merge", "deploy", "provider_call"])
def test_schema_rejects_high_risk_action_classes(action_class: str) -> None:
    with pytest.raises(ValidationError):
        _request(allowed_action_class=action_class)


@pytest.mark.asyncio
@pytest.mark.parametrize("starter_mode", ["research_only", "plan_only"])
async def test_read_only_starter_modes_never_create_state(starter_mode: str) -> None:
    session = cast(AsyncSession, _NoMutationSession())
    response = await build_onboarding_dry_run_plan(
        session,
        project_context=_context(),
        request=_request(
            starter_mode=starter_mode,
            allowed_action_class="pr_open",
            purpose="Investigate the next safe implementation step.",
        ),
    )

    plan = response.dry_run_plan
    assert plan.requested_action_class == "pr_open"
    assert plan.effective_action_class == "read_only"
    assert plan.policy_effect == "allow"
    assert plan.approval_required is False
    assert plan.risk_level == "low"
    assert plan.would_create.model_dump() == {
        "ticket": False,
        "agent_run": False,
        "approval": False,
        "notification": False,
        "audit_event": False,
        "repository_operation": False,
        "provider_call": False,
    }
    assert "starter_mode_forces_read_only" in plan.blocked_reasons


@pytest.mark.asyncio
async def test_draft_pr_runtime_disabled_requires_approval_and_does_not_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_resolver(
        session: AsyncSession,
        *,
        tenant_id: int,
        autonomy_level: str,
        action_class: ActionClass,
        low_risk_input: object,
        runtime_enabled: bool,
    ) -> AutonomyPolicyEngineDecision:
        calls.append(
            {
                "session": session,
                "tenant_id": tenant_id,
                "autonomy_level": autonomy_level,
                "action_class": action_class,
                "low_risk_input": low_risk_input,
                "runtime_enabled": runtime_enabled,
            }
        )
        return _decision(action_class=action_class, decision="require_approval")

    monkeypatch.setattr(
        dry_run_plan,
        "resolve_autonomy_policy_action_effect",
        fake_resolver,
    )

    session = cast(AsyncSession, _NoMutationSession())
    response = await build_onboarding_dry_run_plan(
        session,
        project_context=_context(),
        request=_request(
            starter_mode="draft_pr_requires_approval",
            allowed_action_class="pr_open",
            purpose="Prepare a draft PR plan without starting execution.",
        ),
    )

    plan = response.dry_run_plan
    assert plan.effective_action_class == "pr_open"
    assert plan.policy_effect == "require_approval"
    assert plan.approval_required is True
    assert plan.risk_level == "high"
    assert "approval_required_before_execution" in plan.blocked_reasons
    assert plan.would_create.model_dump() == {
        "ticket": False,
        "agent_run": False,
        "approval": False,
        "notification": False,
        "audit_event": False,
        "repository_operation": False,
        "provider_call": False,
    }
    assert calls == [
        {
            "session": session,
            "tenant_id": 1,
            "autonomy_level": "L3",
            "action_class": "pr_open",
            "low_risk_input": None,
            "runtime_enabled": False,
        }
    ]


@pytest.mark.asyncio
async def test_runtime_disabled_allow_is_fail_closed_to_require_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolver(
        session: AsyncSession,
        **kwargs: object,
    ) -> AutonomyPolicyEngineDecision:
        assert isinstance(session, _NoMutationSession)
        return _decision(
            action_class=cast(ActionClass, kwargs["action_class"]),
            decision="allow",
            reason_code="autonomy_matrix_auto_allow_applied",
        )

    monkeypatch.setattr(
        dry_run_plan,
        "resolve_autonomy_policy_action_effect",
        fake_resolver,
    )

    response = await build_onboarding_dry_run_plan(
        cast(AsyncSession, _NoMutationSession()),
        project_context=_context(),
        request=_request(
            starter_mode="draft_pr_requires_approval",
            allowed_action_class="task_write",
        ),
    )

    plan = response.dry_run_plan
    assert plan.policy_effect == "require_approval"
    assert plan.approval_required is True
    assert "runtime_disabled_allow_downgraded_to_require_approval" in plan.blocked_reasons


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field_name",
    ["purpose", "target_repo_ref", "expected_artifact", "budget_cap"],
)
async def test_raw_secret_canary_is_rejected_before_response_construction(
    field_name: str,
) -> None:
    request = _request(**{field_name: "sk-" + ("A" * 24)})

    with pytest.raises(ValueError, match="raw secret"):
        await build_onboarding_dry_run_plan(
            cast(AsyncSession, _NoMutationSession()),
            project_context=_context(),
            request=request,
        )


@pytest.mark.asyncio
async def test_response_excludes_raw_intake_text_and_sensitive_keys() -> None:
    raw_purpose = "Write a plan using this exact operator note."
    response = await build_onboarding_dry_run_plan(
        cast(AsyncSession, _NoMutationSession()),
        project_context=_context(),
        request=_request(purpose=raw_purpose),
    )

    encoded = response.model_dump_json()
    assert raw_purpose not in encoded
    for forbidden in (
        "provider_request",
        "raw_token",
        "raw_secret",
        "capability_token",
        "stack_trace",
        "policy_profile",
    ):
        assert forbidden not in encoded
