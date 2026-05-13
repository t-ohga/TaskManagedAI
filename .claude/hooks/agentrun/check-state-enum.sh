#!/usr/bin/env bash
# Check AgentRun status enum drift against the fixed 16 states and blocked_reason 3-subcategory contract.
#
# 入力: stdin で JSON (tool_input / tool_response 等)
# 出力: exit 0 で許可、exit 2 で BLOCK + ユーザーへ system message
# 詳細: https://docs.claude.com/en/docs/claude-code/hooks

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

HOOK_EVENT_NAME="PostToolUse"

expected_statuses=(
  queued
  gathering_context
  running
  generated_artifact
  schema_validated
  policy_linted
  diff_ready
  waiting_approval
  blocked
  provider_refused
  provider_incomplete
  validation_failed
  repair_exhausted
  completed
  failed
  cancelled
)

expected_blocked_reasons=(
  policy_blocked
  budget_blocked
  runtime_blocked
)

extract_enum_values() {
  local kind="$1"
  local content="$2"

  printf '%s\n' "$content" | awk -v kind="$kind" '
    function emit_literals(s,   rest, val) {
      rest = s
      while (match(rest, /'\''[a-z][a-z0-9_]*'\''/)) {
        val = substr(rest, RSTART + 1, RLENGTH - 2)
        print val
        rest = substr(rest, RSTART + RLENGTH)
      }

      rest = s
      while (match(rest, /"[a-z][a-z0-9_]*"/)) {
        val = substr(rest, RSTART + 1, RLENGTH - 2)
        print val
        rest = substr(rest, RSTART + RLENGTH)
      }
    }

    function start_py_status(low) {
      return low ~ /^[[:space:]]*class[[:space:]]+[a-z0-9_]*agentrunstatus[^:]*enum/
    }

    function start_py_blocked(low) {
      return low ~ /^[[:space:]]*class[[:space:]]+[a-z0-9_]*blockedreason[^:]*enum/
    }

    function start_ts_status(low) {
      return low ~ /^[[:space:]]*(export[[:space:]]+)?(type|enum|const)[[:space:]]+[a-z0-9_]*agentrunstatus/ || low ~ /agent_run_statuses/
    }

    function start_ts_blocked(low) {
      return low ~ /^[[:space:]]*(export[[:space:]]+)?(type|enum|const)[[:space:]]+[a-z0-9_]*blockedreason/ || low ~ /blocked_reasons/
    }

    function start_sql_status(low) {
      return low ~ /create[[:space:]]+type[[:space:]][a-z0-9_.]*agent_run_status[[:space:]]+as[[:space:]]+enum/
    }

    function start_sql_blocked(low) {
      return low ~ /create[[:space:]]+type[[:space:]][a-z0-9_.]*blocked_reason[[:space:]]+as[[:space:]]+enum/
    }

    function start_status_in(low) {
      return low ~ /status[^a-z0-9_]+in[[:space:]]*\(/ || low ~ /agent_runs_status_check[[:space:]]+check/
    }

    function start_blocked_in(low) {
      return low ~ /blocked_reason[^a-z0-9_]+in[[:space:]]*\(/ || low ~ /agent_runs_blocked_reason_check[[:space:]]+check/
    }

    {
      line = $0
      low = tolower(line)

      if (mode == "py") {
        if (line !~ /^[[:space:]]/ && line !~ /^[[:space:]]*$/) {
          mode = ""
        } else {
          emit_literals(line)
          next
        }
      }

      if (mode == "ts") {
        emit_literals(line)
        if (line ~ /[};\]][[:space:]]*;?[[:space:]]*$/) {
          mode = ""
        }
        next
      }

      if (mode == "sql_semicolon") {
        emit_literals(line)
        if (line ~ /;/) {
          mode = ""
        }
        next
      }

      if (mode == "sql_paren") {
        emit_literals(line)
        if (line ~ /\)/) {
          mode = ""
        }
        next
      }

      if (kind == "status") {
        if (start_py_status(low)) {
          mode = "py"
          emit_literals(line)
          next
        }
        if (start_ts_status(low)) {
          mode = "ts"
          emit_literals(line)
          if (line ~ /[};\]][[:space:]]*;?[[:space:]]*$/) {
            mode = ""
          }
          next
        }
        if (start_sql_status(low)) {
          mode = "sql_semicolon"
          emit_literals(line)
          if (line ~ /;/) {
            mode = ""
          }
          next
        }
        if (start_status_in(low)) {
          mode = "sql_paren"
          emit_literals(line)
          if (line ~ /\)/) {
            mode = ""
          }
          next
        }
      }

      if (kind == "blocked_reason") {
        if (start_py_blocked(low)) {
          mode = "py"
          emit_literals(line)
          next
        }
        if (start_ts_blocked(low)) {
          mode = "ts"
          emit_literals(line)
          if (line ~ /[};\]][[:space:]]*;?[[:space:]]*$/) {
            mode = ""
          }
          next
        }
        if (start_sql_blocked(low)) {
          mode = "sql_semicolon"
          emit_literals(line)
          if (line ~ /;/) {
            mode = ""
          }
          next
        }
        if (start_blocked_in(low)) {
          mode = "sql_paren"
          emit_literals(line)
          if (line ~ /\)/) {
            mode = ""
          }
          next
        }
      }
    }
  ' | sort -u
}

