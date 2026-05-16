from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint

from backend.app.db.models.dataset_version import (
    STANDARD_FIXTURE_KINDS,
    DatasetVersion,
    FixtureKind,
)
from backend.app.services.eval.loader import LOADER_FIXTURE_KINDS, FixtureKindPayload

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_PATH = _REPO_ROOT / "migrations" / "versions" / "0018_eval_dataset_versions.py"

EXPECTED_FIXTURE_KINDS = frozenset({"public_regression", "private_holdout", "adversarial_new"})


def _constraint_values(constraint: CheckConstraint) -> frozenset[str]:
    return frozenset(re.findall(r"'([^']+)'", str(constraint.sqltext)))


def test_fixture_kind_enum_matches_across_five_sources() -> None:
    db_check = next(
        constraint
        for constraint in DatasetVersion.__table__.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name == "dataset_versions_ck_fixture_kind"
    )

    assert _constraint_values(db_check) == EXPECTED_FIXTURE_KINDS
    assert frozenset(get_args(FixtureKind)) == EXPECTED_FIXTURE_KINDS
    assert frozenset(STANDARD_FIXTURE_KINDS) == EXPECTED_FIXTURE_KINDS
    assert frozenset(LOADER_FIXTURE_KINDS) == EXPECTED_FIXTURE_KINDS

    for fixture_kind in EXPECTED_FIXTURE_KINDS:
        payload = FixtureKindPayload.model_validate({"fixture_kind": fixture_kind})
        assert payload.fixture_kind == fixture_kind


def test_fixture_kind_migration_source_contains_all_standard_values() -> None:
    migration_source = _MIGRATION_PATH.read_text(encoding="utf-8")

    assert "dataset_versions_ck_fixture_kind" in migration_source
    for fixture_kind in EXPECTED_FIXTURE_KINDS:
        assert fixture_kind in migration_source


@pytest.mark.parametrize("bad_fixture_kind", ["", "public-regression", "holdout", "private_holdouts", "PUBLIC"])
def test_fixture_kind_loader_validator_rejects_typo_extra_and_missing_values(
    bad_fixture_kind: str,
) -> None:
    with pytest.raises(ValidationError):
        FixtureKindPayload.model_validate({"fixture_kind": bad_fixture_kind})


def test_fixture_kind_orm_check_constraint_rejects_typo_extra_and_missing_values() -> None:
    db_check = next(
        constraint
        for constraint in DatasetVersion.__table__.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name == "dataset_versions_ck_fixture_kind"
    )
    actual = _constraint_values(db_check)

    assert "public-regression" not in actual
    assert "holdout" not in actual
    assert "private_holdouts" not in actual
    assert actual == EXPECTED_FIXTURE_KINDS
