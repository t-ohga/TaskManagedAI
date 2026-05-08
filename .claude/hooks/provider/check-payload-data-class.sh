#!/usr/bin/env bash
# Check ProviderAdapter/provider-call code for payload_data_class and caller allowed_data_class boundary violations.
#
# 入力: stdin で JSON (tool_input / tool_response 等)
# 出力: exit 0 で許可、exit 2 で BLOCK + ユーザーへ system message
# 詳細: https://docs.claude.com/en/docs/claude-code/hooks

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

HOOK_EVENT_NAME="PostToolUse"

detect_caller_allowed_data_class() {
  printf '%s\n' "$1" | awk '
    function has_allowed_text(s,   low) {
      low = tolower(s)
      return low ~ /allowed_data_class|alloweddataclass/
    }

    function class_name(line,   tmp) {
      tmp = line
      sub(/^[[:space:]]*class[[:space:]]+/, "", tmp)
      sub(/[(:].*/, "", tmp)
      gsub(/[[:space:]]+/, "", tmp)
      return tmp
    }

    function interface_name(line,   tmp) {
      tmp = line
      sub(/^[[:space:]]*(export[[:space:]]+)?interface[[:space:]]+/, "", tmp)
      sub(/[[:space:]<{].*/, "", tmp)
      return tmp
    }

    function type_name(line,   tmp) {
      tmp = line
      sub(/^[[:space:]]*(export[[:space:]]+)?type[[:space:]]+/, "", tmp)
      sub(/[[:space:]=<{].*/, "", tmp)
      return tmp
    }

    function const_name(line,   tmp) {
      tmp = line
      sub(/=.*/, "", tmp)
      sub(/^[[:space:]]*(export[[:space:]]+)?(const|let|var)[[:space:]]+/, "", tmp)
      sub(/[[:space:]:].*/, "", tmp)
      return tmp
    }

    function def_name(line,   tmp) {
      tmp = line
      sub(/^[[:space:]]*(async[[:space:]]+)?def[[:space:]]+/, "", tmp)
      sub(/\(.*/, "", tmp)
      return tmp
    }

    function unit_allowlisted(name, body,   lown, lowbody) {
      lown = tolower(name)
      lowbody = tolower(body)

      if (lown ~ /alloweddataclass|allowed_data_class/) {
        return 1
      }
      if (lown ~ /audit|auditevent|auditpayload|decisionevent/) {
        return 1
      }
      if (lown ~ /matrix|matrixrow|matrixentry|providercompliancematrix|compliance(row|entry|config)|loader|configrow|toml/) {
        return 1
      }
      if (lowbody ~ /config\/provider_compliance\.toml|provider_compliance\.toml|provider compliance matrix|matrix loader|load_provider_compliance|alloweddata class enum|enum alloweddataclass/) {
        return 1
      }

      return 0
    }

    function unit_is_caller_input(name, body,   lown, lowbody) {
      lown = tolower(name)
      lowbody = tolower(body)

      if (lown ~ /(request|input|body|params|param|dto|payload|schema|form|command)/) {
        return 1
      }
      if (lowbody ~ /(body[[:space:]]*\(|query[[:space:]]*\(|form[[:space:]]*\(|path[[:space:]]*\(|request body|api body|fastapi|pydantic request|request schema)/) {
        return 1
      }

      return 0
    }

    function finish_unit(kind, name, start, body) {
      if (!has_allowed_text(body)) {
        return
      }

      if (kind == "fastapi") {
        print "FastAPI request parameter " name " starting line " start " exposes allowed_data_class as caller input"
        return
      }

      if (unit_allowlisted(name, body)) {
        return
      }

      if (unit_is_caller_input(name, body)) {
        print kind " " name " starting line " start " exposes allowed_data_class as caller input"
      }
    }

    {
      line = $0
      low = tolower(line)

      if (mode == "pyclass") {
        if (line !~ /^[[:space:]]/ && line !~ /^[[:space:]]*$/) {
          finish_unit("Pydantic BaseModel", unit_name, start_line, unit_body)
          mode = ""
          unit_body = ""
        } else {
          unit_body = unit_body "\n" line
          next
        }
      }

      if (mode == "fastapi") {
        unit_body = unit_body "\n" line
        if (low ~ /\)[[:space:]]*(->[^{:]+)?[[:space:]]*:/) {
          finish_unit("fastapi", unit_name, start_line, unit_body)
          mode = ""
          unit_body = ""
        }
        next
      }

      if (mode == "ts") {
        unit_body = unit_body "\n" line
        if (line ~ /[};\]][[:space:]]*;?[[:space:]]*$/) {
          finish_unit(unit_kind, unit_name, start_line, unit_body)
          mode = ""
          unit_body = ""
        }
        next
      }

      if (mode == "zod") {
        unit_body = unit_body "\n" line
        if (line ~ /\}\)[[:space:]]*;?[[:space:]]*$/ || line ~ /\}\)[.a-zA-Z0-9_]*(;)?[[:space:]]*$/) {
          finish_unit("Zod schema", unit_name, start_line, unit_body)
          mode = ""
          unit_body = ""
        }
        next
      }

      if (has_allowed_text(line) && low ~ /(body[[:space:]]*\(|query[[:space:]]*\(|form[[:space:]]*\(|path[[:space:]]*\(|request[[:space:]]*body)/ && low !~ /(audit|matrix|provider_compliance|compliance matrix)/) {
        print "request body field line " NR " exposes allowed_data_class as caller input"
      }

      if (low ~ /^[[:space:]]*(async[[:space:]]+)?def[[:space:]]+[a-z0-9_]+[[:space:]]*\(/) {
        mode = "fastapi"
        unit_name = def_name(line)
        start_line = NR
        unit_body = line
        if (low ~ /\)[[:space:]]*(->[^{:]+)?[[:space:]]*:/) {
          finish_unit("fastapi", unit_name, start_line, unit_body)
          mode = ""
          unit_body = ""
        }
        next
      }

      if (low ~ /^[[:space:]]*class[[:space:]]+[a-z0-9_]+.*basemodel/) {
        mode = "pyclass"
        unit_name = class_name(line)
        start_line = NR
        unit_body = line
        next
      }

      if (low ~ /^[[:space:]]*(export[[:space:]]+)?interface[[:space:]]+[a-z0-9_]+/) {
        mode = "ts"
        unit_kind = "TypeScript interface"
        unit_name = interface_name(line)
        start_line = NR
        unit_body = line
        if (line ~ /[};\]][[:space:]]*;?[[:space:]]*$/) {
          finish_unit(unit_kind, unit_name, start_line, unit_body)
          mode = ""
          unit_body = ""
        }
        next
      }

      if (low ~ /^[[:space:]]*(export[[:space:]]+)?type[[:space:]]+[a-z0-9_]+[[:space:]]*=/) {
        mode = "ts"
        unit_kind = "TypeScript type"
        unit_name = type_name(line)
        start_line = NR
        unit_body = line
        if (line ~ /[};\]][[:space:]]*;?[[:space:]]*$/) {
          finish_unit(unit_kind, unit_name, start_line, unit_body)
          mode = ""
          unit_body = ""
        }
        next
      }

      if (low ~ /z[.]object[[:space:]]*\(/) {
        mode = "zod"
        unit_name = const_name(line)
        if (unit_name == "") {
          unit_name = "anonymous_zod_object"
        }
        start_line = NR
        unit_body = line
        if (line ~ /\}\)[[:space:]]*;?[[:space:]]*$/ || line ~ /\}\)[.a-zA-Z0-9_]*(;)?[[:space:]]*$/) {
          finish_unit("Zod schema", unit_name, start_line, unit_body)
          mode = ""
          unit_body = ""
        }
        next
      }
    }

    END {
      if (mode == "pyclass") {
        finish_unit("Pydantic BaseModel", unit_name, start_line, unit_body)
      } else if (mode == "fastapi") {
        finish_unit("fastapi", unit_name, start_line, unit_body)
      } else if (mode == "ts") {
        finish_unit(unit_kind, unit_name, start_line, unit_body)
      } else if (mode == "zod") {
        finish_unit("Zod schema", unit_name, start_line, unit_body)
      }
    }
  '
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
case "$rel_path" in
  config/provider_compliance.toml) exit 0 ;;
  backend/*|frontend/*|config/*|docs/基本設計/*|docs/実装計画/*) ;;
  *) exit 0 ;;
esac

content="$(tool_content_or_file "$input" "$file_path")"
if [ -z "$content" ]; then
  exit 0
fi

provider_signal="no"
case "$rel_path" in
  *provider*|*Provider*|*adapter*|*ai*|*llm*|*model*) provider_signal="yes" ;;
esac

if printf '%s\n' "$content" | grep -Eiq 'ProviderAdapter|provider_request_preflight|provider\.call|payload_data_class|payloadDataClass|allowed_data_class|allowedDataClass|openai|anthropic|gemini|responses\.create|messages\.create|Structured Outputs'; then
  provider_signal="yes"
fi

if printf '%s\n' "$content" | grep -Eq 'allowed_data_class|allowedDataClass'; then
  caller_hits="$(detect_caller_allowed_data_class "$content" || true)"
  if [ -n "$caller_hits" ]; then
    caller_summary="$(printf '%s' "$caller_hits" | tr '\n' ';')"
    block_with_message "PostToolUse" "BLOCK provider-allowed-data-class-caller-input: ${rel_path}: ${caller_summary}. allowed_data_class must be resolved only from config/provider_compliance.toml / Provider Compliance Matrix inside the Compliance Gate; caller request schemas, DTOs, API bodies, and Zod/Pydantic/TypeScript request objects must not accept it. refs: .claude/rules/provider-compliance.md §§3-6."
  fi
fi

if [ "$provider_signal" != "yes" ]; then
  exit 0
fi

warnings=()

if ! printf '%s\n' "$content" | grep -Eq 'payload_data_class|payloadDataClass'; then
  warnings+=("provider call / ProviderAdapter code should require payload_data_class before provider request")
fi

if printf '%s\n' "$content" | grep -Eq 'payload_data_class|payloadDataClass|allowed_data_class|allowedDataClass' && ! printf '%s\n' "$content" | grep -Eq 'public[[:space:]]*[:=][[:space:]]*0|internal[[:space:]]*[:=][[:space:]]*1|ordinal|DATA_CLASS_ORDER|DataClassOrder'; then
  warnings+=("data class comparison should use the fixed ordinal public=0, internal=1, confidential=2, pii=3")
fi

if [ "${#warnings[@]}" -gt 0 ]; then
  msg="WARN provider-payload-data-class: ${rel_path}: $(join_by '; ' "${warnings[@]}"). refs: .claude/rules/provider-compliance.md §§3-6, .claude/reference/provider-compliance-matrix.md §§4,9."
  emit_system_message "PostToolUse" "$msg"
fi

exit 0
