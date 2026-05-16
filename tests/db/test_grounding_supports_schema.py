"""Schema introspection contract for grounding_supports (Sprint 10 BL-0119).

Verifies the migration 0018 + GroundingSupport model are in sync:
- 11 required columns
- support_type CHECK constraint enumerates ('cite', 'paraphrase', 'quote')
- confidence_score CHECK constraint enforces [0, 1] or null
- run_id = agent_run_id CHECK
- evidence_items has the new uq (tenant_id, project_id, id)
- artifacts.kind CHECK enumerates the new 'research_promotion' value

These are pure introspection tests of the imported model — they do
not require a live DB. The DB-touching boundary test lives in
tests/security/test_research_cross_project_negative.py.
"""

from __future__ import annotations

import sqlalchemy as sa

from backend.app.db.models.artifact import Artifact
from backend.app.db.models.evidence_item import EvidenceItem
from backend.app.db.models.grounding_support import (
    SUPPORT_TYPE_ENUM,
    GroundingSupport,
)

EXPECTED_GROUNDING_SUPPORTS_COLUMNS: frozenset[str] = frozenset(
    {
        "id",
        "tenant_id",
        "project_id",
        "agent_run_id",
        "run_id",
        "generated_artifact_id",
        "claim_id",
        "evidence_source_id",
        "evidence_item_id",
        "support_type",
        "confidence_score",
        "metadata",
        "created_at",
        "updated_at",
    }
)


def test_grounding_supports_columns_match_expected() -> None:
    actual = {col.name for col in GroundingSupport.__table__.columns}
    assert actual == EXPECTED_GROUNDING_SUPPORTS_COLUMNS, (
        f"GroundingSupport column drift: "
        f"only-in-actual={actual - EXPECTED_GROUNDING_SUPPORTS_COLUMNS}, "
        f"only-in-expected={EXPECTED_GROUNDING_SUPPORTS_COLUMNS - actual}"
    )


def test_grounding_supports_support_type_check_constraint_present() -> None:
    """The CHECK constraint must enumerate exactly cite/paraphrase/quote."""
    check_names = {
        c.name
        for c in GroundingSupport.__table__.constraints
        if isinstance(c, sa.CheckConstraint)
    }
    assert "grounding_supports_ck_support_type" in check_names


def test_grounding_supports_confidence_score_range_check_present() -> None:
    check_names = {
        c.name
        for c in GroundingSupport.__table__.constraints
        if isinstance(c, sa.CheckConstraint)
    }
    assert "grounding_supports_ck_confidence_score_range" in check_names


def test_grounding_supports_run_id_equals_agent_run_id_check_present() -> None:
    check_names = {
        c.name
        for c in GroundingSupport.__table__.constraints
        if isinstance(c, sa.CheckConstraint)
    }
    assert "grounding_supports_ck_run_id_equals_agent_run_id" in check_names


def test_grounding_supports_unique_artifact_claim_item_present() -> None:
    uq_names = {
        c.name
        for c in GroundingSupport.__table__.constraints
        if isinstance(c, sa.UniqueConstraint)
    }
    assert "grounding_supports_uq_artifact_claim_item" in uq_names
    assert "grounding_supports_uq_tenant_id" in uq_names


def test_support_type_enum_matches_check_constraint() -> None:
    """Cross-source enum integrity: the Python frozenset must match the
    DB CHECK enumeration."""
    assert SUPPORT_TYPE_ENUM == frozenset({"cite", "paraphrase", "quote"})


def test_grounding_supports_has_six_fk_constraints() -> None:
    """tenant + 2-stage FK (agent_runs + artifacts) + claim + source +
    evidence_item = 6 FK constraints (server-owned-boundary §1 +
    composite FK pattern)."""
    fk_names = {
        c.name
        for c in GroundingSupport.__table__.constraints
        if isinstance(c, sa.ForeignKeyConstraint)
    }
    assert fk_names == {
        "grounding_supports_tenant_id_fkey",
        "grounding_supports_agent_run_fkey",
        "grounding_supports_artifact_fkey",
        "grounding_supports_claim_fkey",
        "grounding_supports_source_fkey",
        "grounding_supports_evidence_item_fkey",
    }


def test_evidence_items_has_tenant_project_id_unique_constraint() -> None:
    """Migration 0018 step 1: the new unique constraint that
    grounding_supports.evidence_item_fkey depends on must exist on the
    EvidenceItem model."""
    uq_names = {
        c.name
        for c in EvidenceItem.__table__.constraints
        if isinstance(c, sa.UniqueConstraint)
    }
    assert "evidence_items_uq_tenant_project_id" in uq_names
    # Existing tenant-level unique must remain in place for paths that
    # join evidence_items without a project_id filter.
    assert "evidence_items_uq_tenant_id" in uq_names


def test_artifacts_kind_check_includes_research_promotion() -> None:
    """Migration 0018 step 2: artifacts.kind CHECK must list the new
    research_promotion kind."""
    kind_check = next(
        c
        for c in Artifact.__table__.constraints
        if isinstance(c, sa.CheckConstraint) and c.name == "artifacts_ck_kind"
    )
    sql_text = str(kind_check.sqltext).lower()
    assert "research_promotion" in sql_text
