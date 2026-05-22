"""Agent role taxonomy (SP-013 batch 0 / ADR-00014 §1 + ADR-00019 §1).

10 standard role taxonomy (code enum、reserved namespace、PE-F-001 fix).

5+ source 整合 (cross-source-enum-integrity §1 同 pattern):
1. Python Literal type (`StandardRoleId`)
2. Python frozenset (`STANDARD_ROLE_IDS`)
3. Pydantic Field validator (本 module の `validate_role_id` で再利用)
4. pytest EXPECTED_STANDARD_ROLE_IDS constant (`tests/multi_agent/test_role_taxonomy_enum.py`)
5. DB-side `STANDARD_ROLE_IDS_MIRROR` table (SP-013 後続 batch で migration 追加、immutable seed)
6. (option) frontend TypeScript enum (SP-017 AI Society Visualization)

ADR-00014 §1 採用案: 10 役職 + role_scope (`global` / `project`):
- global: STANDARD_ROLE_IDS 内のみ許可
- project: project_agent_roles table から resolve (custom role 含む)

PE-F-001 mitigation: STANDARD_ROLE_IDS は **custom role_id として禁止**
(reserved namespace)、project_agent_roles 作成時に同名で reject。
"""

from __future__ import annotations

from typing import Final, Literal, get_args

# ADR-00019 §1 採用案: 10 標準役職 (code enum)
StandardRoleId = Literal[
    "orchestrator",      # マルチエージェント全体の調整、requester only / approval decider にならない
    "implementer",       # コード実装担当
    "reviewer",          # コード review 担当
    "tester",            # テスト実装 / 実行担当
    "security_agent",    # security audit 担当
    "researcher",        # research / evidence collection 担当
    "observer",          # observability / metrics 担当
    "curator",           # docs / Sprint Pack curation 担当
    "dispatcher",        # task dispatching / queue management 担当
    "repair_specialist", # failure repair / retry orchestration 担当
]


STANDARD_ROLE_IDS: Final[frozenset[str]] = frozenset(
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


RoleScope = Literal["global", "project"]


ALL_ROLE_SCOPES: Final[frozenset[str]] = frozenset({"global", "project"})


def validate_custom_role_id(role_id: str) -> None:
    """PE-F-001 fix: STANDARD_ROLE_IDS は reserved namespace.

    `project_agent_roles` 作成時に同名 role_id で reject、custom role が standard
    role を上書きしないことを invariant 化。

    Raises:
        ValueError: role_id が STANDARD_ROLE_IDS に含まれる場合 (reserved namespace 違反)
    """
    if role_id in STANDARD_ROLE_IDS:
        raise ValueError(
            f"role_id '{role_id}' is reserved for standard role "
            f"(PE-F-001 reserved namespace invariant)"
        )


def validate_role_scope_consistency(
    role_scope: str, role_id: str, *, is_custom: bool = False
) -> None:
    """ADR-00014 §1 採用案 invariant.

    role_scope='global' の場合は STANDARD_ROLE_IDS 内のみ許可、
    role_scope='project' で is_custom=False (= standard role の project-scoped 適用)
    の場合も同 STANDARD_ROLE_IDS 内のみ許可。

    role_scope='project' で is_custom=True (project_agent_roles の custom role) の
    場合は STANDARD_ROLE_IDS に含まれてはいけない (PE-F-001 reserved namespace 違反)。

    Raises:
        ValueError: invariant 違反
    """
    if role_scope not in ALL_ROLE_SCOPES:
        raise ValueError(
            f"role_scope '{role_scope}' invalid (allowed: {sorted(ALL_ROLE_SCOPES)})"
        )

    # Codex PR #133 R1 P1 fix: docstring 通り、is_custom=False は role_scope に
    # 関係なく STANDARD_ROLE_IDS のみ許可。global 限定 enforce では project +
    # is_custom=False で custom role_id を受け入れてしまう invariant 違反。
    if not is_custom and role_id not in STANDARD_ROLE_IDS:
        raise ValueError(
            f"is_custom=False requires role_id in STANDARD_ROLE_IDS "
            f"(got '{role_id}', allowed: {sorted(STANDARD_ROLE_IDS)})"
        )

    if is_custom and role_id in STANDARD_ROLE_IDS:
        raise ValueError(
            f"custom role_id '{role_id}' must not be in STANDARD_ROLE_IDS "
            f"(PE-F-001 reserved namespace)"
        )


__all__ = [
    "ALL_ROLE_SCOPES",
    "STANDARD_ROLE_IDS",
    "RoleScope",
    "StandardRoleId",
    "validate_custom_role_id",
    "validate_role_scope_consistency",
]


# 5+ source 整合 verify: Literal vs frozenset の double-check
# Python Literal の type-level enum と frozenset の runtime enum が一致することを
# import-time に assert (drift 早期検出、cross-source-enum-integrity §1 pattern)
_LITERAL_ARGS: Final[frozenset[str]] = frozenset(get_args(StandardRoleId))
if _LITERAL_ARGS != STANDARD_ROLE_IDS:
    raise AssertionError(
        f"StandardRoleId Literal と STANDARD_ROLE_IDS frozenset が drift: "
        f"Literal={sorted(_LITERAL_ARGS)}, frozenset={sorted(STANDARD_ROLE_IDS)}"
    )
