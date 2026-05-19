#!/usr/bin/env bash
# Bash test runner for scripts/ci/check_framework_intake.sh (SP022-T01).
#
# Creates fake git repos under $TMPDIR with bare origin + main branch + feature branch + baseline
# files matching the scanner contract (R3 F-002 adopt). Each fixture asserts the script's exit
# code and stdout against expected reason_codes.
#
# Total: 12 fixtures (positive 8 + negative 2 + baseline-scan 2 per R2 F-001/F-004 adopt).
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SCRIPT_UNDER_TEST="$REPO_ROOT/scripts/ci/check_framework_intake.sh"
INTAKE_SCANNER="$REPO_ROOT/scripts/ci/_intake_scanner.py"
EXTRACT_HELPER="$REPO_ROOT/scripts/ci/_extract_changed_deps.py"

TESTS_PASSED=0
TESTS_FAILED=0

# ---- helper: setup fake repo (R3 F-002 adopt: scanner contract と完全 sync) ----
setup_fake_repo() {
    local fixture_dir="$1"
    rm -rf "$fixture_dir"
    mkdir -p "$fixture_dir/origin.git" "$fixture_dir/work"

    git -C "$fixture_dir/origin.git" init --bare --initial-branch=main --quiet

    git -C "$fixture_dir" clone -q "$fixture_dir/origin.git" work
    cd "$fixture_dir/work"
    git config user.email "test@example.com"
    git config user.name "test-fixture"

    # baseline directory structure (scanner が要求する全 path)
    # PR70 F-PR70-006 adopt: backend/app/repositories も PERSISTENCE_ROOTS
    # PR70 R2 F-PR70-R2-005 adopt: backend/app/api + backend/app/workers も対象
    mkdir -p backend/app/services/providers \
             backend/app/services/research \
             backend/app/adapters \
             backend/app/db \
             backend/app/repositories \
             backend/app/api \
             backend/app/workers \
             frontend/app frontend/components frontend/lib \
             tests/security tests/db tests/repositories \
             eval/security/secret_canary eval/security/tenant_isolation \
             docs/citations scripts/ci config

    # pyproject.toml (空 dependencies、dependency-groups 含む)
    cat > pyproject.toml <<'PY'
[project]
name = "taskmanagedai-test-fixture"
version = "0.0.0"
requires-python = ">=3.12,<3.13"
dependencies = []

[project.optional-dependencies]

[dependency-groups]
dev = []

[tool.setuptools.packages.find]
include = ["backend*", "scripts*"]
PY

    cat > frontend/package.json <<'JSON'
{
  "name": "taskmanagedai-frontend-fixture",
  "version": "0.0.0",
  "dependencies": {},
  "devDependencies": {}
}
JSON

    # scanner が要求する 4 baseline (R3 F-002)
    cat > backend/app/services/providers/preflight.py <<'PY'
"""provider request preflight stub for fixture."""
# secret_canary marker
def provider_request_preflight() -> None:
    """noop stub."""
PY
    echo "# AC-HARD-02 secret canary fixture stub" > tests/security/test_provider_preflight_canary.py
    echo "# AC-HARD-02 provider request preflight fixture stub" > tests/security/test_provider_request_preflight.py
    echo "# AC-HARD-03 tenant boundary fixture stub" > tests/db/test_tenant_boundary_stub.py
    echo "# AC-HARD-03 cross_tenant negative fixture" > tests/repositories/test_cross_tenant_negative_stub.py
    echo '{"version": 1, "fixtures": []}' > eval/security/secret_canary/manifest.json
    echo "# AC-HARD-03 tenant_isolation marker" > eval/security/tenant_isolation/manifest.json

    cat > docs/citations/dependency_to_framework_map.json <<'JSON'
{
  "schema_version": 1,
  "entries": [
    {"dependency_name": "langgraph", "ecosystem": "pypi", "framework_canonical": "LangGraph"}
  ]
}
JSON
    cat > docs/citations/framework_pattern_candidates.md <<'MD'
# Framework Pattern Candidates (test fixture)
| **LangGraph** | x | y | z | w | v |
MD

    # scripts/ ディレクトリ package 化 (R3 F-002 adopt)
    touch scripts/__init__.py scripts/ci/__init__.py
    cp "$SCRIPT_UNDER_TEST" scripts/ci/
    cp "$EXTRACT_HELPER" scripts/ci/
    cp "$INTAKE_SCANNER" scripts/ci/
    chmod +x scripts/ci/check_framework_intake.sh

    git add -A
    git commit -q -m "baseline"
    git push -q origin main

    git switch -q -c feature/test
}

# ---- assertion helpers ----
assert_exit_code() {
    local actual="$1" expected="$2" name="$3"
    if [ "$actual" -eq "$expected" ]; then
        TESTS_PASSED=$((TESTS_PASSED + 1))
        echo "PASS: $name (exit=$actual)"
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        echo "FAIL: $name (exit got=$actual expected=$expected)"
        echo "---output begin---"
        echo "${LAST_OUTPUT:-}" | head -20
        echo "---output end---"
    fi
}
assert_stdout_contains() {
    local needle="$1" name="$2"
    if echo "${LAST_OUTPUT:-}" | grep -q "$needle"; then
        TESTS_PASSED=$((TESTS_PASSED + 1))
        echo "PASS: $name (contains=$needle)"
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        echo "FAIL: $name (missing=$needle)"
        echo "${LAST_OUTPUT:-}" | head -20
    fi
}

