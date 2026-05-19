#!/usr/bin/env bash
# Framework intake checklist (ADR-00020 §1-§3, SP022-T01).
#
# 2 modes (R1 F-001/F-004 + R2 F-001 adopt):
#   - diff-gate    : pull_request event、dependency 変更時のみ 8 verify 実行
#   - baseline-scan: push to main、dependency 変更無関係に #3-#8 を repo 全体 scan
#
# Exit codes:
#   0 = PASS / SKIP (no dep changes in diff-gate mode)
#   1 = violation found
#   2 = internal error (shallow checkout / base ref resolve failure / parse error / scanner crash)
set -euo pipefail

# ---- 0. mode determination ----
determine_mode() {
    for arg in "$@"; do
        case "$arg" in
            --mode=diff-gate)
                echo "diff-gate"
                return 0
                ;;
            --mode=baseline-scan)
                echo "baseline-scan"
                return 0
                ;;
        esac
    done
    if [ "${GITHUB_EVENT_NAME:-}" = "pull_request" ]; then
        echo "diff-gate"
    elif [ "${GITHUB_EVENT_NAME:-}" = "push" ] && [ "${GITHUB_REF_NAME:-}" = "main" ]; then
        echo "baseline-scan"
    else
        # local execution / other ref push: safe side (baseline-scan)
        echo "baseline-scan"
    fi
}
MODE=$(determine_mode "$@")

# ---- 1. emergency disable flag (R1 F-013 adopt) ----
# Repository/admin-controlled variable only.
# Set via .github/workflows/ci-smoke.yml `env.FRAMEWORK_INTAKE_CHECK_DISABLED:
# ${{ vars.FRAMEWORK_INTAKE_CHECK_DISABLED }}`. PR author cannot set this from
# diff alone; it must be flipped from the GitHub Settings -> Variables UI.
if [ "${FRAMEWORK_INTAKE_CHECK_DISABLED:-}" = "1" ]; then
    {
        echo "framework_intake_check: SKIP (emergency disable flag set, mode=$MODE)"
        echo "audit_marker: framework_intake_check_disabled_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "audit_marker: requires_retro_pack_within_24h=true"
    } >&2
    exit 0
fi

# ---- 2. base ref resolution (R2 F-001 adopt, shallow checkout guard) ----
if ! git rev-parse --verify origin/main >/dev/null 2>&1; then
    echo "framework_intake_check: ERROR origin/main not resolvable (shallow checkout?)" >&2
    echo "  hint: actions/checkout@v4 with fetch-depth: 0 required for diff-gate mode" >&2
    exit 2
fi

# ---- 3. diff-gate mode early exit ----
if [ "$MODE" = "diff-gate" ]; then
    if ! DEPS_CHANGED=$(git diff --name-only origin/main...HEAD -- \
        pyproject.toml uv.lock frontend/package.json frontend/pnpm-lock.yaml 2>&1); then
        echo "framework_intake_check: ERROR git diff failed (base resolve error): $DEPS_CHANGED" >&2
        exit 2
    fi
    if [ -z "$DEPS_CHANGED" ]; then
        echo "framework_intake_check: SKIP (mode=diff-gate, no dependency changes)"
        exit 0
    fi
fi

# ---- 4. violation collector ----
declare -a VIOLATIONS=()

# ---- 5. helper: changed direct deps ----
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
extract_changed_deps_pypi() {
    uv run --no-sync python "$SCRIPT_DIR/_extract_changed_deps.py" --ecosystem=pypi || true
}
extract_changed_deps_npm() {
    uv run --no-sync python "$SCRIPT_DIR/_extract_changed_deps.py" --ecosystem=npm || true
}

