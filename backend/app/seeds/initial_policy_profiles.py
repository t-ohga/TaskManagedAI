"""Shared canonical source for the initial policy_profile seed.

SP-014 batch 0c makes ``projects.policy_profile`` server-owned and FK-backed.
Any tenant that can own projects must also have the two P0 policy profiles and
their 14 action effect rows. Migration 0027 seeds existing tenants and installs
the runtime tenant trigger; tests call this helper after deliberate seed mutation
or fixture truncation to keep the same canonical rows.
"""

from __future__ import annotations

from typing import Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.domain.policy.profile import POLICY_PROFILE_ACTION_EFFECTS, PolicyProfileId

INITIAL_POLICY_PROFILE_TENANT_ID: Final[int] = 1
DEFAULT_POLICY_PROFILE_TENANT_NAME: Final[str] = "default-tenant"
POLICY_PROFILE_DESCRIPTIONS: Final[dict[PolicyProfileId, str]] = {
    "default": "P0 default profile: mutation actions require approval or deny.",
    "low_risk_auto_allow": "P0.1 low-risk auto-allow profile guarded by review artifacts.",
}

_ENSURE_POLICY_PROFILE_TENANT = sa.text(
    """
    insert into tenants (id, name, metadata)
    values (
      :tenant_id,
      :tenant_name,
      '{"rls_ready": true, "seed_version": "sprint2"}'::jsonb
    )
    on conflict (id) do nothing
    """
)
_UPSERT_POLICY_PROFILE = sa.text(
    """
    insert into policy_profiles (tenant_id, profile_id, description)
    values (:tenant_id, :profile_id, :description)
    on conflict (tenant_id, profile_id) do update
      set description = excluded.description
    """
)
_UPSERT_POLICY_PROFILE_ACTION_EFFECT = sa.text(
    """
    insert into policy_profile_action_effects (
      tenant_id,
      profile_id,
      action_class,
      effect,
      require_review_artifact
    )
    values (
      :tenant_id,
      :profile_id,
      :action_class,
      :effect,
      :require_review_artifact
    )
    on conflict (tenant_id, profile_id, action_class) do update
      set effect = excluded.effect,
          require_review_artifact = excluded.require_review_artifact
    """
)


def policy_profile_insert_rows(
    *,
    tenant_id: int = INITIAL_POLICY_PROFILE_TENANT_ID,
) -> list[dict[str, object]]:
    """Build the canonical two policy profile rows for one tenant."""
    return [
        {
            "tenant_id": tenant_id,
            "profile_id": profile_id,
            "description": description,
        }
        for profile_id, description in POLICY_PROFILE_DESCRIPTIONS.items()
    ]


def policy_profile_action_effect_insert_rows(
    *,
    tenant_id: int = INITIAL_POLICY_PROFILE_TENANT_ID,
) -> list[dict[str, object]]:
    """Build the canonical 14 policy profile/action/effect rows for one tenant."""
    rows: list[dict[str, object]] = []
    for profile_id, actions in POLICY_PROFILE_ACTION_EFFECTS.items():
        for action_class, (effect, require_review_artifact) in actions.items():
            rows.append(
                {
                    "tenant_id": tenant_id,
                    "profile_id": profile_id,
                    "action_class": action_class,
                    "effect": effect,
                    "require_review_artifact": require_review_artifact,
                }
            )
    return rows


async def seed_initial_policy_profiles(
    session: AsyncSession,
    *,
    tenant_id: int = INITIAL_POLICY_PROFILE_TENANT_ID,
) -> None:
    """Idempotently restore the P0 policy profiles and action effects."""
    await session.execute(
        _ENSURE_POLICY_PROFILE_TENANT,
        {
            "tenant_id": tenant_id,
            "tenant_name": DEFAULT_POLICY_PROFILE_TENANT_NAME,
        },
    )
    await session.execute(
        _UPSERT_POLICY_PROFILE,
        policy_profile_insert_rows(tenant_id=tenant_id),
    )
    await session.execute(
        _UPSERT_POLICY_PROFILE_ACTION_EFFECT,
        policy_profile_action_effect_insert_rows(tenant_id=tenant_id),
    )
    await session.flush()


__all__ = [
    "DEFAULT_POLICY_PROFILE_TENANT_NAME",
    "INITIAL_POLICY_PROFILE_TENANT_ID",
    "POLICY_PROFILE_DESCRIPTIONS",
    "policy_profile_action_effect_insert_rows",
    "policy_profile_insert_rows",
    "seed_initial_policy_profiles",
]
