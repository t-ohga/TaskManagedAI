from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.domain.agent_runtime.budget import BudgetCheckResult
from backend.app.domain.policy.action_class import ActionClass, PolicyEffect
from backend.app.domain.policy.autonomy_level import AutonomyLevel
from backend.app.domain.provider.compliance import ComplianceDecision
from backend.app.services.policy.autonomy_profile_resolver import (
    AutonomyPolicyProfileResolution,
    resolve_autonomy_policy_profile,
)
from backend.app.services.policy.low_risk_profile import (
    LowRiskProfileAxis,
    LowRiskProfileInput,
    evaluate_low_risk_profile,
)
from backend.app.services.policy.profile_resolver import (
    PolicyProfileResolvedEffect,
    resolve_policy_profile_action_effect,
)
from backend.app.services.tool_registry.network_policy import ToolNetworkDecision

_EMPTY_ACTION_SET: Final[frozenset[ActionClass]] = frozenset()

AUTONOMY_ACTION_ALLOW_MATRIX: Final[dict[AutonomyLevel, frozenset[ActionClass]]] = {
    "L0": _EMPTY_ACTION_SET,
    "L1": cast(frozenset[ActionClass], frozenset({"task_write"})),
    "L2": cast(frozenset[ActionClass], frozenset({"task_write", "repo_write"})),
    "L3": cast(frozenset[ActionClass], frozenset({"task_write", "repo_write", "pr_open"})),
}
HUMAN_REQUIRED_ACTION_CLASSES: Final[frozenset[ActionClass]] = cast(
    frozenset[ActionClass],
    frozenset({"secret_access", "merge", "deploy", "provider_call"}),
)

AutonomyPolicyReasonCode = Literal[
    # SP-PHASE1 B5a (ADR-00048 §A-8): emergency-stop latch deny。budget global_kill_switch とは
    # 別目的 (latch=human 即時全停止 / kill_switch=コスト緊急停止) で choke point で OR 評価する。
    "autonomy_emergency_stop_denied",
    "autonomy_global_kill_switch_denied",
    "autonomy_budget_override_denied",
    "autonomy_provider_block_denied",
    "autonomy_tool_deny_override_denied",
    "autonomy_human_required_action_fallback",
    "autonomy_runtime_disabled_fallback",
    "autonomy_action_not_in_level_fallback",
    "autonomy_low_risk_profile_missing_fallback",
    "autonomy_low_risk_profile_failed_fallback",
    "autonomy_matrix_auto_allow_applied",
]
AutonomyOverrideSource = Literal[
    "emergency_stop", "global_kill_switch", "budget", "provider", "tool"
]


@dataclass(frozen=True)
class AutonomyPolicyEngineDecision:
    autonomy_level: AutonomyLevel
    policy_profile: str
    action_class: ActionClass
    decision: PolicyEffect
    profile_resolved_effect: PolicyEffect
    require_review_artifact: bool
    reason_code: AutonomyPolicyReasonCode
    profile_reason_code: str
    low_risk_failed_axes: tuple[LowRiskProfileAxis, ...]
    override_source: AutonomyOverrideSource | None


