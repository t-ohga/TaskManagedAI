from __future__ import annotations

from typing import Final, Literal, get_args

from backend.app.domain.policy.action_class import ActionClass, PolicyEffect

PolicyProfileId = Literal["default", "low_risk_auto_allow"]

ALL_POLICY_PROFILE_IDS: Final[frozenset[str]] = frozenset(
    {"default", "low_risk_auto_allow"}
)

POLICY_PROFILE_ACTION_EFFECTS: Final[
    dict[PolicyProfileId, dict[ActionClass, tuple[PolicyEffect, bool]]]
] = {
    "default": {
        "task_write": ("require_approval", False),
        "repo_write": ("require_approval", False),
        "pr_open": ("require_approval", False),
        "secret_access": ("deny", False),
        "merge": ("deny", False),
        "deploy": ("deny", False),
        "provider_call": ("deny", False),
    },
    "low_risk_auto_allow": {
        "task_write": ("allow", True),
        "repo_write": ("deny", False),
        "pr_open": ("deny", False),
        "secret_access": ("deny", False),
        "merge": ("deny", False),
        "deploy": ("deny", False),
        "provider_call": ("allow", True),
    },
}

_PROFILE_LITERAL_ARGS: Final[frozenset[str]] = frozenset(get_args(PolicyProfileId))
if _PROFILE_LITERAL_ARGS != ALL_POLICY_PROFILE_IDS:
    raise AssertionError(
        "PolicyProfileId Literal and ALL_POLICY_PROFILE_IDS drift: "
        f"Literal={sorted(_PROFILE_LITERAL_ARGS)}, "
        f"frozenset={sorted(ALL_POLICY_PROFILE_IDS)}"
    )


__all__ = [
    "ALL_POLICY_PROFILE_IDS",
    "POLICY_PROFILE_ACTION_EFFECTS",
    "PolicyProfileId",
]
