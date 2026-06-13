"""SP-029 (ADR-00055) RunMode enum の cross-source 整合 test。

cross-source-enum-integrity rule §1 に従い、run_mode enum を次の source 間で
exact-set 比較で固定する (drift = 超過 / 不足とも reject):

1. Python Literal (`ALL_RUN_MODES`)
2. ORM CheckConstraint (`agent_runs_ck_run_mode`)
3. DB migration CHECK (`migrations/versions/0048_agent_run_run_mode.py`)
4. Pydantic 表面 (`AgentRunRead.run_mode` Literal)
5. pytest `EXPECTED_RUN_MODES`
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from sqlalchemy import CheckConstraint

from backend.app.api.agent_runs import AgentRunRead
from backend.app.db.models.agent_run import AgentRun
from backend.app.domain.agent_runtime.run_mode import (
    ALL_RUN_MODES,
    DEFAULT_RUN_MODE,
    RunMode,
)

# 正本 (ADR-00055 §設計制約 1: production / shadow の 2 値、16 status とは直交)。
EXPECTED_RUN_MODES: frozenset[str] = frozenset({"production", "shadow"})

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_0048 = (
    _REPO_ROOT / "migrations" / "versions" / "0048_agent_run_run_mode.py"
)


def _quoted_values(check_sql: str) -> frozenset[str]:
    """``run_mode in ('production','shadow')`` 形式から quoted 値集合を抽出する。"""
    return frozenset(re.findall(r"'([a-z_]+)'", check_sql))


def test_python_literal_matches_expected() -> None:
    assert frozenset(ALL_RUN_MODES) == EXPECTED_RUN_MODES
    assert frozenset(get_args(RunMode)) == EXPECTED_RUN_MODES
    # tuple 宣言順 (production 先頭、default と一致)。
    assert ALL_RUN_MODES[0] == "production"


def test_default_run_mode_is_production() -> None:
    assert DEFAULT_RUN_MODE == "production"
    assert DEFAULT_RUN_MODE in EXPECTED_RUN_MODES


def test_orm_check_constraint_matches_expected() -> None:
    checks = {
        c.name: c
        for c in AgentRun.__table__.constraints
        if isinstance(c, CheckConstraint)
    }
    assert "agent_runs_ck_run_mode" in checks
    sqltext = str(checks["agent_runs_ck_run_mode"].sqltext)
    assert _quoted_values(sqltext) == EXPECTED_RUN_MODES


def test_migration_0048_check_matches_expected() -> None:
    source = _MIGRATION_0048.read_text(encoding="utf-8")
    # migration 内の run_mode CHECK 文字列から値を抽出 (additive 列 + CHECK)。
    run_mode_checks = [
        line for line in source.splitlines() if "run_mode in" in line.lower()
    ]
    assert run_mode_checks, "migration 0048 must declare a run_mode CHECK"
    extracted: set[str] = set()
    for line in run_mode_checks:
        extracted |= set(_quoted_values(line))
    assert frozenset(extracted) == EXPECTED_RUN_MODES


def test_pydantic_agent_run_read_run_mode_matches_expected() -> None:
    annotation = AgentRunRead.model_fields["run_mode"].annotation
    assert frozenset(get_args(annotation)) == EXPECTED_RUN_MODES
