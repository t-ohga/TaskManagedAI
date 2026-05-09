"""Add AgentRun lifecycle and event log tables.

Revision ID: 0008_agent_runs_lifecycle
Revises: 0007_approval_temporal_check
Create Date: 2026-05-09 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_agent_runs_lifecycle"
down_revision: str | None = "0007_approval_temporal_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")
UUID_V4_DEFAULT = sa.text("uuid_generate_v4()")

# repository の _PROHIBITED_PAYLOAD_KEYS と一致 (drift 防止のため import せず literal で書く)
_PROHIBITED_EVENT_PAYLOAD_KEYS: tuple[str, ...] = (
    "api_key",
    "api_token",
    "raw_secret",
    "secret",
    "secret_value",
    "private_key",
    "auth_token",
    "bearer_token",
    "capability_token",
    "capability_token_value",
    "provider_key",
    "github_installation_token",
    "github_app_private_key",
    "tailscale_auth_key",
    "sops_age_key",
    "age_private_key",
    "canary_value",
    "raw_canary",
)


def _prohibited_event_payload_keys_jsonpath() -> str:
    disjunction = " || ".join(
        f'@.key == "{key}"' for key in _PROHIBITED_EVENT_PAYLOAD_KEYS
    )
    return (
        "'strict $.** ? (@.type() == \"object\")."
        f"keyvalue() ? ({disjunction})'"
    )


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("tokens_input", sa.BigInteger(), nullable=True),
        sa.Column("tokens_output", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in "
            "('queued','gathering_context','running','generated_artifact',"
            "'schema_validated','policy_linted','diff_ready','waiting_approval',"
            "'blocked','provider_refused','provider_incomplete','validation_failed',"
            "'repair_exhausted','completed','failed','cancelled')",
            name="agent_runs_ck_status",
        ),
        sa.CheckConstraint(
            "blocked_reason is null or blocked_reason in "
            "('policy_blocked','budget_blocked','runtime_blocked')",
            name="agent_runs_ck_blocked_reason",
        ),
        sa.CheckConstraint(
            "(status = 'blocked' and blocked_reason is not null) "
            "or (status <> 'blocked' and blocked_reason is null)",
            name="agent_runs_ck_blocked_reason_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="agent_runs_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="agent_runs_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "parent_run_id"],
            ["agent_runs.tenant_id", "agent_runs.project_id", "agent_runs.id"],
            name="agent_runs_parent_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="agent_runs_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="agent_runs_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="agent_runs_uq_tenant_project_id",
        ),
    )
    op.create_index(
        "agent_runs_idx_tenant_project_status",
        "agent_runs",
        ["tenant_id", "project_id", "status"],
    )
    op.create_index(
        "agent_runs_idx_tenant_project_parent",
        "agent_runs",
        ["tenant_id", "project_id", "parent_run_id"],
        postgresql_where=sa.text("parent_run_id is not null"),
    )
    op.create_index(
        "agent_runs_idx_tenant_created_at",
        "agent_runs",
        ["tenant_id", "created_at"],
    )
    op.execute(
        """
        CREATE TRIGGER agent_runs_set_updated_at
        BEFORE UPDATE ON agent_runs
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )

    op.create_table(
        "agent_run_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq_no", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "event_type in "
            "('run_queued','context_gathered','provider_requested','provider_responded',"
            "'artifact_generated','schema_validated','validation_failed',"
            "'repair_retry_scheduled','policy_linted','policy_blocked','budget_blocked',"
            "'runtime_blocked','diff_ready','approval_requested','approval_decided',"
            "'runner_started','runner_completed','runner_blocked','repo_pr_opened',"
            "'run_completed','run_failed','run_cancelled')",
            name="agent_run_events_ck_event_type",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(event_payload) = 'object'",
            name="agent_run_events_ck_event_payload_object",
        ),
        sa.CheckConstraint(
            "not jsonb_path_exists(event_payload, "
            f"{_prohibited_event_payload_keys_jsonpath()}::jsonpath)",
            name="agent_run_events_ck_no_prohibited_payload_keys",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="agent_run_events_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["agent_runs.tenant_id", "agent_runs.id"],
            name="agent_run_events_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="agent_run_events_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="agent_run_events_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="agent_run_events_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "run_id",
            "seq_no",
            name="agent_run_events_uq_tenant_run_seq_no",
        ),
    )
    op.create_index(
        "agent_run_events_uq_tenant_run_idempotency_key",
        "agent_run_events",
        ["tenant_id", "run_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key is not null"),
    )
    op.create_index(
        "agent_run_events_idx_tenant_run_created",
        "agent_run_events",
        ["tenant_id", "run_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("agent_run_events")
    op.execute("DROP TRIGGER IF EXISTS agent_runs_set_updated_at ON agent_runs")
    op.drop_table("agent_runs")

