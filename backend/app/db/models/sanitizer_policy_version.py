from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import Base, TenantIdMixin


class SanitizerPolicyVersion(TenantIdMixin, Base):
    """Canonical sanitizer policy metadata used by ref-only memory artifacts."""

    __tablename__ = "sanitizer_policy_versions"
    __table_args__ = (
        sa.CheckConstraint(
            "config_hash ~ '^[0-9a-f]{64}$'",
            name="sanitizer_policy_versions_ck_config_hash_sha256",
        ),
        sa.CheckConstraint(
            "ruleset_hash ~ '^[0-9a-f]{64}$'",
            name="sanitizer_policy_versions_ck_ruleset_hash_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="sanitizer_policy_versions_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="sanitizer_policy_versions_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "version",
            name="sanitizer_policy_versions_uq_tenant_version",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "config_hash",
            name="sanitizer_policy_versions_uq_tenant_config_hash",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    config_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    ruleset_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    activated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    deprecated_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )


__all__ = ["SanitizerPolicyVersion"]
