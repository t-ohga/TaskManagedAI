"""A-7: tickets.due_date column (期限設定).

Revision ID: 0037_a7_ticket_due_date
Revises: 0036_sp0095_request_revision
Create Date: 2026-05-28 00:00:00.000000

ADR-00034: nullable date カラム追加。期限は時刻概念のないカレンダー日付として扱い、
timezone 変換に起因する round-trip ずれを排除する。既存 row 無影響、rollback は drop_column。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037_a7_ticket_due_date"
down_revision: str | None = "0036_sp0095_request_revision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column("due_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tickets", "due_date")
