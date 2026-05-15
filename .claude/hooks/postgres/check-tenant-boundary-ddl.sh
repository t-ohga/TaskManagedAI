#!/usr/bin/env bash
# Warn on PostgreSQL DDL that weakens TaskManagedAI tenant/project boundary invariants.
#
# 入力: stdin で JSON (tool_input / tool_response 等)
# 出力: exit 0 で許可、exit 2 で BLOCK + ユーザーへ system message
# 詳細: https://docs.claude.com/en/docs/claude-code/hooks

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

HOOK_EVENT_NAME="PostToolUse"

major_tables=(
  users
  actors
  principals
  workspaces
  projects
  repositories
  tickets
  ticket_relations
  acceptance_criteria
  research_tasks
  evidence_sources
  claims
  claim_evidence
  agent_runs
  agent_run_events
  artifacts
  context_snapshots
  secret_refs
  secret_capability_tokens
  audit_events
  notification_events
  policy_decisions
  approval_requests
  approval_events
  dataset_versions
  eval_runs
  eval_cases
  eval_scores
  budgets
)

sql_statements() {
  printf '%s\n' "$1" | awk '
    BEGIN { stmt = "" }
    {
      line = $0
      sub(/[[:space:]]*--.*/, "", line)
      for (i = 1; i <= length(line); i++) {
        ch = substr(line, i, 1)
        stmt = stmt ch
        if (ch == ";") {
          if (stmt ~ /[A-Za-z_]/) {
            printf "%s%c", stmt, 28
          }
          stmt = ""
        }
      }
      stmt = stmt "\n"
    }
    END {
      if (stmt ~ /[A-Za-z_]/) {
        printf "%s%c", stmt, 28
      }
    }
  '
}

normalize_sql_text() {
  tr '\n' ' ' \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/["`]+//g; s/[[:space:]]+/ /g; s/^[[:space:]]+//; s/[[:space:]]+$//'
}

statement_kind_from_norm() {
  local norm="$1"
  case "$norm" in
    *"create table "*|*"create unlogged table "*|*"create temporary table "*|*"create temp table "*) printf 'create' ;;
    *"alter table "*) printf 'alter' ;;
    *) printf '' ;;
  esac
}

table_name_from_statement() {
  local norm="$1"
  local after token

  case "$norm" in
    *"create unlogged table "*) after="${norm#*create unlogged table }" ;;
    *"create temporary table "*) after="${norm#*create temporary table }" ;;
    *"create temp table "*) after="${norm#*create temp table }" ;;
    *"create table "*) after="${norm#*create table }" ;;
    *"alter table "*) after="${norm#*alter table }" ;;
    *) return 0 ;;
  esac

  case "$after" in
    if\ not\ exists\ *) after="${after#if not exists }" ;;
    if\ exists\ *) after="${after#if exists }" ;;
  esac
  case "$after" in
    only\ *) after="${after#only }" ;;
  esac

  token="${after%% *}"
  token="${token%%(*}"
  token="${token%,}"
  token="${token%;}"
  token="${token##*.}"
  printf '%s' "$token"
}

is_major_table() {
  local table="$1"
  local item
  for item in "${major_tables[@]}"; do
    if [ "$item" = "$table" ]; then
      return 0
    fi
  done
  return 1
}

find_table_index() {
  local table="$1"
  local i
  for i in "${!tables[@]}"; do
    if [ "${tables[$i]}" = "$table" ]; then
      printf '%s' "$i"
      return 0
    fi
  done
  return 1
}

