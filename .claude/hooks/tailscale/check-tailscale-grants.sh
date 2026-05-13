#!/usr/bin/env bash
# Block public exposure in Tailscale/grants/network config and warn that ADR-00007 is required.
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
content="$(tool_content_or_file "$input" "$file_path")"

target="no"
case "$rel_path" in
  *tailscale*|*tailnet*|*grants*|config/network/*|infra/*|docker-compose*.yml|docker-compose*.yaml|compose*.yml|compose*.yaml|docs/基本設計/05_ネットワーク境界設計.md) target="yes" ;;
esac

if printf '%s\n' "$content" | grep -Eiq 'tailscale|tailnet|tag:taskhub|tag:taskhub-ci|Funnel|funnel|public ingress|public bind|0\.0\.0\.0'; then
  target="yes"
fi

if [ "$target" != "yes" ]; then
  exit 0
fi

case "$rel_path" in
  *.md)
    emit_system_message "PostToolUse" "WARN tailscale-grants: ${rel_path}: Tailscale/Funnel/public exposure documentation changed. Confirm ADR-00007 and P0 deny-by-default assumptions: Tailscale Serve/SSH closed network, no Funnel, no public bind, minimal tag:taskhub-ci grants. refs: .claude/rules/sprint-pack-adr-gate.md §4, .claude/CLAUDE.md §2."
    exit 0
    ;;
esac

if printf '%s\n' "$content" | grep -Eiq 'tailscale[[:space:]]+funnel|Funnel|funnel[[:space:]]*:|public ingress|cloudflared|Cloudflare Tunnel|0\.0\.0\.0[[:space:]]*:|--host[[:space:]]+0\.0\.0\.0|host:[[:space:]]*0\.0\.0\.0|^[[:space:]]*-[[:space:]]*"?[0-9]+:[0-9]+'; then
  block_with_message "PostToolUse" "BLOCK tailscale-public-exposure: ${rel_path} appears to introduce Funnel, public ingress, Cloudflare tunnel, or public bind. P0 assumes Tailscale closed network and deny-by-default; external exposure is ADR Gate Criteria #7 and requires ADR-00007 before implementation. refs: .claude/rules/core.md §7, .claude/rules/sprint-pack-adr-gate.md §4."
fi

emit_system_message "PostToolUse" "WARN tailscale-grants: ${rel_path}: Tailscale/grants/network config changed. Confirm only intended grants are present and ADR-00007 covers tagOwners, src/dst, TCP/443, ephemeral CI key, reusable key denial, and log masking. refs: .claude/CLAUDE.md §2, docs/sprints/SP-000_bootstrap.md."
exit 0

