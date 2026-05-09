from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import Base, CreatedAtMixin, TenantIdMixin, UpdatedAtMixin
from backend.app.domain.agent_runtime.budget import BudgetLevel


class Budget(TenantIdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "budgets"
    __table_args__ = (
        sa.CheckConstraint(
            "level in ('global','tenant','project','agent_run')",
            name="budgets_ck_level",
        ),
        sa.CheckConstraint(
            "(level in ('global','tenant') and level_id is null) or "
            "(level in ('project','agent_run') and level_id is not null)",
            name="budgets_ck_level_id_consistency",
        ),
        sa.CheckConstraint(
            "level = 'global' or global_kill_switch is null",
            name="budgets_ck_global_kill_switch_only_global",
        ),
        sa.CheckConstraint(
            "(hard_usd_limit is null or hard_usd_limit >= 0) and "
            "(soft_usd_threshold is null or soft_usd_threshold >= 0) and "
            "(hard_tokens_limit is null or hard_tokens_limit >= 0) and "
            "(hard_wall_clock_ms is null or hard_wall_clock_ms >= 0) and "
            "(max_retries is null or max_retries >= 0)",
            name="budgets_ck_non_negative_limits",
        ),
        sa.CheckConstraint(
            "hard_usd_limit is null or soft_usd_threshold is null "
            "or soft_usd_threshold <= hard_usd_limit",
            name="budgets_ck_soft_threshold_lte_hard_limit",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="budgets_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="budgets_uq_tenant_id"),
        sa.Index(
            "budgets_uq_global_level_active",
            "level",
            unique=True,
            postgresql_where=sa.text("level = 'global' and active = true"),
        ),
        sa.Index(
            "budgets_uq_tenant_level_active",
            "tenant_id",
            "level",
            unique=True,
            postgresql_where=sa.text("level = 'tenant' and active = true"),
        ),
        sa.Index(
            "budgets_uq_project_level_active",
            "tenant_id",
            "level",
            "level_id",
            unique=True,
            postgresql_where=sa.text("level = 'project' and active = true"),
        ),
        sa.Index(
            "budgets_uq_agent_run_level_active",
            "tenant_id",
            "level",
            "level_id",
            unique=True,
            postgresql_where=sa.text("level = 'agent_run' and active = true"),
        ),
        sa.Index(
            "budgets_idx_tenant_level_active",
            "tenant_id",
            "level",
            "active",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    level: Mapped[BudgetLevel] = mapped_column(sa.Text, nullable=False)
    level_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    hard_usd_limit: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 6), nullable=True)
    soft_usd_threshold: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 6), nullable=True)
    hard_tokens_limit: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    hard_wall_clock_ms: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    max_retries: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    active: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=True,
        server_default=sa.text("true"),
    )
    global_kill_switch: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)


__all__ = ["Budget"]

