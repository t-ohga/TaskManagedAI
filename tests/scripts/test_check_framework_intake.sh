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
    # PR70 F-PR70-006 adopt: backend/app/repositories も PERSISTENCE_ROOTS、fixture でも作成
    mkdir -p backend/app/services/providers \
             backend/app/services/research \
             backend/app/adapters \
             backend/app/db \
             backend/app/repositories \
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

# ---- 9. test: clean PR (no dep changes) → SKIP ----
test_skip_no_deps_change() {
    local d="$TMPDIR_BASE/skip_no_deps_$$"
    setup_fake_repo "$d"
    # feature branch で何も変更しない
    run_script_pr
    assert_exit_code "$LAST_EXIT" 0 "skip_no_deps_change_exit0"
    assert_stdout_contains "SKIP" "skip_no_deps_change_msg"
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
test_skip_no_deps_change
test_clean_pass_with_known_dep
test_baseline_scan_clean
test_baseline_scan_detects_violation
test_comma_import_detection
test_frontend_side_effect_import
test_persistence_in_repositories
test_frontend_instrumentation_scanned
test_extractor_failure_propagates
test_baseline_scan_without_origin_main

echo ""
echo "== Summary =="
echo "passed: $TESTS_PASSED / failed: $TESTS_FAILED"
[ "$TESTS_FAILED" -eq 0 ]
