#!/usr/bin/env bash
# Validate config/provider_compliance.toml enum, ordinal, training_use, and condition_status invariants.
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
if [ "$rel_path" != "config/provider_compliance.toml" ]; then
  exit 0
fi

abs_path="$(normalize_file_path "$file_path")"
if [ ! -f "$abs_path" ]; then
  exit 0
fi

report="$(
  awk '
    function trim(s) {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", s)
      return s
    }
    function clean_value(s) {
      s=trim(s)
      gsub(/^"/, "", s)
      gsub(/"$/, "", s)
      gsub(/^'\''/, "", s)
      gsub(/'\''$/, "", s)
      return s
    }
    function ord(s) {
      if (s == "public") return 0
      if (s == "internal") return 1
      if (s == "confidential") return 2
      if (s == "pii") return 3
      return 99
    }
    function in_set(s, set) {
      return index("|" set "|", "|" s "|") > 0
    }
    function label() {
      if (v["provider"] != "" || v["api_or_feature"] != "") return v["provider"] "." v["api_or_feature"]
      return "row " row
    }
    function check_row(  i,k,l,allowed,training,zdr,condition) {
      if (row == 0 || seen_count == 0) return

      split("provider api_or_feature zdr_eligible retention training_use region_or_data_transfer subprocessor_or_doc_url plan_required allowed_data_class condition_status p0_policy_note last_verified_at", req, " ")
      for (i in req) {
        k=req[i]
        if (!(k in seen)) print "WARN: " label() " missing required column " k
      }

      if (("zdr_eligible" in seen) && !in_set(v["zdr_eligible"], "yes|no|conditional|n/a")) print "WARN: " label() " invalid zdr_eligible=" v["zdr_eligible"]
      if (("retention" in seen) && !in_set(v["retention"], "0d|30d|90d|unverified")) print "WARN: " label() " invalid retention=" v["retention"]
      if (("training_use" in seen) && !in_set(v["training_use"], "no|yes|unverified")) print "WARN: " label() " invalid training_use=" v["training_use"]
      if (("region_or_data_transfer" in seen) && !in_set(v["region_or_data_transfer"], "verified|unverified")) print "WARN: " label() " invalid region_or_data_transfer=" v["region_or_data_transfer"]
      if (("plan_required" in seen) && !in_set(v["plan_required"], "api_tier|business|enterprise|none")) print "WARN: " label() " invalid plan_required=" v["plan_required"]
      if (("allowed_data_class" in seen) && !in_set(v["allowed_data_class"], "public|internal|confidential|pii")) print "WARN: " label() " invalid/scalar-required allowed_data_class=" v["allowed_data_class"]
      if (("condition_status" in seen) && !in_set(v["condition_status"], "verified|unverified|not_applicable")) print "WARN: " label() " invalid condition_status=" v["condition_status"]

      allowed=v["allowed_data_class"]
      training=v["training_use"]
      zdr=v["zdr_eligible"]
      condition=v["condition_status"]

      if (training != "no" && ord(allowed) >= 1) {
        print "BLOCK: " label() " has training_use=" training " with allowed_data_class=" allowed "; training_use != no must be public-only unless ADR explicitly approves a public-only exception"
      }

      if (zdr == "conditional" && condition != "verified" && ord(allowed) >= 2) {
        print "WARN: " label() " allows confidential/pii while conditional ZDR condition_status is not verified"
      }
    }
    function reset_row() {
      delete v
      delete seen
      seen_count=0
    }
    /^[[:space:]]*#/ {next}
    /^[[:space:]]*$/ {next}
    /^\[\[providers\]\]/ {
      check_row()
      row++
      reset_row()
      next
    }
    /^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*[[:space:]]*=/ {
      if (row == 0) row=1
      line=$0
      sub(/[[:space:]]+#.*/, "", line)
      key=line
      sub(/[[:space:]]*=.*/, "", key)
      key=trim(key)
      value=line
      sub(/^[^=]*=[[:space:]]*/, "", value)
      value=clean_value(value)
      v[key]=value
      if (!(key in seen)) seen_count++
      seen[key]=1
      next
    }
    END {
      check_row()
      if (row == 0) print "WARN: no [[providers]] rows found"
    }
  ' "$abs_path"
)"

if [ -z "$report" ]; then
  exit 0
fi

if printf '%s\n' "$report" | grep -q '^BLOCK:'; then
  block_with_message "PostToolUse" "BLOCK provider-compliance-toml: ${rel_path}: $(printf '%s' "$report" | tr '\n' '; '). refs: .claude/rules/provider-compliance.md §§2-7, .claude/reference/provider-compliance-matrix.md §§3-7."
fi

emit_system_message "PostToolUse" "WARN provider-compliance-toml: ${rel_path}: $(printf '%s' "$report" | tr '\n' '; '). refs: .claude/rules/provider-compliance.md §§2-7, .claude/reference/provider-compliance-matrix.md §§3-7."
exit 0

