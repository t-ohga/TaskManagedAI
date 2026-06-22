"""SP-PHASE1 B5a: autonomy allow 経路の emergency-stop latch deny (ADR-00048 §A-8)。

emergency-stop latch と budget ``global_kill_switch`` は別目的で **OR 評価** (latch=human 即時全停止 /
kill_switch=コスト緊急停止)。本 test は pure evaluator (``evaluate_autonomy_policy_engine_decision``)
で:
- ``emergency_stop_engaged=True`` が全 level で auto-allow を deny (専用 reason_code)。
- emergency-stop が global_kill_switch より **先に** 評価される (専用 reason_code が出る、汎用 kill に
  畳まれない)。
- 両方 engaged でも emergency-stop reason が優先 (human kill が source of truth)。

reason_code の 5+source 整合は ``test_emergency_stop_reason_enum.py`` (application reason_code) と本 file
(autonomy reason_code Literal) で固定する。
"""

from __future__ import annotations

from typing import get_args

from backend.app.domain.policy.action_class import ActionClass, PolicyEffect
from backend.app.domain.policy.autonomy_level import ALL_AUTONOMY_LEVELS
from backend.app.services.policy.autonomy_policy_engine import (
    AutonomyOverrideSource,
    AutonomyPolicyReasonCode,
    evaluate_autonomy_policy_engine_decision,
)
from backend.app.services.policy.autonomy_profile_resolver import (
    AutonomyPolicyProfileResolution,
    resolve_autonomy_policy_profile,
)
from backend.app.services.policy.low_risk_profile import LowRiskProfileInput
from backend.app.services.policy.profile_resolver import PolicyProfileResolvedEffect


def _profile_resolution(level: str) -> AutonomyPolicyProfileResolution:
    return resolve_autonomy_policy_profile(level, runtime_enabled=True)


def _profile_effect(
    action_class: ActionClass,
    *,
    effect: PolicyEffect = "allow",
) -> PolicyProfileResolvedEffect:
    return PolicyProfileResolvedEffect(
        policy_profile="default",
        action_class=action_class,
        effect=effect,
        require_review_artifact=effect == "allow",
        reason_code="policy_profile_action_effect_resolved",
    )


def _low_risk_input() -> LowRiskProfileInput:
    return LowRiskProfileInput(
        payload_data_class="internal",
        diff_line_count=1,
        changed_paths=("docs/sprints/SP-024_autonomy_policy_profiles.md",),
        commands=(),
        provider_request_preflight_passed=True,
        runner_mutation_gateway_passed=True,
        context_snapshot_passed=True,
    )


def test_emergency_stop_denies_auto_allow_for_every_level() -> None:
    for level in sorted(ALL_AUTONOMY_LEVELS):
        decision = evaluate_autonomy_policy_engine_decision(
            profile_resolution=_profile_resolution(level),
            profile_effect=_profile_effect("task_write"),
            low_risk_input=_low_risk_input(),
            emergency_stop_engaged=True,
        )
        assert decision.decision == "deny"
        assert decision.reason_code == "autonomy_emergency_stop_denied"
        assert decision.override_source == "emergency_stop"
        assert decision.require_review_artifact is False


def test_emergency_stop_evaluated_before_global_kill_switch() -> None:
    """A-8: emergency-stop が先 (専用 reason)。両 engaged でも emergency-stop が優先される。"""
    decision = evaluate_autonomy_policy_engine_decision(
        profile_resolution=_profile_resolution("L1"),
        profile_effect=_profile_effect("task_write"),
        low_risk_input=_low_risk_input(),
        emergency_stop_engaged=True,
        global_kill_switch_enabled=True,
    )
    assert decision.decision == "deny"
    assert decision.reason_code == "autonomy_emergency_stop_denied"
    assert decision.override_source == "emergency_stop"


def test_no_emergency_stop_allows_auto_allow_low_risk() -> None:
    """latch off + low-risk allowable は従来どおり auto-allow (regression 防止)。"""
    decision = evaluate_autonomy_policy_engine_decision(
        profile_resolution=_profile_resolution("L1"),
        profile_effect=_profile_effect("task_write"),
        low_risk_input=_low_risk_input(),
        emergency_stop_engaged=False,
    )
    assert decision.decision == "allow"
    assert decision.reason_code == "autonomy_matrix_auto_allow_applied"
    assert decision.override_source is None


def test_autonomy_reason_code_and_override_source_include_emergency_stop() -> None:
    """A-8 5+source: autonomy reason_code Literal / override_source Literal に emergency_stop が含まれる。"""
    assert "autonomy_emergency_stop_denied" in get_args(AutonomyPolicyReasonCode)
    assert "emergency_stop" in get_args(AutonomyOverrideSource)
