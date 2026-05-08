#!/usr/bin/env bash
# Check SecretBroker DDL for raw secret storage and capability-token atomic-claim invariants.
#
# 入力: stdin で JSON (tool_input / tool_response 等)
# 出力: exit 0 で許可、exit 2 で BLOCK + ユーザーへ system message
# 詳細: https://docs.claude.com/en/docs/claude-code/hooks

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

HOOK_EVENT_NAME="PostToolUse"

secretbroker_hook_target() {
  local rel="$1"
  case "$rel" in
    migrations/*|alembic/versions/*|backend/migrations/*|backend/*/migrations/*|backend/*/alembic/versions/*) return 0 ;;
    backend/*[sS]ecret*|backend/*[tT]oken*|backend/*[aA]uth*|backend/*[cC]redential*|backend/*[kK]ey*|backend/*[bB]roker*) return 0 ;;
    *) return 1 ;;
  esac
}

raw_secret_scan_target() {
  secretbroker_hook_target "$1"
}

raw_secret_column_hits() {
  printf '%s\n' "$1" | awk '
    BEGIN {
      terms = "api_key apikey secret_key secretkey private_key privatekey password passphrase access_token accesstoken bearer_token bearertoken client_secret clientsecret auth_token authtoken"
      n = split(terms, term_list, " ")
      type_re = "(text|varchar|character[[:space:]]+varying|bytea|uuid|jsonb|string)"
    }
    {
      line = $0
      sub(/[[:space:]]*--.*/, "", line)
      norm = tolower(line)
      gsub(/["`]/, "", norm)
      gsub(/\[/, "", norm)
      gsub(/\]/, "", norm)
      gsub(/[[:space:]]+/, " ", norm)

      for (i = 1; i <= n; i++) {
        term = term_list[i]
        ddl_re = "(^|[^a-z0-9_])" term "[[:space:]]+" type_re "([[:space:]]|\\(|\\)|,|;|$)"
        add_re = "add[[:space:]]+column([[:space:]]+if[[:space:]]+not[[:space:]]+exists)?[[:space:]]+" term "[[:space:]]+" type_re
        orm_re = "(^|[^a-z0-9_])" term "[[:space:]]*[:=][^#]*(column|mapped_column|sa\\.column)[^#]*(text|string|varchar|bytea|uuid|jsonb)"
        orm_re2 = "(column|mapped_column|sa\\.column)[[:space:]]*\\([[:space:]]*" term "[[:space:]]*,[^#]*(text|string|varchar|bytea|uuid|jsonb)"

        if (norm ~ ddl_re || norm ~ add_re || norm ~ orm_re || norm ~ orm_re2) {
          print "line " NR " column " term
          break
        }
      }
    }
  '
}

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

