from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import Base, CreatedAtMixin, TenantIdMixin, UpdatedAtMixin
from backend.app.domain.agent_runtime.status import AgentRunStatus, BlockedReason


class AgentRun(TenantIdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        sa.CheckConstraint(
            "status in "
            "('queued','gathering_context','running','generated_artifact',"
            "'schema_validated','policy_linted','diff_ready','waiting_approval',"
            "'blocked','provider_refused','provider_incomplete','validation_failed',"
            "'repair_exhausted','completed','failed','cancelled')",
            name="agent_runs_ck_status",
        ),
        sa.CheckConstraint(
            "blocked_reason is null or blocked_reason in "
            "('policy_blocked','budget_blocked','runtime_blocked')",
            name="agent_runs_ck_blocked_reason",
        ),
        sa.CheckConstraint(
            "(status = 'blocked' and blocked_reason is not null) "
            "or (status <> 'blocked' and blocked_reason is null)",
            name="agent_runs_ck_blocked_reason_consistency",
        ),
        sa.CheckConstraint(
            "role_scope is null or role_scope in ('global','project')",
            name="agent_runs_ck_role_scope",
        ),
        sa.CheckConstraint(
            "(role_id is null and role_scope is null) "
            "or (role_id is not null and role_scope is not null "
            "and role_scope in ('global','project'))",
            name="agent_runs_role_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="agent_runs_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="agent_runs_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "parent_run_id"],
            ["agent_runs.tenant_id", "agent_runs.project_id", "agent_runs.id"],
            name="agent_runs_parent_run_fkey",
            ondelete="RESTRICT",
        ),
        # ADR-00037 R13: run→ticket binding (server-owned ticket_id) は同一
        # (tenant_id, project_id) の ticket のみ参照可 (cross-project/cross-tenant 禁止)。
        # ticket_id IS NULL は MATCH SIMPLE で未強制 (ticket-less run)。
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "ticket_id"],
            ["tickets.tenant_id", "tickets.project_id", "tickets.id"],
            name="agent_runs_ticket_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="agent_runs_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="agent_runs_uq_tenant_project_id",
        ),
        sa.Index("agent_runs_idx_tenant_project_status", "tenant_id", "project_id", "status"),
        sa.Index(
            "agent_runs_idx_tenant_project_parent",
            "tenant_id",
            "project_id",
            "parent_run_id",
            postgresql_where=sa.text("parent_run_id is not null"),
        ),
        sa.Index("agent_runs_idx_tenant_created_at", "tenant_id", "created_at"),
        sa.Index(
            "agent_runs_idx_lease_expires",
            "tenant_id",
            "orchestrator_lease_expires_at",
            postgresql_where=sa.text("orchestrator_lease_expires_at is not null"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    # ADR-00037 R12: run→ticket binding を server-owned column 化 (run_queued event payload 依存の
    # fail-open 排除 + KPI active-scope の tickets JOIN を可能にする)。ticket-less run は NULL。
    ticket_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    parent_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    status: Mapped[AgentRunStatus] = mapped_column(
        sa.Text,
        nullable=False,
        default="queued",
        server_default=sa.text("'queued'"),
    )
    blocked_reason: Mapped[BlockedReason | None] = mapped_column(sa.Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 6), nullable=True)
    tokens_input: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    tokens_output: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    role_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    role_scope: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    orchestrator_lease_token: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    orchestrator_lease_expires_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    lease_renewed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    orchestrator_kill_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    last_progress_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    progress_seq: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )


__all__ = ["AgentRun"]
