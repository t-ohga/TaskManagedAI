"""Sprint 8 BL-0098: GitHub App Permission Matrix loader + differential check.

ADR-00011 §採用案 / §Permission Matrix:
- 最小 permission (contents:write + pull_requests:write + metadata:read)
- 明示 deny (actions / workflows / packages / administration / issues / checks)
- CI で current permission (from `gh api repos/owner/repo/installation`) vs
  Matrix toml の diff check、不一致なら fail で merge block

P0 design:
- Matrix toml は repo 内 (`config/github_app_permissions.toml`) で hardcode
- Diff check は Sprint 8 で skeleton 実装、Sprint 11.5 で月次 audit に統合
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class GitHubAppPermissionMatrix:
    """ADR-00011 で承認された Permission Matrix の immutable snapshot."""

    dataset_version: str
    repository_permissions: dict[str, str] = field(default_factory=dict)
    repository_deny_explicit: dict[str, str] = field(default_factory=dict)
    organization_permissions: dict[str, str] = field(default_factory=dict)
    account_permissions: dict[str, str] = field(default_factory=dict)
    webhooks: dict[str, Any] = field(default_factory=dict)
    deny_actions: dict[str, str] = field(default_factory=dict)
    branch_naming: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def load_permission_matrix(
    config_path: str | Path | None = None,
) -> GitHubAppPermissionMatrix:
    """Load Permission Matrix from `config/github_app_permissions.toml`.

    Args:
        config_path: explicit path (test). None = repo default.
    """
    if config_path is None:
        config_path = Path(__file__).resolve().parents[4] / "config" / "github_app_permissions.toml"
    else:
        config_path = Path(config_path)

    with config_path.open("rb") as f:
        data = tomllib.load(f)

    repo_perm = data.get("repository_permissions", {})
    deny_explicit = repo_perm.pop("deny_explicit", {})

    return GitHubAppPermissionMatrix(
        dataset_version=data.get("dataset_version", ""),
        repository_permissions=dict(repo_perm),
        repository_deny_explicit=dict(deny_explicit),
        organization_permissions=dict(data.get("organization_permissions", {})),
        account_permissions=dict(data.get("account_permissions", {})),
        webhooks=dict(data.get("webhooks", {})),
        deny_actions=dict(data.get("deny_actions", {})),
        branch_naming=dict(data.get("branch_naming", {})),
        raw=data,
    )


def check_no_dangerous_permissions(matrix: GitHubAppPermissionMatrix) -> tuple[str, ...]:
    """Verify Permission Matrix has no dangerous permission enabled.

    Returns tuple of violation strings (empty if OK).
    """
    violations: list[str] = []

    # 必須 deny permission list
    must_deny = ("actions", "workflows", "packages", "administration")

    # repository_permissions に actions / workflows / packages / administration が
    # write/read として存在してはいけない
    for perm in must_deny:
        if perm in matrix.repository_permissions:
            violations.append(
                f"repository_permission.{perm}={matrix.repository_permissions[perm]!r} "
                f"is enabled but MUST be denied (ADR-00011 §採用案)"
            )

    # deny_explicit に明示 deny がない場合も violation
    for perm in must_deny:
        if matrix.repository_deny_explicit.get(perm) != "deny":
            violations.append(
                f"repository_permissions.deny_explicit.{perm} must be 'deny' "
                f"(currently {matrix.repository_deny_explicit.get(perm)!r})"
            )

    # merge / deploy が p0_deny でなければ違反
    for action in ("merge", "deploy"):
        if matrix.deny_actions.get(action) != "p0_deny":
            violations.append(
                f"deny_actions.{action} must be 'p0_deny' "
                f"(currently {matrix.deny_actions.get(action)!r})"
            )

    return tuple(violations)


def _diff_against_current(
    matrix: GitHubAppPermissionMatrix, current: dict[str, Any]
) -> tuple[str, ...]:
    """Codex SP8 R1 F-SP8-005 adopt: Matrix toml vs current installation
    permissions の差分検出。`current` は `gh api repos/{owner}/{repo}/installation`
    の `permissions` フィールド (dict[str, str]) を想定。

    Returns tuple of drift descriptions; empty if no drift.
    """
    drifts: list[str] = []
    current_perms = current.get("permissions", current)
    if not isinstance(current_perms, dict):
        return (f"unexpected current permissions shape: {type(current_perms).__name__}",)

    # Matrix で許可された permission が current にあること
    for perm, level in matrix.repository_permissions.items():
        actual = current_perms.get(perm)
        if actual != level:
            drifts.append(
                f"repository_permission.{perm}: matrix={level!r} current={actual!r}"
            )

    # Matrix で deny した permission が current で enabled でないこと
    for perm in matrix.repository_deny_explicit:
        actual = current_perms.get(perm)
        if actual not in (None, "none", ""):
            drifts.append(
                f"repository_permission.{perm} is enabled in current "
                f"({actual!r}) but Matrix denies it"
            )

    return tuple(drifts)


def _cli() -> int:  # noqa: PLR0911, T201 のみ allow (CLI)
    """Codex SP8 R1 F-SP8-005 adopt: ADR-00011 §採用案 CLI differential check。

    使用法:
      python -m backend.app.services.repoproxy.permission_matrix --check
        [--current-permissions-json <path>]

    --check のみ: static `check_no_dangerous_permissions` を実行
    --current-permissions-json <path>: GitHub API response (JSON) と diff 検出

    Exit code:
      0: clean
      1: violation (dangerous permission or drift)
      2: CLI usage error
    """
    import argparse  # noqa: PLC0415
    import json  # noqa: PLC0415
    import sys  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        description="GitHub App Permission Matrix differential check (ADR-00011)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run static check_no_dangerous_permissions on Matrix toml",
    )
    parser.add_argument(
        "--current-permissions-json",
        type=str,
        default=None,
        help="Path to JSON file containing current installation.permissions",
    )
    args = parser.parse_args()

    if not args.check:
        parser.print_help()
        return 2

    matrix = load_permission_matrix()
    violations = check_no_dangerous_permissions(matrix)
    for v in violations:
        print(f"VIOLATION (static): {v}", file=sys.stderr)  # noqa: T201

    drift_violations: tuple[str, ...] = ()
    if args.current_permissions_json:
        try:
            with open(args.current_permissions_json, encoding="utf-8") as f:
                current = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR: cannot load current permissions: {exc}", file=sys.stderr)  # noqa: T201
            return 2
        drift_violations = _diff_against_current(matrix, current)
        for d in drift_violations:
            print(f"DRIFT: {d}", file=sys.stderr)  # noqa: T201

    total = len(violations) + len(drift_violations)
    if total > 0:
        print(  # noqa: T201
            f"FAIL: {total} violation(s) detected. ADR-00011 update required.",
            file=sys.stderr,
        )
        return 1

    print(f"OK: Permission Matrix clean (dataset_version={matrix.dataset_version})")  # noqa: T201
    return 0


__all__ = [
    "GitHubAppPermissionMatrix",
    "check_no_dangerous_permissions",
    "load_permission_matrix",
]


if __name__ == "__main__":
    import sys  # noqa: PLC0415

    sys.exit(_cli())