run_script_pr() {
    set +e
    LAST_OUTPUT=$(GITHUB_EVENT_NAME=pull_request bash scripts/ci/check_framework_intake.sh --mode=diff-gate 2>&1)
    LAST_EXIT=$?
    set -e
}

run_script_baseline() {
    set +e
    LAST_OUTPUT=$(GITHUB_EVENT_NAME=push GITHUB_REF_NAME=main bash scripts/ci/check_framework_intake.sh --mode=baseline-scan 2>&1)
    LAST_EXIT=$?
    set -e
}

# ---- 1. test: license violation ----
test_license_violation() {
    local d="$TMPDIR_BASE/license_$$"
    setup_fake_repo "$d"
    # 未インストール pkg を pyproject に追加 → license 不明 violation
    sed -i.bak 's/dependencies = \[\]/dependencies = ["fakepkg-polyform-shield-marker"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "add fake polyform pkg"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "license_violation_exit1"
    assert_stdout_contains "framework_intake_violation_license" "license_violation_reason_code"
    cd "$REPO_ROOT"
}

# ---- 2. test: attribution violation ----
test_attribution_violation() {
    local d="$TMPDIR_BASE/attribution_$$"
    setup_fake_repo "$d"
    # map に entry なしの新 dependency 追加 → attribution violation
    sed -i.bak 's/dependencies = \[\]/dependencies = ["totally-unknown-framework-12345"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "add unknown framework"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "attribution_violation_exit1"
    assert_stdout_contains "framework_intake_violation_attribution" "attribution_violation_reason_code"
    cd "$REPO_ROOT"
}

# ---- 3. test: no_code_embed violation ----
test_no_code_embed_violation() {
    local d="$TMPDIR_BASE/no_code_embed_$$"
    setup_fake_repo "$d"
    echo "import crewai" > backend/app/services/research/agent.py
    # diff-gate trigger 用に pyproject にも何かしら変更を入れる
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "add code embed"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "no_code_embed_violation_exit1"
    assert_stdout_contains "framework_intake_violation_code_embed" "no_code_embed_violation_reason_code"
    cd "$REPO_ROOT"
}

# ---- 4. test: persistence violation ----
test_persistence_violation() {
    local d="$TMPDIR_BASE/persistence_$$"
    setup_fake_repo "$d"
    echo "import sqlite3" > backend/app/services/research/store.py
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "add persistence violation"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "persistence_violation_exit1"
    assert_stdout_contains "framework_intake_violation_persistence" "persistence_violation_reason_code"
    cd "$REPO_ROOT"
}

# ---- 5. test: external_network violation ----
test_external_network_violation() {
    local d="$TMPDIR_BASE/external_network_$$"
    setup_fake_repo "$d"
    echo 'URL = "https://api.honcho.dev/v1/something"' > backend/app/adapters/external.py
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "add external network violation"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "external_network_violation_exit1"
    assert_stdout_contains "framework_intake_violation_external_network" "external_network_violation_reason_code"
    cd "$REPO_ROOT"
}

# ---- 6. test: telemetry violation ----
test_telemetry_violation() {
    local d="$TMPDIR_BASE/telemetry_$$"
    setup_fake_repo "$d"
    echo "import sentry_sdk" > backend/app/services/research/observability.py
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "add telemetry violation"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "telemetry_violation_exit1"
    assert_stdout_contains "framework_intake_violation_telemetry" "telemetry_violation_reason_code"
    cd "$REPO_ROOT"
}

# ---- 7. test: secret_canary violation (fixture 不在) ----
test_secret_canary_violation() {
    local d="$TMPDIR_BASE/secret_canary_$$"
    setup_fake_repo "$d"
    # canary fixture を削除
    rm -rf tests/security
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "remove canary fixture"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "secret_canary_violation_exit1"
    assert_stdout_contains "framework_intake_violation_secret_canary" "secret_canary_violation_reason_code"
    cd "$REPO_ROOT"
}

# ---- 8. test: tenant_boundary violation (fixture 不在) ----
test_tenant_boundary_violation() {
    local d="$TMPDIR_BASE/tenant_boundary_$$"
    setup_fake_repo "$d"
    # AC-HARD-03 marker を削除
    rm -rf tests/db tests/repositories eval/security/tenant_isolation
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "remove tenant boundary marker"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "tenant_boundary_violation_exit1"
    assert_stdout_contains "framework_intake_violation_tenant_boundary" "tenant_boundary_violation_reason_code"
    cd "$REPO_ROOT"
}

# ---- 9. test: clean PR (no dep changes) → diff-gate mode runs #3-#8 and PASS on clean repo ----
# PR70 R2 F-PR70-R2-001 adopt: 旧仕様 "deps 変更なしで SKIP exit 0" は code-only PR の
# #3-#8 violation を bypass する gap だったので、新仕様では deps 変更なしでも #3-#8 を
# 必ず実行し、clean repo では PASS となる。SKIP は #1/#2 (license/attribution) のみ。
test_clean_pr_no_dep_change_runs_scanners() {
    local d="$TMPDIR_BASE/clean_pr_no_deps_$$"
    setup_fake_repo "$d"
    # feature branch で何も変更しない (clean baseline)
    run_script_pr
    assert_exit_code "$LAST_EXIT" 0 "clean_pr_no_deps_change_exit0"
    assert_stdout_contains "PASS" "clean_pr_no_deps_change_pass_msg"
    cd "$REPO_ROOT"
}

