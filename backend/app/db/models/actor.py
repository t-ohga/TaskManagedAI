from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import (
    Base,
    CreatedAtMixin,
    JsonDict,
    TenantIdMixin,
    UpdatedAtMixin,
    rls_ready_metadata,
)

ActorType = Literal["human", "service", "agent", "provider", "github_app"]


class Actor(TenantIdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "actors"
    __table_args__ = (
        sa.CheckConstraint(
            "actor_type in ('human','service','agent','provider','github_app')",
            name="actors_ck_actor_type",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="actors_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "impersonated_by"],
            ["actors.tenant_id", "actors.id"],
            name="actors_impersonated_by_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="actors_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "actor_id",
            name="actors_uq_tenant_actor_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    actor_type: Mapped[ActorType] = mapped_column(sa.Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    auth_context_hash: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )
    impersonated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )


__all__ = ["Actor", "ActorType"]

