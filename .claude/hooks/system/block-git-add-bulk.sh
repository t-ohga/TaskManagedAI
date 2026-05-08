#!/usr/bin/env bash
# Block bulk git staging so TaskManagedAI commits remain atomic and reviewable.
#
# 入力: stdin で JSON (tool_input / tool_response 等)
# 出力: exit 0 で許可、exit 2 で BLOCK + ユーザーへ system message
# 詳細: https://docs.claude.com/en/docs/claude-code/hooks

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

HOOK_EVENT_NAME="PreToolUse"
input="$(cat)"
if [ -z "${input//[[:space:]]/}" ]; then
  exit 0
fi

command="$(extract_bash_command "$input")"
if [ -z "$command" ]; then
  exit 0
fi

if printf '%s\n' "$command" | grep -Eq '(^|[;&|[:space:]])git[[:space:]]+add[[:space:]]+(-A|--all|\.)([[:space:]]|$)'; then
  block_with_message "PreToolUse" "BLOCK git-add-bulk: TaskManagedAI では git add -A / git add . / git add --all を禁止します。理由: .claude/CLAUDE.md §6 と Git 運用ルールにより、別 Sprint / 別判断の差分混入を防ぐためです。必要なファイルを個別指定してください。"
fi

exit 0