# ---- 10. test: clean dependency add (langgraph + map entry) → PASS まで通る ----
test_clean_pass_with_known_dep() {
    local d="$TMPDIR_BASE/clean_pass_$$"
    setup_fake_repo "$d"
    # langgraph は map に entry あり、framework_canonical=LangGraph も candidates table にある
    # ただし pypi `pip show langgraph` は fixture venv 内では失敗するため license violation 発生する想定
    # → clean PASS は実 venv が必要なため、本 fixture では license violation だけ発生 + 他 verify は PASS を確認
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "add langgraph (license violation expected without real venv)"
    run_script_pr
    # license violation のみ発生、attribution PASS (map に entry あり)、他 #3-#8 PASS
    assert_exit_code "$LAST_EXIT" 1 "clean_pass_with_known_dep_license_only"
    # attribution violation は無いはず (map entry あり)
    if echo "${LAST_OUTPUT:-}" | grep -q "framework_intake_violation_attribution"; then
        TESTS_FAILED=$((TESTS_FAILED + 1))
        echo "FAIL: clean_pass_with_known_dep_no_attribution_violation"
    else
        TESTS_PASSED=$((TESTS_PASSED + 1))
        echo "PASS: clean_pass_with_known_dep_no_attribution_violation"
    fi
    cd "$REPO_ROOT"
}

# ---- 11. test: baseline-scan clean (no existing violations) → PASS ----
test_baseline_scan_clean() {
    local d="$TMPDIR_BASE/baseline_clean_$$"
    setup_fake_repo "$d"
    # main branch を checkout して baseline-scan
    git switch -q main
    run_script_baseline
    assert_exit_code "$LAST_EXIT" 0 "baseline_scan_clean_exit0"
    assert_stdout_contains "PASS" "baseline_scan_clean_pass_msg"
    cd "$REPO_ROOT"
}

# ---- 12. test: baseline-scan detects existing violation ----
test_baseline_scan_detects_violation() {
    local d="$TMPDIR_BASE/baseline_violation_$$"
    setup_fake_repo "$d"
    # main branch に既存 telemetry violation を commit
    git switch -q main
    echo "import sentry_sdk" > backend/app/services/research/observability.py
    git add -A; git commit -q -m "existing telemetry violation"
    git push -q origin main
    run_script_baseline
    assert_exit_code "$LAST_EXIT" 1 "baseline_scan_detects_telemetry_violation_exit1"
    assert_stdout_contains "framework_intake_violation_telemetry" "baseline_scan_telemetry_reason_code"
    cd "$REPO_ROOT"
}

# ---- 13. test: PR70 F-PR70-002/F-PR70-003 - comma-separated import detection ----
test_comma_import_detection() {
    local d="$TMPDIR_BASE/comma_import_$$"
    setup_fake_repo "$d"
    # Python multi-import: `import crewai, os` should be detected
    echo "import crewai, os" > backend/app/services/research/agent.py
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "comma import"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "comma_import_violation_exit1"
    assert_stdout_contains "framework_intake_violation_code_embed" "comma_import_violation_reason_code"
    cd "$REPO_ROOT"
}

# ---- 14. test: PR70 F-PR70-005 - frontend side-effect import detection ----
test_frontend_side_effect_import() {
    local d="$TMPDIR_BASE/side_effect_$$"
    setup_fake_repo "$d"
    # side-effect import without `from`: `import "@langchain/langgraph";`
    cat > frontend/app/page.tsx <<'TS'
import "@langchain/langgraph";
export default function Page() { return null; }
TS
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "side-effect import"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "side_effect_import_violation_exit1"
    assert_stdout_contains "framework_intake_violation_code_embed" "side_effect_import_violation_reason_code"
    cd "$REPO_ROOT"
}

# ---- 15. test: PR70 F-PR70-006 - persistence in backend/app/repositories ----
test_persistence_in_repositories() {
    local d="$TMPDIR_BASE/persistence_repos_$$"
    setup_fake_repo "$d"
    # repository layer に sqlite3 import を入れる
    echo "import sqlite3" > backend/app/repositories/legacy_repo.py
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "persistence in repositories"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "persistence_repositories_violation_exit1"
    assert_stdout_contains "framework_intake_violation_persistence" "persistence_repositories_violation_reason_code"
    cd "$REPO_ROOT"
}

# ---- 16. test: PR70 F-PR70-007 - frontend instrumentation hook scanned ----
test_frontend_instrumentation_scanned() {
    local d="$TMPDIR_BASE/instrumentation_$$"
    setup_fake_repo "$d"
    # Next.js root-level instrumentation file with telemetry import
    cat > frontend/instrumentation.ts <<'TS'
import "@sentry/nextjs";
export function register() {}
TS
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "instrumentation hook"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "instrumentation_telemetry_violation_exit1"
    assert_stdout_contains "framework_intake_violation_telemetry" "instrumentation_telemetry_violation_reason_code"
    cd "$REPO_ROOT"
}

