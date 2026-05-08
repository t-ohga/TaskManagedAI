#!/usr/bin/env bash
# TaskManagedAI hook common helpers: JSON parsing, message emitters, path helpers, and exit-code conventions.
#
# 入力: stdin で JSON (tool_input / tool_response 等)
# 出力: exit 0 で許可、exit 2 で BLOCK + ユーザーへ system message
# 詳細: https://docs.claude.com/en/docs/claude-code/hooks

set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
  printf '[HOOK ERROR] jq is required for TaskManagedAI Claude hooks.\n' >&2
  exit 1
fi

HOOK_EVENT_NAME="${HOOK_EVENT_NAME:-PostToolUse}"

truncate_msg() {
  local msg="$1"
  local max="${2:-700}"
  if [ "${#msg}" -gt "$max" ]; then
    printf '%s... (truncated)' "${msg:0:$max}"
  else
    printf '%s' "$msg"
  fi
}

script_dir() {
  local src="${BASH_SOURCE[1]:-$0}"
  cd "$(dirname "$src")" && pwd
}

project_root() {
  if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
    printf '%s' "$CLAUDE_PROJECT_DIR"
  elif git rev-parse --show-toplevel >/dev/null 2>&1; then
    git rev-parse --show-toplevel
  else
    pwd
  fi
}

extract_file_path() {
  jq -r '.tool_input.file_path // .tool_input.path // empty' <<<"$1"
}

extract_bash_command() {
  jq -r '.tool_input.command // empty' <<<"$1"
}

extract_tool_name() {
  jq -r '.tool_name // empty' <<<"$1"
}

extract_tool_content() {
  jq -r '.tool_input.content // empty' <<<"$1"
}

normalize_file_path() {
  local file_path="$1"
  local root
  root="$(project_root)"

  if [ -z "$file_path" ]; then
    return 0
  fi

  if [[ "$file_path" = /* ]]; then
    printf '%s' "$file_path"
  else
    printf '%s/%s' "$root" "$file_path"
  fi
}

relative_file_path() {
  local file_path="$1"
  local root abs
  root="$(project_root)"
  abs="$(normalize_file_path "$file_path")"

  case "$abs" in
    "$root"/*) printf '%s' "${abs#"$root"/}" ;;
    "$root") printf '.' ;;
    *) printf '%s' "$file_path" ;;
  esac
}

read_file_if_exists() {
  local file_path="$1"
  local abs
  abs="$(normalize_file_path "$file_path")"
  if [ -f "$abs" ]; then
    cat "$abs"
  fi
}

tool_content_or_file() {
  local input="$1"
  local file_path="$2"
  local direct
  direct="$(extract_tool_content "$input")"

  if [ -n "$direct" ]; then
    printf '%s' "$direct"
  elif [ -n "$file_path" ]; then
    read_file_if_exists "$file_path"
  fi
}

join_by() {
  local sep="$1"
  shift || true
  local out=""
  local item
  for item in "$@"; do
    if [ -z "$out" ]; then
      out="$item"
    else
      out="${out}${sep}${item}"
    fi
  done
  printf '%s' "$out"
}

emit_system_message() {
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
      systemMessage: $msg,
      hookSpecificOutput: {hookEventName: $event}
    }'
}

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

block_with_message() {
  local event msg
  if [ "$#" -eq 1 ]; then
    event="${HOOK_EVENT_NAME:-PreToolUse}"
    msg="$1"
  else
    event="$1"
    msg="$2"
  fi

  emit_system_message "$event" "$msg"
  printf '%s\n' "$msg" >&2
  exit 2
}

emit_hook_event() {
  local domain="$1"
  local severity="$2"
  local rule_id="$3"
  local file_path="${4:-}"
  local message="${5:-}"
  local tool_name="${6:-${HOOK_TOOL_NAME:-}}"
  local emitter

  emitter="$(dirname "${BASH_SOURCE[0]}")/../system/emit-hook-event.sh"
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

