from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

BudgetLevel = Literal["tenant", "project", "agent_run", "global"]
BudgetExceedReason = Literal[
    "hard_usd_exceeded",
    "hard_tokens_exceeded",
    "hard_wall_clock_exceeded",
    "max_retries_exceeded",
    "global_kill_switch",
]


@dataclass(frozen=True, slots=True)
class BudgetCheckResult:
    level: BudgetLevel
    exceeded: bool
    current_usd: Decimal | None
    hard_limit_usd: Decimal | None
    soft_threshold_usd: Decimal | None
    reason: BudgetExceedReason | None
    current_tokens: int | None = None
    hard_limit_tokens: int | None = None
    current_wall_clock_ms: int | None = None
    hard_limit_wall_clock_ms: int | None = None
    retry_count: int | None = None
    max_retries: int | None = None


__all__ = [
    "BudgetCheckResult",
    "BudgetExceedReason",
    "BudgetLevel",
]