async def resolve_autonomy_policy_action_effect(
    session: AsyncSession,
    *,
    tenant_id: int,
    autonomy_level: str,
    action_class: ActionClass,
    low_risk_input: LowRiskProfileInput | None,
    runtime_enabled: bool = False,
    global_kill_switch_enabled: bool = False,
    budget_result: BudgetCheckResult | None = None,
    provider_decision: ComplianceDecision | None = None,
    tool_network_decision: ToolNetworkDecision | None = None,
) -> AutonomyPolicyEngineDecision:
    """Resolve the effective autonomy policy decision for one action.

    This is the SP024-T05 Policy Engine boundary. It composes the server-owned
    autonomy profile resolver, DB-backed policy profile action effect resolver,
    low-risk evaluator, and deny overrides. It does not persist audit rows; T06
    wires the returned reason fields into policy_decisions / AgentRunEvent.
    """

    profile_resolution = resolve_autonomy_policy_profile(
        autonomy_level,
        runtime_enabled=runtime_enabled,
    )
    profile_effect = await resolve_policy_profile_action_effect(
        session,
        tenant_id=tenant_id,
        policy_profile=profile_resolution.policy_profile,
        action_class=action_class,
    )
    # SP-PHASE1 B5a (ADR-00048 §A-8): emergency-stop latch を server 側で解決し、auto-approve/allow を
    # deny する。budget global_kill_switch と **別目的で OR 評価** (latch=human 即時全停止)。latch query は
    # fail-closed (DB error 等で確認不能 → engaged 扱いで deny、kill switch fail-open を防ぐ)。
    emergency_stop_engaged = await _resolve_emergency_stop_engaged(session, tenant_id)
    return evaluate_autonomy_policy_engine_decision(
        profile_resolution=profile_resolution,
        profile_effect=profile_effect,
        low_risk_input=low_risk_input,
        emergency_stop_engaged=emergency_stop_engaged,
        global_kill_switch_enabled=global_kill_switch_enabled,
        budget_result=budget_result,
        provider_decision=provider_decision,
        tool_network_decision=tool_network_decision,
    )


async def _resolve_emergency_stop_engaged(
    session: AsyncSession, tenant_id: int
) -> bool:
    """emergency-stop latch を fail-closed で解決する (A-8、autonomy allow 経路)。

    共有 helper ``assert_not_emergency_stopped`` (latch query 失敗も deny 方向) を再利用し、engaged /
    query 失敗の双方を ``True`` (= deny) に畳む。autonomy choke point は latch を見て auto-allow を止める。
    """
    from backend.app.services.superintendent.emergency_stop import (
        EmergencyStopEngagedError,
        assert_not_emergency_stopped,
    )

    try:
        await assert_not_emergency_stopped(session, tenant_id)
    except EmergencyStopEngagedError:
        return True
    return False


def evaluate_autonomy_policy_engine_decision(
    *,
    profile_resolution: AutonomyPolicyProfileResolution,
    profile_effect: PolicyProfileResolvedEffect,
    low_risk_input: LowRiskProfileInput | None,
    emergency_stop_engaged: bool = False,
    global_kill_switch_enabled: bool = False,
    budget_result: BudgetCheckResult | None = None,
    provider_decision: ComplianceDecision | None = None,
    tool_network_decision: ToolNetworkDecision | None = None,
) -> AutonomyPolicyEngineDecision:
    # SP-PHASE1 B5a (ADR-00048 §A-8): emergency-stop latch を最優先 deny (human 即時全停止)。
    # budget global_kill_switch と OR 評価 (どちらか engaged なら deny)。emergency-stop を先に評価し
    # 専用 reason_code で監査を正確化する (汎用 kill_switch reason に畳まない)。
    if emergency_stop_engaged:
        return _deny(
            profile_resolution,
            profile_effect,
            reason_code="autonomy_emergency_stop_denied",
            override_source="emergency_stop",
        )
    if global_kill_switch_enabled:
        return _deny(
            profile_resolution,
            profile_effect,
            reason_code="autonomy_global_kill_switch_denied",
            override_source="global_kill_switch",
        )
    if budget_result is not None and budget_result.exceeded:
        return _deny(
            profile_resolution,
            profile_effect,
            reason_code="autonomy_budget_override_denied",
            override_source="budget",
        )
    if provider_decision is not None and provider_decision.decision == "deny":
        return _deny(
            profile_resolution,
            profile_effect,
            reason_code="autonomy_provider_block_denied",
            override_source="provider",
        )
    if tool_network_decision is not None and tool_network_decision.decision == "deny":
        return _deny(
            profile_resolution,
            profile_effect,
            reason_code="autonomy_tool_deny_override_denied",
            override_source="tool",
        )

    if profile_effect.action_class in HUMAN_REQUIRED_ACTION_CLASSES:
        return _fallback(
            profile_resolution,
            profile_effect,
            reason_code="autonomy_human_required_action_fallback",
        )

    if not profile_resolution.auto_allow_enabled:
        return _fallback(
            profile_resolution,
            profile_effect,
            reason_code="autonomy_runtime_disabled_fallback",
        )

    allowed_actions = AUTONOMY_ACTION_ALLOW_MATRIX[profile_resolution.autonomy_level]
    if profile_effect.action_class not in allowed_actions:
        return _fallback(
            profile_resolution,
            profile_effect,
            reason_code="autonomy_action_not_in_level_fallback",
        )

    if low_risk_input is None:
        return _fallback(
            profile_resolution,
            profile_effect,
            reason_code="autonomy_low_risk_profile_missing_fallback",
        )

    low_risk_decision = evaluate_low_risk_profile(low_risk_input)
    if not low_risk_decision.allowed:
        return _fallback(
            profile_resolution,
            profile_effect,
            reason_code="autonomy_low_risk_profile_failed_fallback",
            low_risk_failed_axes=low_risk_decision.failed_axes,
        )

    return AutonomyPolicyEngineDecision(
        autonomy_level=profile_resolution.autonomy_level,
        policy_profile=profile_resolution.policy_profile,
        action_class=profile_effect.action_class,
        decision="allow",
        profile_resolved_effect=profile_effect.effect,
        require_review_artifact=True,
        reason_code="autonomy_matrix_auto_allow_applied",
        profile_reason_code=profile_effect.reason_code,
        low_risk_failed_axes=(),
        override_source=None,
    )


