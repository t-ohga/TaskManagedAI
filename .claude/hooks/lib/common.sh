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

# is_taskmanagedai_path: project boundary guard
# TaskManagedAI worktree 外の file_path に対しては 1 を返す (hook を no-op で exit させる)
# - 別 project (ieshima-edu 等) session から TaskManagedAI hook が誤発火するのを防ぐ
# - **CRITICAL design (HBG-R1-001 + HBG-R1-002 fix)**: project_root prefix match は使わない
#   (caller の current project_root は漏出先 project であり得るため、TaskManagedAI 配下と誤判定する)
# - 判定は **TaskManagedAI / taskmanagedai path segment match のみ** で行う (`/foo/notes/TaskManagedAI-summary.md`
#   のような filename substring は path segment 単位 match では false、TaskManagedAI directory 配下のみ true)
# - **HBG-R1-004 fix**: symlink を realpath で canonicalize してから match
# - 空 path は安全側 (0 = no-op return) で fall-through、caller 側で別判定
#
# 使用例: hook 冒頭で
#   file_path="$(extract_file_path "$input")"
#   if [ -n "$file_path" ] && ! is_taskmanagedai_path "$file_path"; then exit 0; fi
is_taskmanagedai_path() {
  local file_path="$1"
  local abs resolved

  # 空 path は no-op (caller 側で別判定)
  if [ -z "$file_path" ]; then
    return 0
  fi

  abs="$(normalize_file_path "$file_path")"

  # symlink resolve (HBG-R1-004 + R2-001 fix): macOS の /bin/realpath は -m 非対応のため
  # Python3 経由で `os.path.realpath` を使う (macOS / Linux 双方対応、missing path / symlink 共に canonical 化)
  # python3 が無い環境では GNU realpath (-m 対応) を fallback、両方無ければ raw path で fall-through
  if command -v python3 >/dev/null 2>&1; then
    resolved="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$abs" 2>/dev/null || true)"
  elif command -v realpath >/dev/null 2>&1; then
    resolved="$(realpath -m "$abs" 2>/dev/null || realpath "$abs" 2>/dev/null || true)"
  else
    resolved=""
  fi
  if [ -n "$resolved" ]; then
    abs="$resolved"
  fi

  # path segment 単位の TaskManagedAI / taskmanagedai match
  # (filename substring の偶発 match を避けるため `/` 区切りを必須にする)
  case "$abs" in
    */TaskManagedAI|*/TaskManagedAI/*|*/taskmanagedai|*/taskmanagedai/*)
      return 0
      ;;
  esac

  return 1
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

