"""Action class taxonomy (ADR-00009 proposed): 7 種固定。

Backend domain / DB CHECK / frontend type / fixture schema で同一集合を保つ。
legacy `read/search` (read-only tool action) は Sprint 4.5 Tool Registry
allowed_actions 側に寄せ、Policy action class からは除外する。
"""

from typing import Literal

ActionClass = Literal[
    "task_write",
    "repo_write",
    "pr_open",
    "secret_access",
    "merge",
    "deploy",
    "provider_call",
]

ALL_ACTION_CLASSES: frozenset[ActionClass] = frozenset(
    {
        "task_write",
        "repo_write",
        "pr_open",
        "secret_access",
        "merge",
        "deploy",
        "provider_call",
    }
)

# ADR-00009 採用案: P0 常時 deny の action class
P0_ALWAYS_DENIED: frozenset[ActionClass] = frozenset({"merge", "deploy"})

# ADR-00009 採用案: fail-closed (deny または require_approval) の action class
P0_FAIL_CLOSED: frozenset[ActionClass] = frozenset({"secret_access", "provider_call"})

# ADR-00009 採用案: 条件に応じて require_approval / deny の action class
P0_CONDITIONAL: frozenset[ActionClass] = frozenset({"task_write", "repo_write", "pr_open"})


PolicyEffect = Literal["allow", "deny", "require_approval"]

ALL_POLICY_EFFECTS: frozenset[PolicyEffect] = frozenset({"allow", "deny", "require_approval"})


__all__ = [
    "ActionClass",
    "ALL_ACTION_CLASSES",
    "ALL_POLICY_EFFECTS",
    "P0_ALWAYS_DENIED",
    "P0_CONDITIONAL",
    "P0_FAIL_CLOSED",
    "PolicyEffect",
]

