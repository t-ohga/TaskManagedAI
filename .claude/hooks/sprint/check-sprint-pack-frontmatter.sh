#!/usr/bin/env bash
# Validate Sprint Pack frontmatter for TaskManagedAI Sprint Pack / ADR Gate discipline.
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

# project boundary guard (cross-project hook leak 防止、lib/common.sh § is_taskmanagedai_path)
if ! is_taskmanagedai_path "$file_path"; then
  exit 0
fi

rel_path="$(relative_file_path "$file_path")"
case "$rel_path" in
  docs/sprints/*.md) ;;
  *) exit 0 ;;
esac

base_name="$(basename "$rel_path")"
case "$base_name" in
  README.md|_template_*.md) exit 0 ;;
esac

abs_path="$(normalize_file_path "$file_path")"
if [ ! -f "$abs_path" ]; then
  exit 0
fi

content="$(cat "$abs_path")"
frontmatter="$(awk '
  BEGIN {seen=0; in_fm=0}
  /^---[[:space:]]*$/ {
    if (seen == 0) {seen=1; in_fm=1; next}
    if (in_fm == 1) {exit}
  }
  in_fm == 1 {print}
' "$abs_path")"

warnings=()

if [ -z "$frontmatter" ]; then
  warnings+=("frontmatter block is missing")
else
  required_keys=(id type status sprint_no target_days max_days)
  for key in "${required_keys[@]}"; do
    if ! printf '%s\n' "$frontmatter" | grep -Eq "^${key}:"; then
      warnings+=("frontmatter key '${key}' is missing")
    fi
  done

  pack_type="$(printf '%s\n' "$frontmatter" | awk -F: '/^type:/ {gsub(/[ "]/, "", $2); print $2; exit}')"
  if [ "$pack_type" != "light" ] && [ "$pack_type" != "heavy" ]; then
    warnings+=("frontmatter type must be light or heavy")
  fi

  if [ "$pack_type" = "heavy" ]; then
    for key in adr_refs planned_adr_refs risks; do
      if ! printf '%s\n' "$frontmatter" | grep -Eq "^${key}:"; then
        warnings+=("heavy Sprint Pack should include '${key}'")
      fi
    done
  fi

  adr_refs_has_items="$(
    printf '%s\n' "$frontmatter" | awk '
      /^adr_refs:/ {
        found=1
        rest=$0
        sub(/^[^:]+:[[:space:]]*/, "", rest)
        if (rest ~ /\[[^]]+\]/) {print "yes"; exit}
        if (rest ~ /\[\]/) {print "no"; exit}
        next
      }
      found && /^[^[:space:]-]/ {print "no"; exit}
      found && /^[[:space:]]*-/ {print "yes"; exit}
      END {if (!found) print "no"}
    ' | head -n 1
  )"

  if [ "$pack_type" = "heavy" ] && [ "$adr_refs_has_items" != "yes" ]; then
    if printf '%s\n' "$content" | grep -Eiq '認証|認可|DB schema|migration|migrations/|tenant_id|project boundary|複合 FK|API 契約|event schema|AI エージェント権限|MCP|tool 権限|Secrets|SecretBroker|secret_ref|外部公開|Funnel|public ingress|破壊的|広範囲|Provider|ProviderAdapter|GitHub App|payload_data_class|allowed_data_class|AgentRun|blocked_reason|Tailscale|runner|dangerous command|forbidden path'; then
      warnings+=("heavy Sprint Pack appears to hit ADR Gate Criteria but adr_refs is empty; keep planned_adr_refs only before ADR creation, then promote accepted/proposed ADRs into adr_refs")
    fi
  fi
fi

if [ "${#warnings[@]}" -gt 0 ]; then
  msg="WARN sprint-pack-frontmatter: ${rel_path}: $(join_by '; ' "${warnings[@]}"). refs: .claude/rules/sprint-pack-adr-gate.md §§2-5, .claude/agents/taskmanagedai/sprint-pack-reviewer.md."
  emit_system_message "PostToolUse" "$msg"
fi

exit 0

