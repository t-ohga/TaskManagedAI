"""AgentRun の run_mode enum (SP-029 shadow mode、ADR-00055)。

`production` = 通常実行 (副作用あり、production budget / KPI)。
`shadow` = 試走実行 (副作用 fail-closed 隔離、production budget 非加算、production KPI 除外、
per-run hard cap で capped)。16 status / blocked_reason 3 / ContextSnapshot 10 列は不変で、
run_mode は additive な直交次元。
"""

from __future__ import annotations

from typing import Literal

RunMode = Literal["production", "shadow"]

ALL_RUN_MODES: tuple[RunMode, ...] = (
    "production",
    "shadow",
)

DEFAULT_RUN_MODE: RunMode = "production"

__all__ = [
    "ALL_RUN_MODES",
    "DEFAULT_RUN_MODE",
    "RunMode",
]
