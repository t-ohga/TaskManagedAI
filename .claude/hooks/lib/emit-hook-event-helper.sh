#!/usr/bin/env bash
# TaskManagedAI hook event helper; silently emits to system hook-event logger when present.
#
# 入力: stdin で JSON (tool_input / tool_response 等)
# 出力: exit 0 で許可、exit 2 で BLOCK + ユーザーへ system message
# 詳細: https://docs.claude.com/en/docs/claude-code/hooks

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

emit_hook_event() {
  local domain="$1"
  local severity="$2"
  local rule_id="$3"
  local file_path="${4:-}"
  local message="${5:-}"
  local tool_name="${6:-${HOOK_TOOL_NAME:-}}"
  local emitter

  emitter="$SCRIPT_DIR/../system/emit-hook-event.sh"
  if [ ! -x "$emitter" ]; then
    return 0
  fi

  "$emitter" \
    --domain "$domain" \
    --severity "$severity" \
    --rule-id "$rule_id" \
    --file-path "$file_path" \
    --message "$message" \
    --tool-name "$tool_name" \
    2>/dev/null || true
}