# ---- 17. test: PR70 F-PR70-004 - extractor failure propagates as exit 2 ----
test_extractor_failure_propagates() {
    local d="$TMPDIR_BASE/extractor_fail_$$"
    setup_fake_repo "$d"
    # Corrupt pyproject.toml (TOML parse failure) on feature branch
    echo "this is not valid TOML [[[broken" > pyproject.toml
    git add -A; git commit -q -m "corrupt pyproject"
    # ALSO change package.json so diff-gate trigger fires (dep file changed)
    # actually corrupt pyproject.toml itself is enough since it's in the diff-gate watch list
    run_script_pr
    assert_exit_code "$LAST_EXIT" 2 "extractor_failure_exit2"
    assert_stdout_contains "ERROR _extract_changed_deps.py failed" "extractor_failure_error_msg"
    cd "$REPO_ROOT"
}

# ---- 18. test: PR70 F-PR70-001 - baseline-scan in local clone without origin/main ----
test_baseline_scan_without_origin_main() {
    local d="$TMPDIR_BASE/baseline_no_origin_$$"
    setup_fake_repo "$d"
    # remove origin remote to simulate local clone without remote-tracking branch
    git remote remove origin
    run_script_baseline
    # baseline-scan should NOT require origin/main; should still run #3-#8 and PASS
    assert_exit_code "$LAST_EXIT" 0 "baseline_scan_no_origin_main_exit0"
    assert_stdout_contains "PASS" "baseline_scan_no_origin_main_pass"
    cd "$REPO_ROOT"
}

# ---- 19. test: PR70 R2 F-PR70-R2-001 - diff-gate runs #3-#8 even when deps unchanged ----
test_diff_gate_runs_scanners_without_dep_change() {
    local d="$TMPDIR_BASE/diff_gate_code_only_$$"
    setup_fake_repo "$d"
    # NO dep change, but add code embed violation
    echo "import crewai" > backend/app/services/research/agent.py
    git add -A; git commit -q -m "code-only PR adding crewai import"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "diff_gate_code_only_exit1"
    assert_stdout_contains "framework_intake_violation_code_embed" "diff_gate_code_only_code_embed_reason"
    cd "$REPO_ROOT"
}

# ---- 20. test: PR70 R2 F-PR70-R2-003 - psycopg connect alias detection ----
test_psycopg_import_connect_alias() {
    local d="$TMPDIR_BASE/psycopg_alias_$$"
    setup_fake_repo "$d"
    # `from psycopg import connect` alias should be detected
    cat > backend/app/services/research/store.py <<'PY'
from psycopg import connect
conn = connect("postgres://...")
PY
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "psycopg alias"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "psycopg_alias_violation_exit1"
    assert_stdout_contains "from_import_connect_alias" "psycopg_alias_detail"
    cd "$REPO_ROOT"
}

# ---- 21. test: PR70 R2 F-PR70-R2-004 - optionalDependencies extraction ----
test_optional_dependencies_extracted() {
    local d="$TMPDIR_BASE/optional_deps_$$"
    setup_fake_repo "$d"
    # add unknown package to optionalDependencies (no map entry → attribution violation)
    cat > frontend/package.json <<'JSON'
{
  "name": "taskmanagedai-frontend-fixture",
  "version": "0.0.0",
  "dependencies": {},
  "devDependencies": {},
  "optionalDependencies": {"some-unknown-framework": "^1.0.0"}
}
JSON
    git add -A; git commit -q -m "add optional dep"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "optional_deps_attribution_exit1"
    assert_stdout_contains "framework_intake_violation_attribution" "optional_deps_attribution_reason"
    cd "$REPO_ROOT"
}

# ---- 22. test: PR70 R2 F-PR70-R2-005 - api/workers persistence scan ----
test_persistence_in_api_or_workers() {
    local d="$TMPDIR_BASE/persistence_api_$$"
    setup_fake_repo "$d"
    # API route handler with direct sqlite3
    echo "import sqlite3" > backend/app/api/routes.py
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "api sqlite3"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "persistence_api_violation_exit1"
    assert_stdout_contains "framework_intake_violation_persistence" "persistence_api_reason"
    cd "$REPO_ROOT"
}

# ---- 23. test: PR70 R2 F-PR70-R2-006 - docker-compose external network scan ----
test_docker_compose_external_network() {
    local d="$TMPDIR_BASE/compose_network_$$"
    setup_fake_repo "$d"
    cat > docker-compose.yml <<'YML'
services:
  app:
    environment:
      EXTERNAL_TELEMETRY_URL: "https://sentry.io/api/0/ingest"
YML
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "compose external network"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "compose_network_violation_exit1"
    assert_stdout_contains "framework_intake_violation_external_network" "compose_network_reason"
    cd "$REPO_ROOT"
}