has_extracted_value() {
  local values="$1"
  local needle="$2"
  printf '%s\n' "$values" | grep -Fxq "$needle"
}

is_expected_status() {
  local value="$1"
  case "$value" in
    queued|gathering_context|running|generated_artifact|schema_validated|policy_linted|diff_ready|waiting_approval|blocked|provider_refused|provider_incomplete|validation_failed|repair_exhausted|completed|failed|cancelled) return 0 ;;
    *) return 1 ;;
  esac
}

is_expected_blocked_reason() {
  local value="$1"
  case "$value" in
    policy_blocked|budget_blocked|runtime_blocked) return 0 ;;
    *) return 1 ;;
  esac
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
  migrations/*|backend/*|frontend/*|docs/基本設計/*|docs/実装計画/*) ;;
  *) exit 0 ;;
esac

content="$(tool_content_or_file "$input" "$file_path")"
if ! printf '%s\n' "$content" | grep -Eiq 'AgentRun|agent_runs|agent_run_status|AgentRunStatus|blocked_reason'; then
  exit 0
fi

if ! printf '%s\n' "$content" | grep -Eiq 'enum|Enum|CREATE[[:space:]]+TYPE|CHECK|status|blocked_reason|type[[:space:]]+AgentRunStatus|interface[[:space:]]+AgentRunStatus'; then
  exit 0
fi

warnings=()
block_reasons=()

status_values="$(extract_enum_values "status" "$content")"
blocked_reason_values="$(extract_enum_values "blocked_reason" "$content")"

if [ -n "$status_values" ]; then
  missing_statuses=()
  extra_statuses=()

  for status in "${expected_statuses[@]}"; do
    if ! has_extracted_value "$status_values" "$status"; then
      missing_statuses+=("$status")
    fi
  done

  while IFS= read -r value; do
    if [ -z "$value" ]; then
      continue
    fi
    if ! is_expected_status "$value"; then
      extra_statuses+=("$value")
    fi
  done <<<"$status_values"

  if [ "${#extra_statuses[@]}" -gt 0 ]; then
    block_reasons+=("extra AgentRun status values: $(join_by ', ' "${extra_statuses[@]}")")
  fi
  if [ "${#missing_statuses[@]}" -gt 0 ]; then
    warnings+=("AgentRun status enum missing exact values: $(join_by ', ' "${missing_statuses[@]}")")
  fi
else
  warnings+=("AgentRun status enum/check/type signal found but enum values could not be extracted for exact-set comparison")
fi

if printf '%s\n' "$content" | grep -Eq 'blocked_reason|BlockedReason|blocked_reasons'; then
  if [ -n "$blocked_reason_values" ]; then
    missing_blocked_reasons=()
    extra_blocked_reasons=()

    for reason in "${expected_blocked_reasons[@]}"; do
      if ! has_extracted_value "$blocked_reason_values" "$reason"; then
        missing_blocked_reasons+=("$reason")
      fi
    done

    while IFS= read -r value; do
      if [ -z "$value" ] || [ "$value" = "blocked" ]; then
        continue
      fi
      if ! is_expected_blocked_reason "$value"; then
        extra_blocked_reasons+=("$value")
      fi
    done <<<"$blocked_reason_values"

    if [ "${#extra_blocked_reasons[@]}" -gt 0 ]; then
      block_reasons+=("extra blocked_reason values: $(join_by ', ' "${extra_blocked_reasons[@]}")")
    fi
    if [ "${#missing_blocked_reasons[@]}" -gt 0 ]; then
      warnings+=("blocked_reason enum missing exact values: $(join_by ', ' "${missing_blocked_reasons[@]}")")
    fi
  else
    warnings+=("blocked_reason signal found but enum values could not be extracted for exact-set comparison")
  fi

  if ! printf '%s\n' "$content" | grep -Eq "status[[:space:]]*(=|==)[[:space:]]*'blocked'|status[[:space:]]*(=|==)[[:space:]]*\"blocked\""; then
    warnings+=("blocked_reason consistency check missing status='blocked' positive branch")
  fi
  if ! printf '%s\n' "$content" | grep -Eq "status[[:space:]]*(<>|!=)[[:space:]]*'blocked'|status[[:space:]]*(<>|!=)[[:space:]]*\"blocked\""; then
    warnings+=("blocked_reason consistency check missing status<>'blocked' null branch")
  fi
fi

if [ "${#block_reasons[@]}" -gt 0 ]; then
  extra_msg="BLOCK agentrun-state-enum: ${rel_path}: $(join_by '; ' "${block_reasons[@]}")."
  if [ "${#warnings[@]}" -gt 0 ]; then
    extra_msg="${extra_msg} Additional exact-set warnings: $(join_by '; ' "${warnings[@]}")."
  fi
  block_with_message "PostToolUse" "${extra_msg} refs: .claude/rules/agentrun-state-machine.md §§1-3, .claude/reference/db-schema-notes.md §6."
fi

if [ "${#warnings[@]}" -gt 0 ]; then
  msg="WARN agentrun-state-enum: ${rel_path}: $(join_by '; ' "${warnings[@]}"). refs: .claude/rules/agentrun-state-machine.md §§1-3, .claude/reference/db-schema-notes.md §6."
  emit_system_message "PostToolUse" "$msg"
fi

exit 0

