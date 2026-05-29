from __future__ import annotations

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
    UpdatedAtMixin,
    rls_ready_metadata,
)
from backend.app.domain.policy.autonomy_level import DEFAULT_AUTONOMY_LEVEL, AutonomyLevel
from backend.app.domain.policy.profile import PolicyProfileId

ProjectStatus = Literal["active", "archived"]


class Project(TenantIdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        sa.CheckConstraint(
            "status in ('active','archived')",
            name="projects_ck_status",
        ),
        sa.CheckConstraint(
            "autonomy_level in ('L0','L1','L2','L3')",
            name="projects_ck_autonomy_level",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="projects_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workspace_id"],
            ["workspaces.tenant_id", "workspaces.id"],
            name="projects_workspace_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "policy_profile"],
            ["policy_profiles.tenant_id", "policy_profiles.profile_id"],
            name="projects_policy_profile_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="projects_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "slug",
            name="projects_uq_tenant_workspace_slug",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    slug: Mapped[str] = mapped_column(sa.Text, nullable=False)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    status: Mapped[ProjectStatus] = mapped_column(
        sa.Text,
        nullable=False,
        default="active",
        server_default=sa.text("'active'"),
    )
    policy_profile: Mapped[PolicyProfileId] = mapped_column(
        sa.Text,
        nullable=False,
        default="default",
        server_default=sa.text("'default'"),
    )
    autonomy_level: Mapped[AutonomyLevel] = mapped_column(
        sa.Text,
        nullable=False,
        default=DEFAULT_AUTONOMY_LEVEL,
        server_default=sa.text("'L0'"),
    )
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )


__all__ = ["Project", "ProjectStatus"]
