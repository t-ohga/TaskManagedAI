from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.budget import Budget
from backend.app.domain.agent_runtime.budget import (
    BudgetCheckResult,
    BudgetExceedReason,
    BudgetLevel,
)
from backend.app.repositories.budget import BudgetRepository
from backend.app.repositories.notification_event import NotificationEventRepository
from backend.app.services.agent_runtime.event_log import transition_with_event


class BudgetGuard:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def evaluate_budget(
        self,
        run: AgentRun,
        current_usage_usd: Decimal | int | str | float | None,
        current_tokens: int,
        current_wall_clock_ms: int,
        retry_count: int,
    ) -> BudgetCheckResult:
        budgets = await BudgetRepository(self.session).list_effective_for_run(
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            run_id=run.id,
        )
        current_usd = _decimal_or_none(current_usage_usd)

        for level in ("global", "tenant", "project", "agent_run"):
            budget = budgets.get(level)
            if budget is None:
                continue

            hard_result = _hard_limit_result(
                budget=budget,
                current_usd=current_usd,
                current_tokens=current_tokens,
                current_wall_clock_ms=current_wall_clock_ms,
                retry_count=retry_count,
            )
            if hard_result is not None:
                return hard_result

        soft_result = _first_soft_threshold_result(
            budgets=budgets,
            current_usd=current_usd,
            current_tokens=current_tokens,
            current_wall_clock_ms=current_wall_clock_ms,
            retry_count=retry_count,
        )
        if soft_result is not None:
            return soft_result

        return BudgetCheckResult(
            level="agent_run",
            exceeded=False,
            current_usd=current_usd,
            hard_limit_usd=None,
            soft_threshold_usd=None,
            reason=None,
            current_tokens=current_tokens,
            hard_limit_tokens=None,
            current_wall_clock_ms=current_wall_clock_ms,
            hard_limit_wall_clock_ms=None,
            retry_count=retry_count,
            max_retries=None,
        )

    async def enforce_budget_or_block(
        self,
        run: AgentRun,
        current_usage_usd: Decimal | int | str | float | None,
        current_tokens: int,
        current_wall_clock_ms: int,
        retry_count: int,
        actor_id: UUID,
    ) -> BudgetCheckResult:
        result = await self.evaluate_budget(
            run=run,
            current_usage_usd=current_usage_usd,
            current_tokens=current_tokens,
            current_wall_clock_ms=current_wall_clock_ms,
            retry_count=retry_count,
        )

        if result.exceeded:
            await transition_with_event(
                self.session,
                run=run,
                to_state="blocked",
                event_type="budget_blocked",
                actor_id=actor_id,
                blocked_reason="budget_blocked",
                payload={
                    "budget_level": result.level,
                    "exceed_reason": result.reason,
                    "current_usd": _string_or_none(result.current_usd),
                    "hard_limit_usd": _string_or_none(result.hard_limit_usd),
                    "current_tokens": result.current_tokens,
                    "hard_limit_tokens": result.hard_limit_tokens,
                    "current_wall_clock_ms": result.current_wall_clock_ms,
                    "hard_limit_wall_clock_ms": result.hard_limit_wall_clock_ms,
                    "retry_count": result.retry_count,
                    "max_retries": result.max_retries,
                },
            )
            return result

        if result.soft_threshold_usd is not None and result.current_usd is not None:
            await NotificationEventRepository(self.session).append(
                tenant_id=run.tenant_id,
                event_type="budget_soft_threshold_warning",
                recipient_actor_id=actor_id,
                payload={
                    "run_id": str(run.id),
                    "project_id": str(run.project_id),
                    "budget_level": result.level,
                    "current_usd": str(result.current_usd),
                    "soft_threshold_usd": str(result.soft_threshold_usd),
                    "hard_limit_usd": _string_or_none(result.hard_limit_usd),
                },
            )

        return result


async def evaluate_budget(
    session: AsyncSession,
    run: AgentRun,
    current_usage_usd: Decimal | int | str | float | None,
    current_tokens: int,
    current_wall_clock_ms: int,
    retry_count: int,
) -> BudgetCheckResult:
    return await BudgetGuard(session).evaluate_budget(
        run=run,
        current_usage_usd=current_usage_usd,
        current_tokens=current_tokens,
        current_wall_clock_ms=current_wall_clock_ms,
        retry_count=retry_count,
    )


