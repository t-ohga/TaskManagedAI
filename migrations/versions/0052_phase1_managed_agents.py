"""SP-PHASE1 B2: managed_agents registry + agent_runs.pre_stop_status (ADR-00048 §F/A-1/A-2/A-5).

Adds the DB-backed agent supervision registry that makes cross-process kill possible:

- ``managed_agents`` table (新規): in-process ``_active_agents`` dict を DB-backed registry に置換し、
  kill の正本を process-local でなく DB にする (ADR-00048 §F)。supervisor は ``host_id`` /
  ``process_group_id`` / ``state`` を見て restart 後も ``killpg`` で kill 到達できる (A-2)。
  tenant_id NOT NULL + 複合 FK で tenant/project boundary に閉じる (core.md §8)。
- ``agent_runs.pre_stop_status`` (additive 列): emergency-stop block 時に block 前 status を保存し、
  clear / resume で復元する (A-5、B3 resume が依存)。nullable で既存 row は NULL backfill (非破壊)。
  block source = resume 復元先 = {running, policy_linted, diff_ready, waiting_approval} (ADR A-5)
  に限定する DB CHECK を付与 (4-layer 防御の DB 層、status/blocked_reason/run_mode の前例に倣う)。
- ``managed_agents`` partial unique index ``(tenant_id, agent_run_id) WHERE agent_run_id IS NOT NULL
  AND state IN ('spawning','running')``: 1 run = 1 active managed_agent を強制し二重 spawn を防ぐ。

additive のみ、downgrade は lossless (table drop + column drop + CHECK/index drop)。state CHECK /
pre_stop_status CHECK / partial unique の literal は **hardcode** (cross-source-enum-integrity §1:
migration が他 source と独立に同じ enum を宣言することで drift guard が成立する。Python Literal /
ORM CheckConstraint からの import に置き換えない)。

Revision ID: 0052_phase1_managed_agents
Revises: 0051_phase1_event_type_39
Create Date: 2026-06-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "0052_phase1_managed_agents"
down_revision: str | None = "0051_phase1_event_type_39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AGENT_RUNS = "agent_runs"
_PRE_STOP_COLUMN = "pre_stop_status"
_PRE_STOP_CONSTRAINT = "agent_runs_ck_pre_stop_status"
# ADR-00048 A-5: emergency block source / resume 復元先と一致する subset (hardcode、drift guard)。
_PRE_STOP_CHECK = (
    "pre_stop_status is null or pre_stop_status in "
    "('running','policy_linted','diff_ready','waiting_approval')"
)
_RUN_ACTIVE_UNIQUE_INDEX = "managed_agents_uq_active_agent_run"


def upgrade() -> None:
    op.create_table(
        "managed_agents",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "project_id",
            PG_UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "agent_run_id",
            PG_UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("host_id", sa.Text(), nullable=False),
        sa.Column("process_group_id", sa.Integer(), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("supervisor_id", sa.Text(), nullable=True),
        sa.Column(
            "state",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'spawning'"),
        ),
        sa.Column("boot_id", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="managed_agents_pkey"),
        sa.CheckConstraint(
            "state in ('spawning','running','stopped','failed')",
            name="managed_agents_ck_state",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="managed_agents_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="managed_agents_project_fkey",
            ondelete="RESTRICT",
        ),
        # agent_run_id IS NULL の registry 行は MATCH SIMPLE で FK 未強制 (run-less spawn)。
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "agent_run_id"],
            ["agent_runs.tenant_id", "agent_runs.project_id", "agent_runs.id"],
            name="managed_agents_agent_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="managed_agents_uq_tenant_id"),
    )
    op.create_index(
        "managed_agents_idx_host_state",
        "managed_agents",
        ["host_id", "state"],
    )
    op.create_index(
        "managed_agents_idx_tenant_state",
        "managed_agents",
        ["tenant_id", "state"],
    )
    # LOW-4: 1 run = 1 active managed_agent (二重 spawn 防止)。terminal 行は対象外なので
    # 同 run の再 spawn は許可される。
    op.create_index(
        _RUN_ACTIVE_UNIQUE_INDEX,
        "managed_agents",
        ["tenant_id", "agent_run_id"],
        unique=True,
        postgresql_where=sa.text(
            "agent_run_id is not null and state in ('spawning','running')"
        ),
    )

    # ADR-00048 A-5: emergency-stop resume が依存する pre_stop_status 列 (additive、nullable)。
    op.add_column(
        _AGENT_RUNS,
        sa.Column(_PRE_STOP_COLUMN, sa.Text(), nullable=True),
    )
    # MEDIUM-1 / LOW-5: 4-layer 防御の DB 層 (block source / resume 復元先 subset)。
    op.create_check_constraint(
        _PRE_STOP_CONSTRAINT,
        _AGENT_RUNS,
        _PRE_STOP_CHECK,
    )


def downgrade() -> None:
    op.drop_constraint(_PRE_STOP_CONSTRAINT, _AGENT_RUNS, type_="check")
    op.drop_column(_AGENT_RUNS, _PRE_STOP_COLUMN)
    op.drop_index(_RUN_ACTIVE_UNIQUE_INDEX, table_name="managed_agents")
    op.drop_index("managed_agents_idx_tenant_state", table_name="managed_agents")
    op.drop_index("managed_agents_idx_host_state", table_name="managed_agents")
    op.drop_table("managed_agents")
