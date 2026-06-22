from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.domain.agent_runtime.budget import BudgetCheckResult
from backend.app.domain.policy.action_class import ActionClass, PolicyEffect
from backend.app.domain.provider.compliance import ComplianceDecision
from backend.app.services.policy import autonomy_policy_engine as engine
from backend.app.services.policy.autonomy_profile_resolver import (
    AutonomyPolicyProfileResolution,
    resolve_autonomy_policy_profile,
)
from backend.app.services.policy.low_risk_profile import LowRiskProfileInput
from backend.app.services.policy.profile_resolver import PolicyProfileResolvedEffect
from backend.app.services.tool_registry.network_policy import ToolNetworkDecision


def _profile_resolution(
    level: str,
    *,
    runtime_enabled: bool = True,
) -> AutonomyPolicyProfileResolution:
    return resolve_autonomy_policy_profile(level, runtime_enabled=runtime_enabled)


def _profile_effect(
    action_class: ActionClass,
    *,
    effect: PolicyEffect = "require_approval",
) -> PolicyProfileResolvedEffect:
    return PolicyProfileResolvedEffect(
        policy_profile="default",
        action_class=action_class,
        effect=effect,
        require_review_artifact=effect == "allow",
        reason_code="policy_profile_action_effect_resolved",
    )


def _low_risk_input(**overrides: object) -> LowRiskProfileInput:
    values: dict[str, object] = {
        "payload_data_class": "internal",
        "diff_line_count": 12,
        "changed_paths": ("docs/sprints/SP-024_autonomy_policy_profiles.md",),
        "commands": (),
        "provider_request_preflight_passed": True,
        "runner_mutation_gateway_passed": True,
        "context_snapshot_passed": True,
    }
    values.update(overrides)
    return LowRiskProfileInput(**values)  # type: ignore[arg-type]


def test_l0_never_auto_allows_even_when_low_risk_passes() -> None:
    decision = engine.evaluate_autonomy_policy_engine_decision(
        profile_resolution=_profile_resolution("L0", runtime_enabled=True),
        profile_effect=_profile_effect("task_write"),
        low_risk_input=_low_risk_input(),
    )

    assert decision.decision == "require_approval"
    assert decision.reason_code == "autonomy_runtime_disabled_fallback"
    assert decision.override_source is None


@pytest.mark.parametrize(
    ("level", "action_class"),
    [
        ("L1", "task_write"),
        ("L2", "task_write"),
        ("L2", "repo_write"),
        ("L3", "task_write"),
        ("L3", "repo_write"),
        ("L3", "pr_open"),
    ],
)
def test_l1_l3_matrix_auto_allows_only_low_risk_actions(
    level: str,
    action_class: ActionClass,
) -> None:
    decision = engine.evaluate_autonomy_policy_engine_decision(
        profile_resolution=_profile_resolution(level, runtime_enabled=True),
        profile_effect=_profile_effect(action_class),
        low_risk_input=_low_risk_input(),
    )

    assert decision.decision == "allow"
    assert decision.require_review_artifact is True
    assert decision.reason_code == "autonomy_matrix_auto_allow_applied"
    assert decision.low_risk_failed_axes == ()


@pytest.mark.parametrize(
    ("level", "action_class"),
    [
        ("L1", "repo_write"),
        ("L1", "pr_open"),
        ("L2", "pr_open"),
    ],
)
def test_matrix_falls_back_when_action_is_not_enabled_for_level(
    level: str,
    action_class: ActionClass,
) -> None:
    decision = engine.evaluate_autonomy_policy_engine_decision(
        profile_resolution=_profile_resolution(level, runtime_enabled=True),
        profile_effect=_profile_effect(action_class),
        low_risk_input=_low_risk_input(),
    )

    assert decision.decision == "require_approval"
    assert decision.reason_code == "autonomy_action_not_in_level_fallback"


@pytest.mark.parametrize(
    "action_class",
    ["secret_access", "merge", "deploy", "provider_call"],
)
def test_human_required_actions_never_auto_allow_even_if_profile_effect_allows(
    action_class: ActionClass,
) -> None:
    decision = engine.evaluate_autonomy_policy_engine_decision(
        profile_resolution=_profile_resolution("L3", runtime_enabled=True),
        profile_effect=_profile_effect(action_class, effect="allow"),
        low_risk_input=_low_risk_input(),
    )

    assert decision.decision == "require_approval"
    assert decision.reason_code == "autonomy_human_required_action_fallback"
    assert decision.profile_resolved_effect == "allow"


