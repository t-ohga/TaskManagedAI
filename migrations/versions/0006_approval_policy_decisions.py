"""Add approval requests and policy decisions.

Revision ID: 0006_approval_policy_decisions
Revises: 0005_policy_rules
Create Date: 2026-05-08 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_approval_policy_decisions"
down_revision: str | None = "0005_policy_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_READY_DEFAULT = sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb")
TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")
UUID_V4_DEFAULT = sa.text("uuid_generate_v4()")


def upgrade() -> None:
    op.create_table(
        "approval_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        # TODO Sprint 4: add FK (tenant_id, run_id) -> agent_runs(tenant_id, id).
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_class", sa.Text(), nullable=False),
        sa.Column("resource_ref", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.Text(), nullable=False),
        sa.Column("artifact_hash", sa.Text(), nullable=True),
        sa.Column("diff_hash", sa.Text(), nullable=True),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("policy_pack_lock", sa.Text(), nullable=True),
        sa.Column("provider_request_fingerprint", sa.Text(), nullable=True),
        sa.Column("stale_after_event_seq", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("requested_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decided_by_actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.CheckConstraint(
            "action_class in "
            "('task_write','repo_write','pr_open','secret_access','merge','deploy','provider_call')",
            name="approval_requests_ck_action_class",
        ),
        sa.CheckConstraint(
            "risk_level in ('low','medium','high','critical')",
            name="approval_requests_ck_risk_level",
        ),
        sa.CheckConstraint(
            "status in ('pending','approved','rejected','expired','invalidated')",
            name="approval_requests_ck_status",
        ),
        sa.CheckConstraint(
            "status not in ('approved','rejected') "
            "or (decided_by_actor_id is not null and decided_at is not null)",
            name="approval_requests_ck_decision_completeness",
        ),
        sa.CheckConstraint(
            "decided_by_actor_id is null or requested_by_actor_id != decided_by_actor_id",
            name="approval_requests_ck_self_approval",
        ),
        sa.CheckConstraint(
            "(decided_by_actor_id is null and decided_at is null) "
            "or (decided_by_actor_id is not null and decided_at is not null)",
            name="approval_requests_ck_decided_at_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="approval_requests_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="approval_requests_requested_by_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "decided_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="approval_requests_decided_by_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="approval_requests_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="approval_requests_uq_tenant_id"),
    )

    op.create_table(
        "policy_decisions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        # TODO Sprint 4: add FK (tenant_id, run_id) -> agent_runs(tenant_id, id).
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approval_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_class", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("input_hash", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "action_class in "
            "('task_write','repo_write','pr_open','secret_access','merge','deploy','provider_call')",
            name="policy_decisions_ck_action_class",
        ),
        sa.CheckConstraint(
            "decision in ('allow','deny','require_approval')",
            name="policy_decisions_ck_decision",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="policy_decisions_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approval_request_id"],
            ["approval_requests.tenant_id", "approval_requests.id"],
            name="policy_decisions_approval_request_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="policy_decisions_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="policy_decisions_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="policy_decisions_uq_tenant_id"),
    )

    op.create_index(
        "approval_requests_idx_tenant_status",
        "approval_requests",
        ["tenant_id", "status"],
    )
    op.create_index(
        "approval_requests_idx_tenant_run",
        "approval_requests",
        ["tenant_id", "run_id"],
        postgresql_where=sa.text("run_id is not null"),
    )
    op.create_index(
        "approval_requests_idx_requested_at",
        "approval_requests",
        ["tenant_id", "requested_at"],
    )

    op.create_index(
        "policy_decisions_idx_tenant_action_class",
        "policy_decisions",
        ["tenant_id", "action_class"],
    )
    op.create_index(
        "policy_decisions_idx_tenant_approval",
        "policy_decisions",
        ["tenant_id", "approval_request_id"],
        postgresql_where=sa.text("approval_request_id is not null"),
    )
    op.create_index(
        "policy_decisions_idx_created_at",
        "policy_decisions",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("policy_decisions")
    op.drop_table("approval_requests")

