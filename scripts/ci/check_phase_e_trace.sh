#!/usr/bin/env bash
# Phase E adversarial closure trace audit (SP022-T04, ADR-00020 audit-only gate).
#
# This wrapper invokes the Python verifier against
# `docs/sprints/SP-022_framework_intake_hardening.md` to ensure the
# `## Phase E adversarial closure trace` section matrix continues to cover all
# 16 findings (PE-F-001〜PE-F-016) with the expected 5-column schema, per-row
# owning sprint mapping, and PE-F-010 closure marker.
#
# Only one mode is supported: `baseline-scan` (PR diff trigger 不要、毎 CI run
# で SP-022 Pack の trace matrix structural integrity を確認).
#
# Exit codes:
#   0 = PASS / SKIP (emergency disable)
#   1 = violation found
#   2 = internal error (scanner crash)
set -euo pipefail

# ---- 1. emergency disable flag (R1-F-008 adopt) ----
# Repository/admin-controlled variable only. workflow `if:` 条件で primary skip、
# shell 内 defense-in-depth で二重 check (admin variable 経由のみ).
if [ "${PHASE_E_TRACE_CHECK_DISABLED:-}" = "1" ]; then
    echo "phase_e_trace_check: SKIP disabled_by=PHASE_E_TRACE_CHECK_DISABLED"
    {
        echo "audit_marker: phase_e_trace_check_disabled_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "audit_marker: emergency_disable=true"
        echo "audit_marker: requires_retro_pack_within_24h=true"
        echo "audit_marker: ADR=ADR-00020"
    } >&2
    exit 0
fi

# ---- 2. baseline-scan ----
set +e
uv run --no-sync python -m scripts.ci._phase_e_trace_verifier --mode=baseline-scan
SCANNER_EXIT=$?
set -e

case "$SCANNER_EXIT" in
    0) echo "phase_e_trace_check: PASS (mode=baseline-scan)"; exit 0 ;;
    1) echo "phase_e_trace_check: FAIL (mode=baseline-scan)"; exit 1 ;;
    *) echo "phase_e_trace_check: ERROR scanner crashed (exit=$SCANNER_EXIT)" >&2; exit 2 ;;
esac
