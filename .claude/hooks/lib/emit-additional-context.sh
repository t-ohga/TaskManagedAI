#!/usr/bin/env bash
# TaskManagedAI additionalContext emit helper for Claude Code hooks.
#
# 入力: stdin で JSON (tool_input / tool_response 等)
# 出力: exit 0 で許可、exit 2 で BLOCK + ユーザーへ system message
# 詳細: https://docs.claude.com/en/docs/claude-code/hooks

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

emit_additional_context() {
  local event msg
  if [ "$#" -eq 1 ]; then
    event="${HOOK_EVENT_NAME:-PostToolUse}"
    msg="$1"
  else
    event="$1"
    msg="$2"
  fi

  jq -n \
    --arg event "$event" \
    --arg msg "$(truncate_msg "$msg")" \
    '{
      hookSpecificOutput: {
        hookEventName: $event,
        additionalContext: $msg
      }
    }'
}

