#!/usr/bin/env bash
# stale-test-content-check.sh
# Wave 18 BL-WP018-004 移送 (refs: ADR-harness-consolidation [planned])
# source: reference_review_observations.md §1 stale test pattern
#
# file-changed hook で source code の `_RAW_SECRET_PATTERNS` / `_PROHIBITED_PAYLOAD_KEYS` 等
# constant 変更時、対応 test の `EXPECTED_*` / `len ==` 期待値 drift を WARN。
#
# exit 0 = pass / exit 1 = WARN (non-blocking) / exit 2 = BLOCK
set -euo pipefail
FILE_PATH="${1:-}"
[[ -z "$FILE_PATH" ]] && exit 0

# project boundary guard (lightweight、cross-project hook leak 防止)
# HBG-R1-003 + HBG-R1-004 + R2-001 fix: macOS /bin/realpath -m 非対応のため Python3 fallback
_fp_abs="$FILE_PATH"
if command -v python3 >/dev/null 2>&1; then
  _fp_resolved="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$FILE_PATH" 2>/dev/null || true)"
  [ -n "$_fp_resolved" ] && _fp_abs="$_fp_resolved"
elif command -v realpath >/dev/null 2>&1; then
  _fp_resolved="$(realpath -m "$FILE_PATH" 2>/dev/null || realpath "$FILE_PATH" 2>/dev/null || true)"
  [ -n "$_fp_resolved" ] && _fp_abs="$_fp_resolved"
fi
case "$_fp_abs" in
  */TaskManagedAI|*/TaskManagedAI/*|*/taskmanagedai|*/taskmanagedai/*) ;;
  *) exit 0 ;;
esac
unset _fp_abs _fp_resolved

# Wave 18 残実装で content 充実: constant grep + test EXPECTED_* drift check
echo "INFO stale-test-content-check: $FILE_PATH (skeleton、実装は Wave 18 残 session)" >&2
exit 0