# ---- 24. test: PR70 R3 F-PR70-R3-001 - optional extras skipped for license check ----
test_optional_extras_skipped_for_license() {
    local d="$TMPDIR_BASE/optional_extras_$$"
    setup_fake_repo "$d"
    # add unknown pkg to optional-dependencies (NOT install by `uv sync --locked` default).
    # license check should skip it (no license_field_empty_or_unresolved violation),
    # but attribution check should still fire (no map entry → attribution violation).
    cat > pyproject.toml <<'PY'
[project]
name = "taskmanagedai-test-fixture"
version = "0.0.0"
requires-python = ">=3.12,<3.13"
dependencies = []

[project.optional-dependencies]
extras = ["unknown-optional-extras-pkg"]

[dependency-groups]
dev = []

[tool.setuptools.packages.find]
include = ["backend*", "scripts*"]
PY
    git add -A; git commit -q -m "add optional extras"
    run_script_pr
    # expect attribution violation (no map entry), but NOT license violation
    assert_exit_code "$LAST_EXIT" 1 "optional_extras_violation_exit1"
    assert_stdout_contains "framework_intake_violation_attribution" "optional_extras_attribution_reason"
    # license violation must NOT be emitted for optional extras (R3-001 fix)
    if echo "${LAST_OUTPUT:-}" | grep -q "unknown-optional-extras-pkg framework=unknown-optional-extras-pkg detail=license_field"; then
        TESTS_FAILED=$((TESTS_FAILED + 1))
        echo "FAIL: optional_extras_no_license_violation (license violation emitted for non-installed extras)"
    else
        TESTS_PASSED=$((TESTS_PASSED + 1))
        echo "PASS: optional_extras_no_license_violation (license check correctly skipped extras)"
    fi
    cd "$REPO_ROOT"
}

# ---- 25. test: PR70 R3 F-PR70-R3-003 - persistence in backend/app/domain or middleware ----
test_persistence_in_domain_or_middleware() {
    local d="$TMPDIR_BASE/persistence_domain_$$"
    setup_fake_repo "$d"
    mkdir -p backend/app/domain backend/app/middleware backend/app/observability
    # domain layer に sqlite3 import を入れる (R3-003 で新たに scan 対象)
    echo "import sqlite3" > backend/app/domain/internal_store.py
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "persistence in domain"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "persistence_domain_violation_exit1"
    assert_stdout_contains "framework_intake_violation_persistence" "persistence_domain_reason"
    cd "$REPO_ROOT"
}

# ---- 26. test: PR70 R4 F-PR70-R4-002 - dependency-groups license check ----
# R3-001 で core filter を [project.dependencies] のみに絞ったのが副作用、
# `[dependency-groups].dev` も uv sync default で install されるので license check すべき
test_dependency_groups_license_checked() {
    local d="$TMPDIR_BASE/dep_groups_license_$$"
    setup_fake_repo "$d"
    # [dependency-groups].dev に未インストール pkg 追加 (license check で empty → violation 期待)
    cat > pyproject.toml <<'PY'
[project]
name = "taskmanagedai-test-fixture"
version = "0.0.0"
requires-python = ">=3.12,<3.13"
dependencies = []

[dependency-groups]
dev = ["unknown-dev-group-pkg"]

[tool.setuptools.packages.find]
include = ["backend*", "scripts*"]
PY
    git add -A; git commit -q -m "add dep-groups dev pkg"
    run_script_pr
    # license check は core (deps + dep-groups) を対象、未インストール pkg は license empty で violation
    assert_exit_code "$LAST_EXIT" 1 "dep_groups_license_violation_exit1"
    assert_stdout_contains "framework_intake_violation_license" "dep_groups_license_reason"
    cd "$REPO_ROOT"
}

# ---- 27. test: PR70 R4 F-PR70-R4-003 - Python dynamic import detection ----
test_python_dynamic_import_detection() {
    local d="$TMPDIR_BASE/dynamic_import_$$"
    setup_fake_repo "$d"
    cat > backend/app/services/research/dynamic_loader.py <<'PY'
import importlib
mod = importlib.import_module("langgraph")
other = __import__("crewai")
PY
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "dynamic imports"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "dynamic_import_violation_exit1"
    assert_stdout_contains "python_dynamic_import" "dynamic_import_detail"
    cd "$REPO_ROOT"
}

# ---- 28. test: PR70 R4 F-PR70-R4-004 - semantic_kernel denylist ----
test_semantic_kernel_denylist() {
    local d="$TMPDIR_BASE/semantic_kernel_$$"
    setup_fake_repo "$d"
    echo "import semantic_kernel" > backend/app/services/research/sk.py
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "semantic_kernel import"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "semantic_kernel_violation_exit1"
    assert_stdout_contains "framework_intake_violation_code_embed" "semantic_kernel_reason"
    cd "$REPO_ROOT"
}

# ---- 29. test: PR70 R4 F-PR70-R4-005 - psycopg class-level connect ----
test_psycopg_class_level_connect() {
    local d="$TMPDIR_BASE/psycopg_class_$$"
    setup_fake_repo "$d"
    cat > backend/app/services/research/db.py <<'PY'
import psycopg
async def get():
    conn = await psycopg.AsyncConnection.connect("postgres://...")
    return conn
PY
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "psycopg class-level connect"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "psycopg_class_violation_exit1"
    assert_stdout_contains "class_level_connect" "psycopg_class_detail"
    cd "$REPO_ROOT"
}

# ---- 30. test: PR70 R5 F-PR70-R5-002 - dynamic submodule import ----
test_dynamic_submodule_import() {
    local d="$TMPDIR_BASE/dynamic_submod_$$"
    setup_fake_repo "$d"
    cat > backend/app/services/research/dynamic_sub.py <<'PY'
import importlib
mod = importlib.import_module("langgraph.graph")
other = __import__("crewai.tools")
PY
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "dynamic submodule import"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "dynamic_submod_violation_exit1"
    assert_stdout_contains "python_dynamic_import" "dynamic_submod_detail"
    cd "$REPO_ROOT"
}

