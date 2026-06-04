"""MCP create idempotency (SP-034): mcp_idempotency_keys reservation table.

Revision ID: 0043_sp034_mcp_idempotency
Revises: 0042_a5_ticket_tags
Create Date: 2026-06-05 00:00:00.000000

ADR-00049. MCP create 系 (ticket_create / run_create) の作成-level idempotency。
(tenant_id, actor_id, tool_name, idempotency_key) で bind し cross-actor replay を deny。
reservation-first: row を先に予約 (created_resource_* NULL) し、winner だけが resource を作成して
completed (3 列同時 set) にする。CHECK で「全 NULL (reservation 中) か 全 NOT NULL (completed)」を
DB enforce し、loser が半端 resource を返さないことを保証する (ADR-00049 R2 F-N3 / R3 F-N4)。
additive のみ、downgrade lossless。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043_sp034_mcp_idempotency"
down_revision: str | None = "0042_a5_ticket_tags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")

# ADR-00049: idempotency 対象 MCP tool (5+ source 整合の DB CHECK 側)。
TOOL_NAMES = ("ticket_create", "run_create")
RESOURCE_KINDS = ("ticket", "agent_run")


def upgrade() -> None:
    op.create_table(
        "mcp_idempotency_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False
        ),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        # reservation 中は NULL、completed で 3 列同時 set (CHECK で enforce)。
        sa.Column("created_resource_kind", sa.Text(), nullable=True),
        sa.Column("created_resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="mcp_idempotency_keys_pkey"),
        # cross-actor replay deny の核: 同 (tenant, actor, tool, key) は 1 row のみ。
        sa.UniqueConstraint(
            "tenant_id",
            "actor_id",
            "tool_name",
            "idempotency_key",
            name="mcp_idempotency_keys_uq_tenant_actor_tool_key",
        ),
        # tool_name / resource_kind は固定 enum (5+ source 整合)。
        sa.CheckConstraint(
            "tool_name IN ('ticket_create', 'run_create')",
            name="mcp_idempotency_keys_tool_name_check",
        ),
        sa.CheckConstraint(
            "created_resource_kind IS NULL "
            "OR created_resource_kind IN ('ticket', 'agent_run')",
            name="mcp_idempotency_keys_resource_kind_check",
        ),
        # R2 F-N3 / R3 F-N4: reservation 中 (全 NULL) か completed (3 列全 NOT NULL) のいずれかのみ。
        # winner の completion UPDATE は created_resource_kind / created_resource_id / completed_at を
        # 同時 set する必要がある (3 列が揃わないと CHECK violation)。
        sa.CheckConstraint(
            "(created_resource_kind IS NULL AND created_resource_id IS NULL "
            "AND completed_at IS NULL) "
            "OR (created_resource_kind IS NOT NULL AND created_resource_id IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name="mcp_idempotency_keys_reservation_complete_check",
        ),
    )


def downgrade() -> None:
    op.drop_table("mcp_idempotency_keys")
