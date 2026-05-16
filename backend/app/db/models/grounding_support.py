from __future__ import annotations

from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import (
    Base,
    CreatedAtMixin,
    JsonDict,
    TenantIdMixin,
    UpdatedAtMixin,
    rls_ready_metadata,
)

SUPPORT_TYPE_ENUM: frozenset[str] = frozenset({"cite", "paraphrase", "quote"})


class GroundingSupport(TenantIdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """Generated-artifact ↔ Evidence binding for citation_coverage.

    SP-010 QL-C spec (line 132-142):
    - 2-stage FK: (tenant_id, project_id, agent_run_id) -> agent_runs +
      (tenant_id, run_id, generated_artifact_id) -> artifacts. Same-run
      identity is asserted via the ``run_id = agent_run_id`` CHECK and
      the spec's eval_runs.agent_run_id contract.
    - claim/source agreement with evidence_items is enforced by a
      row-level trigger installed in migration 0018 (a CHECK constraint
      cannot reference another table).
    - support_type enum: ``cite`` / ``paraphrase`` / ``quote``.
    - confidence_score: float in [0, 1] or null.
    """

    __tablename__ = "grounding_supports"
    __table_args__ = (
        sa.CheckConstraint(
            "support_type in ('cite', 'paraphrase', 'quote')",
            name="grounding_supports_ck_support_type",
        ),
        sa.CheckConstraint(
            "confidence_score is null or "
            "(confidence_score >= 0.0 and confidence_score <= 1.0)",
            name="grounding_supports_ck_confidence_score_range",
        ),
        sa.CheckConstraint(
            "run_id = agent_run_id",
            name="grounding_supports_ck_run_id_equals_agent_run_id",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="grounding_supports_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "agent_run_id"],
            ["agent_runs.tenant_id", "agent_runs.project_id", "agent_runs.id"],
            name="grounding_supports_agent_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id", "generated_artifact_id"],
            ["artifacts.tenant_id", "artifacts.run_id", "artifacts.id"],
            name="grounding_supports_artifact_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "claim_id"],
            ["claims.tenant_id", "claims.project_id", "claims.id"],
            name="grounding_supports_claim_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "evidence_source_id"],
            ["evidence_sources.tenant_id", "evidence_sources.id"],
            name="grounding_supports_source_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "evidence_item_id"],
            ["evidence_items.tenant_id", "evidence_items.project_id", "evidence_items.id"],
            name="grounding_supports_evidence_item_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="grounding_supports_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "generated_artifact_id",
            "claim_id",
            "evidence_item_id",
            name="grounding_supports_uq_artifact_claim_item",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    agent_run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    generated_artifact_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    evidence_source_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    evidence_item_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    support_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )

    def __repr__(self) -> str:
        return (
            f"GroundingSupport(id={self.id!s}, tenant_id={self.tenant_id!r}, "
            f"project_id={self.project_id!s}, claim_id={self.claim_id!s})"
        )


__all__ = ["GroundingSupport", "SUPPORT_TYPE_ENUM"]
