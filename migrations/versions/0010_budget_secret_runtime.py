"""Add BudgetGuard runtime tables.

Revision ID: 0010_budget_secret_runtime
Revises: 0009_artifacts_context_snapshots
Create Date: 2026-05-09 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_budget_secret_runtime"
down_revision: str | None = "0009_artifacts_context_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")
UUID_V4_DEFAULT = sa.text("uuid_generate_v4()")
PROJECT_DEFAULT_LEVEL_ID = "00000000-0000-4000-8000-000000004501"


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("level_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("hard_usd_limit", sa.Numeric(12, 6), nullable=True),
        sa.Column("soft_usd_threshold", sa.Numeric(12, 6), nullable=True),
        sa.Column("hard_tokens_limit", sa.BigInteger(), nullable=True),
        sa.Column("hard_wall_clock_ms", sa.BigInteger(), nullable=True),
        sa.Column("max_retries", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("global_kill_switch", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "level in ('global','tenant','project','agent_run')",
            name="budgets_ck_level",
        ),
        sa.CheckConstraint(
            "(level in ('global','tenant') and level_id is null) or "
            "(level in ('project','agent_run') and level_id is not null)",
            name="budgets_ck_level_id_consistency",
        ),
        sa.CheckConstraint(
            "level = 'global' or global_kill_switch is null",
            name="budgets_ck_global_kill_switch_only_global",
        ),
        sa.CheckConstraint(
            "(hard_usd_limit is null or hard_usd_limit >= 0) and "
            "(soft_usd_threshold is null or soft_usd_threshold >= 0) and "
            "(hard_tokens_limit is null or hard_tokens_limit >= 0) and "
            "(hard_wall_clock_ms is null or hard_wall_clock_ms >= 0) and "
            "(max_retries is null or max_retries >= 0)",
            name="budgets_ck_non_negative_limits",
        ),
        sa.CheckConstraint(
            "hard_usd_limit is null or soft_usd_threshold is null "
            "or soft_usd_threshold <= hard_usd_limit",
            name="budgets_ck_soft_threshold_lte_hard_limit",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="budgets_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="budgets_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="budgets_uq_tenant_id"),
    )
    op.create_index(
        "budgets_uq_global_level_active",
        "budgets",
        ["level"],
        unique=True,
        postgresql_where=sa.text("level = 'global' and active = true"),
    )
    op.create_index(
        "budgets_uq_tenant_level_active",
        "budgets",
        ["tenant_id", "level"],
        unique=True,
        postgresql_where=sa.text("level = 'tenant' and active = true"),
    )
    op.create_index(
        "budgets_uq_project_level_active",
        "budgets",
        ["tenant_id", "level", "level_id"],
        unique=True,
        postgresql_where=sa.text("level = 'project' and active = true"),
    )
    op.create_index(
        "budgets_uq_agent_run_level_active",
        "budgets",
        ["tenant_id", "level", "level_id"],
        unique=True,
        postgresql_where=sa.text("level = 'agent_run' and active = true"),
    )
    op.create_index(
        "budgets_idx_tenant_level_active",
        "budgets",
        ["tenant_id", "level", "active"],
    )
    op.execute(
        """
        CREATE TRIGGER budgets_set_updated_at
        BEFORE UPDATE ON budgets
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )

    op.execute(
        sa.text(
            """
            insert into budgets (
              tenant_id,
              level,
              level_id,
              hard_usd_limit,
              soft_usd_threshold,
              hard_tokens_limit,
              hard_wall_clock_ms,
              max_retries,
              active,
              global_kill_switch
            )
            values
              (1, 'global', null, 100.000000, 80.000000, null, null, null, true, false),
              (1, 'tenant', null, 50.000000, 40.000000, null, null, null, true, null),
              (
                1,
                'project',
                cast(:project_default_level_id as uuid),
                10.000000,
                8.000000,
                500000,
                7200000,
                3,
                true,
                null
              )
            on conflict do nothing
            """
        ).bindparams(project_default_level_id=PROJECT_DEFAULT_LEVEL_ID)
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS budgets_set_updated_at ON budgets")
    op.drop_table("budgets")

