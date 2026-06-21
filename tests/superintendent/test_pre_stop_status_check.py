"""SP-PHASE1 B2 (adversarial MEDIUM-1 / LOW-5): agent_runs.pre_stop_status CHECK の cross-source 整合。

4-layer 防御の DB/ORM 層を固定する。pre_stop_status は emergency-stop block source = resume 復元先
= {running, policy_linted, diff_ready, waiting_approval} (ADR-00048 §A-5) の subset しか許さない:

1. migration 0052 CHECK (`agent_runs_ck_pre_stop_status`)
2. ORM CheckConstraint (`agent_runs_ck_pre_stop_status`)
3. pytest `EXPECTED_PRE_STOP_STATUSES` (block source / resume 復元先 subset)

加えて subset ⊆ AgentRunStatus (Literal) を確認する (status enum に存在しない値を許さない)。
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import CheckConstraint

from backend.app.db.models.agent_run import AgentRun
from backend.app.domain.agent_runtime.status import ALL_AGENT_RUN_STATUSES

# 正本: ADR-00048 §A-5 の emergency block source / resume 復元先。
EXPECTED_PRE_STOP_STATUSES: frozenset[str] = frozenset(
    {"running", "policy_linted", "diff_ready", "waiting_approval"}
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = (
    _REPO_ROOT / "migrations" / "versions" / "0052_phase1_managed_agents.py"
)


def _quoted_values(check_sql: str) -> frozenset[str]:
    return frozenset(re.findall(r"'([a-z_]+)'", check_sql))


def test_expected_subset_is_within_agent_run_status() -> None:
    # 4-status subset は AgentRunStatus enum に存在する値のみ。
    assert EXPECTED_PRE_STOP_STATUSES <= frozenset(ALL_AGENT_RUN_STATUSES)
    # block 不可な terminal / 中間 state は含まない。
    assert "blocked" not in EXPECTED_PRE_STOP_STATUSES
    assert "completed" not in EXPECTED_PRE_STOP_STATUSES
    assert "queued" not in EXPECTED_PRE_STOP_STATUSES


def test_orm_check_constraint_matches_expected() -> None:
    checks = {
        c.name: c
        for c in AgentRun.__table__.constraints
        if isinstance(c, CheckConstraint)
    }
    assert "agent_runs_ck_pre_stop_status" in checks
    sqltext = str(checks["agent_runs_ck_pre_stop_status"].sqltext)
    assert _quoted_values(sqltext) == EXPECTED_PRE_STOP_STATUSES


def test_migration_0052_pre_stop_check_matches_expected() -> None:
    source = _MIGRATION.read_text(encoding="utf-8")
    # `_PRE_STOP_CHECK = (...)` assignment block を抽出 (複数行 string concat に対応)。
    match = re.search(
        r"_PRE_STOP_CHECK\s*=\s*\((.*?)\)", source, flags=re.DOTALL
    )
    assert match, "migration 0052 must declare _PRE_STOP_CHECK"
    block = match.group(1)
    assert "pre_stop_status in" in block.lower()
    assert frozenset(_quoted_values(block)) == EXPECTED_PRE_STOP_STATUSES
