from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import cast, get_args
from uuid import uuid4

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.schema import DefaultClause

from backend.app.db.models.project import Project
from backend.app.domain.policy.autonomy_level import (
    ALL_AUTONOMY_LEVELS,
    DEFAULT_AUTONOMY_LEVEL,
    AutonomyLevel,
)
from backend.app.schemas.project import ProjectRead

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "migrations" / "versions" / "0034_sp024_autonomy_level.py"
ADR_PATH = REPO_ROOT / "docs" / "adr" / "00025_autonomy_policy_profiles.md"
EXPECTED_AUTONOMY_LEVELS = {"L0", "L1", "L2", "L3"}


def _quoted_values(sql_expression: str) -> set[str]:
    return set(re.findall(r"'([^']+)'", sql_expression))


def test_autonomy_level_literal_matches_expected_set() -> None:
    assert set(get_args(AutonomyLevel)) == EXPECTED_AUTONOMY_LEVELS
    assert set(ALL_AUTONOMY_LEVELS) == EXPECTED_AUTONOMY_LEVELS
    assert DEFAULT_AUTONOMY_LEVEL == "L0"


def test_autonomy_level_migration_check_matches_domain_enum() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    match = re.search(r'AUTONOMY_LEVEL_CHECK = "([^"]+)"', migration)
    assert match is not None
    assert _quoted_values(match.group(1)) == EXPECTED_AUTONOMY_LEVELS
    assert 'server_default=sa.text("\'L0\'")' in migration
    assert 'revision: str = "0034_sp024_autonomy_level"' in migration
    assert 'down_revision: str | None = "0033_sp020_adopted_artifacts"' in migration


def test_project_model_autonomy_level_check_matches_domain_enum() -> None:
    project_table = cast(sa.Table, Project.__table__)
    constraints = {
        constraint.name: constraint
        for constraint in project_table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }

    constraint = constraints["projects_ck_autonomy_level"]
    assert _quoted_values(str(constraint.sqltext)) == EXPECTED_AUTONOMY_LEVELS
    assert project_table.c.autonomy_level.default is not None
    server_default = project_table.c.autonomy_level.server_default
    assert server_default is not None
    assert str(cast(DefaultClause, server_default).arg) == "'L0'"


def test_project_read_schema_accepts_only_autonomy_level_enum() -> None:
    payload = {
        "id": uuid4(),
        "tenant_id": 1,
        "workspace_id": uuid4(),
        "slug": "project",
        "name": "Project",
        "status": "active",
        "policy_profile": "default",
        "autonomy_level": "L0",
        "metadata_": {"rls_ready": True},
        "created_at": datetime.now(tz=UTC),
        "updated_at": datetime.now(tz=UTC),
    }

    assert ProjectRead.model_validate(payload).autonomy_level == "L0"

    payload["autonomy_level"] = "L4"
    try:
        ProjectRead.model_validate(payload)
    except ValidationError as exc:
        assert "autonomy_level" in str(exc)
    else:  # pragma: no cover - explicit failure keeps assertion message precise.
        raise AssertionError("ProjectRead accepted an unknown autonomy_level.")


def test_adr_level_matrix_matches_domain_enum() -> None:
    adr = ADR_PATH.read_text(encoding="utf-8")

    matrix_levels = set(re.findall(r"\|\s+\*\*(L[0-9])\*\*", adr))
    assert matrix_levels == EXPECTED_AUTONOMY_LEVELS