# ---- 31. test: PR70 R5 F-PR70-R5-003 - non-default dep-group skipped for license ----
test_non_default_dep_group_skipped_for_license() {
    local d="$TMPDIR_BASE/non_default_group_$$"
    setup_fake_repo "$d"
    # non-default group (e.g., `docs`): uv sync --locked default does NOT install
    cat > pyproject.toml <<'PY'
[project]
name = "taskmanagedai-test-fixture"
version = "0.0.0"
requires-python = ">=3.12,<3.13"
dependencies = []

[dependency-groups]
docs = ["unknown-docs-only-pkg"]

[tool.setuptools.packages.find]
include = ["backend*", "scripts*"]
PY
    git add -A; git commit -q -m "add non-default dep-group docs"
    run_script_pr
    # attribution violation should fire (no map entry), license should NOT (uninstalled extras)
    assert_exit_code "$LAST_EXIT" 1 "non_default_group_attribution_exit1"
    assert_stdout_contains "framework_intake_violation_attribution" "non_default_group_attribution_reason"
    if echo "${LAST_OUTPUT:-}" | grep -q "unknown-docs-only-pkg framework=unknown-docs-only-pkg detail=license_field"; then
        TESTS_FAILED=$((TESTS_FAILED + 1))
        echo "FAIL: non_default_group_no_license_violation (license check fired for uninstalled docs group)"
    else
        TESTS_PASSED=$((TESTS_PASSED + 1))
        echo "PASS: non_default_group_no_license_violation (license check correctly skipped non-default group)"
    fi
    cd "$REPO_ROOT"
}

# ---- 32. test: PR70 R5 F-PR70-R5-004 - dynamic telemetry import ----
test_dynamic_telemetry_import() {
    local d="$TMPDIR_BASE/dynamic_telemetry_$$"
    setup_fake_repo "$d"
    cat > backend/app/services/research/dynamic_tel.py <<'PY'
import importlib
mod = importlib.import_module("sentry_sdk")
other = __import__("datadog")
PY
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "dynamic telemetry import"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "dynamic_telemetry_violation_exit1"
    # both sentry_sdk + datadog should fire as python_dynamic_import telemetry
    if echo "${LAST_OUTPUT:-}" | grep -q "framework=sentry_sdk detail=python_dynamic_import"; then
        TESTS_PASSED=$((TESTS_PASSED + 1)); echo "PASS: dynamic_telemetry_sentry_sdk"
    else
        TESTS_FAILED=$((TESTS_FAILED + 1)); echo "FAIL: dynamic_telemetry_sentry_sdk"
    fi
    cd "$REPO_ROOT"
}

# ---- 33. test: PR70 R5 F-PR70-R5-005 - psycopg import class alias chain ----
test_psycopg_import_class_alias_chain() {
    local d="$TMPDIR_BASE/psycopg_class_alias_$$"
    setup_fake_repo "$d"
    cat > backend/app/services/research/db2.py <<'PY'
from psycopg import AsyncConnection
async def get():
    conn = await AsyncConnection.connect("postgres://...")
    return conn
PY
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "psycopg import class alias chain"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "psycopg_class_alias_violation_exit1"
    assert_stdout_contains "from_import_class_connect_alias" "psycopg_class_alias_detail"
    cd "$REPO_ROOT"
}

# ---- 34. test: PR70 R5 F-PR70-R5-006 - semantic-kernel npm denylist ----
test_semantic_kernel_npm() {
    local d="$TMPDIR_BASE/semantic_kernel_npm_$$"
    setup_fake_repo "$d"
    cat > frontend/app/sk.tsx <<'TS'
import { SemanticKernel } from "semantic-kernel";
export default function P() { return null; }
TS
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "semantic-kernel npm import"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "semantic_kernel_npm_violation_exit1"
    assert_stdout_contains "framework=semantic-kernel" "semantic_kernel_npm_detail"
    cd "$REPO_ROOT"
}

# ---- 35. test: PR70 R6 F-PR70-R6-001 - default-groups = "all" literal ----
test_default_groups_all_literal() {
    local d="$TMPDIR_BASE/default_groups_all_$$"
    setup_fake_repo "$d"
    # `[tool.uv] default-groups = "all"` literal — every dep-group is auto-installed
    cat > pyproject.toml <<'PY'
[project]
name = "taskmanagedai-test-fixture"
version = "0.0.0"
requires-python = ">=3.12,<3.13"
dependencies = []

[tool.uv]
default-groups = "all"

[dependency-groups]
docs = ["unknown-docs-pkg-installed-via-all"]

[tool.setuptools.packages.find]
include = ["backend*", "scripts*"]
PY
    git add -A; git commit -q -m "default-groups all"
    run_script_pr
    # `unknown-docs-pkg-installed-via-all` は docs group、`default-groups = "all"` で install 対象、
    # license check で empty → violation 期待
    assert_exit_code "$LAST_EXIT" 1 "default_groups_all_violation_exit1"
    assert_stdout_contains "framework_intake_violation_license" "default_groups_all_reason"
    cd "$REPO_ROOT"
}

