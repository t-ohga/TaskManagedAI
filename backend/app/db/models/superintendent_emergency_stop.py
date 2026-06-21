"""Persistent emergency-stop latch (SP-PHASE1 B3、ADR-00048 §B/B-1/B-3/A-5/A-7)。

``superintendent_emergency_stops`` は tenant-scoped な **永続 emergency-stop latch** (新規活動を
全 mutating choke point で fail-closed deny する正本)。active latch は tenant 毎に高々 1 件
(``(tenant_id) WHERE cleared_at IS NULL`` partial unique) で、``generation`` (CAS) は engage/clear の
stale 操作を線形化する (B-3 generation CAS、B-1 advisory lock と二重)。

invariant (rules instincts §14「global kill switch は新規を止める」):
- engage で active row (cleared_at IS NULL) を作成し、generation = (前 active の generation) + 1。
- 既に active なら engage は冪等 no-op (同一 latch を返す)。partial unique が二重 active を構造的に禁止。
- clear で ``cleared_at`` / ``cleared_by_actor_id`` を埋め active を解除 (= 同 tenant の次 engage を許可)。

tenant/project boundary (core.md §8): 全 query は ``tenant_id`` 条件を含み、tenants に複合 FK で閉じる。
raw secret / token は持たない (reason は free-text だが assert_no_raw_secret 対象、actor は FK)。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import Base, CreatedAtMixin, TenantIdMixin


class SuperintendentEmergencyStop(TenantIdMixin, CreatedAtMixin, Base):
    __tablename__ = "superintendent_emergency_stops"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="superintendent_emergency_stops_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        # actor は tenant 内 (human) を参照 (engage/clear operator)。複合 FK で tenant 越境を禁止。
        sa.ForeignKeyConstraint(
            ["tenant_id", "engaged_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="superintendent_emergency_stops_engaged_by_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "cleared_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="superintendent_emergency_stops_cleared_by_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="superintendent_emergency_stops_uq_tenant_id"
        ),
        # active latch は tenant 毎に高々 1 件 (B、二重 engage 防止の構造的保証)。
        sa.Index(
            "superintendent_emergency_stops_uq_active",
            "tenant_id",
            unique=True,
            postgresql_where=sa.text("cleared_at is null"),
        ),
        sa.Index(
            "superintendent_emergency_stops_idx_tenant_generation",
            "tenant_id",
            "generation",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    # generation CAS (B-3): engage 毎に単調増加。clear は expected_generation と一致時のみ成功。
    generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    engaged_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
    )
    engaged_by_actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    cleared_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    cleared_by_actor_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    # 操作理由 (free-text)。raw secret を入れない (audit emit 時に assert_no_raw_secret)。
    reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


__all__ = ["SuperintendentEmergencyStop"]
