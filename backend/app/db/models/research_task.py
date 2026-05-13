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

ResearchTaskStatus = Literal["queued", "running", "completed", "failed"]


class ResearchTask(TenantIdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "research_tasks"
    __table_args__ = (
        sa.CheckConstraint(
            "status in ('queued','running','completed','failed')",
            name="research_tasks_ck_status",
        ),
        sa.CheckConstraint(
            "length(title) between 1 and 200",
            name="research_tasks_ck_title_length",
        ),
        sa.CheckConstraint(
            "(description is null) or (length(description) <= 2000)",
            name="research_tasks_ck_description_length",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="research_tasks_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="research_tasks_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="research_tasks_created_by_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="research_tasks_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="research_tasks_uq_tenant_project_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    created_by_actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    status: Mapped[ResearchTaskStatus] = mapped_column(
        sa.Text,
        nullable=False,
        default="queued",
        server_default=sa.text("'queued'"),
    )
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )


__all__ = ["ResearchTask", "ResearchTaskStatus"]