def test_low_risk_failure_falls_back_and_records_failed_axes() -> None:
    decision = engine.evaluate_autonomy_policy_engine_decision(
        profile_resolution=_profile_resolution("L3", runtime_enabled=True),
        profile_effect=_profile_effect("repo_write"),
        low_risk_input=_low_risk_input(payload_data_class="confidential"),
    )

    assert decision.decision == "require_approval"
    assert decision.reason_code == "autonomy_low_risk_profile_failed_fallback"
    assert decision.low_risk_failed_axes == ("payload_data_class",)


def test_missing_low_risk_input_falls_back() -> None:
    decision = engine.evaluate_autonomy_policy_engine_decision(
        profile_resolution=_profile_resolution("L3", runtime_enabled=True),
        profile_effect=_profile_effect("task_write"),
        low_risk_input=None,
    )

    assert decision.decision == "require_approval"
    assert decision.reason_code == "autonomy_low_risk_profile_missing_fallback"


@pytest.mark.parametrize(
    ("override_payload", "reason_code", "override_source"),
    [
        ({"global_kill_switch_enabled": True}, "autonomy_global_kill_switch_denied", "global_kill_switch"),
        (
            {
                "budget_result": BudgetCheckResult(
                    level="global",
                    exceeded=True,
                    current_usd=Decimal("1.00"),
                    hard_limit_usd=Decimal("0.00"),
                    soft_threshold_usd=None,
                    reason="global_kill_switch",
                )
            },
            "autonomy_budget_override_denied",
            "budget",
        ),
        (
            {
                "provider_decision": ComplianceDecision(
                    decision="deny",
                    reason_code="provider_not_in_matrix",
                    allowed_data_class=None,
                    effective_allowed_data_class=None,
                    payload_data_class="internal",
                    provider_compliance_matrix_version="pcm-v1",
                )
            },
            "autonomy_provider_block_denied",
            "provider",
        ),
        (
            {
                "tool_network_decision": ToolNetworkDecision(
                    tool_key="web_fetch",
                    network_access="none",
                    decision="deny",
                    reason_code="tool_network_access_none_denied",
                )
            },
            "autonomy_tool_deny_override_denied",
            "tool",
        ),
    ],
)
def test_deny_overrides_take_precedence_over_matrix_allow(
    override_payload: dict[str, Any],
    reason_code: str,
    override_source: str,
) -> None:
    decision = engine.evaluate_autonomy_policy_engine_decision(
        profile_resolution=_profile_resolution("L3", runtime_enabled=True),
        profile_effect=_profile_effect("task_write"),
        low_risk_input=_low_risk_input(),
        **override_payload,
    )

    assert decision.decision == "deny"
    assert decision.reason_code == reason_code
    assert decision.override_source == override_source


def test_profile_allow_cannot_leak_through_when_runtime_is_disabled() -> None:
    decision = engine.evaluate_autonomy_policy_engine_decision(
        profile_resolution=_profile_resolution("L3", runtime_enabled=False),
        profile_effect=_profile_effect("task_write", effect="allow"),
        low_risk_input=_low_risk_input(),
    )

    assert decision.decision == "require_approval"
    assert decision.reason_code == "autonomy_runtime_disabled_fallback"
    assert decision.profile_resolved_effect == "allow"


@pytest.mark.asyncio
async def test_async_policy_engine_uses_server_owned_profile_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_profile_effect_resolver(
        session: AsyncSession,
        *,
        tenant_id: int,
        policy_profile: str,
        action_class: ActionClass,
    ) -> PolicyProfileResolvedEffect:
        calls.append(
            {
                "session": session,
                "tenant_id": tenant_id,
                "policy_profile": policy_profile,
                "action_class": action_class,
            }
        )
        return _profile_effect(action_class)

    monkeypatch.setattr(
        engine,
        "resolve_policy_profile_action_effect",
        fake_profile_effect_resolver,
    )

    # SP-PHASE1 B5a: profile resolution の単離 test。emergency-stop latch 解決は dummy session では
    # fail-closed deny になるため、本 test では latch off を stub する (emergency-stop 経路は専用 test
    # ``test_autonomy_emergency_stop.py`` で検証)。
    async def _no_emergency_stop(_session: AsyncSession, _tenant_id: int) -> bool:
        return False

    monkeypatch.setattr(engine, "_resolve_emergency_stop_engaged", _no_emergency_stop)

    session = cast(AsyncSession, object())
    decision = await engine.resolve_autonomy_policy_action_effect(
        session,
        tenant_id=1,
        autonomy_level="L2",
        action_class="repo_write",
        low_risk_input=_low_risk_input(),
        runtime_enabled=True,
    )

    assert decision.decision == "allow"
    assert decision.policy_profile == "default"
    assert calls == [
        {
            "session": session,
            "tenant_id": 1,
            "policy_profile": "default",
            "action_class": "repo_write",
        }
    ]
