"""managed_agents.state enum (SP-PHASE1 B2、ADR-00048 §Amendment A-1)。

DB-backed agent supervision registry (`managed_agents`) の lifecycle state。
cross-process kill の正本 (in-process dict ではない) であり、supervisor は kill 時
``state ∈ {spawning, running}`` を全対象とする (A-1)。

- ``spawning``: spawn ordering A-1 で process 起動前に pre-register された状態
  (advisory lock + 同一 transaction 内、latch generation 刻印)。pid/pgid 未確定。
- ``running``: process 起動 + pid/pgid/boot_id 確定後の状態。kill 対象。
- ``stopped``: 正常終了 / stop / kill 後の terminal 状態。
- ``failed``: 起動失敗・例外 compensating terminalize 後の terminal 状態 (orphan 行を残さない)。

cross-source-enum-integrity §1 に従い 5+source (DB CHECK / ORM CheckConstraint /
Python Literal / pytest EXPECTED) で exact-set 整合させる。
"""

from __future__ import annotations

from typing import Literal

ManagedAgentState = Literal["spawning", "running", "stopped", "failed"]

ALL_MANAGED_AGENT_STATES: tuple[ManagedAgentState, ...] = (
    "spawning",
    "running",
    "stopped",
    "failed",
)

#: supervisor が kill 対象とする非 terminal state (A-1)。
ACTIVE_MANAGED_AGENT_STATES: frozenset[ManagedAgentState] = frozenset(
    {"spawning", "running"}
)

#: terminal state (これ以上 kill しない)。
TERMINAL_MANAGED_AGENT_STATES: frozenset[ManagedAgentState] = frozenset(
    {"stopped", "failed"}
)

__all__ = [
    "ACTIVE_MANAGED_AGENT_STATES",
    "ALL_MANAGED_AGENT_STATES",
    "ManagedAgentState",
    "TERMINAL_MANAGED_AGENT_STATES",
]
