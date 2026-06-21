"""SP-PHASE1 B3: superintendent_emergency_stops latch table (ADR-00048 §B/B-1/B-3/A-7).

Adds the persistent, tenant-scoped emergency-stop latch that makes "human がいつでも全 AI を
即停止できる" durable across processes:

- ``superintendent_emergency_stops`` table (新規): tenant-scoped emergency-stop state。
  ``generation`` (CAS, bigint) で engage/clear の stale 操作を線形化し (B-3、advisory lock A-7 と二重)、
  ``(tenant_id) WHERE cleared_at IS NULL`` partial unique で active latch を tenant 毎 ≤ 1 に強制する
  (二重 engage の構造的禁止)。actor は (tenant, actor) 複合 FK で tenant 越境を禁止する (core.md §8)。

additive のみ、downgrade は lossless (table drop + index drop)。新規活動 deny は latch row が無ければ
常に allow なので、revert 後も既存挙動に影響しない (ADR-00048 rollback §4)。

Revision ID: 0053_phase1_emergency_stop
Revises: 0052_phase1_managed_agents
Create Date: 2026-06-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "0053_phase1_emergency_stop"
down_revision: str | None = "0052_phase1_managed_agents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE_UNIQUE_INDEX = "superintendent_emergency_stops_uq_active"
_TENANT_GENERATION_INDEX = "superintendent_emergency_stops_idx_tenant_generation"


def upgrade() -> None:
    op.create_table(
        "superintendent_emergency_stops",
        sa.Column("id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("engaged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("engaged_by_actor_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleared_by_actor_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="superintendent_emergency_stops_pkey"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="superintendent_emergency_stops_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        # operator actor は同一 tenant の actor (human) のみ参照可 (tenant 越境禁止)。
        sa.ForeignKeyConstraint(
            ["tenant_id", "engaged_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="superintendent_emergency_stops_engaged_by_fkey",
            ondelete="RESTRICT",
        ),
        # cleared_by_actor_id IS NULL は MATCH SIMPLE で FK 未強制 (未 clear の active latch)。
        sa.ForeignKeyConstraint(
            ["tenant_id", "cleared_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="superintendent_emergency_stops_cleared_by_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="superintendent_emergency_stops_uq_tenant_id"
        ),
    )
    # active latch は tenant 毎 ≤ 1 (B、二重 engage の構造的禁止)。cleared 行は対象外。
    op.create_index(
        _ACTIVE_UNIQUE_INDEX,
        "superintendent_emergency_stops",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("cleared_at is null"),
    )
    op.create_index(
        _TENANT_GENERATION_INDEX,
        "superintendent_emergency_stops",
        ["tenant_id", "generation"],
    )


def downgrade() -> None:
    op.drop_index(
        _TENANT_GENERATION_INDEX, table_name="superintendent_emergency_stops"
    )
    op.drop_index(_ACTIVE_UNIQUE_INDEX, table_name="superintendent_emergency_stops")
    op.drop_table("superintendent_emergency_stops")
