"""Extract changed direct dependencies from pyproject.toml or frontend/package.json.

SP022-T01 ADR-00020 §1 #2 Attribution + #1 License で使う dependency name 抽出 helper。

Compares `origin/main` (base) vs working tree (HEAD), prints **added** dependency names
(direct dependencies only, transitive is out-of-scope per R1 F-005 + R2 F-003 adopt).

- pyproject.toml: [project.dependencies] + [project.optional-dependencies.*] +
  [dependency-groups].* (uv direct dev/group dependencies、R2 F-003 adopt)
- frontend/package.json: dependencies + devDependencies (R2 F-006 adopt: scoped name
  `@scope/name` は canonical name としてそのまま保持)

PEP 503 canonicalization (lowercase + `[-_.]+` -> `-`) for PyPI; npm scoped names
are preserved verbatim. Lockfile (uv.lock / pnpm-lock.yaml) は trigger detection 用のみ、
本 helper では抽出対象外。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path


def _normalize_pypi(name: str) -> str:
    """PEP 503: lowercase + collapse `[-_.]+` to `-`, strip leading/trailing `-`."""
    return re.sub(r"[-_.]+", "-", name.lower()).strip("-")


def _parse_dep_name(spec: str) -> str | None:
    """Parse `name[extras]>=X` style spec, return canonical PyPI name."""
    m = re.match(r"^\s*([A-Za-z0-9_.\-]+)", spec)
    return _normalize_pypi(m.group(1)) if m else None


def load_pyproject_at(ref: str | None) -> set[str]:
    """Load direct dependency names from pyproject.toml at given git ref (or working tree)."""
    if ref is None:
        path = Path("pyproject.toml")
        if not path.exists():
            return set()
        content = path.read_text(encoding="utf-8")
    else:
        try:
            content = subprocess.check_output(
                ["git", "show", f"{ref}:pyproject.toml"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            # base ref に pyproject.toml が存在しない (e.g., 新規 repo) は空 set
            return set()

    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError as e:
        print(f"ERROR: pyproject.toml parse failed at ref={ref or 'HEAD'}: {e}", file=sys.stderr)
        sys.exit(2)

    deps: set[str] = set()
    project = data.get("project", {})

    # [project.dependencies]
    for dep_spec in project.get("dependencies", []):
        name = _parse_dep_name(dep_spec)
        if name:
            deps.add(name)

    # [project.optional-dependencies.*]
    for _, items in (project.get("optional-dependencies") or {}).items():
        for dep_spec in items:
            name = _parse_dep_name(dep_spec)
            if name:
                deps.add(name)

    # [dependency-groups].* (R2 F-003 adopt: uv direct dev/group dependency)
    for _, items in (data.get("dependency-groups") or {}).items():
        for dep_spec in items:
            if not isinstance(dep_spec, str):
                # `{include-group = "..."}` 形式は対象外 (include-group 名のみ参照)
                continue
            name = _parse_dep_name(dep_spec)
            if name:
                deps.add(name)

    return deps


def load_package_json_at(ref: str | None) -> set[str]:
    """Load direct dependency names from frontend/package.json at given git ref (or working tree)."""
    if ref is None:
        path = Path("frontend/package.json")
        if not path.exists():
            return set()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"ERROR: frontend/package.json parse failed: {e}", file=sys.stderr)
            sys.exit(2)
    else:
        try:
            content = subprocess.check_output(
                ["git", "show", f"{ref}:frontend/package.json"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            return set()
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            print(f"ERROR: frontend/package.json parse failed at ref={ref}: {e}", file=sys.stderr)
            sys.exit(2)

    deps: set[str] = set()
    # R2 F-006 adopt: scoped name `@scope/name` は canonical のまま保持
    deps.update((data.get("dependencies") or {}).keys())
    deps.update((data.get("devDependencies") or {}).keys())
    return deps


def main() -> int:
    p = argparse.ArgumentParser(
        description="Extract changed direct dependencies (added in working tree vs base ref)."
    )
    p.add_argument(
        "--ecosystem",
        choices=["pypi", "npm"],
        required=True,
        help="pypi=pyproject.toml / npm=frontend/package.json",
    )
    p.add_argument(
        "--base",
        default="origin/main",
        help="base git ref for diff (default: origin/main)",
    )
    args = p.parse_args()

    loader = load_pyproject_at if args.ecosystem == "pypi" else load_package_json_at
    base_deps = loader(args.base)
    head_deps = loader(None)  # working tree

    added = sorted(head_deps - base_deps)
    for dep in added:
        print(dep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
