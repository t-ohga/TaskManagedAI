from __future__ import annotations

from typing import Any, NoReturn
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.budget import Budget
from backend.app.domain.agent_runtime.budget import BudgetLevel
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.repositories.base import BaseRepository

_MUTABLE_FIELDS = frozenset(
    {
        "hard_usd_limit",
        "soft_usd_threshold",
        "hard_tokens_limit",
        "hard_wall_clock_ms",
        "max_retries",
        "active",
        "global_kill_switch",
    }
)


class BudgetRepository(BaseRepository[Budget]):
    def __init__(self, session: AsyncSession, tenant_id: int | None = None) -> None:
        super().__init__(session, Budget, tenant_id=tenant_id)

    async def get(self, tenant_id: int, id: UUID) -> Budget | None:
        return await super().get(tenant_id=tenant_id, id=id)

    async def list_active(self, tenant_id: int) -> list[Budget]:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            sa.select(Budget)
            .where(
                Budget.tenant_id == tenant_id,
                Budget.active.is_(True),
            )
            .order_by(Budget.level, Budget.created_at, Budget.id)
        )
        return list(result.scalars().all())

    async def list_effective_for_run(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        run_id: UUID,
    ) -> dict[BudgetLevel, Budget]:
        await self._ensure_tenant_context(tenant_id)

        result = await self.session.execute(
            sa.select(Budget)
            .where(
                Budget.tenant_id == tenant_id,
                Budget.active.is_(True),
                sa.or_(
                    Budget.level == "global",
                    Budget.level == "tenant",
                    sa.and_(Budget.level == "project", Budget.level_id == project_id),
                    sa.and_(Budget.level == "agent_run", Budget.level_id == run_id),
                ),
            )
            .order_by(Budget.created_at, Budget.id)
        )

        budgets: dict[BudgetLevel, Budget] = {}
        for budget in result.scalars().all():
            budgets.setdefault(budget.level, budget)
        return budgets

    async def create_with_audit(
        self,
        *,
        tenant_id: int,
        payload: dict[str, Any],
        actor_id: UUID,
    ) -> Budget:
        budget = await super().create(tenant_id=tenant_id, payload=payload)
        await AuditEventRepository(self.session).append(
            tenant_id=tenant_id,
            event_type="budget_created",
            actor_id=actor_id,
            payload={
                "budget_id": str(budget.id),
                "level": budget.level,
                "level_id": None if budget.level_id is None else str(budget.level_id),
                "active": budget.active,
            },
        )
        return budget

    async def update_active_flag(
        self,
        *,
        tenant_id: int,
        id: UUID,
        active: bool,
        actor_id: UUID,
    ) -> Budget | None:
        budget = await super().update(tenant_id=tenant_id, id=id, payload={"active": active})
        if budget is not None:
            await AuditEventRepository(self.session).append(
                tenant_id=tenant_id,
                event_type="budget_active_flag_updated",
                actor_id=actor_id,
                payload={
                    "budget_id": str(budget.id),
                    "level": budget.level,
                    "level_id": None if budget.level_id is None else str(budget.level_id),
                    "active": budget.active,
                },
            )
        return budget

    async def update_limits_with_audit(
        self,
        *,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
        actor_id: UUID,
    ) -> Budget | None:
        unexpected = sorted(set(payload) - _MUTABLE_FIELDS)
        if unexpected:
            raise ValueError(f"budget update fields are not mutable: {unexpected}")

        budget = await super().update(tenant_id=tenant_id, id=id, payload=payload)
        if budget is not None:
            await AuditEventRepository(self.session).append(
                tenant_id=tenant_id,
                event_type="budget_limits_updated",
                actor_id=actor_id,
                payload={
                    "budget_id": str(budget.id),
                    "level": budget.level,
                    "level_id": None if budget.level_id is None else str(budget.level_id),
                    "changed_fields": sorted(payload),
                },
            )
        return budget

    async def get_active_global(self, tenant_id: int) -> Budget | None:
        """active な global-level budget row を返す (SP-PHASE1 B6、ADR-00048 §A-8)。

        global budget は ``budgets_uq_global_level_active`` partial unique index で
        ``level='global' AND active=true`` が最大 1 件。``global_kill_switch`` flag を載せられるのは
        global budget のみ (``budgets_ck_global_kill_switch_only_global``)。
        """
        await self._ensure_tenant_context(tenant_id)
        budget: Budget | None = await self.session.scalar(
            sa.select(Budget).where(
                Budget.tenant_id == tenant_id,
                Budget.level == "global",
                Budget.active.is_(True),
            )
        )
        return budget

    async def set_global_kill_switch(
        self,
        *,
        tenant_id: int,
        engaged: bool,
        actor_id: UUID,
    ) -> Budget:
        """budget global_kill_switch (コスト緊急停止) を engage/clear する (SP-PHASE1 B6、ADR-00048 §A-8)。

        emergency-stop latch (human 即時全停止) とは **別目的** だが、autonomy / budget choke point で
        OR 評価される (どちらか engaged なら deny。OR 配線は B5a で済、本 API は budget 側 flag の operator
        surface)。active な global budget が無ければ flag だけ持つ minimal global budget を **find-or-create**
        し、``global_kill_switch`` を set する。audit (``budget_global_kill_switch_updated``、raw 値なし)。

        並行 engage は同 row の FOR UPDATE で線形化する (toggle の lost update を防ぐ)。冪等: 既に同値なら
        no-op で row を返す (audit は engage 操作の証跡として常に残す)。
        """
        await self._ensure_tenant_context(tenant_id)
        # FOR UPDATE で active global budget を lock (並行 toggle 直列化)。
        budget = await self.session.scalar(
            sa.select(Budget)
            .where(
                Budget.tenant_id == tenant_id,
                Budget.level == "global",
                Budget.active.is_(True),
            )
            .with_for_update()
        )
        if budget is None:
            budget = await super().create(
                tenant_id=tenant_id,
                payload={
                    "level": "global",
                    "level_id": None,
                    "active": True,
                    "global_kill_switch": engaged,
                },
            )
            created = True
        else:
            budget.global_kill_switch = engaged
            await self.session.flush()
            created = False
        await AuditEventRepository(self.session).append(
            tenant_id=tenant_id,
            event_type="budget_global_kill_switch_updated",
            actor_id=actor_id,
            payload={
                "budget_id": str(budget.id),
                "level": budget.level,
                "global_kill_switch": engaged,
                "created": created,
            },
        )
        return budget

    async def delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Budget rows are disabled with active=false, not deleted.")

    def statement_for_delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Budget rows are disabled with active=false, not deleted.")


__all__ = ["BudgetRepository"]

