"""Add grounding_supports (BL-0119 citation_coverage source) + add
``unique (tenant_id, project_id, id)`` to evidence_items + extend
``artifacts.kind`` enum with ``research_promotion`` (BL-0118 Research-to-
Ticket artifact contract).

Sprint Pack SP-010 batch 3 (BL-0118 + BL-0119). The new table holds the
generated-artifact ↔ Evidence binding that AC-KPI-04 citation_coverage
consumes (claim-level numerator / denominator per SP-011 contract).

Revision ID: 0018_grounding_supports
Revises: 0017_claims_evidence_items
Create Date: 2026-05-16 12:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_grounding_supports"
down_revision: str | None = "0017_claims_evidence_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_READY_DEFAULT = sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb")
TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")
UUID_V4_DEFAULT = sa.text("uuid_generate_v4()")


def upgrade() -> None:
    # 1) Extend evidence_items with the project-scoped unique key that
    #    grounding_supports needs to bind ``(tenant_id, project_id,
    #    evidence_item_id)`` as a composite FK. The existing
    #    ``(tenant_id, id)`` unique stays in place for the tenant-level
    #    join paths used by compute_evidence_set_hash.
    op.create_unique_constraint(
        "evidence_items_uq_tenant_project_id",
        "evidence_items",
        ["tenant_id", "project_id", "id"],
    )

    # 2) Extend artifacts.kind CHECK to allow the Research-to-Ticket
    #    promotion artifact (BL-0118). Drop+recreate the constraint
    #    rather than ALTER COLUMN TYPE so existing rows are not rewritten.
    op.drop_constraint("artifacts_ck_kind", "artifacts", type_="check")
    op.create_check_constraint(
        "artifacts_ck_kind",
        "artifacts",
        "kind in "
        "('plan','patch','evidence','citation','provider_continuation_ref','other',"
        "'cli_input','cli_stdout','cli_stderr','cli_exit','cli_result_summary',"
        "'research_promotion')",
    )

    # 3) Create grounding_supports — generated_artifact ↔ Evidence
    #    binding for citation_coverage (AC-KPI-04 source).
    #
    #    QL-C spec (SP-010 §line 132-142): 2-stage FK split with
    #    ``agent_run_id`` (project binding) + ``run_id``/``generated_artifact_id``
    #    (artifact same-run binding). evidence_items reference uses the
    #    new ``(tenant_id, project_id, evidence_item_id)`` unique added
    #    above + a CHECK constraint asserting the evidence_item's
    #    claim_id and source_id match the GroundingSupport's own.
    op.create_table(
        "grounding_supports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generated_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("support_type", sa.Text(), nullable=False),
        sa.Column("confidence_score", sa.Double(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        # Enum CHECK
        sa.CheckConstraint(
            "support_type in ('cite', 'paraphrase', 'quote')",
            name="grounding_supports_ck_support_type",
        ),
        # Score range CHECK
        sa.CheckConstraint(
            "confidence_score is null or "
            "(confidence_score >= 0.0 and confidence_score <= 1.0)",
            name="grounding_supports_ck_confidence_score_range",
        ),
        # run_id and agent_run_id must point to the same AgentRun row
        # (the 2-stage FK design verifies it via separate joins; this
        # CHECK is the in-row equality assertion the spec mandates).
        sa.CheckConstraint(
            "run_id = agent_run_id",
            name="grounding_supports_ck_run_id_equals_agent_run_id",
        ),
        # Tenant boundary
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="grounding_supports_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        # Stage A: AgentRun project binding —
        # (tenant_id, project_id, agent_run_id) -> agent_runs(tenant_id, project_id, id)
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "agent_run_id"],
            ["agent_runs.tenant_id", "agent_runs.project_id", "agent_runs.id"],
            name="grounding_supports_agent_run_fkey",
            ondelete="RESTRICT",
        ),
        # Stage B: Artifact same-run binding —
        # (tenant_id, run_id, generated_artifact_id) -> artifacts(tenant_id, run_id, id)
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id", "generated_artifact_id"],
            ["artifacts.tenant_id", "artifacts.run_id", "artifacts.id"],
            name="grounding_supports_artifact_fkey",
            ondelete="RESTRICT",
        ),
        # Project-scoped Claim binding
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "claim_id"],
            ["claims.tenant_id", "claims.project_id", "claims.id"],
            name="grounding_supports_claim_fkey",
            ondelete="RESTRICT",
        ),
        # Tenant-scoped EvidenceSource binding (sources are tenant-shared)
        sa.ForeignKeyConstraint(
            ["tenant_id", "evidence_source_id"],
            ["evidence_sources.tenant_id", "evidence_sources.id"],
            name="grounding_supports_source_fkey",
            ondelete="RESTRICT",
        ),
        # Project-scoped EvidenceItem binding (uses the new uq added above)
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "evidence_item_id"],
            ["evidence_items.tenant_id", "evidence_items.project_id", "evidence_items.id"],
            name="grounding_supports_evidence_item_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="grounding_supports_pkey"),
        sa.UniqueConstraint(
            "tenant_id", "id",
            name="grounding_supports_uq_tenant_id",
        ),
        # Per QL-C: same (generated_artifact, claim, evidence_item) cannot
        # be recorded twice. The triple is the deduplication identity.
        sa.UniqueConstraint(
            "tenant_id",
            "generated_artifact_id",
            "claim_id",
            "evidence_item_id",
            name="grounding_supports_uq_artifact_claim_item",
        ),
    )
    op.execute(
        """
        CREATE TRIGGER grounding_supports_set_updated_at
        BEFORE UPDATE ON grounding_supports
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )

    # 4) Trigger function to verify the QL-C ``evidence_item ↔
    #    claim/source`` agreement invariant. A pure CHECK constraint
    #    cannot reference another table, so we install a row-level
    #    trigger that consults ``evidence_items`` on every insert /
    #    update.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION grounding_supports_assert_evidence_item_match()
        RETURNS TRIGGER AS $$
        DECLARE
            item_claim_id uuid;
            item_source_id uuid;
        BEGIN
            SELECT claim_id, source_id
              INTO item_claim_id, item_source_id
              FROM evidence_items
             WHERE tenant_id = NEW.tenant_id
               AND id = NEW.evidence_item_id
             FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'grounding_supports.evidence_item_id % not found for tenant %',
                    NEW.evidence_item_id, NEW.tenant_id
                  USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF item_claim_id <> NEW.claim_id THEN
                RAISE EXCEPTION
                    'grounding_supports.claim_id (%) does not match '
                    'evidence_items.claim_id (%) for evidence_item %',
                    NEW.claim_id, item_claim_id, NEW.evidence_item_id
                  USING ERRCODE = 'check_violation';
            END IF;
            IF item_source_id <> NEW.evidence_source_id THEN
                RAISE EXCEPTION
                    'grounding_supports.evidence_source_id (%) does not match '
                    'evidence_items.source_id (%) for evidence_item %',
                    NEW.evidence_source_id, item_source_id, NEW.evidence_item_id
                  USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER grounding_supports_assert_evidence_item_match_trigger
        BEFORE INSERT OR UPDATE ON grounding_supports
        FOR EACH ROW EXECUTE FUNCTION grounding_supports_assert_evidence_item_match()
        """
    )

    # 5) Listing index: citation_coverage query path filters on
    #    (tenant_id, project_id, agent_run_id) + groups by claim_id.
    op.create_index(
        "grounding_supports_ix_tenant_project_agent_run",
        "grounding_supports",
        ["tenant_id", "project_id", "agent_run_id", "claim_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "grounding_supports_ix_tenant_project_agent_run",
        table_name="grounding_supports",
    )
    op.execute(
        "DROP TRIGGER IF EXISTS grounding_supports_assert_evidence_item_match_trigger "
        "ON grounding_supports"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS grounding_supports_assert_evidence_item_match()"
    )
    op.execute("DROP TRIGGER IF EXISTS grounding_supports_set_updated_at ON grounding_supports")
    op.drop_table("grounding_supports")

    # Revert artifacts.kind enum
    op.drop_constraint("artifacts_ck_kind", "artifacts", type_="check")
    op.create_check_constraint(
        "artifacts_ck_kind",
        "artifacts",
        "kind in "
        "('plan','patch','evidence','citation','provider_continuation_ref','other',"
        "'cli_input','cli_stdout','cli_stderr','cli_exit','cli_result_summary')",
    )

    # Revert evidence_items uq
    op.drop_constraint(
        "evidence_items_uq_tenant_project_id",
        "evidence_items",
        type_="unique",
    )
