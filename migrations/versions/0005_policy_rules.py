"""Add policy rules table and initial policy matrix.

Revision ID: 0005_policy_rules
Revises: 0004_secret_capability_tokens
Create Date: 2026-05-08 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_policy_rules"
down_revision: str | None = "0004_secret_capability_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_READY_DEFAULT = sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb")
TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")
UUID_V4_DEFAULT = sa.text("uuid_generate_v4()")


def upgrade() -> None:
    op.create_table(
        "policy_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_class", sa.Text(), nullable=False),
        sa.Column("effect", sa.Text(), nullable=False),
        sa.Column("rule_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=NOW_DEFAULT,
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=NOW_DEFAULT,
            nullable=False,
        ),
        sa.CheckConstraint(
            "action_class in "
            "('task_write','repo_write','pr_open','secret_access','merge','deploy','provider_call')",
            name="policy_rules_ck_action_class",
        ),
        sa.CheckConstraint(
            "effect in ('allow','deny','require_approval')",
            name="policy_rules_ck_effect",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="policy_rules_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="policy_rules_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="policy_rules_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="policy_rules_uq_tenant_id"),
    )

    op.create_index(
        "policy_rules_idx_tenant_action_class",
        "policy_rules",
        ["tenant_id", "action_class"],
    )
    op.create_index(
        "policy_rules_idx_policy_version",
        "policy_rules",
        ["tenant_id", "policy_version"],
    )

    op.execute(
        sa.text(
            """
            INSERT INTO policy_rules (
              id,
              tenant_id,
              action_class,
              effect,
              rule_json,
              policy_version,
              metadata,
              created_at,
              updated_at
            )
            SELECT
              uuid_generate_v4(),
              1,
              matrix.action_class,
              matrix.effect,
              jsonb_strip_nulls(
                jsonb_build_object(
                  'reason_code', matrix.reason_code,
                  'scope', matrix.scope,
                  'note', matrix.note
                )
              ),
              '2026-05-08-initial',
              '{"rls_ready": true}'::jsonb,
              now(),
              now()
            FROM (
              VALUES
                ('merge', 'deny', 'p0_merge_deploy_disabled', 'all', NULL),
                ('deploy', 'deny', 'p0_merge_deploy_disabled', 'all', NULL),
                (
                  'secret_access',
                  'deny',
                  'policy_matrix_default_deny',
                  'default',
                  'Sprint 4 SecretBroker で fail-closed override'
                ),
                (
                  'provider_call',
                  'deny',
                  'policy_matrix_default_deny',
                  'default',
                  'Sprint 5 Provider Compliance で fail-closed override'
                ),
                (
                  'task_write',
                  'require_approval',
                  'task_write_requires_approval',
                  'default',
                  NULL
                ),
                (
                  'repo_write',
                  'require_approval',
                  'repo_write_requires_approval',
                  'default',
                  NULL
                ),
                (
                  'pr_open',
                  'require_approval',
                  'pr_open_requires_approval',
                  'default',
                  NULL
                )
            ) AS matrix(action_class, effect, reason_code, scope, note)
            """
        )
    )

    op.execute(
        """
        CREATE TRIGGER policy_rules_set_updated_at
        BEFORE UPDATE ON policy_rules
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS policy_rules_set_updated_at ON policy_rules")

    op.drop_table("policy_rules")

