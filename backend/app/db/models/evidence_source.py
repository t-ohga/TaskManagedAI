from __future__ import annotations

from datetime import datetime
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
from backend.app.db.models.domain_trust import TrustTier


class EvidenceSource(TenantIdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "evidence_sources"
    __table_args__ = (
        sa.CheckConstraint(
            "length(canonical_url) between 1 and 2000",
            name="evidence_sources_ck_canonical_url_length",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[a-f0-9]{64}$'",
            name="evidence_sources_ck_content_hash_sha256_hex",
        ),
        # SP-027 (ADR-00053): per-source manual trust。trust_level は TrustTier reuse。
        sa.CheckConstraint(
            "trust_level is null or trust_level in ('low', 'medium', 'high')",
            name="evidence_sources_ck_trust_level",
        ),
        sa.CheckConstraint(
            "trust_score is null or (trust_score >= 0.0 and trust_score <= 1.0)",
            name="evidence_sources_ck_trust_score_range",
        ),
        # R1 F-004: trust_score 単独 (level null + score 非 null) 禁止。manual override は level 必須。
        sa.CheckConstraint(
            "trust_level is not null or trust_score is null",
            name="evidence_sources_ck_trust_score_requires_level",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="evidence_sources_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="evidence_sources_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "canonical_url",
            name="evidence_sources_uq_tenant_canonical_url",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    canonical_url: Mapped[str] = mapped_column(sa.Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    # SP-027 (ADR-00053): per-source manual trust (未設定 = domain 由来 fallback)。
    trust_level: Mapped[TrustTier | None] = mapped_column(sa.Text, nullable=True)
    trust_score: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )


__all__ = ["EvidenceSource"]
