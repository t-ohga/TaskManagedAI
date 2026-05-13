"""Add Research/Evidence foundation skeleton tables.

Revision ID: 0016_research_evidence
Revises: 0015_artifact_prohibited_keys_21
Create Date: 2026-05-13 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_research_evidence"
down_revision: str | None = "0015_artifact_prohibited_keys_21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_READY_DEFAULT = sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb")
TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")
UUID_V4_DEFAULT = sa.text("uuid_generate_v4()")


def upgrade() -> None:
    op.create_table(
        "research_tasks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'queued'"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "status in ('queued','running','completed','failed')",
            name="research_tasks_ck_status",
        ),
        sa.CheckConstraint(
            "length(title) between 1 and 200",
            name="research_tasks_ck_title_length",
        ),
        sa.CheckConstraint(
            "(description is null) or (length(description) <= 2000)",
            name="research_tasks_ck_description_length",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="research_tasks_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="research_tasks_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="research_tasks_created_by_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="research_tasks_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="research_tasks_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="research_tasks_uq_tenant_project_id",
        ),
    )
    op.execute(
        """
        CREATE TRIGGER research_tasks_set_updated_at
        BEFORE UPDATE ON research_tasks
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )

    op.create_table(
        "evidence_sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "length(canonical_url) between 1 and 2000",
            name="evidence_sources_ck_canonical_url_length",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[a-f0-9]{64}$'",
            name="evidence_sources_ck_content_hash_sha256_hex",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="evidence_sources_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="evidence_sources_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="evidence_sources_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "canonical_url",
            name="evidence_sources_uq_tenant_canonical_url",
        ),
    )
    op.execute(
        """
        CREATE TRIGGER evidence_sources_set_updated_at
        BEFORE UPDATE ON evidence_sources
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS evidence_sources_set_updated_at ON evidence_sources")
    op.execute("DROP TRIGGER IF EXISTS research_tasks_set_updated_at ON research_tasks")

    op.drop_table("evidence_sources")
    op.drop_table("research_tasks")
