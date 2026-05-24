from __future__ import annotations

from backend.app.domain.policy.action_class import ActionClass, PolicyEffect
from backend.app.domain.policy.autonomy_level import ALL_AUTONOMY_LEVELS
from backend.app.services.policy.autonomy_policy_engine import (
    AUTONOMY_ACTION_ALLOW_MATRIX,
    HUMAN_REQUIRED_ACTION_CLASSES,
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


def test_t08_allow_matrix_never_contains_human_required_actions() -> None:
    assert set(AUTONOMY_ACTION_ALLOW_MATRIX) == ALL_AUTONOMY_LEVELS
    assert AUTONOMY_ACTION_ALLOW_MATRIX["L0"] == frozenset()
    assert AUTONOMY_ACTION_ALLOW_MATRIX["L1"] < AUTONOMY_ACTION_ALLOW_MATRIX["L2"]
    assert AUTONOMY_ACTION_ALLOW_MATRIX["L2"] < AUTONOMY_ACTION_ALLOW_MATRIX["L3"]

    for allowed_actions in AUTONOMY_ACTION_ALLOW_MATRIX.values():
        assert allowed_actions.isdisjoint(HUMAN_REQUIRED_ACTION_CLASSES)


def test_t08_human_required_actions_require_approval_for_every_level() -> None:
    for level in sorted(ALL_AUTONOMY_LEVELS):
        for action_class in sorted(HUMAN_REQUIRED_ACTION_CLASSES):
            decision = evaluate_autonomy_policy_engine_decision(
                profile_resolution=_profile_resolution(level),
                profile_effect=_profile_effect(action_class),
                low_risk_input=_low_risk_input(),
            )

            assert decision.decision == "require_approval"
            assert decision.reason_code == "autonomy_human_required_action_fallback"
            assert decision.require_review_artifact is False


def test_t08_global_kill_switch_denies_before_any_level_matrix_allow() -> None:
    for level in sorted(ALL_AUTONOMY_LEVELS):
        decision = evaluate_autonomy_policy_engine_decision(
            profile_resolution=_profile_resolution(level),
            profile_effect=_profile_effect("task_write"),
            low_risk_input=_low_risk_input(),
            global_kill_switch_enabled=True,
        )

        assert decision.decision == "deny"
        assert decision.reason_code == "autonomy_global_kill_switch_denied"
        assert decision.override_source == "global_kill_switch"


def test_t08_l0_downgrade_disables_auto_allow_even_when_runtime_is_enabled() -> None:
    decision = evaluate_autonomy_policy_engine_decision(
        profile_resolution=_profile_resolution("L0"),
        profile_effect=_profile_effect("task_write"),
        low_risk_input=_low_risk_input(),
    )

    assert decision.decision == "require_approval"
    assert decision.reason_code == "autonomy_runtime_disabled_fallback"
