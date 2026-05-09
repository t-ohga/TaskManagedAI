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

    async def delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Budget rows are disabled with active=false, not deleted.")

    def statement_for_delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Budget rows are disabled with active=false, not deleted.")


__all__ = ["BudgetRepository"]

