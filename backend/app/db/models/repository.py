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

RepositoryProvider = Literal["github", "gitlab", "bitbucket"]


class Repository(TenantIdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "repositories"
    __table_args__ = (
        sa.CheckConstraint(
            "provider in ('github','gitlab','bitbucket')",
            name="repositories_ck_provider",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="repositories_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="repositories_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="repositories_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="repositories_uq_tenant_project_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "provider",
            "external_id",
            name="repositories_uq_tenant_provider_external",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    provider: Mapped[RepositoryProvider] = mapped_column(sa.Text, nullable=False)
    external_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    owner_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    repo_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    default_branch: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
        default="main",
        server_default=sa.text("'main'"),
    )
    installation_ref: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )


__all__ = ["Repository", "RepositoryProvider"]

