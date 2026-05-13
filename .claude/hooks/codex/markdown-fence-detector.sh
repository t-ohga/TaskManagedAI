#!/usr/bin/env bash
# markdown-fence-detector.sh
# Wave 18 BL-WP018-004 移送 (refs: ADR-harness-consolidation [planned])
# source: feedback_codex_multi_round_workflow.md §2 markdown fence 罠
#
# PostToolUse hook で `===FILE: ` 区切り Codex 出力 file の line 1 が
# ` ```python ` / ` ```json ` / ` ```bash ` 等 markdown fence なら BLOCK。
#
# 起動: PostToolUse for Write/Edit tool (TaskManagedAI .claude/settings.json で binding)
# exit 2 = BLOCK
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

[[ ! -f "$FILE_PATH" ]] && exit 0
line1=$(head -1 "$FILE_PATH" 2>/dev/null || echo "")
if [[ "$line1" =~ ^\`\`\`(python|json|bash|sh|markdown|yaml|toml|sql)?$ ]]; then
  echo "BLOCK: $FILE_PATH line 1 starts with markdown fence: $line1" >&2
  echo "Codex 出力で markdown fence が混入。先頭行を削除してください。" >&2
  exit 2
fi
exit 0
