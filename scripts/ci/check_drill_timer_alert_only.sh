#!/usr/bin/env bash
# Drill timer alert-only enforcement (ADR-00021 §14.2 #4 PGA-F-013, SP022-T03).
#
# 2 modes (SP022-T01 PR #70 pattern 踏襲):
#   - diff-gate    : pull_request event、drill timer file 変更時のみ scan
#                    (R2 F-PR70-T03-R2-001: NUL byte は temp file 経由で scanner に渡す)
#   - baseline-scan: push to main、scope 限定 glob で repo 全 drill timer / cron file を scan
#
# Exit codes:
#   0 = PASS / SKIP (no changes in diff-gate)
#   1 = violation found
#   2 = internal error (shallow checkout / scanner crash / extractor failure)
set -euo pipefail

# ---- 0. mode determination ----
determine_mode() {
    for arg in "$@"; do
        case "$arg" in
            --mode=diff-gate) echo "diff-gate"; return 0 ;;
            --mode=baseline-scan) echo "baseline-scan"; return 0 ;;
        esac
    done
    if [ "${GITHUB_EVENT_NAME:-}" = "pull_request" ]; then
        echo "diff-gate"
    elif [ "${GITHUB_EVENT_NAME:-}" = "push" ] && [ "${GITHUB_REF_NAME:-}" = "main" ]; then
        echo "baseline-scan"
    else
        echo "baseline-scan"
    fi
}
MODE=$(determine_mode "$@")

# ---- 1. emergency disable flag (R1 F-010 adopt) ----
# Repository/admin-controlled variable only. workflow `if:` 条件で primary skip、shell 内
# defense-in-depth で二重 check (admin variable 経由のみ、PR author diff 設定不可).
if [ "${DRILL_TIMER_ALERT_ONLY_CHECK_DISABLED:-}" = "1" ]; then
    {
        echo "drill_timer_alert_only_check: SKIP (emergency disable flag set, mode=$MODE)"
        echo "audit_marker: drill_timer_alert_only_check_disabled_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "audit_marker: emergency_disable=true"
        echo "audit_marker: requires_retro_pack_within_24h=true"
        echo "audit_marker: ADR_PGA=ADR-00021-§14.2-#4-PGA-F-013"
    } >&2
    exit 0
fi

# ---- 2. diff-gate mode: base ref + changed-file extraction ----
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

if [ "$MODE" = "diff-gate" ]; then
    BASE_REF="${GITHUB_BASE_REF:-main}"
    if ! git rev-parse --verify "origin/${BASE_REF}" >/dev/null 2>&1; then
        echo "drill_timer_alert_only_check: ERROR origin/${BASE_REF} not resolvable (shallow checkout?)" >&2
        echo "  hint: actions/checkout@v4 with fetch-depth: 0 required for diff-gate mode" >&2
        exit 2
    fi
    # R2 F-PR70-T03-R2-001 adopt: NUL list は temp file 経由 (bash command substitution は NUL を潰す)
    CHANGED_FILE=$(mktemp -t drill_timer_changed.XXXXXX)
    trap 'rm -f "$CHANGED_FILE"' EXIT
    if ! git diff --name-only -z --diff-filter=ACMRD "origin/${BASE_REF}...HEAD" > "$CHANGED_FILE" 2>&1; then
        echo "drill_timer_alert_only_check: ERROR git diff failed" >&2
        cat "$CHANGED_FILE" >&2 || true
        exit 2
    fi
    if [ ! -s "$CHANGED_FILE" ]; then
        echo "drill_timer_alert_only_check: SKIP (mode=diff-gate, no file changes)"
        exit 0
    fi
    # Quick pre-filter: temp file の中に drill / timer / service / cron file 候補が含まれるか
    # (NUL list で `grep -z` する、含まれなければ scanner 起動せず SKIP)
    if ! grep -zE '(drill|\.timer|\.service|crontab|cron\.d)' "$CHANGED_FILE" >/dev/null 2>&1; then
        echo "drill_timer_alert_only_check: SKIP (mode=diff-gate, no drill timer / cron files changed)"
        exit 0
    fi
    set +e
    uv run --no-sync python -m scripts.ci._drill_timer_scanner \
        --mode=diff-gate --paths-from-file="$CHANGED_FILE"
    SCANNER_EXIT=$?
    set -e
    case "$SCANNER_EXIT" in
        0) echo "drill_timer_alert_only_check: PASS (mode=diff-gate)"; exit 0 ;;
        1) echo "drill_timer_alert_only_check: FAIL (mode=diff-gate)"; exit 1 ;;
        *) echo "drill_timer_alert_only_check: ERROR scanner crashed (exit=$SCANNER_EXIT)" >&2; exit 2 ;;
    esac
fi

# ---- 3. baseline-scan mode ----
set +e
uv run --no-sync python -m scripts.ci._drill_timer_scanner --mode=baseline-scan
SCANNER_EXIT=$?
set -e
case "$SCANNER_EXIT" in
    0) echo "drill_timer_alert_only_check: PASS (mode=baseline-scan)"; exit 0 ;;
    1) echo "drill_timer_alert_only_check: FAIL (mode=baseline-scan)"; exit 1 ;;
    *) echo "drill_timer_alert_only_check: ERROR scanner crashed (exit=$SCANNER_EXIT)" >&2; exit 2 ;;
esac
