"""SP-020 batch T05: adopted artifact attribution schema.

Revision ID: 0033_sp020_adopted_artifacts
Revises: 0032_sp018_memory_records
Create Date: 2026-05-24 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033_sp020_adopted_artifacts"
down_revision: str | None = "0032_sp018_memory_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW_DEFAULT = sa.text("now()")
TENANT_ID_DEFAULT = sa.text("1")
UUID_V4_DEFAULT = sa.text("uuid_generate_v4()")
RLS_READY_DEFAULT = sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb")
PROHIBITED_METADATA_KEYS: tuple[str, ...] = (
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
    "secret_capability_token",
    "raw_token",
    "session_token",
)


def _prohibited_metadata_keys_jsonpath() -> str:
    disjunction = " || ".join(f'@.key == "{key}"' for key in PROHIBITED_METADATA_KEYS)
    return (
        "'strict $.** ? (@.type() == \"object\")."
        f"keyvalue() ? ({disjunction})'"
    )


def upgrade() -> None:
    op.create_unique_constraint(
        "agent_run_events_uq_tenant_run_id",
        "agent_run_events",
        ["tenant_id", "run_id", "id"],
    )
    op.create_table(
        "adopted_artifacts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "adoption_state",
            sa.Text(),
            server_default=sa.text("'final'"),
            nullable=False,
        ),
        sa.Column("adoption_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("adopted_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), server_default=RLS_READY_DEFAULT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "adoption_state in ('draft','final')",
            name="adopted_artifacts_ck_adoption_state",
        ),
        sa.CheckConstraint(
            "((adoption_state = 'final' and finalized_at is not null "
            "and adoption_event_id is not null) or "
            "(adoption_state = 'draft' and finalized_at is null "
            "and adoption_event_id is null))",
            name="adopted_artifacts_ck_final_event_consistency",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="adopted_artifacts_ck_metadata_object",
        ),
        sa.CheckConstraint(
            "not jsonb_path_exists(metadata, "
            f"{_prohibited_metadata_keys_jsonpath()}::jsonpath)",
            name="adopted_artifacts_ck_no_prohibited_metadata_keys",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="adopted_artifacts_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="adopted_artifacts_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "run_id"],
            ["agent_runs.tenant_id", "agent_runs.project_id", "agent_runs.id"],
            name="adopted_artifacts_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "artifact_id"],
            ["artifacts.tenant_id", "artifacts.project_id", "artifacts.id"],
            name="adopted_artifacts_artifact_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id", "adoption_event_id"],
            ["agent_run_events.tenant_id", "agent_run_events.run_id", "agent_run_events.id"],
            name="adopted_artifacts_adoption_event_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "adopted_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="adopted_artifacts_adopted_by_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="adopted_artifacts_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="adopted_artifacts_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="adopted_artifacts_uq_tenant_project_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "run_id",
            "artifact_id",
            name="adopted_artifacts_uq_tenant_project_run_artifact",
        ),
        comment=(
            "Dedicated final-adopted artifact attribution table. "
            "citation_coverage uses only adoption_state='final' rows."
        ),
    )
    op.create_index(
        "adopted_artifacts_idx_final_project_run",
        "adopted_artifacts",
        ["tenant_id", "project_id", "run_id"],
        postgresql_where=sa.text("adoption_state = 'final'"),
    )
    op.create_index(
        "adopted_artifacts_idx_final_artifact",
        "adopted_artifacts",
        ["tenant_id", "project_id", "artifact_id"],
        postgresql_where=sa.text("adoption_state = 'final'"),
    )


def downgrade() -> None:
    op.drop_index("adopted_artifacts_idx_final_artifact", table_name="adopted_artifacts")
    op.drop_index("adopted_artifacts_idx_final_project_run", table_name="adopted_artifacts")
    op.drop_table("adopted_artifacts")
    op.drop_constraint(
        "agent_run_events_uq_tenant_run_id",
        "agent_run_events",
        type_="unique",
    )
