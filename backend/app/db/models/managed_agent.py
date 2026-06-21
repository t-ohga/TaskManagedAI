"""DB-backed agent supervision registry (SP-PHASE1 B2、ADR-00048 §Amendment A-1/A-2/A-3)。

``managed_agents`` は **cross-process kill の正本** (in-process ``_active_agents`` dict ではない)。
FastAPI process と MCP/worker process が別 process / 別 container で動くため、emergency-stop は
DB に永続登録された ``host_id`` / ``process_group_id`` / ``state`` を見て、当該 subprocess を実際に
signal できる host の supervisor 経由で kill する (ADR-00048 §F)。

責務分離 (A-3): ``managed_agents`` = **agent process supervision** (host/pgid/pid/state)。
既存 ``active_registry_worker_gate`` / ``with_active_registry_gate`` = **host-fleet DML mutation gate**
(host freeze 用、別責務)。両者を混同しない。

tenant/project boundary (core.md §8): 全 query は ``tenant_id`` 条件を含む。``agent_run_id`` がある
run は同一 ``(tenant_id, project_id)`` の agent_runs に複合 FK で閉じる (cross-tenant/cross-project
参照禁止)。``agent_run_id`` IS NULL の registry 行 (run に紐付かない直接 spawn) は MATCH SIMPLE で
FK 未強制。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import Base, CreatedAtMixin, TenantIdMixin, UpdatedAtMixin
from backend.app.domain.superintendent.managed_agent_state import ManagedAgentState


class ManagedAgentRecord(TenantIdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "managed_agents"
    __table_args__ = (
        sa.CheckConstraint(
            "state in ('spawning','running','stopped','failed')",
            name="managed_agents_ck_state",
        ),
        # B4 adversarial HIGH-2: 0/負 pgid を構造的に排除 (killpg(0) = supervisor self-kill 防止)。
        # supervisor ``_killpg`` guard + migration 0054 DB CHECK と合わせ 4-layer 防御。
        sa.CheckConstraint(
            "process_group_id IS NULL OR process_group_id > 0",
            name="managed_agents_ck_pgid_positive",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="managed_agents_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        # project boundary: 同一 (tenant_id, project_id) の project に閉じる。
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="managed_agents_project_fkey",
            ondelete="RESTRICT",
        ),
        # agent_run_id がある run は同一 (tenant_id, project_id) の agent_runs に閉じる。
        # MATCH SIMPLE (default): agent_run_id IS NULL なら FK 未強制 (run-less registry 行)。
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "agent_run_id"],
            ["agent_runs.tenant_id", "agent_runs.project_id", "agent_runs.id"],
            name="managed_agents_agent_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="managed_agents_uq_tenant_id"),
        # supervisor は host scope で active 行を列挙し killpg する (A-2)。
        sa.Index(
            "managed_agents_idx_host_state",
            "host_id",
            "state",
        ),
        sa.Index(
            "managed_agents_idx_tenant_state",
            "tenant_id",
            "state",
        ),
        # LOW-4: 1 run = 1 active managed_agent (二重 spawn 防止)。terminal 行は対象外なので
        # 同 run の再 spawn は許可される。agent_run_id IS NULL の run-less 行も対象外。
        sa.Index(
            "managed_agents_uq_active_agent_run",
            "tenant_id",
            "agent_run_id",
            unique=True,
            postgresql_where=sa.text(
                "agent_run_id is not null and state in ('spawning','running')"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    # 該当 run があれば紐付ける (run-less 直接 spawn は NULL)。
    agent_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    # kill 到達性 (A-2): 当該 subprocess を spawn した host (同一 PID namespace)。
    host_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # killpg 用 pgid (A-2): supervisor restart 後も in-process handle 無しに kill 可能。
    process_group_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    pid: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    supervisor_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    state: Mapped[ManagedAgentState] = mapped_column(
        sa.Text,
        nullable=False,
        default="spawning",
        server_default=sa.text("'spawning'"),
    )
    # pid/pgid 再利用防御 (A-2): kill 前に boot_id / started_at を照合し、死亡 process の
    # pgid を無関係 process が再利用していた場合の誤 kill を防ぐ。
    boot_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )


__all__ = ["ManagedAgentRecord"]
