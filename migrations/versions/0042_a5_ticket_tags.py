"""Add ticket tags (A-5): tags + ticket_tags join tables.

Revision ID: 0042_a5_ticket_tags
Revises: 0041_agent_run_event_notify
Create Date: 2026-06-02 00:00:00.000000

ADR-00044. project-scoped tag/label system。tags は project 境界の複合 FK で閉じ、
ticket_tags は (tenant_id, project_id) を両 FK で共有して同一 project の ticket/tag のみ
付与可能。FK2 (ticket_tags -> tags) は ON DELETE RESTRICT で「使用中 tag の削除」を DB enforce。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042_a5_ticket_tags"
down_revision: str | None = "0041_agent_run_event_notify"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_READY_DEFAULT = sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb")
TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")

# ADR-00044: 固定 color palette (UI / caller 自由入力不可、5+ source 整合の DB CHECK 側)
TAG_COLORS = ("slate", "red", "orange", "amber", "green", "teal", "blue", "purple", "pink")


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("color", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "char_length(name) between 1 and 50",
            name="tags_ck_name_length",
        ),
        sa.CheckConstraint(
            "color in (" + ", ".join(f"'{c}'" for c in TAG_COLORS) + ")",
            name="tags_ck_color",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="tags_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="tags_project_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="tags_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="tags_uq_tenant_id"),
        # ticket_tags の複合 FK target + 同一 project 強制のための複合 unique
        sa.UniqueConstraint("tenant_id", "project_id", "id", name="tags_uq_tenant_project_id"),
        # project 内で tag 名重複禁止 (ADR-00044)
        sa.UniqueConstraint("tenant_id", "project_id", "name", name="tags_uq_tenant_project_name"),
    )

    op.create_table(
        "ticket_tags",
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="ticket_tags_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        # FK1: ticket 削除時は付与も消える
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "ticket_id"],
            ["tickets.tenant_id", "tickets.project_id", "tickets.id"],
            name="ticket_tags_ticket_fkey",
            ondelete="CASCADE",
        ),
        # FK2 (ADR-00044 R6): ON DELETE RESTRICT で「使用中 tag の削除」を DB レベルで拒否。
        # 両 FK が (tenant_id, project_id) を共有するため ticket と tag は必ず同一 project。
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "tag_id"],
            ["tags.tenant_id", "tags.project_id", "tags.id"],
            name="ticket_tags_tag_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "project_id", "ticket_id", "tag_id", name="ticket_tags_pkey"
        ),
    )
    # tag -> ticket 逆引き / tag filter 用
    op.create_index(
        "ticket_tags_ix_tag",
        "ticket_tags",
        ["tenant_id", "project_id", "tag_id"],
    )


def downgrade() -> None:
    # FK 依存順: ticket_tags -> tags。運用中 rollback は事前 backup / maintenance window 前提 (ADR-00044)。
    op.drop_index("ticket_tags_ix_tag", table_name="ticket_tags")
    op.drop_table("ticket_tags")
    op.drop_table("tags")
