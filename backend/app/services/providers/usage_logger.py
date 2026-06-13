from __future__ import annotations

import inspect
from decimal import Decimal
from typing import SupportsInt
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import get_settings
from backend.app.db.models.agent_run import AgentRun
from backend.app.domain.agent_runtime.budget import BudgetCheckResult, BudgetExceedReason
from backend.app.domain.provider.result import ProviderUsage
from backend.app.repositories.budget import BudgetRepository
from backend.app.services.agent_runtime.budget_guard import BudgetGuard
from backend.app.services.agent_runtime.event_log import transition_with_event


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

    is_shadow = getattr(run, "run_mode", "production") == "shadow"
    reported_cost = Decimal(str(resolved_usage.cost_usd))
    # SP-029 (Codex R13 F-1): shadow は provider 報告 cost を信用せず、token 由来の下限 cost で
    # floor する (`max(reported, tokens * worst-case 単価)`)。provider/API skew や degraded
    # response で cost=0 と過少報告されても、token がある限り run.cost_usd が増え USD cap が
    # **複数 call で累積的に** 効く (fail-safe)。production は従来どおり reported cost を使う。
    if is_shadow:
        delta_tokens = resolved_usage.tokens_input + resolved_usage.tokens_output
        token_floor_cost = Decimal(delta_tokens) * get_settings().shadow_run_max_usd_per_token
        cost_delta = max(reported_cost, token_floor_cost)
    else:
        cost_delta = reported_cost

    run.cost_usd = _decimal_or_zero(getattr(run, "cost_usd", None)) + cost_delta
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

    # SP-029 (ADR-00055 §設計制約 4+5): shadow run は production budget accumulator を
    # 通さない。cost は run.cost_usd に tag 記録済みだが、production の global/tenant/project
    # budget を読まず・誘発せず (production run の budget_blocked を起こさない)、shadow per-run
    # hard cap (settings.shadow_run_max_cost_usd) のみ enforce する。run_mode は本 module の
    # 既存 getattr pattern に合わせ、属性欠落 fake (test fixture 等) は production として扱う。
    if getattr(run, "run_mode", "production") == "shadow":
        return await _enforce_shadow_run_cap(
            session,
            run=run,
            actor_id=actor_id,
            current_tokens=current_tokens,
            current_wall_clock_ms=resolved_wall_clock_ms,
            retry_count=resolved_retry_count,
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


async def _enforce_shadow_run_cap(
    session: AsyncSession,
    *,
    run: AgentRun,
    actor_id: UUID,
    current_tokens: int,
    current_wall_clock_ms: int,
    retry_count: int,
) -> BudgetCheckResult:
    """shadow run の global kill switch + per-run USD/token hard cap を post-execution 評価する。

    production の tenant/project/agent_run SPEND budget (accumulator) は参照しない
    (§4 非擾乱)。ただし global_kill_switch は **全 run を止める緊急停止** であり shadow でも
    必ず評価する (Codex R1 F-3)。USD cap (§5) に加え token cap も評価し、provider が
    ``cost_usd=0`` / 未報告でも shadow provider spend を bound する (Codex R6 F-1)。block 時は
    production と同じ ``running -> blocked`` (budget_blocked) 遷移 + ``exceeded=True`` を返し、
    orchestrator の ``blocked_budget`` 経路をそのまま流用できる。
    """

    blocked = await _evaluate_shadow_block(
        session,
        run=run,
        actor_id=actor_id,
        current_tokens=current_tokens,
        current_wall_clock_ms=current_wall_clock_ms,
        retry_count=retry_count,
        at_or_over=False,
    )
    if blocked is not None:
        return blocked

    settings = get_settings()
    return BudgetCheckResult(
        level="agent_run",
        exceeded=False,
        current_usd=_decimal_or_zero(getattr(run, "cost_usd", None)),
        hard_limit_usd=settings.shadow_run_max_cost_usd,
        soft_threshold_usd=None,
        reason=None,
        current_tokens=current_tokens,
        hard_limit_tokens=settings.shadow_run_max_total_tokens,
        current_wall_clock_ms=current_wall_clock_ms,
        hard_limit_wall_clock_ms=None,
        retry_count=retry_count,
        max_retries=None,
    )


async def preflight_shadow_budget(
    session: AsyncSession,
    *,
    run: AgentRun,
    actor_id: UUID,
) -> BudgetCheckResult | None:
    """provider 実行 **前** に shadow run の kill switch + 既存累計 USD/token cap を評価する。

    production / 非 shadow run は ``None`` (no-op)。``record_provider_usage`` の
    post-execution 評価 (cost 加算後) を補完する pre-execution gate であり: (1) global kill
    switch を usage の有無に関わらず provider 課金前に効かせる (Codex R4 F-2)、(2) 既に
    USD/token cap に到達 (>=) した shadow run の **次 call** を課金前に block する
    (Codex R5 F-3 / R6 F-1)。

    block する場合は ``running -> blocked`` (budget_blocked) へ遷移し ``exceeded=True`` を
    返す (caller は provider.execute せず blocked_budget を surface する)。block 不要なら
    ``None`` を返す。
    """

    if getattr(run, "run_mode", "production") != "shadow":
        return None

    current_tokens = _int_or_zero(getattr(run, "tokens_input", None)) + _int_or_zero(
        getattr(run, "tokens_output", None)
    )
    return await _evaluate_shadow_block(
        session,
        run=run,
        actor_id=actor_id,
        current_tokens=current_tokens,
        current_wall_clock_ms=0,
        retry_count=0,
        at_or_over=True,
    )


async def preflight_shadow_request_tokens(
    session: AsyncSession,
    *,
    run: AgentRun,
    actor_id: UUID,
    request_max_tokens: int | None,
    estimated_input_tokens: int = 0,
) -> BudgetCheckResult | None:
    """shadow run の **単一 provider call** を input + output token で pre-execution 上限化する。

    production / 非 shadow run は ``None`` (no-op)。shadow run は (1) ``max_tokens`` (output 上限) を
    必須宣言し (unbounded request 禁止)、(2) ``current_tokens + estimated_input_tokens +
    max_tokens`` が token cap 以内でなければ provider 課金前に block する。``estimated_input_tokens``
    は caller (orchestrator) が prompt から算出する **保守的 (over-estimate) な input token 概算**
    (Codex R7/R8/R9 F-2: output 上限だけでは巨大 prompt の input spend を課金前に bound できない。
    tokenizer 非依存の保守見積で fail-safe にする)。block 時は ``running -> blocked``
    (budget_blocked) 遷移 + ``exceeded=True`` を返す。
    """

    if getattr(run, "run_mode", "production") != "shadow":
        return None

    settings = get_settings()
    token_cap = settings.shadow_run_max_total_tokens
    current_tokens = _int_or_zero(getattr(run, "tokens_input", None)) + _int_or_zero(
        getattr(run, "tokens_output", None)
    )
    current_usd = _decimal_or_zero(getattr(run, "cost_usd", None))

    # (1) max_tokens 未宣言 (unbounded) / token cap 超過は block。
    projected_tokens = current_tokens + estimated_input_tokens + (request_max_tokens or 0)
    if request_max_tokens is None or projected_tokens > token_cap:
        return await _block_shadow_run(
            session,
            run=run,
            actor_id=actor_id,
            current_usd=current_usd,
            hard_limit_usd=None,
            hard_limit_tokens=token_cap,
            reason="hard_tokens_exceeded",
            budget_level="shadow_request_tokens",
            current_tokens=current_tokens,
            current_wall_clock_ms=0,
            retry_count=0,
        )

    # (2) USD も provider 課金前に projection で bound する (Codex R11 F-1)。
    # projected_call_usd = (input + output) * worst-case 単価 (over-estimate = fail-safe)。
    # per-model pricing table が無いため保守的 single ceiling で USD cap を pre-execution 化。
    usd_cap = settings.shadow_run_max_cost_usd
    projected_call_usd = (
        Decimal(estimated_input_tokens + request_max_tokens)
        * settings.shadow_run_max_usd_per_token
    )
    if current_usd + projected_call_usd > usd_cap:
        return await _block_shadow_run(
            session,
            run=run,
            actor_id=actor_id,
            current_usd=current_usd,
            hard_limit_usd=usd_cap,
            hard_limit_tokens=None,
            reason="hard_usd_exceeded",
            budget_level="shadow_request_usd",
            current_tokens=current_tokens,
            current_wall_clock_ms=0,
            retry_count=0,
        )
    return None


async def _evaluate_shadow_block(
    session: AsyncSession,
    *,
    run: AgentRun,
    actor_id: UUID,
    current_tokens: int,
    current_wall_clock_ms: int,
    retry_count: int,
    at_or_over: bool,
) -> BudgetCheckResult | None:
    """shadow の kill switch + USD cap + token cap を評価し、block 時に遷移 + result を返す。

    ``at_or_over=True`` (preflight): cap **到達** (>=) で block (次 call を課金前に止める)。
    ``at_or_over=False`` (post-execution): cap **超過** (>) で block (cost 加算後に跨いだ call)。
    通過なら ``None``。
    """

    settings = get_settings()
    current_usd = _decimal_or_zero(getattr(run, "cost_usd", None))

    if await _global_kill_switch_engaged(session, run):
        return await _block_shadow_run(
            session,
            run=run,
            actor_id=actor_id,
            current_usd=current_usd,
            hard_limit_usd=None,
            hard_limit_tokens=None,
            reason="global_kill_switch",
            budget_level="global",
            current_tokens=current_tokens,
            current_wall_clock_ms=current_wall_clock_ms,
            retry_count=retry_count,
        )

    usd_cap = settings.shadow_run_max_cost_usd
    usd_exceeded = current_usd >= usd_cap if at_or_over else current_usd > usd_cap
    if usd_exceeded:
        return await _block_shadow_run(
            session,
            run=run,
            actor_id=actor_id,
            current_usd=current_usd,
            hard_limit_usd=usd_cap,
            hard_limit_tokens=None,
            reason="hard_usd_exceeded",
            budget_level="shadow_run_cap",
            current_tokens=current_tokens,
            current_wall_clock_ms=current_wall_clock_ms,
            retry_count=retry_count,
        )

    token_cap = settings.shadow_run_max_total_tokens
    token_exceeded = (
        current_tokens >= token_cap if at_or_over else current_tokens > token_cap
    )
    if token_exceeded:
        return await _block_shadow_run(
            session,
            run=run,
            actor_id=actor_id,
            current_usd=current_usd,
            hard_limit_usd=None,
            hard_limit_tokens=token_cap,
            reason="hard_tokens_exceeded",
            budget_level="shadow_run_token_cap",
            current_tokens=current_tokens,
            current_wall_clock_ms=current_wall_clock_ms,
            retry_count=retry_count,
        )

    return None


async def _global_kill_switch_engaged(session: AsyncSession, run: AgentRun) -> bool:
    """active な global budget の global_kill_switch を読む (spend 限度は適用しない)。

    config の読み取りのみで shadow cost を production accumulator へ加算しないため、
    §4 production budget 非擾乱を破らない。
    """

    budgets = await BudgetRepository(session).list_effective_for_run(
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        run_id=run.id,
    )
    global_budget = budgets.get("global")
    return global_budget is not None and global_budget.global_kill_switch is True


async def _block_shadow_run(
    session: AsyncSession,
    *,
    run: AgentRun,
    actor_id: UUID,
    current_usd: Decimal,
    hard_limit_usd: Decimal | None,
    hard_limit_tokens: int | None,
    reason: BudgetExceedReason,
    budget_level: str,
    current_tokens: int,
    current_wall_clock_ms: int,
    retry_count: int,
) -> BudgetCheckResult:
    await transition_with_event(
        session,
        run=run,
        to_state="blocked",
        event_type="budget_blocked",
        actor_id=actor_id,
        blocked_reason="budget_blocked",
        payload={
            "budget_level": budget_level,
            "exceed_reason": reason,
            "current_usd": str(current_usd),
            "hard_limit_usd": None if hard_limit_usd is None else str(hard_limit_usd),
            "current_tokens": current_tokens,
            "hard_limit_tokens": hard_limit_tokens,
            "run_mode": "shadow",
        },
    )
    return BudgetCheckResult(
        level="agent_run",
        exceeded=True,
        current_usd=current_usd,
        hard_limit_usd=hard_limit_usd,
        soft_threshold_usd=None,
        reason=reason,
        current_tokens=current_tokens,
        hard_limit_tokens=hard_limit_tokens,
        current_wall_clock_ms=current_wall_clock_ms,
        hard_limit_wall_clock_ms=None,
        retry_count=retry_count,
        max_retries=None,
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
    if isinstance(value, str | bytes | bytearray):
        return int(value)
    if isinstance(value, SupportsInt):
        return int(value)
    raise TypeError("value must be int-compatible.")


def _require_positive_tenant_id(tenant_id: int) -> None:
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
        raise ValueError("tenant_id must be a positive integer.")


def _require_nonempty_matrix_version(matrix_version: str) -> None:
    if not isinstance(matrix_version, str) or not matrix_version:
        raise ValueError("matrix_version must be a non-empty string.")


__all__ = [
    "preflight_shadow_budget",
    "preflight_shadow_request_tokens",
    "record_provider_usage",
]