def _deny(
    profile_resolution: AutonomyPolicyProfileResolution,
    profile_effect: PolicyProfileResolvedEffect,
    *,
    reason_code: AutonomyPolicyReasonCode,
    override_source: AutonomyOverrideSource,
) -> AutonomyPolicyEngineDecision:
    return AutonomyPolicyEngineDecision(
        autonomy_level=profile_resolution.autonomy_level,
        policy_profile=profile_resolution.policy_profile,
        action_class=profile_effect.action_class,
        decision="deny",
        profile_resolved_effect=profile_effect.effect,
        require_review_artifact=False,
        reason_code=reason_code,
        profile_reason_code=profile_effect.reason_code,
        low_risk_failed_axes=(),
        override_source=override_source,
    )


def _fallback(
    profile_resolution: AutonomyPolicyProfileResolution,
    profile_effect: PolicyProfileResolvedEffect,
    *,
    reason_code: AutonomyPolicyReasonCode,
    low_risk_failed_axes: tuple[LowRiskProfileAxis, ...] = (),
) -> AutonomyPolicyEngineDecision:
    decision = _non_allowing_fallback(profile_effect.effect)
    return AutonomyPolicyEngineDecision(
        autonomy_level=profile_resolution.autonomy_level,
        policy_profile=profile_resolution.policy_profile,
        action_class=profile_effect.action_class,
        decision=decision,
        profile_resolved_effect=profile_effect.effect,
        require_review_artifact=profile_effect.require_review_artifact
        if decision == profile_effect.effect
        else False,
        reason_code=reason_code,
        profile_reason_code=profile_effect.reason_code,
        low_risk_failed_axes=low_risk_failed_axes,
        override_source=None,
    )


def _non_allowing_fallback(profile_effect: PolicyEffect) -> PolicyEffect:
    if profile_effect == "allow":
        return "require_approval"
    return profile_effect


__all__ = [
    "AUTONOMY_ACTION_ALLOW_MATRIX",
    "HUMAN_REQUIRED_ACTION_CLASSES",
    "AutonomyPolicyEngineDecision",
    "AutonomyPolicyReasonCode",
    "evaluate_autonomy_policy_engine_decision",
    "resolve_autonomy_policy_action_effect",
]
