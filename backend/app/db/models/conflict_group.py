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

# ADR-00052: conflict group status (5+ source integrity の Python Literal 側)
ConflictGroupStatus = Literal["open", "resolved", "dismissed"]
CONFLICT_GROUP_STATUSES: frozenset[str] = frozenset(get_args(ConflictGroupStatus))


class ConflictGroup(TenantIdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """SP-032 (ADR-00052): research_task 内で互いに矛盾する claim を束ねる reviewer 判断単位。

    claims.conflict_group_id が 4-col 複合 FK で同一 (tenant, project, research_task) に束縛される。
    hard delete は提供せず、status='dismissed' が soft-removal。
    """

    __tablename__ = "conflict_groups"
    __table_args__ = (
        sa.CheckConstraint(
            "char_length(title) between 1 and 200",
            name="conflict_groups_ck_title_length",
        ),
        sa.CheckConstraint(
            "status in ('open', 'resolved', 'dismissed')",
            name="conflict_groups_ck_status",
        ),
        sa.CheckConstraint(
            "status <> 'resolved' or resolution_note is not null",
            name="conflict_groups_ck_resolved_note_required",
        ),
        sa.CheckConstraint(
            "resolution_note is null or char_length(resolution_note) between 1 and 2000",
            name="conflict_groups_ck_resolution_note_length",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="conflict_groups_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "research_task_id"],
            ["research_tasks.tenant_id", "research_tasks.project_id", "research_tasks.id"],
            name="conflict_groups_research_task_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="conflict_groups_created_by_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="conflict_groups_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "project_id", "id", name="conflict_groups_uq_tenant_project_id"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "research_task_id",
            "id",
            name="conflict_groups_uq_tenant_project_rt_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    research_task_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[ConflictGroupStatus] = mapped_column(
        sa.Text,
        nullable=False,
        default="open",
        server_default=sa.text("'open'"),
    )
    resolution_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
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
            f"ConflictGroup(id={self.id!s}, tenant_id={self.tenant_id!r}, "
            f"research_task_id={self.research_task_id!s}, status={self.status!r})"
        )


__all__ = ["CONFLICT_GROUP_STATUSES", "ConflictGroup", "ConflictGroupStatus"]
