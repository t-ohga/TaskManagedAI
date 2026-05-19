"""Framework intake scanner for verify items #3-#8 (SP022-T01 ADR-00020).

Per R2 F-004/F-005/F-006 adopt, this is a pure-Python replacement for ripgrep-based
scanning. `ubuntu-latest` GitHub runner does not include ripgrep in its preinstalled
software list, so we implement scanning via pathlib + re module.

Rules (exit code 0 = no violation, 1 = violations found, 2 = internal error):
- no_code_embed: Python `import langgraph` / npm `from '@langchain/langgraph'` etc.
- persistence: `import sqlite3` / `psycopg.connect(` direct call
- external_network: literal `https://api.honcho.dev/...` etc.
- telemetry: `import sentry_sdk` / `from '@sentry/node'` etc.
- secret_canary: existence verify of preflight file + tests/security fixture pair +
  eval/security/secret_canary dir
- tenant_boundary: existence verify of AC-HARD-03 / tenant_isolation marker in
  tests/db, tests/repositories, or eval/security/tenant_isolation

Frontend scan roots reflect actual Next.js App Router layout (frontend/app, components,
lib, middleware.ts, next.config.ts) per R2 F-006 adopt. `frontend/src/` does not exist
in this repo.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Callable

PY_DENYLIST_FRAMEWORKS: tuple[str, ...] = (
    "langgraph",
    "crewai",
    "autogen",
    "pyautogen",
    "letta",
    "dapr",
    "dify_client",
    "openhands",
    "taskingai",
    # PR70 R4 F-PR70-R4-004 adopt: Semantic Kernel (10-framework candidate ledger entry)
    "semantic_kernel",
)
NPM_DENYLIST_FRAMEWORKS: tuple[str, ...] = (
    "langgraph",
    "@langchain/langgraph",
    "@langchain/langgraph-sdk",
    "@langchain/core",
    "crewai",
    "autogen",
    "letta",
    "dapr",
    "dify",
    "flowise",
    "openhands",
    "taskingai",
    # PR70 R5 F-PR70-R5-006 adopt: Semantic Kernel npm canonical name
    "semantic-kernel",
)
NETWORK_DENYLIST: tuple[str, ...] = (
    "api.honcho.dev",
    "api.mem0.ai",
    "api.supermemory.ai",
    "sentry.io",
    "api.datadoghq.com",
    "api.newrelic.com",
)
TELEMETRY_PY: tuple[str, ...] = ("sentry_sdk", "datadog", "newrelic", "honcho")
TELEMETRY_NPM: tuple[str, ...] = (
    "@sentry/node",
    "@sentry/nextjs",
    "@datadog/browser-logs",
    "newrelic",
    "honcho",
)

# R2 F-006 adopt: actual Next.js App Router layout (no frontend/src/).
# PR70 F-PR70-007 adopt: include Next.js root-level instrumentation hooks.
FRONTEND_SCAN_ROOTS: tuple[Path, ...] = (
    Path("frontend/app"),
    Path("frontend/components"),
    Path("frontend/lib"),
    Path("frontend/middleware.ts"),
    Path("frontend/next.config.ts"),
    Path("frontend/instrumentation.ts"),
    Path("frontend/instrumentation-client.ts"),
)
FRONTEND_EXCLUDE_PARTS: frozenset[str] = frozenset({"__tests__", "tests", "node_modules"})
BACKEND_SCAN_ROOTS: tuple[Path, ...] = (Path("backend/app"),)
BACKEND_EXCLUDE_PARTS: frozenset[str] = frozenset({"migrations"})
# PR70 F-PR70-006 adopt: include backend/app/repositories (SQLAlchemy session boundary).
# PR70 R2 F-PR70-R2-005 adopt: include backend/app/api + backend/app/workers (route handlers /
# arq workers can call DB connect directly, must be scanned).
# PR70 R3 F-PR70-R3-003 adopt: scope expanded to entire backend/app to cover product paths
# (domain / middleware / observability / seeds / schemas). BACKEND_EXCLUDE_PARTS still excludes
# `migrations` to avoid Alembic migration files matching.
PERSISTENCE_ROOTS: tuple[Path, ...] = (Path("backend/app"),)

FRONTEND_EXTS: frozenset[str] = frozenset({".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"})
CONFIG_EXTS: frozenset[str] = frozenset({".toml", ".yaml", ".yml", ".json", ".py"})


def _iter_python_files(roots: tuple[Path, ...]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            files.append(root)
            continue
        for path in root.rglob("*.py"):
            if any(part in BACKEND_EXCLUDE_PARTS for part in path.parts):
                continue
            files.append(path)
    return files


def _iter_frontend_files(roots: tuple[Path, ...]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            files.append(root)
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in FRONTEND_EXTS:
                continue
            if any(part in FRONTEND_EXCLUDE_PARTS for part in path.parts):
                continue
            files.append(path)
    return files


def _read_text_or_none(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError, OSError):
        return None


def check_no_code_embed() -> list[str]:
    violations: list[str] = []
    # PR70 F-PR70-002 adopt: include `,` after package name (e.g., `import langgraph, os`)
    py_pattern = re.compile(
        r"^\s*(import|from)\s+("
        + "|".join(re.escape(n) for n in PY_DENYLIST_FRAMEWORKS)
        + r")(\s|,|\.|$)",
        re.MULTILINE,
    )
    # PR70 R4 F-PR70-R4-003 + R5 F-PR70-R5-002 adopt: detect Python dynamic imports
    # `importlib.import_module("langgraph")` / `__import__("crewai")` and submodule variants
    # `importlib.import_module("langgraph.graph")` / `__import__("crewai.tools")`
    py_alts = "|".join(re.escape(n) for n in PY_DENYLIST_FRAMEWORKS)
    py_dynamic_pattern = re.compile(
        r"""(?:importlib\.import_module|__import__)\s*\(\s*['"]("""
        + py_alts
        + r""")(?:\.[A-Za-z_][A-Za-z0-9_.]*)?['"]"""
    )
    for path in _iter_python_files(BACKEND_SCAN_ROOTS):
        content = _read_text_or_none(path)
        if content is None:
            continue
        for match in py_pattern.finditer(content):
            line_num = content[: match.start()].count("\n") + 1
            violations.append(
                f"VIOLATION reason_code=framework_intake_violation_code_embed "
                f"evidence={path}:{line_num} framework={match.group(2)} detail=python_import"
            )
        for match in py_dynamic_pattern.finditer(content):
            line_num = content[: match.start()].count("\n") + 1
            violations.append(
                f"VIOLATION reason_code=framework_intake_violation_code_embed "
                f"evidence={path}:{line_num} framework={match.group(1)} detail=python_dynamic_import"
            )

    # PR70 F-PR70-005 adopt: include side-effect import `import "@scope/name";`
    npm_alts = "|".join(re.escape(n) for n in NPM_DENYLIST_FRAMEWORKS)
    # PR70 R6 F-PR70-R6-005 adopt: allow whitespace in `require ( ` / `import ( ` for valid
    # dynamic import variants like `await import ("@langchain/core")`.
    npm_pattern = re.compile(
        r"""(?:from\s+['"]|require\s*\(\s*['"]|import\s*\(\s*['"]|import\s+['"])("""
        + npm_alts
        + r""")(?:/[^'"]*)?['"]"""
    )
    for path in _iter_frontend_files(FRONTEND_SCAN_ROOTS):
        content = _read_text_or_none(path)
        if content is None:
            continue
        for match in npm_pattern.finditer(content):
            line_num = content[: match.start()].count("\n") + 1
            violations.append(
                f"VIOLATION reason_code=framework_intake_violation_code_embed "
                f"evidence={path}:{line_num} framework={match.group(1)} detail=npm_import"
            )
    return violations


def check_persistence() -> list[str]:
    violations: list[str] = []
    sqlite_pattern = re.compile(r"^\s*(import\s+sqlite3|from\s+sqlite3\s+import)", re.MULTILINE)
    # PR70 R2 F-PR70-R2-003 + R4 F-PR70-R4-005 + R5 F-PR70-R5-005 adopt:
    # - module-qualified `psycopg.connect(` / `psycopg2.connect(`
    # - `from psycopg import connect` alias
    # - class-level `psycopg.AsyncConnection.connect(` / `psycopg.Connection.connect(`
    # - `from psycopg import AsyncConnection; AsyncConnection.connect(...)` import alias chain
    psycopg_pattern = re.compile(r"psycopg2?\.connect\(")
    psycopg_class_connect = re.compile(r"psycopg2?\.(?:Async)?Connection\.connect\(")
    psycopg_import_connect = re.compile(
        r"^\s*from\s+psycopg2?\s+import\s+(?:[^#\n]*?\b)?connect\b", re.MULTILINE
    )
    # R5-005 + R6 F-PR70-R6-004 adopt: `from psycopg import [Async]Connection [as <alias>]`
    # の import-class-then-call chain。R6 で `as <alias>` 別名取得を追加、`<alias>.connect(`
    # も検出 (alias は per-file 集合として下記 loop 内で動的 regex 構築)。
    psycopg_import_class_re = re.compile(
        r"^\s*from\s+psycopg2?\s+import\s+([^#\n]+)$", re.MULTILINE
    )
    for path in _iter_python_files(PERSISTENCE_ROOTS):
        content = _read_text_or_none(path)
        if content is None:
            continue
        for match in sqlite_pattern.finditer(content):
            line_num = content[: match.start()].count("\n") + 1
            violations.append(
                f"VIOLATION reason_code=framework_intake_violation_persistence "
                f"evidence={path}:{line_num} framework=sqlite3 detail=direct_import"
            )
        for match in psycopg_pattern.finditer(content):
            line_num = content[: match.start()].count("\n") + 1
            violations.append(
                f"VIOLATION reason_code=framework_intake_violation_persistence "
                f"evidence={path}:{line_num} framework=psycopg detail=direct_connect"
            )
        for match in psycopg_class_connect.finditer(content):
            line_num = content[: match.start()].count("\n") + 1
            violations.append(
                f"VIOLATION reason_code=framework_intake_violation_persistence "
                f"evidence={path}:{line_num} framework=psycopg detail=class_level_connect"
            )
        for match in psycopg_import_connect.finditer(content):
            line_num = content[: match.start()].count("\n") + 1
            violations.append(
                f"VIOLATION reason_code=framework_intake_violation_persistence "
                f"evidence={path}:{line_num} framework=psycopg detail=from_import_connect_alias"
            )
        # R5-005 + R6 F-PR70-R6-004 adopt: file imports Connection/AsyncConnection from psycopg
        # (possibly with `as <alias>`) AND calls `<alias>.connect(` or `[Async]Connection.connect(`
        # → flag both as alias-chain bypass.
        imported_aliases: set[str] = set()
        for imp_match in psycopg_import_class_re.finditer(content):
            # parse `Connection, AsyncConnection as PG, errors` into class names + aliases
            spec = imp_match.group(1)
            for item in spec.split(","):
                item = item.strip()
                if not item:
                    continue
                parts = item.split(" as ")
                base = parts[0].strip()
                alias = parts[-1].strip() if len(parts) > 1 else base
                if base in ("Connection", "AsyncConnection"):
                    imported_aliases.add(alias)
        for alias in imported_aliases:
            # `alias.connect(` literal pattern per alias
            alias_call = re.compile(re.escape(alias) + r"\.connect\(")
            for match in alias_call.finditer(content):
                line_num = content[: match.start()].count("\n") + 1
                violations.append(
                    f"VIOLATION reason_code=framework_intake_violation_persistence "
                    f"evidence={path}:{line_num} framework=psycopg detail=from_import_class_connect_alias"
                )
    return violations


def check_external_network() -> list[str]:
    violations: list[str] = []
    net_alts = "|".join(re.escape(n) for n in NETWORK_DENYLIST)
    url_pattern = re.compile(r"https?://[^\"'\s]*(" + net_alts + r")")

    targets: list[Path] = []
    targets.extend(_iter_python_files(BACKEND_SCAN_ROOTS))
    targets.extend(_iter_frontend_files(FRONTEND_SCAN_ROOTS))
    config_root = Path("config")
    if config_root.exists():
        for path in config_root.rglob("*"):
            if path.is_file() and path.suffix in CONFIG_EXTS:
                targets.append(path)
    # PR70 R2 F-PR70-R2-006 adopt: scan deployment YAML files (docker-compose*.yml / *.yaml)
    # at repo root so framework integrations that introduce denylisted SaaS URLs via env vars
    # in deployment config are caught.
    for compose_glob in ("docker-compose*.yml", "docker-compose*.yaml", "compose*.yml", "compose*.yaml"):
        for path in Path(".").glob(compose_glob):
            if path.is_file():
                targets.append(path)

    for path in targets:
        content = _read_text_or_none(path)
        if content is None:
            continue
        for match in url_pattern.finditer(content):
            line_num = content[: match.start()].count("\n") + 1
            violations.append(
                f"VIOLATION reason_code=framework_intake_violation_external_network "
                f"evidence={path}:{line_num} host={match.group(1)} detail=denylisted_endpoint"
            )
    return violations


def check_telemetry() -> list[str]:
    violations: list[str] = []
    # PR70 F-PR70-003 adopt: include `,` after package name (e.g., `import sentry_sdk, os`)
    py_pattern = re.compile(
        r"^\s*(import|from)\s+("
        + "|".join(re.escape(n) for n in TELEMETRY_PY)
        + r")(\s|,|\.|$)",
        re.MULTILINE,
    )
    # PR70 R5 F-PR70-R5-004 adopt: detect dynamic telemetry imports
    # `importlib.import_module("sentry_sdk")` / `__import__("datadog")` + submodule variants
    py_telemetry_alts = "|".join(re.escape(n) for n in TELEMETRY_PY)
    py_telemetry_dynamic = re.compile(
        r"""(?:importlib\.import_module|__import__)\s*\(\s*['"]("""
        + py_telemetry_alts
        + r""")(?:\.[A-Za-z_][A-Za-z0-9_.]*)?['"]"""
    )
    for path in _iter_python_files(BACKEND_SCAN_ROOTS):
        content = _read_text_or_none(path)
        if content is None:
            continue
        for match in py_pattern.finditer(content):
            line_num = content[: match.start()].count("\n") + 1
            violations.append(
                f"VIOLATION reason_code=framework_intake_violation_telemetry "
                f"evidence={path}:{line_num} framework={match.group(2)} detail=python_import"
            )
        for match in py_telemetry_dynamic.finditer(content):
            line_num = content[: match.start()].count("\n") + 1
            violations.append(
                f"VIOLATION reason_code=framework_intake_violation_telemetry "
                f"evidence={path}:{line_num} framework={match.group(1)} detail=python_dynamic_import"
            )

    # PR70 F-PR70-003 adopt: include side-effect import `import "@sentry/nextjs";`
    npm_alts = "|".join(re.escape(n) for n in TELEMETRY_NPM)
    # PR70 R6 F-PR70-R6-005 adopt: allow whitespace in `require ( ` / `import ( ` for valid
    # dynamic import variants like `await import ("@langchain/core")`.
    npm_pattern = re.compile(
        r"""(?:from\s+['"]|require\s*\(\s*['"]|import\s*\(\s*['"]|import\s+['"])("""
        + npm_alts
        + r""")(?:/[^'"]*)?['"]"""
    )
    for path in _iter_frontend_files(FRONTEND_SCAN_ROOTS):
        content = _read_text_or_none(path)
        if content is None:
            continue
        for match in npm_pattern.finditer(content):
            line_num = content[: match.start()].count("\n") + 1
            violations.append(
                f"VIOLATION reason_code=framework_intake_violation_telemetry "
                f"evidence={path}:{line_num} framework={match.group(1)} detail=npm_import"
            )
    return violations


def check_secret_canary() -> list[str]:
    """R2 F-005 adopt: real preflight path + real test fixture paths."""
    violations: list[str] = []

    preflight = Path("backend/app/services/providers/preflight.py")
    if not preflight.exists():
        violations.append(
            f"VIOLATION reason_code=framework_intake_violation_secret_canary "
            f"evidence={preflight} detail=preflight_file_missing"
        )
    else:
        content = _read_text_or_none(preflight)
        if content is None or (
            "secret_canary" not in content and "provider_request_preflight" not in content
        ):
            violations.append(
                f"VIOLATION reason_code=framework_intake_violation_secret_canary "
                f"evidence={preflight} detail=canary_marker_missing"
            )

    canary_fixture = Path("tests/security/test_provider_preflight_canary.py")
    preflight_fixture = Path("tests/security/test_provider_request_preflight.py")
    if not canary_fixture.exists() or not preflight_fixture.exists():
        violations.append(
            f"VIOLATION reason_code=framework_intake_violation_secret_canary "
            f"evidence={canary_fixture},{preflight_fixture} detail=test_fixture_missing"
        )

    eval_dir = Path("eval/security/secret_canary")
    if not eval_dir.exists():
        violations.append(
            f"VIOLATION reason_code=framework_intake_violation_secret_canary "
            f"evidence={eval_dir} detail=eval_fixture_dir_missing"
        )

    return violations


def check_tenant_boundary() -> list[str]:
    """R2 F-004 adopt: Python scanner for AC-HARD-03 / tenant_isolation / cross_tenant marker."""
    violations: list[str] = []
    roots = (
        Path("tests/db"),
        Path("tests/repositories"),
        Path("eval/security/tenant_isolation"),
    )
    pattern = re.compile(r"AC-HARD-03|tenant_isolation|cross_tenant")

    found = False
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".json", ".md", ".toml", ".yml", ".yaml"}:
                continue
            content = _read_text_or_none(path)
            if content is None:
                continue
            if pattern.search(content):
                found = True
                break
        if found:
            break

    if not found:
        violations.append(
            "VIOLATION reason_code=framework_intake_violation_tenant_boundary "
            f"evidence={','.join(str(r) for r in roots)} detail=no_ac_hard_03_marker_found"
        )
    return violations


RULES: dict[str, Callable[[], list[str]]] = {
    "no_code_embed": check_no_code_embed,
    "persistence": check_persistence,
    "external_network": check_external_network,
    "telemetry": check_telemetry,
    "secret_canary": check_secret_canary,
    "tenant_boundary": check_tenant_boundary,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Framework intake scanner (#3-#8 verify rules)")
    parser.add_argument("--rule", choices=list(RULES.keys()), required=True)
    parser.add_argument(
        "--mode",
        choices=["diff-gate", "baseline-scan"],
        required=True,
        help="diff-gate=PR event / baseline-scan=push to main",
    )
    args = parser.parse_args()

    try:
        violations = RULES[args.rule]()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: scanner rule={args.rule} mode={args.mode} failed: {exc}", file=sys.stderr)
        return 2

    for line in violations:
        print(line)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
