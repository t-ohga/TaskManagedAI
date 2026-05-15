"""Add claims and evidence item Research/Evidence tables.

Revision ID: 0017_claims_evidence_items
Revises: 0016_research_evidence
Create Date: 2026-05-16 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_claims_evidence_items"
down_revision: str | None = "0016_research_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_READY_DEFAULT = sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb")
TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")
UUID_V4_DEFAULT = sa.text("uuid_generate_v4()")


def upgrade() -> None:
    op.create_table(
        "claims",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("research_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column(
            "provenance_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("freshness_score", sa.Double(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "length(claim_text) between 1 and 2000",
            name="claims_ck_claim_text_length",
        ),
        sa.CheckConstraint(
            "freshness_score is null or (freshness_score >= 0.0 and freshness_score <= 1.0)",
            name="claims_ck_freshness_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="claims_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "research_task_id"],
            ["research_tasks.tenant_id", "research_tasks.project_id", "research_tasks.id"],
            name="claims_research_task_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="claims_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="claims_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="claims_uq_tenant_project_id",
        ),
    )
    op.execute(
        """
        CREATE TRIGGER claims_set_updated_at
        BEFORE UPDATE ON claims
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )

    # F-PR19-R8-002 P2 adopt: list_claims_by_research_task (tenant_id, project_id, research_task_id)
    # filter + order by created_at, id の listing 用 index 追加 (performance optimization)。
    op.create_index(
        "claims_ix_tenant_project_research_task_created",
        "claims",
        ["tenant_id", "project_id", "research_task_id", "created_at", "id"],
    )

    op.create_table(
        "evidence_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column("relevance_score", sa.Double(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "length(locator) between 1 and 500",
            name="evidence_items_ck_locator_length",
        ),
        sa.CheckConstraint(
            "relevance_score is null or (relevance_score >= 0.0 and relevance_score <= 1.0)",
            name="evidence_items_ck_relevance_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="evidence_items_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "claim_id"],
            ["claims.tenant_id", "claims.project_id", "claims.id"],
            name="evidence_items_claim_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_id"],
            ["evidence_sources.tenant_id", "evidence_sources.id"],
            name="evidence_items_source_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="evidence_items_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="evidence_items_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "claim_id",
            "source_id",
            "locator",
            name="evidence_items_uq_claim_source_locator",
        ),
    )
    op.execute(
        """
        CREATE TRIGGER evidence_items_set_updated_at
        BEFORE UPDATE ON evidence_items
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS evidence_items_set_updated_at ON evidence_items")
    op.execute("DROP TRIGGER IF EXISTS claims_set_updated_at ON claims")
    op.drop_index("claims_ix_tenant_project_research_task_created", table_name="claims")

    op.drop_table("evidence_items")
    op.drop_table("claims")
