from __future__ import annotations

from datetime import datetime
from typing import Literal
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
    rls_ready_metadata,
)

PrincipalType = Literal["session", "api_token", "capability_token", "installation", "worker"]


class Principal(TenantIdMixin, CreatedAtMixin, Base):
    __tablename__ = "principals"
    __table_args__ = (
        sa.CheckConstraint(
            "principal_type in "
            "('session','api_token','capability_token','installation','worker')",
            name="principals_ck_principal_type",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="principals_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="principals_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="principals_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "actor_id",
            "id",
            name="principals_uq_tenant_actor_principal_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    principal_type: Mapped[PrincipalType] = mapped_column(sa.Text, nullable=False)
    auth_context_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


__all__ = ["Principal", "PrincipalType"]