add_table_statement() {
  local table="$1"
  local kind="$2"
  local norm="$3"
  local idx

  idx="$(find_table_index "$table" || true)"
  if [ -z "$idx" ]; then
    idx="${#tables[@]}"
    tables+=("$table")
    table_sql+=("")
    table_created+=("no")
  fi

  table_sql[$idx]="${table_sql[$idx]} ${norm}"
  if [ "$kind" = "create" ]; then
    table_created[$idx]="yes"
  fi
}

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
  migrations/*|alembic/versions/*|backend/migrations/*|backend/*/migrations/*|backend/*/alembic/versions/*) ;;
  *) exit 0 ;;
esac

content="$(tool_content_or_file "$input" "$file_path")"
if ! printf '%s\n' "$content" | grep -Eiq 'create[[:space:]]+.*table|alter[[:space:]]+table|foreign[[:space:]]+key|references[[:space:]]+'; then
  exit 0
fi

warnings=()
tables=()
table_sql=()
table_created=()
record_sep="$(printf '\034')"

while IFS= read -r -d "$record_sep" stmt; do
  norm="$(printf '%s' "$stmt" | normalize_sql_text)"
  kind="$(statement_kind_from_norm "$norm")"
  if [ -z "$kind" ]; then
    continue
  fi

  table="$(table_name_from_statement "$norm")"
  if [ -z "$table" ]; then
    continue
  fi

  if is_major_table "$table"; then
    add_table_statement "$table" "$kind" "$norm"
  fi

  if [[ "$norm" =~ foreign[[:space:]]+key[[:space:]]*\([[:space:]]*([a-z_][a-z0-9_]*_id)[[:space:]]*\)[[:space:]]+references ]]; then
    fk_col="${BASH_REMATCH[1]}"
    if [ "$fk_col" != "tenant_id" ]; then
      warnings+=("${table}: single-column FK ${fk_col} detected; parent/child FK should include tenant_id")
    fi
  fi

  if [[ "$norm" =~ references[[:space:]]+([a-z_][a-z0-9_]*)[[:space:]]*\([[:space:]]*id[[:space:]]*\) ]]; then
    ref_table="${BASH_REMATCH[1]}"
    if [ "$ref_table" != "tenants" ]; then
      warnings+=("${table}: REFERENCES ${ref_table}(id) detected; TaskManagedAI FK should usually reference (tenant_id, id) or (tenant_id, project_id, id)")
    fi
  fi
done < <(sql_statements "$content")

for i in "${!tables[@]}"; do
  table="${tables[$i]}"
  combined="${table_sql[$i]}"

  if [ "${table_created[$i]}" != "yes" ]; then
    continue
  fi

  pattern_tenant='tenant_id[[:space:]]+bigint[[:space:]]+not[[:space:]]+null[[:space:]]+default[[:space:]]+1[^,)]*references[[:space:]]+tenants[[:space:]]*\([[:space:]]*id[[:space:]]*\)'
  if ! [[ "$combined" =~ $pattern_tenant ]]; then
    warnings+=("${table}: major table should include tenant_id bigint NOT NULL DEFAULT 1 REFERENCES tenants(id)")
  fi

  if ! [[ "$combined" =~ unique[[:space:]]*\([[:space:]]*tenant_id[[:space:]]*,[[:space:]]*id[[:space:]]*\) ]]; then
    warnings+=("${table}: major table should expose UNIQUE (tenant_id, id)")
  fi

  if [[ "$combined" =~ (^|[^a-z0-9_])project_id([^a-z0-9_]|$) ]] && ! [[ "$combined" =~ unique[[:space:]]*\([[:space:]]*tenant_id[[:space:]]*,[[:space:]]*project_id[[:space:]]*,[[:space:]]*id[[:space:]]*\) ]]; then
    warnings+=("${table}: project-boundary table should expose UNIQUE (tenant_id, project_id, id)")
  fi
done

if [ "${#warnings[@]}" -gt 0 ]; then
  msg="WARN postgres-tenant-boundary-ddl: ${rel_path}: $(join_by '; ' "${warnings[@]}"). refs: .claude/rules/core.md §8, .claude/reference/db-schema-notes.md §§1,3-4, .claude/agents/taskmanagedai/tenant-project-isolation-reviewer.md."
  emit_system_message "PostToolUse" "$msg"
fi

exit 0