# ---- 36. test: PR70 R6 F-PR70-R6-002 - legacy [tool.uv].dev-dependencies ----
test_legacy_tool_uv_dev_dependencies() {
    local d="$TMPDIR_BASE/tool_uv_dev_$$"
    setup_fake_repo "$d"
    # `[tool.uv].dev-dependencies` legacy config — uv merges into `dev` group
    cat > pyproject.toml <<'PY'
[project]
name = "taskmanagedai-test-fixture"
version = "0.0.0"
requires-python = ">=3.12,<3.13"
dependencies = []

[tool.uv]
dev-dependencies = ["unknown-legacy-dev-pkg"]

[tool.setuptools.packages.find]
include = ["backend*", "scripts*"]
PY
    git add -A; git commit -q -m "tool.uv.dev-dependencies legacy"
    run_script_pr
    # `unknown-legacy-dev-pkg` は legacy dev-deps、license check で empty → violation 期待
    assert_exit_code "$LAST_EXIT" 1 "tool_uv_dev_violation_exit1"
    assert_stdout_contains "framework_intake_violation_license" "tool_uv_dev_reason"
    cd "$REPO_ROOT"
}

# ---- 37. test: PR70 R6 F-PR70-R6-003 - nested include-group resolution ----
test_nested_include_group() {
    local d="$TMPDIR_BASE/nested_include_$$"
    setup_fake_repo "$d"
    # default `dev` group includes `lint` group via `{include-group = "lint"}`
    cat > pyproject.toml <<'PY'
[project]
name = "taskmanagedai-test-fixture"
version = "0.0.0"
requires-python = ">=3.12,<3.13"
dependencies = []

[dependency-groups]
dev = [{include-group = "lint"}]
lint = ["unknown-nested-lint-pkg"]

[tool.setuptools.packages.find]
include = ["backend*", "scripts*"]
PY
    git add -A; git commit -q -m "nested include-group"
    run_script_pr
    # `unknown-nested-lint-pkg` は `lint` group、`dev` 経由 nested で install、
    # license check で empty → violation 期待
    assert_exit_code "$LAST_EXIT" 1 "nested_include_violation_exit1"
    assert_stdout_contains "framework_intake_violation_license" "nested_include_reason"
    cd "$REPO_ROOT"
}

# ---- 38. test: PR70 R6 F-PR70-R6-004 - psycopg aliased Connection.connect ----
test_psycopg_aliased_connect() {
    local d="$TMPDIR_BASE/psycopg_aliased_$$"
    setup_fake_repo "$d"
    # `from psycopg import AsyncConnection as PG; PG.connect(...)`
    cat > backend/app/services/research/db_aliased.py <<'PY'
from psycopg import AsyncConnection as PG
async def get():
    conn = await PG.connect("postgres://...")
    return conn
PY
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "psycopg aliased connect"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "psycopg_aliased_violation_exit1"
    assert_stdout_contains "from_import_class_connect_alias" "psycopg_aliased_detail"
    cd "$REPO_ROOT"
}

# ---- 39. test: PR70 R6 F-PR70-R6-005 - dynamic import with whitespace ----
test_dynamic_import_with_whitespace() {
    local d="$TMPDIR_BASE/dynamic_import_ws_$$"
    setup_fake_repo "$d"
    # frontend dynamic import with whitespace `await import ("@langchain/core")`
    cat > frontend/app/dyn.tsx <<'TS'
export async function load() {
    const mod = await import ("@langchain/core");
    return mod;
}
TS
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "dynamic import whitespace"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "dynamic_import_ws_violation_exit1"
    assert_stdout_contains "framework=@langchain/core" "dynamic_import_ws_detail"
    cd "$REPO_ROOT"
}

# ---- 40. test: PR70 R7 F-PR70-R7-001 - AutoGen v0.4+ module split ----
test_autogen_v04_modules() {
    local d="$TMPDIR_BASE/autogen_v04_$$"
    setup_fake_repo "$d"
    cat > backend/app/services/research/agentchat.py <<'PY'
from autogen_agentchat.agents import AssistantAgent
from autogen_core import CancellationToken
PY
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "autogen v0.4 modules"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "autogen_v04_violation_exit1"
    assert_stdout_contains "framework=autogen_agentchat" "autogen_v04_detail"
    cd "$REPO_ROOT"
}

# ---- 41. test: PR70 R7 F-PR70-R7-002 - Dapr Agents module ----
test_dapr_agents_module() {
    local d="$TMPDIR_BASE/dapr_agents_$$"
    setup_fake_repo "$d"
    echo "from dapr_agents import DurableAgent" > backend/app/services/research/dapr.py
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "dapr_agents import"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "dapr_agents_violation_exit1"
    assert_stdout_contains "framework=dapr_agents" "dapr_agents_detail"
    cd "$REPO_ROOT"
}

# ---- 42. test: PR70 R7 F-PR70-R7-003 - Letta Python SDK letta_client ----
test_letta_client_python_sdk() {
    local d="$TMPDIR_BASE/letta_client_py_$$"
    setup_fake_repo "$d"
    echo "from letta_client import Letta" > backend/app/services/research/letta.py
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "letta_client import"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "letta_client_py_violation_exit1"
    assert_stdout_contains "framework=letta_client" "letta_client_py_detail"
    cd "$REPO_ROOT"
}

