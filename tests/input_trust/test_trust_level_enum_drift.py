"""trust_level 5+ source integrity (Sprint 5.5 BL-0065).

Verifies that the 3-value ``trust_level`` enum is consistent across every
source of truth so adding or removing a value requires updating every
authoritative location (`.claude/rules/cross-source-enum-integrity.md` §1):

1. DB CHECK constraint (migration ``0011_trust_level_event_25.py``)
2. ORM CheckConstraint (``backend.app.db.models.artifact.Artifact``)
3. Python ``Literal`` (``backend.app.domain.artifact.trust_level.TrustLevel``)
4. ``frozenset`` (``backend.app.domain.artifact.trust_level.TRUST_LEVELS``)
5. pytest ``EXPECTED_TRUST_LEVELS`` (this file)
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import get_args

from backend.app.db.models.artifact import Artifact
from backend.app.domain.artifact.trust_level import (
    ALL_TRUST_LEVELS,
    TRUST_LEVELS,
    TrustLevel,
    trust_level_ordinal,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRUST_LEVEL_MIGRATION = (
    _REPO_ROOT / "migrations" / "versions" / "0011_trust_level_event_25.py"
)

EXPECTED_TRUST_LEVELS: tuple[TrustLevel, ...] = (
    "untrusted_content",
    "validated_artifact",
    "trusted_instruction",
)


def _module_string_constants(module: ast.Module) -> dict[str, str]:
    result: dict[str, str] = {}
    for stmt in module.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            result[target.id] = stmt.value.value
    return result


def _trust_level_values_from_migration() -> set[str]:
    """Parse ``op.create_check_constraint("artifacts_ck_trust_level", ...)``.

    The ``condition`` argument MAY be either an inline string literal or a
    reference to a module-level string constant (e.g. ``_TRUST_LEVEL_CHECK_SQL``).
    """

    module = ast.parse(_TRUST_LEVEL_MIGRATION.read_text(encoding="utf-8"))
    constants = _module_string_constants(module)
    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "create_check_constraint":
            continue
        if len(node.args) < 3:
            continue
        name_arg = node.args[0]
        cond_arg = node.args[2]
        if not isinstance(name_arg, ast.Constant) or name_arg.value != "artifacts_ck_trust_level":
            continue
        condition: str | None = None
        if isinstance(cond_arg, ast.Constant) and isinstance(cond_arg.value, str):
            condition = cond_arg.value
        elif isinstance(cond_arg, ast.Name) and cond_arg.id in constants:
            condition = constants[cond_arg.id]
        if condition is None:
            raise AssertionError(
                "artifacts_ck_trust_level condition must be a string literal "
                "or module-level string constant."
            )
        return set(re.findall(r"'([^']+)'", condition))
    raise AssertionError(
        "artifacts_ck_trust_level not found in 0011_trust_level_event_25.py."
    )


def _trust_level_values_from_orm() -> set[str]:
    # ``__table_args__`` is a heterogeneous tuple — typically a sequence of
    # constraints / indexes followed by an options dict. Skip anything that
    # does not have both a ``name`` and a ``sqltext`` attribute.
    for constraint in Artifact.__table_args__:
        name = getattr(constraint, "name", None)
        if name != "artifacts_ck_trust_level":
            continue
        sqltext = getattr(constraint, "sqltext", None)
        if sqltext is None:
            continue
        return set(re.findall(r"'([^']+)'", str(sqltext)))
    raise AssertionError("artifacts_ck_trust_level not present in ORM __table_args__.")


def test_trust_level_literal_matches_expected_tuple() -> None:
    assert tuple(get_args(TrustLevel)) == EXPECTED_TRUST_LEVELS
    assert ALL_TRUST_LEVELS == EXPECTED_TRUST_LEVELS


def test_trust_level_frozenset_matches_expected() -> None:
    assert TRUST_LEVELS == frozenset(EXPECTED_TRUST_LEVELS)


def test_trust_level_db_migration_check_matches() -> None:
    assert _trust_level_values_from_migration() == set(EXPECTED_TRUST_LEVELS)


def test_trust_level_orm_check_constraint_matches() -> None:
    assert _trust_level_values_from_orm() == set(EXPECTED_TRUST_LEVELS)


def test_trust_level_ordinal_is_strictly_increasing() -> None:
    """Ordinal contract: untrusted < validated < trusted (ADR-00009 §198)."""

    ordinals = [trust_level_ordinal(level) for level in EXPECTED_TRUST_LEVELS]
    assert ordinals == [0, 1, 2]


def test_trust_level_ordinal_rejects_unknown_values() -> None:
    import pytest

    with pytest.raises(ValueError, match="unknown trust_level"):
        trust_level_ordinal("validated_instruction")  # type: ignore[arg-type]
