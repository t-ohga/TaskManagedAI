from __future__ import annotations

import inspect
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run import AgentRun
from backend.app.domain.agent_runtime.budget import BudgetCheckResult
from backend.app.domain.provider.result import ProviderUsage
from backend.app.services.agent_runtime.budget_guard import BudgetGuard


async def record_provider_usage(
    session: AsyncSession,
    *,
    run: AgentRun,
    usage: ProviderUsage,
    actor_id: UUID,
    matrix_version: str,
    current_wall_clock_ms: int | None = None,
    retry_count: int | None = None,
    expected_tenant_id: int | None = None,
) -> BudgetCheckResult:
    """ProviderResult.usage を AgentRun に集計し、BudgetGuard 4 階層を再評価する。

    hard exceed -> blocked + budget_blocked transition は transition_with_event 経由で
    実行するため actor_id が必須。caller が provider service / worker actor_id を渡す。
    matrix_version は provider request fingerprint と同じ matrix snapshot を usage 記録側で
    明示的に受け取り、caller の境界入力を揃えるために必須にしている。
    """

    _require_nonempty_matrix_version(matrix_version)
    resolved_usage = ProviderUsage.model_validate(usage)

    if expected_tenant_id is not None and run.tenant_id != expected_tenant_id:
        raise ValueError("run tenant_id must match expected_tenant_id.")

    _require_positive_tenant_id(run.tenant_id)

    run.cost_usd = _decimal_or_zero(getattr(run, "cost_usd", None)) + Decimal(
        str(resolved_usage.cost_usd)
    )
    run.tokens_input = _int_or_zero(getattr(run, "tokens_input", None)) + resolved_usage.tokens_input
    run.tokens_output = (
        _int_or_zero(getattr(run, "tokens_output", None)) + resolved_usage.tokens_output
    )

    await _maybe_add_and_flush(session, run)

    current_tokens = _int_or_zero(run.tokens_input) + _int_or_zero(run.tokens_output)
    resolved_wall_clock_ms = (
        current_wall_clock_ms
        if current_wall_clock_ms is not None
        else _int_or_zero(getattr(run, "current_wall_clock_ms", None))
    )
    resolved_retry_count = (
        retry_count if retry_count is not None else _int_or_zero(getattr(run, "retry_count", None))
    )

    guard = BudgetGuard(session)
    return await guard.enforce_budget_or_block(
        run=run,
        current_usage_usd=run.cost_usd,
        current_tokens=current_tokens,
        current_wall_clock_ms=resolved_wall_clock_ms,
        retry_count=resolved_retry_count,
        actor_id=actor_id,
    )


async def _maybe_add_and_flush(session: AsyncSession, run: AgentRun) -> None:
    add = getattr(session, "add", None)
    if callable(add):
        add(run)

    flush = getattr(session, "flush", None)
    if callable(flush):
        result = flush()
        if inspect.isawaitable(result):
            await result


def _decimal_or_zero(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _int_or_zero(value: object) -> int:
    if value is None:
        return 0
    return int(value)


def _require_positive_tenant_id(tenant_id: int) -> None:
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
        raise ValueError("tenant_id must be a positive integer.")


def _require_nonempty_matrix_version(matrix_version: str) -> None:
    if not isinstance(matrix_version, str) or not matrix_version:
        raise ValueError("matrix_version must be a non-empty string.")


__all__ = ["record_provider_usage"]

