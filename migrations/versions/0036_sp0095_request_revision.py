"""SP-009-5 batch E1: approval request revision contract.

Revision ID: 0036_sp0095_request_revision
Revises: 0035_sp0095_notification_triage
Create Date: 2026-05-24 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036_sp0095_request_revision"
down_revision: str | None = "0035_sp0095_notification_triage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_READY_DEFAULT = sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb")
TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")
UUID_V4_DEFAULT = sa.text("uuid_generate_v4()")


def upgrade() -> None:
    op.create_table(
        "approval_revision_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("approval_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("artifact_hash", sa.Text(), nullable=True),
        sa.Column("diff_hash", sa.Text(), nullable=True),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("policy_pack_lock", sa.Text(), nullable=True),
        sa.Column("provider_request_fingerprint", sa.Text(), nullable=True),
        sa.Column("stale_after_event_seq", sa.BigInteger(), nullable=True),
        sa.Column("superseded_by_approval_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(rationale) <> '' and char_length(rationale) <= 2000",
            name="approval_revision_requests_ck_rationale",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="approval_revision_requests_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approval_request_id"],
            ["approval_requests.tenant_id", "approval_requests.id"],
            name="approval_revision_requests_approval_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="approval_revision_requests_requested_by_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "superseded_by_approval_request_id"],
            ["approval_requests.tenant_id", "approval_requests.id"],
            name="approval_revision_requests_superseded_by_approval_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="approval_revision_requests_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="approval_revision_requests_uq_tenant_id"),
    )

    op.create_index(
        "approval_revision_requests_uq_open_approval",
        "approval_revision_requests",
        ["tenant_id", "approval_request_id"],
        unique=True,
        postgresql_where=sa.text("superseded_by_approval_request_id is null"),
    )
    op.create_index(
        "approval_revision_requests_idx_approval",
        "approval_revision_requests",
        ["tenant_id", "approval_request_id"],
    )
    op.create_index(
        "approval_revision_requests_idx_requested_by",
        "approval_revision_requests",
        ["tenant_id", "requested_by_actor_id", "created_at"],
    )
    op.create_index(
        "approval_revision_requests_idx_superseded_by",
        "approval_revision_requests",
        ["tenant_id", "superseded_by_approval_request_id"],
        postgresql_where=sa.text("superseded_by_approval_request_id is not null"),
    )


def downgrade() -> None:
    op.drop_index(
        "approval_revision_requests_idx_superseded_by",
        table_name="approval_revision_requests",
        postgresql_where=sa.text("superseded_by_approval_request_id is not null"),
    )
    op.drop_index("approval_revision_requests_idx_requested_by", table_name="approval_revision_requests")
    op.drop_index("approval_revision_requests_idx_approval", table_name="approval_revision_requests")
    op.drop_index(
        "approval_revision_requests_uq_open_approval",
        table_name="approval_revision_requests",
        postgresql_where=sa.text("superseded_by_approval_request_id is null"),
    )
    op.drop_table("approval_revision_requests")
