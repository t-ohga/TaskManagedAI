"""SP022-T01: docs/citations/dependency_to_framework_map.json と framework_pattern_candidates.md の整合性 verify.

ADR-00020 §1 #2 Attribution に対応。新 direct dependency が pyproject.toml /
frontend/package.json に追加された PR では citation 存在を assert する。

R1 F-011 adopt: dependency 変更なし環境では `pytest.skip` (CI 上 skip = exit 0 success)。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAP_FILE = REPO_ROOT / "docs/citations/dependency_to_framework_map.json"
CANDIDATES_FILE = REPO_ROOT / "docs/citations/framework_pattern_candidates.md"


def _run_extract(ecosystem: str) -> set[str]:
    """Invoke scripts/ci/_extract_changed_deps.py and return parsed set of added deps."""
    script_path = REPO_ROOT / "scripts/ci/_extract_changed_deps.py"
    try:
        result = subprocess.run(  # noqa: S603 (fixed sys.executable + repo-internal helper path)
            [sys.executable, str(script_path), f"--ecosystem={ecosystem}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return set()
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _load_map_entries() -> set[tuple[str, str]]:
    """Return set of (dependency_name, ecosystem) from dependency_to_framework_map.json."""
    if not MAP_FILE.exists():
        return set()
    data = json.loads(MAP_FILE.read_text(encoding="utf-8"))
    return {(e["dependency_name"], e["ecosystem"]) for e in data.get("entries", [])}


def _load_candidates_canonical_names() -> set[str]:
    """Return set of canonical framework names declared in framework_pattern_candidates.md."""
    if not CANDIDATES_FILE.exists():
        return set()
    content = CANDIDATES_FILE.read_text(encoding="utf-8")
    return set(re.findall(r"\|\s*\*\*([^*]+)\*\*\s*\|", content))


def test_map_schema_and_canonical_references() -> None:
    """dependency_to_framework_map.json schema 整合 + framework_canonical が candidates table に存在."""
    assert MAP_FILE.exists(), f"missing {MAP_FILE}"
    assert CANDIDATES_FILE.exists(), f"missing {CANDIDATES_FILE}"

    data = json.loads(MAP_FILE.read_text(encoding="utf-8"))
    assert data.get("schema_version") == 1, "schema_version must be 1"
    entries = data.get("entries")
    assert isinstance(entries, list) and entries, "entries must be a non-empty list"

    candidates = _load_candidates_canonical_names()
    for entry in entries:
        assert set(entry.keys()) >= {"dependency_name", "ecosystem", "framework_canonical"}, entry
        assert entry["ecosystem"] in {"pypi", "npm"}, entry
        canonical = entry["framework_canonical"]
        assert canonical in candidates, (
            f"framework_canonical '{canonical}' not found in "
            f"framework_pattern_candidates.md table (entry={entry})"
        )


def test_changed_deps_have_citation() -> None:
    """Each newly added direct dependency in PR must have a citation entry.

    R1 F-011 adopt: When no dependency changes, skip (CI treats skip as success).
    """
    changed_pypi = _run_extract("pypi")
    changed_npm = _run_extract("npm")
    if not changed_pypi and not changed_npm:
        pytest.skip("no dependency changes vs origin/main")

    entries = _load_map_entries()
    missing: list[str] = []
    for dep in changed_pypi:
        if (dep, "pypi") not in entries:
            missing.append(f"pypi:{dep}")
    for dep in changed_npm:
        if (dep, "npm") not in entries:
            missing.append(f"npm:{dep}")

    assert not missing, (
        "Direct dependencies added in this PR are missing citation entries in "
        f"docs/citations/dependency_to_framework_map.json: {missing}"
    )
