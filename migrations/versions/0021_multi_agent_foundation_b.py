"""Multi-agent orchestration foundation phase B: agent_runs extension.

SP-013 batch 0c (ADR-00014 §3 + PD-R4-F-002 + PE-F-004 + PE-F-012 mitigation).

agent_runs に role / lease / progress 関連 8 columns 追加 + role_consistency CHECK
+ unique (tenant_id, project_id, id) constraint。

scope:
- role_id / role_scope: dispatch hint (authorization は capability token + 3 gateway 別軸)
- orchestrator_lease_token / orchestrator_lease_expires_at / lease_renewed_at: PD-R2-F-012 lease
- orchestrator_kill_at: kill switch
- last_progress_at / progress_seq: PE-F-004 no-progress detection
- agent_runs_role_consistency CHECK: role_id と role_scope の整合
- agent_runs_tenant_project_id_uniq UNIQUE: project boundary 強制

scope 外 (次 batch):
- check_project_role_link() trigger 関数 (batch 0d)
- sanitizer_policy_versions table (batch 0e)

Revision ID: 0021_multi_agent_foundation_b
Revises: 0020_multi_agent_foundation_a
Create Date: 2026-05-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_multi_agent_foundation_b"
down_revision: str | None = "0020_multi_agent_foundation_a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # agent_runs に 8 columns 追加
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.add_column(sa.Column("role_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("role_scope", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("orchestrator_lease_token", postgresql.UUID(as_uuid=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "orchestrator_lease_expires_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("lease_renewed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("orchestrator_kill_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("last_progress_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "progress_seq",
                sa.BigInteger(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )

    # CHECK: role_scope enum
    op.create_check_constraint(
        "agent_runs_ck_role_scope",
        "agent_runs",
        "role_scope is null or role_scope in ('global','project')",
    )

    # PD-R4-F-002 strict fail-closed CHECK: role_id と role_scope の整合
    op.create_check_constraint(
        "agent_runs_role_consistency",
        "agent_runs",
        (
            "(role_id is null and role_scope is null) "
            "or (role_id is not null and role_scope is not null "
            "    and role_scope in ('global','project'))"
        ),
    )

    # 注: UNIQUE (tenant_id, project_id, id) は既存 `agent_runs_uq_tenant_project_id`
    # (migration 0008 由来) で satisfy 済、本 migration では追加しない (冗長回避)。

    # index: lease lookup 用 (orchestrator failover / heartbeat detection の効率化)
    op.create_index(
        "agent_runs_idx_lease_expires",
        "agent_runs",
        ["tenant_id", "orchestrator_lease_expires_at"],
        postgresql_where=sa.text("orchestrator_lease_expires_at is not null"),
    )


def downgrade() -> None:
    op.drop_index(
        "agent_runs_idx_lease_expires",
        table_name="agent_runs",
        postgresql_where=sa.text("orchestrator_lease_expires_at is not null"),
    )
    op.drop_constraint(
        "agent_runs_role_consistency",
        "agent_runs",
        type_="check",
    )
    op.drop_constraint(
        "agent_runs_ck_role_scope",
        "agent_runs",
        type_="check",
    )
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_column("progress_seq")
        batch_op.drop_column("last_progress_at")
        batch_op.drop_column("orchestrator_kill_at")
        batch_op.drop_column("lease_renewed_at")
        batch_op.drop_column("orchestrator_lease_expires_at")
        batch_op.drop_column("orchestrator_lease_token")
        batch_op.drop_column("role_scope")
        batch_op.drop_column("role_id")
