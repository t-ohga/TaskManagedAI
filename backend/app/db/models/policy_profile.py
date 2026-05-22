from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import Base, TenantIdMixin
from backend.app.domain.policy.action_class import ActionClass, PolicyEffect
from backend.app.domain.policy.profile import PolicyProfileId


class PolicyProfile(TenantIdMixin, Base):
    __tablename__ = "policy_profiles"
    __table_args__ = (
        sa.CheckConstraint(
            "profile_id in ('default','low_risk_auto_allow')",
            name="policy_profiles_ck_profile_id",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="policy_profiles_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "profile_id", name="policy_profiles_pk"),
    )

    profile_id: Mapped[PolicyProfileId] = mapped_column(sa.Text, nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


class PolicyProfileActionEffect(TenantIdMixin, Base):
    __tablename__ = "policy_profile_action_effects"
    __table_args__ = (
        sa.CheckConstraint(
            "action_class in "
            "('task_write','repo_write','pr_open','secret_access','merge','deploy','provider_call')",
            name="policy_profile_action_effects_ck_action_class",
        ),
        sa.CheckConstraint(
            "effect in ('allow','deny','require_approval')",
            name="policy_profile_action_effects_ck_effect",
        ),
        sa.CheckConstraint(
            "(effect = 'allow') or (require_review_artifact = false)",
            name="policy_profile_action_effects_ck_review_only_for_allow",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="policy_profile_action_effects_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "profile_id"],
            ["policy_profiles.tenant_id", "policy_profiles.profile_id"],
            name="policy_profile_action_effects_profile_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "profile_id",
            "action_class",
            name="policy_profile_action_effects_pk",
        ),
    )

    profile_id: Mapped[PolicyProfileId] = mapped_column(sa.Text, nullable=False)
    action_class: Mapped[ActionClass] = mapped_column(sa.Text, nullable=False)
    effect: Mapped[PolicyEffect] = mapped_column(sa.Text, nullable=False)
    require_review_artifact: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=False,
        server_default=sa.text("false"),
    )


__all__ = ["PolicyProfile", "PolicyProfileActionEffect"]
