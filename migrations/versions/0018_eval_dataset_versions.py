"""Add Eval Harness dataset version tables.

Revision ID: 0018_eval_dataset_versions
Revises: 0017_claims_evidence_items
Create Date: 2026-05-16 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_eval_dataset_versions"
down_revision: str | None = "0017_claims_evidence_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_READY_DEFAULT = sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb")
EMPTY_JSON_DEFAULT = sa.text("'{}'::jsonb")
TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")
UUID_V4_DEFAULT = sa.text("uuid_generate_v4()")


def upgrade() -> None:
    op.create_table(
        "dataset_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("dataset_key", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("fixture_kind", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "fixture_kind in ('public_regression','private_holdout','adversarial_new')",
            name="dataset_versions_ck_fixture_kind",
        ),
        sa.CheckConstraint(
            "length(dataset_key) between 1 and 200",
            name="dataset_versions_ck_dataset_key_length",
        ),
        sa.CheckConstraint(
            "length(version) between 1 and 100",
            name="dataset_versions_ck_version_length",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[a-f0-9]{64}$'",
            name="dataset_versions_ck_content_hash_format",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="dataset_versions_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="dataset_versions_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="dataset_versions_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "dataset_key",
            "version",
            "fixture_kind",
            name="dataset_versions_uq_tenant_dataset_key_version_kind",
        ),
    )
    op.create_index(
        "dataset_versions_ix_tenant_kind_created",
        "dataset_versions",
        ["tenant_id", "fixture_kind", "created_at"],
    )

    op.create_table(
        "eval_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dataset_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suite_name", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column(
            "summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=EMPTY_JSON_DEFAULT,
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(suite_name) between 1 and 100",
            name="eval_runs_ck_suite_name_length",
        ),
        sa.CheckConstraint(
            "length(provider) between 1 and 50",
            name="eval_runs_ck_provider_length",
        ),
        sa.CheckConstraint(
            "length(model) between 1 and 100",
            name="eval_runs_ck_model_length",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="eval_runs_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["agent_runs.tenant_id", "agent_runs.id"],
            name="eval_runs_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "dataset_version_id"],
            ["dataset_versions.tenant_id", "dataset_versions.id"],
            name="eval_runs_dataset_version_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="eval_runs_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="eval_runs_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            "dataset_version_id",
            name="eval_runs_uq_tenant_id_dataset_version",
        ),
        # F-PR28-R3-005 P2 adopt: composite unique key needed as the FK target
        # for future RetrievalEvalRun spec (SP-010 QL-C cross-ref):
        # ``(tenant_id, eval_run_id, agent_run_id) references eval_runs(tenant_id, id, run_id)``.
        # Even though ``(tenant_id, id)`` is already unique, the FK target tuple
        # must be declared explicitly.
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            "run_id",
            name="eval_runs_uq_tenant_id_run",
        ),
    )
    op.create_index(
        "eval_runs_ix_tenant_dataset_started",
        "eval_runs",
        ["tenant_id", "dataset_version_id", "started_at"],
    )

    op.create_table(
        "eval_cases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("dataset_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_key", sa.Text(), nullable=False),
        sa.Column("case_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expected_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "length(case_key) between 1 and 200",
            name="eval_cases_ck_case_key_length",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="eval_cases_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "dataset_version_id"],
            ["dataset_versions.tenant_id", "dataset_versions.id"],
            name="eval_cases_dataset_version_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="eval_cases_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="eval_cases_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            "dataset_version_id",
            name="eval_cases_uq_tenant_id_dataset_version",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "dataset_version_id",
            "case_key",
            name="eval_cases_uq_tenant_dataset_case_key",
        ),
    )
    op.create_index(
        "eval_cases_ix_tenant_dataset",
        "eval_cases",
        ["tenant_id", "dataset_version_id"],
    )

    op.create_table(
        "eval_scores",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("eval_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("eval_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_key", sa.Text(), nullable=False),
        sa.Column("score", sa.Numeric(12, 4), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=EMPTY_JSON_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "length(metric_key) between 1 and 100",
            name="eval_scores_ck_metric_key_length",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="eval_scores_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "eval_run_id", "dataset_version_id"],
            ["eval_runs.tenant_id", "eval_runs.id", "eval_runs.dataset_version_id"],
            name="eval_scores_eval_run_dataset_version_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "eval_case_id", "dataset_version_id"],
            ["eval_cases.tenant_id", "eval_cases.id", "eval_cases.dataset_version_id"],
            name="eval_scores_eval_case_dataset_version_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="eval_scores_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "eval_run_id",
            "eval_case_id",
            "metric_key",
            name="eval_scores_uq_tenant_run_case_metric",
        ),
    )
    op.create_index(
        "eval_scores_ix_tenant_run_metric",
        "eval_scores",
        ["tenant_id", "eval_run_id", "metric_key"],
    )


def downgrade() -> None:
    op.drop_index("eval_scores_ix_tenant_run_metric", table_name="eval_scores")
    op.drop_index("eval_cases_ix_tenant_dataset", table_name="eval_cases")
    op.drop_index("eval_runs_ix_tenant_dataset_started", table_name="eval_runs")
    op.drop_index("dataset_versions_ix_tenant_kind_created", table_name="dataset_versions")

    op.drop_table("eval_scores")
    op.drop_table("eval_cases")
    op.drop_table("eval_runs")
    op.drop_table("dataset_versions")