async def enforce_budget_or_block(
    session: AsyncSession,
    run: AgentRun,
    current_usage_usd: Decimal | int | str | float | None,
    current_tokens: int,
    current_wall_clock_ms: int,
    retry_count: int,
    actor_id: UUID,
) -> BudgetCheckResult:
    return await BudgetGuard(session).enforce_budget_or_block(
        run=run,
        current_usage_usd=current_usage_usd,
        current_tokens=current_tokens,
        current_wall_clock_ms=current_wall_clock_ms,
        retry_count=retry_count,
        actor_id=actor_id,
    )


def _hard_limit_result(
    *,
    budget: Budget,
    current_usd: Decimal | None,
    current_tokens: int,
    current_wall_clock_ms: int,
    retry_count: int,
) -> BudgetCheckResult | None:
    if budget.level == "global" and budget.global_kill_switch is True:
        return _result(
            budget,
            current_usd,
            "global_kill_switch",
            current_tokens=current_tokens,
            current_wall_clock_ms=current_wall_clock_ms,
            retry_count=retry_count,
        )

    if (
        current_usd is not None
        and budget.hard_usd_limit is not None
        and current_usd > budget.hard_usd_limit
    ):
        return _result(
            budget,
            current_usd,
            "hard_usd_exceeded",
            current_tokens=current_tokens,
            current_wall_clock_ms=current_wall_clock_ms,
            retry_count=retry_count,
        )

    if budget.hard_tokens_limit is not None and current_tokens > budget.hard_tokens_limit:
        return _result(
            budget,
            current_usd,
            "hard_tokens_exceeded",
            current_tokens=current_tokens,
            current_wall_clock_ms=current_wall_clock_ms,
            retry_count=retry_count,
        )

    if (
        budget.hard_wall_clock_ms is not None
        and current_wall_clock_ms > budget.hard_wall_clock_ms
    ):
        return _result(
            budget,
            current_usd,
            "hard_wall_clock_exceeded",
            current_tokens=current_tokens,
            current_wall_clock_ms=current_wall_clock_ms,
            retry_count=retry_count,
        )

    if budget.max_retries is not None and retry_count > budget.max_retries:
        return _result(
            budget,
            current_usd,
            "max_retries_exceeded",
            current_tokens=current_tokens,
            current_wall_clock_ms=current_wall_clock_ms,
            retry_count=retry_count,
        )

    return None


def _first_soft_threshold_result(
    *,
    budgets: dict[BudgetLevel, Budget],
    current_usd: Decimal | None,
    current_tokens: int,
    current_wall_clock_ms: int,
    retry_count: int,
) -> BudgetCheckResult | None:
    if current_usd is None:
        return None

    for level in ("global", "tenant", "project", "agent_run"):
        budget = budgets.get(level)
        if (
            budget is not None
            and budget.soft_usd_threshold is not None
            and current_usd >= budget.soft_usd_threshold
        ):
            return BudgetCheckResult(
                level=budget.level,
                exceeded=False,
                current_usd=current_usd,
                hard_limit_usd=budget.hard_usd_limit,
                soft_threshold_usd=budget.soft_usd_threshold,
                reason=None,
                current_tokens=current_tokens,
                hard_limit_tokens=budget.hard_tokens_limit,
                current_wall_clock_ms=current_wall_clock_ms,
                hard_limit_wall_clock_ms=budget.hard_wall_clock_ms,
                retry_count=retry_count,
                max_retries=budget.max_retries,
            )

    return None


def _result(
    budget: Budget,
    current_usd: Decimal | None,
    reason: BudgetExceedReason,
    *,
    current_tokens: int,
    current_wall_clock_ms: int,
    retry_count: int,
) -> BudgetCheckResult:
    return BudgetCheckResult(
        level=budget.level,
        exceeded=True,
        current_usd=current_usd,
        hard_limit_usd=budget.hard_usd_limit,
        soft_threshold_usd=budget.soft_usd_threshold,
        reason=reason,
        current_tokens=current_tokens,
        hard_limit_tokens=budget.hard_tokens_limit,
        current_wall_clock_ms=current_wall_clock_ms,
        hard_limit_wall_clock_ms=budget.hard_wall_clock_ms,
        retry_count=retry_count,
        max_retries=budget.max_retries,
    )


def _decimal_or_none(value: Decimal | int | str | float | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _string_or_none(value: object) -> str | None:
    return None if value is None else str(value)


__all__ = [
    "BudgetGuard",
    "enforce_budget_or_block",
    "evaluate_budget",
]

