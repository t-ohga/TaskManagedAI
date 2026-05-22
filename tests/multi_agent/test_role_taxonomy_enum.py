"""SP-013 batch 0 / ADR-00014 + ADR-00019: agent role taxonomy contract test.

5+ source 整合 (cross-source-enum-integrity §1 pattern):
- Literal type + frozenset の drift 検出
- validate_custom_role_id / validate_role_scope_consistency invariant verify
- PE-F-001 reserved namespace 違反 reject
"""

from __future__ import annotations

from typing import get_args

import pytest

from backend.app.domain.agent_role.taxonomy import (
    ALL_ROLE_SCOPES,
    STANDARD_ROLE_IDS,
    StandardRoleId,
    validate_custom_role_id,
    validate_role_scope_consistency,
)

# ADR-00019 §1 採用案: 10 標準役職 (5+ source 整合の正本 fixture)
EXPECTED_STANDARD_ROLE_IDS = frozenset(
    {
        "orchestrator",
        "implementer",
        "reviewer",
        "tester",
        "security_agent",
        "researcher",
        "observer",
        "curator",
        "dispatcher",
        "repair_specialist",
    }
)

EXPECTED_ROLE_SCOPES = frozenset({"global", "project"})


def test_standard_role_ids_match_expected_fixture() -> None:
    """STANDARD_ROLE_IDS frozenset が EXPECTED 10 役職と完全一致 (drift 検出)."""
    assert STANDARD_ROLE_IDS == EXPECTED_STANDARD_ROLE_IDS, (
        f"STANDARD_ROLE_IDS drift: got {sorted(STANDARD_ROLE_IDS)}, "
        f"expected {sorted(EXPECTED_STANDARD_ROLE_IDS)}"
    )


def test_standard_role_id_literal_matches_frozenset() -> None:
    """Python Literal `StandardRoleId` と frozenset の 5+ source 整合."""
    literal_args = frozenset(get_args(StandardRoleId))
    assert literal_args == STANDARD_ROLE_IDS, (
        f"StandardRoleId Literal と STANDARD_ROLE_IDS drift: "
        f"Literal={sorted(literal_args)}, frozenset={sorted(STANDARD_ROLE_IDS)}"
    )


def test_role_scope_enum_matches_expected() -> None:
    """ALL_ROLE_SCOPES が global / project の 2 種完全一致."""
    assert ALL_ROLE_SCOPES == EXPECTED_ROLE_SCOPES


def test_validate_custom_role_id_rejects_standard_role() -> None:
    """PE-F-001: STANDARD_ROLE_IDS は custom role_id として禁止 (reserved namespace)."""
    for standard_role in STANDARD_ROLE_IDS:
        with pytest.raises(ValueError, match="reserved"):
            validate_custom_role_id(standard_role)


def test_validate_custom_role_id_accepts_non_standard() -> None:
    """非 standard role_id (custom) は accept."""
    custom_role_ids = [
        "my-custom-role",
        "team-alpha-reviewer",
        "domain-expert-finance",
    ]
    for role_id in custom_role_ids:
        # should not raise
        validate_custom_role_id(role_id)


def test_validate_role_scope_global_requires_standard_role() -> None:
    """role_scope='global' は STANDARD_ROLE_IDS 内のみ許可."""
    # global + standard role: OK
    for standard_role in STANDARD_ROLE_IDS:
        validate_role_scope_consistency("global", standard_role)

    # global + non-standard: reject
    with pytest.raises(ValueError, match="STANDARD_ROLE_IDS"):
        validate_role_scope_consistency("global", "my-custom-role")


def test_validate_role_scope_project_with_standard_role_ok() -> None:
    """role_scope='project' + standard role (is_custom=False) は OK."""
    for standard_role in STANDARD_ROLE_IDS:
        validate_role_scope_consistency("project", standard_role, is_custom=False)


# Codex PR #133 R1 P1 regression test
def test_validate_role_scope_project_is_custom_false_rejects_non_standard() -> None:
    """role_scope='project' + is_custom=False で非 STANDARD_ROLE_IDS は reject.

    docstring 通り、is_custom=False は role_scope に関係なく STANDARD_ROLE_IDS のみ許可。
    """
    with pytest.raises(ValueError, match="STANDARD_ROLE_IDS"):
        validate_role_scope_consistency(
            "project", "my-custom-non-standard", is_custom=False
        )


def test_validate_role_scope_project_custom_rejects_standard_id() -> None:
    """role_scope='project' + is_custom=True で STANDARD_ROLE_IDS は reject (PE-F-001)."""
    for standard_role in STANDARD_ROLE_IDS:
        with pytest.raises(ValueError, match="reserved namespace|STANDARD_ROLE_IDS"):
            validate_role_scope_consistency("project", standard_role, is_custom=True)


def test_validate_role_scope_invalid_scope_rejects() -> None:
    """role_scope が enum 外なら reject."""
    with pytest.raises(ValueError, match="role_scope"):
        validate_role_scope_consistency("invalid", "implementer")

    with pytest.raises(ValueError, match="role_scope"):
        validate_role_scope_consistency("", "implementer")


def test_standard_role_ids_count_is_exactly_10() -> None:
    """ADR-00019 §1 fixture: 10 役職 (drift 検出)."""
    assert len(STANDARD_ROLE_IDS) == 10, (
        f"STANDARD_ROLE_IDS は 10 役職想定、got {len(STANDARD_ROLE_IDS)}: "
        f"{sorted(STANDARD_ROLE_IDS)}"
    )
