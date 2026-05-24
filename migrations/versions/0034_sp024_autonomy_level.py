"""SP-024 batch T02: project autonomy level.

Revision ID: 0034_sp024_autonomy_level
Revises: 0033_sp020_adopted_artifacts
Create Date: 2026-05-24 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034_sp024_autonomy_level"
down_revision: str | None = "0033_sp020_adopted_artifacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUTONOMY_LEVEL_CHECK = "autonomy_level in ('L0','L1','L2','L3')"


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "autonomy_level",
            sa.Text(),
            server_default=sa.text("'L0'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "projects_ck_autonomy_level",
        "projects",
        AUTONOMY_LEVEL_CHECK,
    )
    op.create_index(
        "projects_idx_tenant_autonomy_level",
        "projects",
        ["tenant_id", "autonomy_level"],
    )


def downgrade() -> None:
    op.drop_index("projects_idx_tenant_autonomy_level", table_name="projects")
    op.drop_constraint("projects_ck_autonomy_level", "projects", type_="check")
    op.drop_column("projects", "autonomy_level")
