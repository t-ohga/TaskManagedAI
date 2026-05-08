from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import get_args
from uuid import uuid4

import pytest

from backend.app.domain.policy.action_class import (
    ALL_ACTION_CLASSES,
    P0_ALWAYS_DENIED,
    P0_CONDITIONAL,
    P0_FAIL_CLOSED,
    ActionClass,
)
from backend.app.repositories.policy_rule import PolicyRuleRepository

_REPO_ROOT = Path(__file__).resolve().parents[2]
_POLICY_RULES_MIGRATION = _REPO_ROOT / "migrations" / "versions" / "0005_policy_rules.py"


class _DummySession:
    pass


def _call_keyword_string(node: ast.Call, keyword_name: str) -> str | None:
    for keyword in node.keywords:
        if (
            keyword.arg == keyword_name
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
        ):
            return keyword.value.value
    return None


def _check_constraint_values_from_migration(constraint_name: str) -> set[str]:
    module = ast.parse(_POLICY_RULES_MIGRATION.read_text(encoding="utf-8"))

    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "CheckConstraint":
            continue
        if _call_keyword_string(node, "name") != constraint_name:
            continue
        if not node.args:
            raise AssertionError(f"{constraint_name} has no SQL expression.")

        expression_node = node.args[0]
        if not isinstance(expression_node, ast.Constant) or not isinstance(
            expression_node.value,
            str,
        ):
            raise AssertionError(f"{constraint_name} SQL expression must be a string literal.")

        return set(re.findall(r"'([^']+)'", expression_node.value))

    raise AssertionError(f"{constraint_name} was not found in 0005_policy_rules.py.")


def test_all_action_classes_set_matches_literal() -> None:
    assert set(get_args(ActionClass)) == set(ALL_ACTION_CLASSES)


def test_db_check_constraint_matches_action_classes() -> None:
    assert (
        _check_constraint_values_from_migration("policy_rules_ck_action_class")
        == ALL_ACTION_CLASSES
    )


def test_p0_always_denied_subset() -> None:
    assert P0_ALWAYS_DENIED == {"merge", "deploy"}


def test_p0_fail_closed_subset() -> None:
    assert P0_FAIL_CLOSED == {"secret_access", "provider_call"}


def test_p0_conditional_subset() -> None:
    assert P0_CONDITIONAL == {"task_write", "repo_write", "pr_open"}


def test_disjoint_action_class_subsets() -> None:
    assert P0_ALWAYS_DENIED.isdisjoint(P0_FAIL_CLOSED)
    assert P0_ALWAYS_DENIED.isdisjoint(P0_CONDITIONAL)
    assert P0_FAIL_CLOSED.isdisjoint(P0_CONDITIONAL)
    assert P0_ALWAYS_DENIED | P0_FAIL_CLOSED | P0_CONDITIONAL == ALL_ACTION_CLASSES


@pytest.mark.asyncio
async def test_policy_rule_repository_create_raises_not_implemented() -> None:
    repo = PolicyRuleRepository(_DummySession())  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError, match="migration seed"):
        await repo.create(tenant_id=1, payload={})


@pytest.mark.asyncio
async def test_policy_rule_repository_update_raises_not_implemented() -> None:
    repo = PolicyRuleRepository(_DummySession())  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError, match="policy_version"):
        await repo.update(tenant_id=1, id=uuid4(), payload={})


@pytest.mark.asyncio
async def test_policy_rule_repository_delete_raises_not_implemented() -> None:
    repo = PolicyRuleRepository(_DummySession())  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError, match="append-only"):
        await repo.delete(tenant_id=1, id=uuid4())


def test_policy_rule_repository_statement_for_update_raises() -> None:
    repo = PolicyRuleRepository(_DummySession())  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError, match="statement_for_update"):
        repo.statement_for_update(tenant_id=1, id=uuid4(), payload={})


def test_policy_rule_repository_statement_for_delete_raises() -> None:
    repo = PolicyRuleRepository(_DummySession())  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError, match="statement_for_delete"):
        repo.statement_for_delete(tenant_id=1, id=uuid4())
