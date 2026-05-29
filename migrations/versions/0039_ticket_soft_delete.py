"""Q-3 (ADR-00037): ticket soft-delete columns (deleted_at / deleted_batch_id / deleted_by_actor_id).

Revision ID: 0039_ticket_soft_delete
Revises: 0038_m3_project_description
Create Date: 2026-05-29 00:00:00.000000

ADR-00037: ticket 一括 soft-delete + batch restore のための nullable 3 列追加。既存行無影響。
downgrade は **fail-closed** (Codex plan R3/R4/R5): soft-deleted 行が存在する状態で column を落とすと、
owner が削除した ticket が restore 確認・audit なしで全 read path に silent resurrection するため、
ACCESS EXCLUSIVE lock を取得してから count を確認し、1 件でも deleted_at IS NOT NULL があれば中断する。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "0039_ticket_soft_delete"
down_revision: str | None = "0038_m3_project_description"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "tickets",
        sa.Column("deleted_batch_id", PG_UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "tickets",
        sa.Column(
            "deleted_by_actor_id", PG_UUID(as_uuid=True), nullable=True
        ),
    )
    # soft-deleted ticket を効率的に除外/列挙するための index。
    op.create_index(
        "tickets_idx_active",
        "tickets",
        ["tenant_id", "project_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "tickets_idx_deleted_batch",
        "tickets",
        ["tenant_id", "project_id", "deleted_batch_id"],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )


def downgrade() -> None:
    # Codex plan R3/R4/R5: fail-closed downgrade。ACCESS EXCLUSIVE lock を取得してから count を
    # 確認し (lock-before-count、TOCTOU 排除)、soft-deleted 行が 1 件でもあれば中断する。
    # column を黙って drop すると silent resurrection になるため。
    bind = op.get_bind()
    bind.execute(sa.text("LOCK TABLE tickets IN ACCESS EXCLUSIVE MODE"))
    deleted_count = bind.execute(
        sa.text("SELECT count(*) FROM tickets WHERE deleted_at IS NOT NULL")
    ).scalar_one()
    if deleted_count and int(deleted_count) > 0:
        raise RuntimeError(
            "Refusing to downgrade 0039_ticket_soft_delete: "
            f"{deleted_count} soft-deleted ticket(s) exist. Restore the deletion batches "
            "(or explicitly accept resurrection) before dropping the soft-delete columns; "
            "dropping them silently resurrects deleted tickets across all read paths."
        )
    op.drop_index("tickets_idx_deleted_batch", table_name="tickets")
    op.drop_index("tickets_idx_active", table_name="tickets")
    op.drop_column("tickets", "deleted_by_actor_id")
    op.drop_column("tickets", "deleted_batch_id")
    op.drop_column("tickets", "deleted_at")
