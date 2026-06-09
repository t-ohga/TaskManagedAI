from __future__ import annotations

from typing import Literal, get_args
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

# ADR-00052: domain trust tier (5+ source integrity の Python Literal 側)
TrustTier = Literal["low", "medium", "high"]
TRUST_TIERS: frozenset[str] = frozenset(get_args(TrustTier))


class DomainTrustRegistry(TenantIdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """SP-032 (ADR-00052): tenant-scoped な domain → trust_tier registry。

    project boundary を持たない (evidence_sources と同 scope)。domain は server-owned 正規化
    (hostname-level exact match)。SP-027 で per-source trust 派生の入力になる。
    """

    __tablename__ = "domain_trust_registry"
    __table_args__ = (
        sa.CheckConstraint(
            "char_length(domain) between 1 and 253",
            name="domain_trust_registry_ck_domain_length",
        ),
        sa.CheckConstraint(
            "domain = lower(domain) and domain ~ '^[a-z0-9.-]+$'",
            name="domain_trust_registry_ck_domain_format",
        ),
        sa.CheckConstraint(
            "trust_tier in ('low', 'medium', 'high')",
            name="domain_trust_registry_ck_trust_tier",
        ),
        sa.CheckConstraint(
            "rationale is null or char_length(rationale) between 1 and 1000",
            name="domain_trust_registry_ck_rationale_length",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="domain_trust_registry_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="domain_trust_registry_created_by_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="domain_trust_registry_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "domain", name="domain_trust_registry_uq_tenant_domain"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    domain: Mapped[str] = mapped_column(sa.Text, nullable=False)
    trust_tier: Mapped[TrustTier] = mapped_column(sa.Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_by_actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )

    def __repr__(self) -> str:
        return (
            f"DomainTrustRegistry(id={self.id!s}, tenant_id={self.tenant_id!r}, "
            f"domain={self.domain!r}, trust_tier={self.trust_tier!r})"
        )


__all__ = ["TRUST_TIERS", "DomainTrustRegistry", "TrustTier"]
