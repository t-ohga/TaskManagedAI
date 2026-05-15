#!/usr/bin/env bash
# Warn that runner allowlist/denylist changes require AC-HARD-05/06 fixture updates.
#
# 入力: stdin で JSON (tool_input / tool_response 等)
# 出力: exit 0 で許可、exit 2 で BLOCK + ユーザーへ system message
# 詳細: https://docs.claude.com/en/docs/claude-code/hooks

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/../lib/common.sh"

# shellcheck disable=SC2034  # 共通 lib helper が参照
export HOOK_EVENT_NAME="PostToolUse"
input="$(cat)"
if [ -z "${input//[[:space:]]/}" ]; then
  exit 0
fi

file_path="$(extract_file_path "$input")"
if [ -z "$file_path" ]; then
  exit 0
fi

# project boundary guard (cross-project hook leak 防止、lib/common.sh § is_taskmanagedai_path)
if ! is_taskmanagedai_path "$file_path"; then
  exit 0
fi

rel_path="$(relative_file_path "$file_path")"
content="$(tool_content_or_file "$input" "$file_path")"

target="no"
case "$rel_path" in
  config/runner/*|backend/*[Rr]unner*|eval/security/dangerous_command/*|eval/security/forbidden_path/*) target="yes" ;;
esac

if printf '%s\n' "$content" | grep -Eiq 'runner_mutation_gateway|dangerous_command|forbidden_path|command allowlist|command denylist|allowlist|denylist|resource cap'; then
  target="yes"
fi

if [ "$target" != "yes" ]; then
  exit 0
fi

msg="WARN runner-dangerous-command-fixture: ${rel_path}: runner allowlist/denylist or gateway boundary changed. Update or review AC-HARD-05 forbidden_path and AC-HARD-06 dangerous_command fixtures; include rm -rf, curl|sh, fork bomb (:(){ :|:& };:), chmod 777, Docker socket/privileged/host-network cases where applicable. This hook is a reminder only; final Hard Gate judgment is fixture-based eval. refs: .claude/reference/hard-gates-and-kpis.md §§2-3, .claude/agents/taskmanagedai/runner-security-reviewer.md."
emit_system_message "PostToolUse" "$msg"

exit 0

