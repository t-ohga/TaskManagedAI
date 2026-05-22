from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.policy_profile import PolicyProfileActionEffect
from backend.app.domain.policy.action_class import ActionClass, PolicyEffect


@dataclass(frozen=True)
class PolicyProfileResolvedEffect:
    policy_profile: str
    action_class: ActionClass
    effect: PolicyEffect
    require_review_artifact: bool
    reason_code: str


async def resolve_policy_profile_action_effect(
    session: AsyncSession,
    *,
    tenant_id: int,
    policy_profile: str,
    action_class: ActionClass,
) -> PolicyProfileResolvedEffect:
    """Resolve a policy profile/action pair fail-closed.

    Unknown profiles or missing seed rows return deny instead of falling back to
    a broader approval path. Tier 2 auto-allow is valid only when the exact seed
    row exists and explicitly says allow.
    """

    await _ensure_tenant_context(session, tenant_id)
    row = await session.scalar(
        sa.select(PolicyProfileActionEffect).where(
            PolicyProfileActionEffect.tenant_id == tenant_id,
            PolicyProfileActionEffect.profile_id == policy_profile,
            PolicyProfileActionEffect.action_class == action_class,
        )
    )
    if row is None:
        profile_exists = await session.scalar(
            sa.select(sa.literal(True))
            .select_from(PolicyProfileActionEffect)
            .where(
                PolicyProfileActionEffect.tenant_id == tenant_id,
                PolicyProfileActionEffect.profile_id == policy_profile,
            )
            .limit(1)
        )
        reason_code = (
            "missing_policy_profile_action_effect_denied"
            if profile_exists
            else "unknown_policy_profile_denied"
        )
        return PolicyProfileResolvedEffect(
            policy_profile=policy_profile,
            action_class=action_class,
            effect="deny",
            require_review_artifact=False,
            reason_code=reason_code,
        )

    return PolicyProfileResolvedEffect(
        policy_profile=row.profile_id,
        action_class=row.action_class,
        effect=row.effect,
        require_review_artifact=row.require_review_artifact,
        reason_code="policy_profile_action_effect_resolved",
    )


async def _ensure_tenant_context(session: AsyncSession, tenant_id: int) -> None:
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
        raise ValueError("tenant_id must be a positive integer.")
    current = await get_tenant_context(session)
    if current is None:
        await set_tenant_context(session, tenant_id)
    await assert_tenant_context(session, tenant_id)


__all__ = ["PolicyProfileResolvedEffect", "resolve_policy_profile_action_effect"]
