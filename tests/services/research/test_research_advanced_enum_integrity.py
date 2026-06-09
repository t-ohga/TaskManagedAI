"""SP-032 (ADR-00052): conflict status + trust_tier の 5+ source enum integrity (no-DB)。

DB CHECK (migration constant) / ORM CheckConstraint / Python Literal / Pydantic / pytest EXPECTED を
exact set で比較する (cross-source-enum-integrity §1)。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import get_args

import pytest

from backend.app.db.models.conflict_group import (
    CONFLICT_GROUP_STATUSES,
    ConflictGroup,
    ConflictGroupStatus,
)
from backend.app.db.models.domain_trust import (
    TRUST_TIERS,
    DomainTrustRegistry,
    TrustTier,
)
from backend.app.schemas.conflict_group import ConflictGroupUpdate
from backend.app.schemas.domain_trust import DomainTrustUpdate

EXPECTED_CONFLICT_STATUSES = {"open", "resolved", "dismissed"}
EXPECTED_TRUST_TIERS = {"low", "medium", "high"}

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "migrations"
    / "versions"
    / "0045_sp032_research_advanced.py"
)


def _load_migration() -> object:
    spec = importlib.util.spec_from_file_location("_sp032_migration", _MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check_constraint_sql(model: type, name: str) -> str:
    for constraint in model.__table__.constraints:
        if getattr(constraint, "name", None) == name:
            return str(constraint.sqltext)
    raise AssertionError(f"check constraint {name!r} not found on {model.__name__}")


def test_conflict_status_literal_matches_expected() -> None:
    assert set(get_args(ConflictGroupStatus)) == EXPECTED_CONFLICT_STATUSES
    assert CONFLICT_GROUP_STATUSES == frozenset(EXPECTED_CONFLICT_STATUSES)


def test_trust_tier_literal_matches_expected() -> None:
    assert set(get_args(TrustTier)) == EXPECTED_TRUST_TIERS
    assert TRUST_TIERS == frozenset(EXPECTED_TRUST_TIERS)


def test_migration_constants_match_expected() -> None:
    migration = _load_migration()
    assert set(migration.CONFLICT_STATUSES) == EXPECTED_CONFLICT_STATUSES  # type: ignore[attr-defined]
    assert set(migration.TRUST_TIERS) == EXPECTED_TRUST_TIERS  # type: ignore[attr-defined]


def test_orm_check_constraint_contains_all_statuses() -> None:
    sql = _check_constraint_sql(ConflictGroup, "conflict_groups_ck_status")
    for value in EXPECTED_CONFLICT_STATUSES:
        assert f"'{value}'" in sql


def test_orm_check_constraint_contains_all_trust_tiers() -> None:
    sql = _check_constraint_sql(DomainTrustRegistry, "domain_trust_registry_ck_trust_tier")
    for value in EXPECTED_TRUST_TIERS:
        assert f"'{value}'" in sql


@pytest.mark.parametrize("value", sorted(EXPECTED_CONFLICT_STATUSES))
def test_pydantic_accepts_valid_conflict_status(value: str) -> None:
    parsed = ConflictGroupUpdate.model_validate({"status": value, "resolution_note": "x"})
    assert parsed.status == value


def test_pydantic_rejects_invalid_conflict_status() -> None:
    with pytest.raises(ValueError, match="status"):
        ConflictGroupUpdate.model_validate({"status": "archived"})


@pytest.mark.parametrize("value", sorted(EXPECTED_TRUST_TIERS))
def test_pydantic_accepts_valid_trust_tier(value: str) -> None:
    parsed = DomainTrustUpdate.model_validate({"trust_tier": value})
    assert parsed.trust_tier == value


def test_pydantic_rejects_invalid_trust_tier() -> None:
    with pytest.raises(ValueError, match="trust_tier"):
        DomainTrustUpdate.model_validate({"trust_tier": "ultra"})