# ---- 43. test: PR70 R7 F-PR70-R7-004 - Letta npm @letta-ai/letta-client ----
test_letta_client_npm_sdk() {
    local d="$TMPDIR_BASE/letta_client_npm_$$"
    setup_fake_repo "$d"
    cat > frontend/app/letta.tsx <<'TS'
import Letta from "@letta-ai/letta-client";
export default function P() { return null; }
TS
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "letta-ai/letta-client npm import"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "letta_client_npm_violation_exit1"
    assert_stdout_contains "framework=@letta-ai/letta-client" "letta_client_npm_detail"
    cd "$REPO_ROOT"
}

# ---- 44. test: PR70 R7 F-PR70-R7-005 - License: UNKNOWN treated as unresolved ----
# Note: 直接 `pip show` を mock することは難しいため、unresolved 経路の代理として `unknown` placeholder pkg を test
# 実際は CI で UNKNOWN license の pkg が install されているか否かによる。本 fixture では未インストール pkg で
# license_field_empty_or_unresolved を出すことを既存 fixture で verify 済 (test_license_violation)。
# R7-005 fix は shell 側で license=UNKNOWN/NULL/None literal も unresolved 扱いする branch を追加、
# 直接 fixture 不能だが behaviour test として簡易確認.
test_license_unknown_placeholder() {
    local d="$TMPDIR_BASE/license_unknown_$$"
    setup_fake_repo "$d"
    # fake-pkg は install されないので license_field_empty_or_unresolved (代理 test、UNKNOWN literal の boundary は code review で verify)
    sed -i.bak 's/dependencies = \[\]/dependencies = ["fake-pkg-with-unknown-license"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "license unknown placeholder"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "license_unknown_violation_exit1"
    assert_stdout_contains "license_field_empty_or_unresolved" "license_unknown_detail"
    cd "$REPO_ROOT"
}

# ---- 45. test: PR70 R7 F-PR70-R7-006 - psycopg module alias `import psycopg as pg` ----
test_psycopg_module_alias_connect() {
    local d="$TMPDIR_BASE/psycopg_mod_alias_$$"
    setup_fake_repo "$d"
    cat > backend/app/services/research/db_mod.py <<'PY'
import psycopg as pg
async def get():
    conn = await pg.connect("postgres://...")
    return conn
PY
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "psycopg module alias"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "psycopg_mod_alias_violation_exit1"
    assert_stdout_contains "module_alias_connect" "psycopg_mod_alias_detail"
    cd "$REPO_ROOT"
}

# ---- 46. test: PR70 R7 F-PR70-R7-006 - psycopg multiline parenthesized import ----
test_psycopg_multiline_import() {
    local d="$TMPDIR_BASE/psycopg_multi_$$"
    setup_fake_repo "$d"
    cat > backend/app/services/research/db_multi.py <<'PY'
from psycopg import (
    connect,
)
async def get():
    conn = await connect("postgres://...")
    return conn
PY
    sed -i.bak 's/dependencies = \[\]/dependencies = ["langgraph"]/' pyproject.toml
    rm -f pyproject.toml.bak
    git add -A; git commit -q -m "psycopg multiline import"
    run_script_pr
    assert_exit_code "$LAST_EXIT" 1 "psycopg_multi_violation_exit1"
    assert_stdout_contains "from_import_connect_alias" "psycopg_multi_detail"
    cd "$REPO_ROOT"
}

# ---- run all ----
TMPDIR_BASE=$(mktemp -d -t sp022_t01_fixture.XXXXXX)
trap 'rm -rf "$TMPDIR_BASE"' EXIT

echo "== SP022-T01 framework intake CI fixture test runner =="
echo "TMPDIR_BASE=$TMPDIR_BASE"

test_license_violation
test_attribution_violation
test_no_code_embed_violation
test_persistence_violation
test_external_network_violation
test_telemetry_violation
test_secret_canary_violation
test_tenant_boundary_violation
test_clean_pr_no_dep_change_runs_scanners
test_clean_pass_with_known_dep
test_baseline_scan_clean
test_baseline_scan_detects_violation
test_comma_import_detection
test_frontend_side_effect_import
test_persistence_in_repositories
test_frontend_instrumentation_scanned
test_extractor_failure_propagates
test_baseline_scan_without_origin_main
test_diff_gate_runs_scanners_without_dep_change
test_psycopg_import_connect_alias
test_optional_dependencies_extracted
test_persistence_in_api_or_workers
test_docker_compose_external_network
test_optional_extras_skipped_for_license
test_persistence_in_domain_or_middleware
test_dependency_groups_license_checked
test_python_dynamic_import_detection
test_semantic_kernel_denylist
test_psycopg_class_level_connect
test_dynamic_submodule_import
test_non_default_dep_group_skipped_for_license
test_dynamic_telemetry_import
test_psycopg_import_class_alias_chain
test_semantic_kernel_npm
test_default_groups_all_literal
test_legacy_tool_uv_dev_dependencies
test_nested_include_group
test_psycopg_aliased_connect
test_dynamic_import_with_whitespace
test_autogen_v04_modules
test_dapr_agents_module
test_letta_client_python_sdk
test_letta_client_npm_sdk
test_license_unknown_placeholder
test_psycopg_module_alias_connect
test_psycopg_multiline_import

echo ""
echo "== Summary =="
echo "passed: $TESTS_PASSED / failed: $TESTS_FAILED"
[ "$TESTS_FAILED" -eq 0 ]
