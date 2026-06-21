"""SP-PHASE1 B2: managed_agents.state enum の cross-source 整合 test。

cross-source-enum-integrity §1 に従い、state enum を次の source 間で exact-set 比較で固定する
(drift = 超過 / 不足とも reject):

1. Python Literal (`ALL_MANAGED_AGENT_STATES`)
2. ORM CheckConstraint (`managed_agents_ck_state`)
3. DB migration CHECK (`migrations/versions/0052_phase1_managed_agents.py`)
4. pytest `EXPECTED_MANAGED_AGENT_STATES`

(Pydantic 表面は B2 では未追加 — registry は内部 service。frontend は P0.1 forward-compat。)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from sqlalchemy import CheckConstraint

from backend.app.db.models.managed_agent import ManagedAgentRecord
from backend.app.domain.superintendent.managed_agent_state import (
    ACTIVE_MANAGED_AGENT_STATES,
    ALL_MANAGED_AGENT_STATES,
    TERMINAL_MANAGED_AGENT_STATES,
    ManagedAgentState,
)

# 正本 (ADR-00048 §Amendment A-1)。
EXPECTED_MANAGED_AGENT_STATES: frozenset[str] = frozenset(
    {"spawning", "running", "stopped", "failed"}
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = (
    _REPO_ROOT / "migrations" / "versions" / "0052_phase1_managed_agents.py"
)


def _quoted_values(check_sql: str) -> frozenset[str]:
    return frozenset(re.findall(r"'([a-z_]+)'", check_sql))


def test_python_literal_matches_expected() -> None:
    assert frozenset(ALL_MANAGED_AGENT_STATES) == EXPECTED_MANAGED_AGENT_STATES
    assert frozenset(get_args(ManagedAgentState)) == EXPECTED_MANAGED_AGENT_STATES
    # tuple 宣言順の先頭は spawning (pre-register default)。
    assert ALL_MANAGED_AGENT_STATES[0] == "spawning"


def test_active_and_terminal_partition_all_states() -> None:
    # active ∪ terminal == 全 state、かつ disjoint (overlap なし)。
    assert ACTIVE_MANAGED_AGENT_STATES | TERMINAL_MANAGED_AGENT_STATES == (
        EXPECTED_MANAGED_AGENT_STATES
    )
    assert ACTIVE_MANAGED_AGENT_STATES & TERMINAL_MANAGED_AGENT_STATES == frozenset()
    assert ACTIVE_MANAGED_AGENT_STATES == frozenset({"spawning", "running"})
    assert TERMINAL_MANAGED_AGENT_STATES == frozenset({"stopped", "failed"})


def test_orm_check_constraint_matches_expected() -> None:
    checks = {
        c.name: c
        for c in ManagedAgentRecord.__table__.constraints
        if isinstance(c, CheckConstraint)
    }
    assert "managed_agents_ck_state" in checks
    sqltext = str(checks["managed_agents_ck_state"].sqltext)
    assert _quoted_values(sqltext) == EXPECTED_MANAGED_AGENT_STATES


def test_migration_0052_check_matches_expected() -> None:
    source = _MIGRATION.read_text(encoding="utf-8")
    state_checks = [
        line for line in source.splitlines() if "state in" in line.lower()
    ]
    assert state_checks, "migration 0052 must declare a managed_agents state CHECK"
    extracted: set[str] = set()
    for line in state_checks:
        extracted |= set(_quoted_values(line))
    assert frozenset(extracted) == EXPECTED_MANAGED_AGENT_STATES
