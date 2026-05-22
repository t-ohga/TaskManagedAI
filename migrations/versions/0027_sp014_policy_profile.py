"""SP-014 batch 0c: policy_profile schema and decision trace.

Revision ID: 0027_sp014_policy_profile
Revises: 0026_sp014_review_artifacts
Create Date: 2026-05-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027_sp014_policy_profile"
down_revision: str | None = "0026_sp014_review_artifacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")

ACTION_CLASS_CHECK = (
    "action_class in "
    "('task_write','repo_write','pr_open','secret_access','merge','deploy','provider_call')"
)
POLICY_EFFECT_CHECK = "effect in ('allow','deny','require_approval')"


def upgrade() -> None:
    op.create_table(
        "policy_profiles",
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("profile_id", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "profile_id", name="policy_profiles_pk"),
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
    )
    op.create_table(
        "policy_profile_action_effects",
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("profile_id", sa.Text(), nullable=False),
        sa.Column("action_class", sa.Text(), nullable=False),
        sa.Column("effect", sa.Text(), nullable=False),
        sa.Column(
            "require_review_artifact",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "profile_id",
            "action_class",
            name="policy_profile_action_effects_pk",
        ),
        sa.CheckConstraint(
            ACTION_CLASS_CHECK,
            name="policy_profile_action_effects_ck_action_class",
        ),
        sa.CheckConstraint(POLICY_EFFECT_CHECK, name="policy_profile_action_effects_ck_effect"),
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
    )
    _seed_policy_profiles()
    _seed_policy_profile_action_effects()
    _create_policy_profile_seed_trigger()

    op.execute("update projects set policy_profile = 'default' where policy_profile is null")
    op.alter_column(
        "projects",
        "policy_profile",
        existing_type=sa.Text(),
        nullable=False,
        server_default=sa.text("'default'"),
    )
    op.create_foreign_key(
        "projects_policy_profile_fkey",
        "projects",
        "policy_profiles",
        ["tenant_id", "policy_profile"],
        ["tenant_id", "profile_id"],
        ondelete="RESTRICT",
    )

    with op.batch_alter_table("policy_decisions") as batch_op:
        batch_op.add_column(sa.Column("policy_profile", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("profile_resolved_effect", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("required_review_artifact_id", postgresql.UUID(as_uuid=True), nullable=True)
        )

    op.execute(
        """
        update policy_decisions
           set policy_profile = coalesce(policy_profile, 'default'),
               profile_resolved_effect = coalesce(profile_resolved_effect, decision)
        """
    )
    op.execute(
        """
        create or replace function set_policy_decision_profile_defaults()
            returns trigger
            language plpgsql
        as $$
        begin
            if NEW.policy_profile is null then
                NEW.policy_profile := 'default';
            end if;
            if NEW.profile_resolved_effect is null then
                NEW.profile_resolved_effect := NEW.decision;
            end if;
            return NEW;
        end;
        $$;
        """
    )
    op.execute(
        """
        create trigger policy_decisions_set_profile_defaults
            before insert or update of decision, policy_profile, profile_resolved_effect
            on policy_decisions
            for each row execute function set_policy_decision_profile_defaults();
        """
    )
    op.alter_column(
        "policy_decisions",
        "policy_profile",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.alter_column(
        "policy_decisions",
        "profile_resolved_effect",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.create_check_constraint(
        "policy_decisions_ck_profile_resolved_effect",
        "policy_decisions",
        "profile_resolved_effect in ('allow','deny','require_approval')",
    )
    op.create_foreign_key(
        "policy_decisions_policy_profile_fkey",
        "policy_decisions",
        "policy_profiles",
        ["tenant_id", "policy_profile"],
        ["tenant_id", "profile_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "policy_decisions_required_review_artifact_fkey",
        "policy_decisions",
        "review_artifacts",
        ["tenant_id", "required_review_artifact_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "policy_decisions_idx_tenant_policy_profile",
        "policy_decisions",
        ["tenant_id", "policy_profile"],
    )
    op.create_index(
        "policy_decisions_idx_required_review_artifact",
        "policy_decisions",
        ["tenant_id", "required_review_artifact_id"],
        postgresql_where=sa.text("required_review_artifact_id is not null"),
    )


def downgrade() -> None:
    op.execute("drop trigger if exists tenants_seed_policy_profiles on tenants")
    op.execute("drop function if exists seed_policy_profiles_for_tenant()")
    op.drop_index(
        "policy_decisions_idx_required_review_artifact",
        table_name="policy_decisions",
        postgresql_where=sa.text("required_review_artifact_id is not null"),
    )
    op.drop_index("policy_decisions_idx_tenant_policy_profile", table_name="policy_decisions")
    op.drop_constraint(
        "policy_decisions_required_review_artifact_fkey",
        "policy_decisions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "policy_decisions_policy_profile_fkey",
        "policy_decisions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "policy_decisions_ck_profile_resolved_effect",
        "policy_decisions",
        type_="check",
    )
    op.execute("drop trigger if exists policy_decisions_set_profile_defaults on policy_decisions")
    op.execute("drop function if exists set_policy_decision_profile_defaults()")
    with op.batch_alter_table("policy_decisions") as batch_op:
        batch_op.drop_column("required_review_artifact_id")
        batch_op.drop_column("profile_resolved_effect")
        batch_op.drop_column("policy_profile")

    op.drop_constraint("projects_policy_profile_fkey", "projects", type_="foreignkey")
    op.alter_column(
        "projects",
        "policy_profile",
        existing_type=sa.Text(),
        nullable=True,
        server_default=None,
    )
    op.drop_table("policy_profile_action_effects")
    op.drop_table("policy_profiles")


def _seed_policy_profiles() -> None:
    op.execute(
        """
        insert into policy_profiles (tenant_id, profile_id, description)
        select tenants.id, profiles.profile_id, profiles.description
          from tenants
          cross join (
            values
              ('default', 'P0 default profile: mutation actions require approval or deny.'),
              ('low_risk_auto_allow', 'P0.1 low-risk auto-allow profile guarded by review artifacts.')
          ) as profiles(profile_id, description)
        on conflict do nothing
        """
    )


def _seed_policy_profile_action_effects() -> None:
    op.execute(
        """
        insert into policy_profile_action_effects (
            tenant_id, profile_id, action_class, effect, require_review_artifact
        )
        select tenants.id, effects.profile_id, effects.action_class, effects.effect,
               effects.require_review_artifact
          from tenants
          cross join (
            values
              ('default', 'task_write', 'require_approval', false),
              ('default', 'repo_write', 'require_approval', false),
              ('default', 'pr_open', 'require_approval', false),
              ('default', 'secret_access', 'deny', false),
              ('default', 'merge', 'deny', false),
              ('default', 'deploy', 'deny', false),
              ('default', 'provider_call', 'deny', false),
              ('low_risk_auto_allow', 'task_write', 'allow', true),
              ('low_risk_auto_allow', 'repo_write', 'deny', false),
              ('low_risk_auto_allow', 'pr_open', 'deny', false),
              ('low_risk_auto_allow', 'secret_access', 'deny', false),
              ('low_risk_auto_allow', 'merge', 'deny', false),
              ('low_risk_auto_allow', 'deploy', 'deny', false),
              ('low_risk_auto_allow', 'provider_call', 'allow', true)
          ) as effects(profile_id, action_class, effect, require_review_artifact)
        on conflict do nothing
        """
    )


def _create_policy_profile_seed_trigger() -> None:
    op.execute(
        """
        create or replace function seed_policy_profiles_for_tenant()
            returns trigger
            language plpgsql
        as $$
        begin
            insert into policy_profiles (tenant_id, profile_id, description)
            values
              (NEW.id, 'default', 'P0 default profile: mutation actions require approval or deny.'),
              (NEW.id, 'low_risk_auto_allow',
               'P0.1 low-risk auto-allow profile guarded by review artifacts.')
            on conflict do nothing;

            insert into policy_profile_action_effects (
                tenant_id, profile_id, action_class, effect, require_review_artifact
            )
            values
              (NEW.id, 'default', 'task_write', 'require_approval', false),
              (NEW.id, 'default', 'repo_write', 'require_approval', false),
              (NEW.id, 'default', 'pr_open', 'require_approval', false),
              (NEW.id, 'default', 'secret_access', 'deny', false),
              (NEW.id, 'default', 'merge', 'deny', false),
              (NEW.id, 'default', 'deploy', 'deny', false),
              (NEW.id, 'default', 'provider_call', 'deny', false),
              (NEW.id, 'low_risk_auto_allow', 'task_write', 'allow', true),
              (NEW.id, 'low_risk_auto_allow', 'repo_write', 'deny', false),
              (NEW.id, 'low_risk_auto_allow', 'pr_open', 'deny', false),
              (NEW.id, 'low_risk_auto_allow', 'secret_access', 'deny', false),
              (NEW.id, 'low_risk_auto_allow', 'merge', 'deny', false),
              (NEW.id, 'low_risk_auto_allow', 'deploy', 'deny', false),
              (NEW.id, 'low_risk_auto_allow', 'provider_call', 'allow', true)
            on conflict do nothing;

            return NEW;
        end;
        $$;
        """
    )
    op.execute(
        """
        create trigger tenants_seed_policy_profiles
            after insert on tenants
            for each row execute function seed_policy_profiles_for_tenant();
        """
    )
