#!/usr/bin/env bash
set -euo pipefail

# TaskManagedAI MCP Client Setup
# 他プロジェクトの .mcp.json に TaskManagedAI MCP Server を追加する
#
# Usage:
#   bash /path/to/TaskManagedAI/scripts/setup-mcp-client.sh [target-project-dir]
#
# target-project-dir を省略すると現在のディレクトリに .mcp.json を作成/更新する

TASKMANAGEDAI_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_DIR="${1:-.}"
MCP_JSON="${TARGET_DIR}/.mcp.json"

DB_URL="postgresql+asyncpg://taskmanagedai:taskmanagedai_local_smoke_pwd@127.0.0.1:5432/taskmanagedai"

echo "TaskManagedAI MCP Client Setup"
echo "  TaskManagedAI: ${TASKMANAGEDAI_ROOT}"
echo "  Target:        ${TARGET_DIR}"
echo "  .mcp.json:     ${MCP_JSON}"
echo ""

MCP_ENTRY=$(cat << JSONEOF
{
  "command": "uv",
  "args": ["run", "--directory", "${TASKMANAGEDAI_ROOT}", "python", "-m", "backend.app.mcp"],
  "env": {
    "TASKMANAGEDAI_DATABASE_URL": "${DB_URL}"
  }
}
JSONEOF
)

if [ -f "$MCP_JSON" ]; then
    if jq -e '.mcpServers.taskmanagedai' "$MCP_JSON" >/dev/null 2>&1; then
        echo "taskmanagedai already exists in ${MCP_JSON}, updating..."
        jq --argjson entry "$MCP_ENTRY" '.mcpServers.taskmanagedai = $entry' "$MCP_JSON" > "${MCP_JSON}.tmp"
        mv "${MCP_JSON}.tmp" "$MCP_JSON"
    else
        echo "Adding taskmanagedai to existing ${MCP_JSON}..."
        jq --argjson entry "$MCP_ENTRY" '.mcpServers.taskmanagedai = $entry' "$MCP_JSON" > "${MCP_JSON}.tmp"
        mv "${MCP_JSON}.tmp" "$MCP_JSON"
    fi
else
    mkdir -p "$(dirname "$MCP_JSON")"
    echo "Creating new ${MCP_JSON}..."
    jq -n --argjson entry "$MCP_ENTRY" '{"mcpServers": {"taskmanagedai": $entry}}' > "$MCP_JSON"
fi

echo ""
echo "Done! TaskManagedAI MCP Server is configured."
echo ""
echo "Available tools (21):"
echo "  ticket_create, ticket_list, ticket_show, ticket_update"
echo "  run_create, run_show, run_cancel, run_plan_dry_run"
echo "  approval_list, approval_show"
echo "  audit_list, context_show, kpi_show"
echo "  notification_list, notification_resolve"
echo "  superintendent_agent_register, superintendent_agent_start"
echo "  superintendent_agent_stop, superintendent_agent_list"
echo "  superintendent_delegation_show, superintendent_dispatch"
echo ""
echo "Restart Claude Code session to activate."
