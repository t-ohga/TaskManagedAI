"""M-3: projects.description column (設定編集機能).

Revision ID: 0038_m3_project_description
Revises: 0037_a7_ticket_due_date
Create Date: 2026-05-28 00:00:00.000000

ADR-00035: nullable text カラム追加。プロジェクト説明を Settings UI で編集可能にする。
既存 row 無影響、rollback は drop_column。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038_m3_project_description"
down_revision: str | None = "0037_a7_ticket_due_date"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("description", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "description")
