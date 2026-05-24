from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from backend.app.domain.policy.autonomy_level import ALL_AUTONOMY_LEVELS, AutonomyLevel
from backend.app.domain.policy.profile import PolicyProfileId

AutonomyPolicyProfileReason = Literal[
    "autonomy_l0_default",
    "autonomy_runtime_disabled",
    "autonomy_runtime_not_implemented",
]


@dataclass(frozen=True)
class AutonomyPolicyProfileResolution:
    autonomy_level: AutonomyLevel
    policy_profile: PolicyProfileId
    auto_allow_enabled: bool
    reason_code: AutonomyPolicyProfileReason


def resolve_autonomy_policy_profile(
    autonomy_level: str,
    *,
    runtime_enabled: bool = False,
) -> AutonomyPolicyProfileResolution:
    """Resolve caller-visible autonomy level to a server-owned policy profile.

    SP024-T03 intentionally keeps L1-L3 fail-closed. Existing
    ``low_risk_auto_allow`` allows provider_call in SP-014 semantics, while
    ADR-00025 requires provider_call to remain human-approval-only for every
    autonomy level. T05 must update Policy Engine/profile semantics before this
    resolver can return anything other than ``default``.
    """

    if autonomy_level not in ALL_AUTONOMY_LEVELS:
        raise ValueError(f"unknown autonomy_level: {autonomy_level}")

    level = cast(AutonomyLevel, autonomy_level)
    if level == "L0":
        reason_code: AutonomyPolicyProfileReason = "autonomy_l0_default"
    elif runtime_enabled:
        reason_code = "autonomy_runtime_not_implemented"
    else:
        reason_code = "autonomy_runtime_disabled"

    return AutonomyPolicyProfileResolution(
        autonomy_level=level,
        policy_profile="default",
        auto_allow_enabled=False,
        reason_code=reason_code,
    )


__all__ = [
    "AutonomyPolicyProfileReason",
    "AutonomyPolicyProfileResolution",
    "resolve_autonomy_policy_profile",
]