# ---- 6. verify item #1: License (diff-gate mode only, R2 F-002 + R3 F-001 adopt) ----
# `|| true` keeps script alive under `set -euo pipefail` when pip show / metadata fails;
# all empty-license cases are recorded as license_field_empty_or_unresolved violations.
check_license() {
    if [ "$MODE" = "baseline-scan" ]; then
        return 0
    fi
    local pkg license
    while IFS= read -r pkg; do
        [ -z "$pkg" ] && continue
        license=$(uv run --no-sync python -m pip show "$pkg" 2>/dev/null | awk -F': ' '/^License: /{print $2}' 2>/dev/null || true)
        if [ -z "$license" ]; then
            license=$(uv run --no-sync python -c "import importlib.metadata as m
try:
    md = m.metadata('$pkg')
    print((md.get('License-Expression') or md.get('License') or '').strip())
except Exception:
    pass" 2>/dev/null || true)
        fi
        if [ -z "$license" ]; then
            VIOLATIONS+=("VIOLATION reason_code=framework_intake_violation_license evidence=$pkg framework=$pkg detail=license_field_empty_or_unresolved")
            continue
        fi
        for denied in "polyform-shield" "polyform-perimeter" "polyform-noncommercial" "rus license" "sspl" "commons clause"; do
            if echo "$license" | grep -iq "$denied"; then
                VIOLATIONS+=("VIOLATION reason_code=framework_intake_violation_license evidence=$pkg framework=$pkg detail=$denied")
            fi
        done
    done < <(extract_changed_deps_pypi)
}

# ---- 7. verify item #2: Attribution (diff-gate mode only) ----
check_attribution() {
    if [ "$MODE" = "baseline-scan" ]; then
        return 0
    fi
    local map_file="docs/citations/dependency_to_framework_map.json"
    if [ ! -f "$map_file" ]; then
        VIOLATIONS+=("VIOLATION reason_code=framework_intake_violation_attribution evidence=$map_file detail=dep_to_framework_map_missing")
        return 0
    fi
    local pkg ecosystem framework_canonical
    for ecosystem in pypi npm; do
        if [ "$ecosystem" = "pypi" ]; then
            mapfile -t deps < <(extract_changed_deps_pypi)
        else
            mapfile -t deps < <(extract_changed_deps_npm)
        fi
        for pkg in "${deps[@]}"; do
            [ -z "$pkg" ] && continue
            framework_canonical=$(jq -r --arg p "$pkg" --arg e "$ecosystem" \
                '.entries[] | select(.dependency_name==$p and .ecosystem==$e) | .framework_canonical' \
                "$map_file")
            if [ -z "$framework_canonical" ]; then
                VIOLATIONS+=("VIOLATION reason_code=framework_intake_violation_attribution evidence=$pkg framework=$pkg detail=map_entry_missing_ecosystem=$ecosystem")
                continue
            fi
            if ! grep -qE "\\| \*\*${framework_canonical}\*\* \\|" docs/citations/framework_pattern_candidates.md 2>/dev/null; then
                VIOLATIONS+=("VIOLATION reason_code=framework_intake_violation_attribution evidence=$pkg framework=$framework_canonical detail=citation_table_missing")
            fi
        done
    done
}

# ---- 8. verify items #3-#8 (both modes, R2 F-004/F-005/F-006 adopt: Python scanner) ----
run_python_scan() {
    local rule_name="$1"
    local output
    local exit_code=0
    output=$(uv run --no-sync python -m scripts.ci._intake_scanner --rule="$rule_name" --mode="$MODE" 2>&1) || exit_code=$?
    case "$exit_code" in
        0)
            return 0
            ;;
        1)
            while IFS= read -r line; do
                [ -n "$line" ] && VIOLATIONS+=("$line")
            done <<< "$output"
            return 0
            ;;
        *)
            echo "framework_intake_check: ERROR scanner crashed for rule=$rule_name (exit=$exit_code)" >&2
            echo "$output" >&2
            exit 2
            ;;
    esac
}

check_no_code_embed() { run_python_scan no_code_embed; }
check_persistence() { run_python_scan persistence; }
check_external_network() { run_python_scan external_network; }
check_telemetry() { run_python_scan telemetry; }
check_secret_canary() { run_python_scan secret_canary; }
check_tenant_boundary() { run_python_scan tenant_boundary; }

# ---- 9. run all checks ----
check_license
check_attribution
check_no_code_embed
check_persistence
check_external_network
check_telemetry
check_secret_canary
check_tenant_boundary

# ---- 10. report ----
if [ ${#VIOLATIONS[@]} -gt 0 ]; then
    printf '%s\n' "${VIOLATIONS[@]}"
    echo "framework_intake_check: FAIL (${#VIOLATIONS[@]} violations, mode=$MODE)"
    exit 1
fi
echo "framework_intake_check: PASS (mode=$MODE)"
exit 0
