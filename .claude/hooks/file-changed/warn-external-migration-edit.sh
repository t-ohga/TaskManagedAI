#!/usr/bin/env bash
# Warn when edits touch external-impacting TaskManagedAI config, migrations, or CI workflows.
#
# 入力: stdin で JSON (tool_input / tool_response 等)
# 出力: exit 0 で許可、exit 2 で BLOCK + ユーザーへ system message
# 詳細: https://docs.claude.com/en/docs/claude-code/hooks

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

HOOK_EVENT_NAME="PostToolUse"
input="$(cat)"
if [ -z "${input//[[:space:]]/}" ]; then
  exit 0
fi

file_path="$(extract_file_path "$input")"
if [ -z "$file_path" ]; then
  exit 0
fi

rel_path="$(relative_file_path "$file_path")"

case "$rel_path" in
  config/provider_compliance.toml|migrations/*|backend/*/migrations/*|.github/workflows/*|.claude/reference/provider-compliance-matrix.md|docs/基本設計/04_セキュリティ_権限_監査設計.md)
    msg="WARN external-impact-edit: ${rel_path}: external/runtime-impacting file changed. Re-check Sprint Pack, ADR Gate, rollback, tests, and audit evidence before finalizing. Provider Matrix, migrations, and GitHub workflows can affect provider data transfer, DB integrity, CI permissions, and external execution. refs: .claude/rules/plan-review.md, .claude/reference/audit-ownership-matrix.md."
    emit_system_message "PostToolUse" "$msg"
    ;;
esac

exit 0

