#!/usr/bin/env bash
# Warn when ADR Gate Criteria files are edited without a corresponding TaskManagedAI ADR reference.
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
case "$rel_path" in
  docs/adr/*) exit 0 ;;
esac

# shellcheck disable=SC2034  # diagnostics 出力用に保持
abs_path="$(normalize_file_path "$file_path")"
content="$(tool_content_or_file "$input" "$file_path")"
root="$(project_root)"
expected=()

add_expected() {
  local adr="$1"
  local item
  for item in "${expected[@]:-}"; do
    [ "$item" = "$adr" ] && return 0
  done
  expected+=("$adr")
}

case "$rel_path" in
  migrations/*|backend/*/migrations/*) add_expected "00002" ;;
  config/provider_compliance.toml) add_expected "00010" ;;
  .github/workflows/*) add_expected "00003"; add_expected "00011" ;;
  *auth*|*rbac*|*actor*|*principal*|*approval*) add_expected "00001" ;;
  *openapi*|*api*|*event_schema*) add_expected "00003" ;;
  *agent*permission*|*trusted_instruction*|*action_class*) add_expected "00004" ;;
  *mcp*|*tool*registry*|*tool_mutating_gateway*) add_expected "00005" ;;
  *[Ss]ecret*) add_expected "00006" ;;
  *tailscale*|*tailnet*|*grants*|*funnel*|*network*) add_expected "00007" ;;
  *github*app*|*installation*permission*) add_expected "00011" ;;
esac

if printf '%s\n' "$content" | grep -Eiq 'drop[[:space:]]+table|drop[[:space:]]+column|truncate[[:space:]]+|delete[[:space:]]+from|alter[[:space:]]+table|migration|data move|tenant data'; then
  add_expected "00008"
fi

if printf '%s\n' "$content" | grep -Eiq 'payload_data_class|allowed_data_class|ProviderAdapter|provider_compliance|provider_request_preflight'; then
  add_expected "00010"
fi

if printf '%s\n' "$content" | grep -Eiq 'SecretBroker|secret_ref|secret_capability_tokens|capability token|atomic claim'; then
  add_expected "00006"
fi

if [ "${#expected[@]}" -eq 0 ]; then
  exit 0
fi

warnings=()
for adr in "${expected[@]}"; do
  if ! ls "$root/docs/adr/${adr}_"*.md >/dev/null 2>&1; then
    warnings+=("expected docs/adr/${adr}_*.md for ADR-${adr}")
  fi
done

if ! printf '%s\n' "$content" | grep -Eq 'ADR-[0-9]{5}|docs/adr/[0-9]{5}_'; then
  warnings+=("edited file does not reference an ADR")
fi

if [ "${#warnings[@]}" -gt 0 ]; then
  msg="WARN adr-gate: ${rel_path}: $(join_by '; ' "${warnings[@]}"). ADR Gate Criteria 11 種に該当する変更は実装前 ADR が必要です。refs: .claude/rules/sprint-pack-adr-gate.md §4, .claude/reference/audit-ownership-matrix.md §4."
  emit_system_message "PostToolUse" "$msg"
fi

exit 0

