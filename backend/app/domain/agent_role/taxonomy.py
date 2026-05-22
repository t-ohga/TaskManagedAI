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

    matrix:
    - global + standard role + is_custom=False: OK (default、tenant-wide standard role)
    - global + standard role + is_custom=True: reject (global is incompatible with custom)
    - global + non-standard (任意 is_custom): reject (global は STANDARD_ROLE_IDS only)
    - project + standard role + is_custom=False: OK (project-scoped standard role)
    - project + standard role + is_custom=True: reject (PE-F-001 reserved namespace)
    - project + non-standard + is_custom=True: OK (project_agent_roles の custom role)
    - project + non-standard + is_custom=False: reject (custom role なら is_custom=True 必須)

    Raises:
        ValueError: invariant 違反
    """
    if role_scope not in ALL_ROLE_SCOPES:
        raise ValueError(
            f"role_scope '{role_scope}' invalid (allowed: {sorted(ALL_ROLE_SCOPES)})"
        )

    if role_scope == "global":
        # global は always STANDARD_ROLE_IDS only、custom 非対応
        # Codex PR #135 R1 P1 fix: PR #133 fix で global-scope check が is_custom=True
        # で bypass される invariant 違反を導入 → global は is_custom 関係なく
        # STANDARD_ROLE_IDS only enforce + is_custom=True との互換性 reject
        if role_id not in STANDARD_ROLE_IDS:
            raise ValueError(
                f"role_scope='global' requires role_id in STANDARD_ROLE_IDS "
                f"(got '{role_id}', allowed: {sorted(STANDARD_ROLE_IDS)})"
            )
        if is_custom:
            raise ValueError(
                "role_scope='global' is incompatible with is_custom=True "
                "(global scope is reserved for standard roles only)"
            )
    elif role_scope == "project":
        # Codex PR #133 R1 P1 fix: project + is_custom=False は STANDARD_ROLE_IDS only enforce
        if not is_custom and role_id not in STANDARD_ROLE_IDS:
            raise ValueError(
                f"is_custom=False with role_scope='project' requires role_id in STANDARD_ROLE_IDS "
                f"(got '{role_id}', allowed: {sorted(STANDARD_ROLE_IDS)})"
            )
        # PE-F-001 reserved namespace: custom role と standard role の同名禁止
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