atomic_claim_warnings() {
  local content="$1"
  local record_sep
  local stmt norm update_count complete_claim redeem_signal
  record_sep="$(printf '\034')"
  update_count=0
  complete_claim=0
  redeem_signal="no"

  if printf '%s\n' "$content" | grep -Eiq 'redeem|one-time[[:space:]]+redeem|atomic[[:space:]]+claim'; then
    redeem_signal="yes"
  fi

  while IFS= read -r -d "$record_sep" stmt; do
    norm="$(printf '%s' "$stmt" | normalize_sql_text)"
    if [[ ! "$norm" =~ update[[:space:]]+secret_capability_tokens ]]; then
      continue
    fi

    update_count=$((update_count + 1))
    local missing=()

    if [[ ! "$norm" =~ (^|[^a-z0-9_])tenant_id([^a-z0-9_]|$) ]]; then
      missing+=("tenant_id")
    fi
    if [[ ! "$norm" =~ (^|[^a-z0-9_])token_hash([^a-z0-9_]|$) ]]; then
      missing+=("token_hash")
    fi
    if [[ ! "$norm" =~ status[[:space:]]*=[[:space:]]*\'issued\' ]]; then
      missing+=("status='issued'")
    fi
    if [[ ! "$norm" =~ used_at[[:space:]]+is[[:space:]]+null ]]; then
      missing+=("used_at IS NULL")
    fi
    if ! [[ "$norm" =~ expires_at[[:space:]]*\>[[:space:]]*(now\(\)|current_timestamp|transaction_timestamp\(\)|clock_timestamp\(\)) || "$norm" =~ (now\(\)|current_timestamp|transaction_timestamp\(\)|clock_timestamp\(\))[[:space:]]*\<[[:space:]]*expires_at ]]; then
      missing+=("expires_at > now()")
    fi
    if [[ ! "$norm" =~ (^|[^a-z0-9_])issued_to_actor_id([^a-z0-9_]|$) ]]; then
      missing+=("issued_to_actor_id")
    fi
    if [[ ! "$norm" =~ (^|[^a-z0-9_])issued_run_id([^a-z0-9_]|$) ]]; then
      missing+=("issued_run_id")
    fi
    if [[ ! "$norm" =~ (^|[^a-z0-9_])expected_request_fingerprint([^a-z0-9_]|$) ]]; then
      missing+=("expected_request_fingerprint")
    fi
    if [[ ! "$norm" =~ (^|[^a-z0-9_])returning([^a-z0-9_]|$) ]]; then
      missing+=("RETURNING")
    fi

    if [ "${#missing[@]}" -gt 0 ]; then
      printf 'secret_capability_tokens atomic claim UPDATE statement %s missing %s\n' "$update_count" "$(join_by ', ' "${missing[@]}")"
    else
      complete_claim=1
    fi
  done < <(sql_statements "$content")

  if [ "$redeem_signal" = "yes" ] && [ "$update_count" -eq 0 ]; then
    printf 'STRONG WARN redeem flow mentions capability token redeem but no UPDATE secret_capability_tokens statement was found; redeem must be a single conditional UPDATE ... RETURNING atomic claim\n'
  elif [ "$redeem_signal" = "yes" ] && [ "$complete_claim" -eq 0 ]; then
    printf 'STRONG WARN redeem flow appears to touch secret_capability_tokens but no complete atomic claim UPDATE was found\n'
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

rel_path="$(relative_file_path "$file_path")"
if ! secretbroker_hook_target "$rel_path"; then
  exit 0
fi

content="$(tool_content_or_file "$input" "$file_path")"
if [ -z "$content" ]; then
  exit 0
fi

if raw_secret_scan_target "$rel_path"; then
  raw_hit="$(raw_secret_column_hits "$content" || true)"
  if [ -n "$raw_hit" ]; then
    raw_hit_summary="$(printf '%s' "$raw_hit" | tr '\n' ';')"
    block_with_message "PostToolUse" "BLOCK secretbroker-raw-secret-column: ${rel_path} appears to add raw secret/token/key storage (${raw_hit_summary}). Store secret_ref URI metadata or *_hash values only; do not store API keys, private keys, passwords, passphrases, access tokens, bearer tokens, client secrets, auth tokens, or capability token raw values. refs: .claude/rules/secretbroker-boundary.md §§1,4,6."
  fi
fi

if ! printf '%s\n' "$content" | grep -Eiq 'secret_refs|secret_capability_tokens|SecretBroker|secret_ref|capability token'; then
  exit 0
fi

warnings=()

if printf '%s\n' "$content" | grep -Eq 'secret_refs'; then
  for term in 'secret_uri' 'scope' 'name' 'version' 'status' 'allowed_consumers' 'allowed_operations' 'runner_injectable'; do
    if ! printf '%s\n' "$content" | grep -Eq "$term"; then
      warnings+=("secret_refs missing ${term}")
    fi
  done

  if ! printf '%s\n' "$content" | grep -Eq "pending|active|deprecated|revoked"; then
    warnings+=("secret_refs.status enum should include pending/active/deprecated/revoked")
  fi

  if ! printf '%s\n' "$content" | grep -Eiq "where[[:space:]]+status[[:space:]]*=[[:space:]]*'active'|status[[:space:]]*=[[:space:]]*'active'.*unique"; then
    warnings+=("secret_refs should enforce active per (tenant_id, scope, name) with a partial unique invariant")
  fi
fi

if printf '%s\n' "$content" | grep -Eq 'secret_capability_tokens'; then
  for term in 'token_hash' 'status' 'expires_at' 'used_at' 'issued_to_actor_id' 'issued_run_id' 'allowed_operations' 'expected_request_fingerprint'; do
    if ! printf '%s\n' "$content" | grep -Eq "$term"; then
      warnings+=("secret_capability_tokens missing ${term}")
    fi
  done

  if ! printf '%s\n' "$content" | grep -Eq "issued|redeeming|used|expired|revoked"; then
    warnings+=("secret_capability_tokens.status enum should include issued/redeeming/used/expired/revoked")
  fi

  while IFS= read -r atomic_warning; do
    if [ -n "$atomic_warning" ]; then
      warnings+=("$atomic_warning")
    fi
  done < <(atomic_claim_warnings "$content")
fi

if [ "${#warnings[@]}" -gt 0 ]; then
  msg="WARN secretbroker-ddl: ${rel_path}: $(join_by '; ' "${warnings[@]}"). refs: .claude/rules/secretbroker-boundary.md §§4-8, .claude/reference/secretbroker-contract.md."
  emit_system_message "PostToolUse" "$msg"
fi

exit 0

