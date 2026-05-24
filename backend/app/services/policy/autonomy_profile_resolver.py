from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from backend.app.domain.policy.autonomy_level import ALL_AUTONOMY_LEVELS, AutonomyLevel
from backend.app.domain.policy.profile import PolicyProfileId

AutonomyPolicyProfileReason = Literal[
    "autonomy_l0_default",
    "autonomy_runtime_disabled",
    "autonomy_runtime_matrix_enabled",
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

    The resolver never accepts caller-supplied ``policy_profile``. SP024-T05
    keeps the DB-backed profile cache on ``default`` and lets the Policy Engine
    apply the L0-L3 matrix above the resolved profile effect. Existing
    ``low_risk_auto_allow`` still contains SP-014 semantics and is intentionally
    not returned here because it allows provider_call.
    """

    if autonomy_level not in ALL_AUTONOMY_LEVELS:
        raise ValueError(f"unknown autonomy_level: {autonomy_level}")

    level = cast(AutonomyLevel, autonomy_level)
    if level == "L0":
        reason_code: AutonomyPolicyProfileReason = "autonomy_l0_default"
        auto_allow_enabled = False
    elif runtime_enabled:
        reason_code = "autonomy_runtime_matrix_enabled"
        auto_allow_enabled = True
    else:
        reason_code = "autonomy_runtime_disabled"
        auto_allow_enabled = False

    return AutonomyPolicyProfileResolution(
        autonomy_level=level,
        policy_profile="default",
        auto_allow_enabled=auto_allow_enabled,
        reason_code=reason_code,
    )


__all__ = [
    "AutonomyPolicyProfileReason",
    "AutonomyPolicyProfileResolution",
    "resolve_autonomy_policy_profile",
]
