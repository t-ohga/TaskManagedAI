"""SP-009-5 batch D1: notification triage contract.

Revision ID: 0035_sp0095_notification_triage
Revises: 0034_sp024_autonomy_level
Create Date: 2026-05-24 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035_sp0095_notification_triage"
down_revision: str | None = "0034_sp024_autonomy_level"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEVERITY_CHECK = "severity in ('info','low','medium','high','critical')"
REQUIRED_ACTION_CHECK = (
    "required_action in "
    "('acknowledge','review_approval','inspect_run','resolve_blocker','external_followup')"
)


def upgrade() -> None:
    op.add_column(
        "notification_events",
        sa.Column("severity", sa.Text(), server_default=sa.text("'info'"), nullable=False),
    )
    op.add_column(
        "notification_events",
        sa.Column(
            "required_action",
            sa.Text(),
            server_default=sa.text("'acknowledge'"),
            nullable=False,
        ),
    )
    op.add_column("notification_events", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "notification_events",
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notification_events",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notification_events",
        sa.Column("resolved_by_actor_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("notification_events", sa.Column("dedupe_key", sa.Text(), nullable=True))

    op.create_check_constraint(
        "notification_events_ck_severity",
        "notification_events",
        SEVERITY_CHECK,
    )
    op.create_check_constraint(
        "notification_events_ck_required_action",
        "notification_events",
        REQUIRED_ACTION_CHECK,
    )
    op.create_check_constraint(
        "notification_events_ck_resolved_consistency",
        "notification_events",
        "(resolved_at is null and resolved_by_actor_id is null) "
        "or (resolved_at is not null and resolved_by_actor_id is not null)",
    )
    op.create_foreign_key(
        "notification_events_resolved_by_actor_fkey",
        "notification_events",
        "actors",
        ["tenant_id", "resolved_by_actor_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "notification_events_idx_triage_open",
        "notification_events",
        ["tenant_id", "recipient_actor_id", "severity", "due_at", "created_at"],
        postgresql_where=sa.text("resolved_at is null"),
    )
    op.create_index(
        "notification_events_uq_open_dedupe",
        "notification_events",
        ["tenant_id", "recipient_actor_id", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key is not null and resolved_at is null"),
    )


def downgrade() -> None:
    op.drop_index(
        "notification_events_uq_open_dedupe",
        table_name="notification_events",
        postgresql_where=sa.text("dedupe_key is not null and resolved_at is null"),
    )
    op.drop_index(
        "notification_events_idx_triage_open",
        table_name="notification_events",
        postgresql_where=sa.text("resolved_at is null"),
    )
    op.drop_constraint(
        "notification_events_resolved_by_actor_fkey",
        "notification_events",
        type_="foreignkey",
    )
    op.drop_constraint(
        "notification_events_ck_resolved_consistency",
        "notification_events",
        type_="check",
    )
    op.drop_constraint(
        "notification_events_ck_required_action",
        "notification_events",
        type_="check",
    )
    op.drop_constraint("notification_events_ck_severity", "notification_events", type_="check")

    op.drop_column("notification_events", "dedupe_key")
    op.drop_column("notification_events", "resolved_by_actor_id")
    op.drop_column("notification_events", "resolved_at")
    op.drop_column("notification_events", "snoozed_until")
    op.drop_column("notification_events", "due_at")
    op.drop_column("notification_events", "required_action")
    op.drop_column("notification_events", "severity")
