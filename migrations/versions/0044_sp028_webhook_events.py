"""GitHub webhook events (SP-028): github_webhook_events table。

Revision ID: 0044_sp028_webhook_events
Revises: 0043_sp034_mcp_idempotency
Create Date: 2026-06-05 00:00:00.000000

ADR-00050. verification accepted 後の best-effort read-only enrichment で PR / CI イベントの非機密
field のみを保存する。既存 webhook ingress security (verifier / secret resolver / replay store) は不変。

- unique (tenant_id, delivery_id) で GitHub redelivery を冪等化 (conflict は payload_hash 比較、R2 F-002/F-003)。
- 複合 FK (tenant_id, repository_id) -> repositories(tenant_id, id) を **ON DELETE SET NULL (repository_id)**
  (PostgreSQL 16 column-list、tenant_id は NULL 化しない、R1 F-003)。MATCH SIMPLE なので repository_id NULL
  (quarantine) row は FK 未チェック。
- event_kind / status / quarantine_reason は固定 enum、全 string field は length CHECK (parser bound と同値、
  R1 F-010、5+ source 整合)。
- read feed index (tenant_id, status, repository_id, received_at DESC, id DESC) (R1 F-012)。

additive のみ (既存 table 不変)。downgrade は新 table drop = 蓄積 event row は失われる (ADR-00050 §rollback)。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0044_sp028_webhook_events"
down_revision: str | None = "0043_sp034_mcp_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "github_webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False
        ),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("delivery_id", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("event_kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("quarantine_reason", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=True),
        sa.Column("external_ref", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("sender_login", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=NOW_DEFAULT,
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="github_webhook_events_pkey"),
        sa.UniqueConstraint(
            "tenant_id", "delivery_id", name="github_webhook_events_uq_tenant_delivery"
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="github_webhook_events_uq_tenant_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="github_webhook_events_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "event_kind IN ('pull_request', 'check_run', 'check_suite', 'status', 'push')",
            name="github_webhook_events_event_kind_check",
        ),
        sa.CheckConstraint(
            "status IN ('accepted', 'quarantined')",
            name="github_webhook_events_status_check",
        ),
        sa.CheckConstraint(
            "(status = 'accepted' AND quarantine_reason IS NULL) "
            "OR (status = 'quarantined' AND quarantine_reason IN "
            "('unregistered_repo', 'repo_lookup_ambiguous', 'payload_shape_mismatch', "
            "'header_event_mismatch', 'parse_validation_failed'))",
            name="github_webhook_events_quarantine_reason_check",
        ),
        sa.CheckConstraint(
            "length(delivery_id) > 0 AND length(delivery_id) <= 100",
            name="github_webhook_events_delivery_id_length_check",
        ),
        sa.CheckConstraint(
            "action IS NULL OR length(action) <= 64",
            name="github_webhook_events_action_length_check",
        ),
        sa.CheckConstraint(
            "external_ref IS NULL OR length(external_ref) <= 255",
            name="github_webhook_events_external_ref_length_check",
        ),
        sa.CheckConstraint(
            "state IS NULL OR length(state) <= 32",
            name="github_webhook_events_state_length_check",
        ),
        sa.CheckConstraint(
            "title IS NULL OR length(title) <= 512",
            name="github_webhook_events_title_length_check",
        ),
        sa.CheckConstraint(
            "sender_login IS NULL OR length(sender_login) <= 64",
            name="github_webhook_events_sender_login_length_check",
        ),
    )
    # 複合 FK は PostgreSQL 16 の column-list ON DELETE SET NULL (repository_id) で付与する。
    # SQLAlchemy ForeignKeyConstraint は column-list SET NULL を直接表現できないため raw DDL。
    # repository 削除時に repository_id だけ NULL 化し tenant_id NOT NULL を保つ (R1 F-003)。
    op.execute(
        "ALTER TABLE github_webhook_events "
        "ADD CONSTRAINT github_webhook_events_repository_fkey "
        "FOREIGN KEY (tenant_id, repository_id) "
        "REFERENCES repositories (tenant_id, id) "
        "ON DELETE SET NULL (repository_id)"
    )
    op.create_index(
        "github_webhook_events_ix_feed",
        "github_webhook_events",
        ["tenant_id", "status", "repository_id", sa.text("received_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "github_webhook_events_ix_feed", table_name="github_webhook_events"
    )
    op.drop_table("github_webhook_events")
