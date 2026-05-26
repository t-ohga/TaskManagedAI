"""TaskManagedAI MCP Server — stdio transport, 15 tools.

AI agents (Claude Code / Codex / others) connect as MCP clients.
All operations go through TaskManagedAI API with audit + approval boundaries.

Security invariants:
- approval_decide is human-only (not exposed as tool)
- server-owned fields (actor_id/tenant_id/policy_profile) resolved from session
- raw secret / provider key never in tool response
- agent self-registration not possible (human admin CLI only)
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

mcp = FastMCP(
    "TaskManagedAI",
    instructions=(
        "TaskManagedAI は AI-native な開発タスク管理ツールです。"
        "チケット作成、AI 実行管理、承認ワークフロー、監査ログを統合管理します。"
        "approval_decide は human-only です。AI agent は承認要求の作成のみ可能です。"
    ),
)


@mcp.tool()
async def ticket_list(project_id: str, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """プロジェクト内のチケット一覧を取得。"""
    return {
        "tickets": [],
        "total": 0,
        "limit": limit,
        "offset": offset,
        "project_id": project_id,
        "_stub": True,
    }


@mcp.tool()
async def ticket_show(project_id: str, ticket_id: str) -> dict[str, Any]:
    """チケット詳細を取得。"""
    return {"ticket_id": ticket_id, "project_id": project_id, "_stub": True}


@mcp.tool()
async def ticket_create(
    project_id: str,
    title: str,
    description: str = "",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """新規チケットを作成。idempotency_key で重複防止。"""
    return {
        "ticket_id": "stub-id",
        "title": title,
        "project_id": project_id,
        "idempotency_key": idempotency_key,
        "_stub": True,
    }


@mcp.tool()
async def ticket_update(
    project_id: str,
    ticket_id: str,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """チケットを更新。"""
    return {"ticket_id": ticket_id, "updated": True, "_stub": True}


@mcp.tool()
async def run_create(
    project_id: str,
    ticket_id: str,
    purpose: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """AI 実行 (AgentRun) を開始。run_id を即時返却、進捗は run_show で確認。"""
    return {
        "run_id": "stub-run-id",
        "status": "queued",
        "ticket_id": ticket_id,
        "_stub": True,
    }


@mcp.tool()
async def run_show(run_id: str) -> dict[str, Any]:
    """AgentRun の状態と events timeline を取得。"""
    return {"run_id": run_id, "status": "queued", "events": [], "_stub": True}


@mcp.tool()
async def run_cancel(run_id: str) -> dict[str, Any]:
    """AgentRun をキャンセル。既にキャンセル済みなら 200。"""
    return {"run_id": run_id, "status": "cancelled", "_stub": True}


@mcp.tool()
async def run_plan_dry_run(
    purpose: str,
    expected_artifact: str = "",
) -> dict[str, Any]:
    """実行計画のドライラン。実際には実行しない (response-only)。"""
    return {"purpose": purpose, "plan": "stub-plan", "_stub": True}


@mcp.tool()
async def approval_list(status: str = "pending") -> dict[str, Any]:
    """承認リクエスト一覧を取得。"""
    return {"approvals": [], "status_filter": status, "_stub": True}


@mcp.tool()
async def approval_show(approval_id: str) -> dict[str, Any]:
    """承認リクエスト詳細を取得。"""
    return {"approval_id": approval_id, "_stub": True}


@mcp.tool()
async def audit_list(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """監査ログ一覧を取得 (keys_only、raw secret 除外)。"""
    return {"events": [], "total": 0, "limit": limit, "_stub": True}


@mcp.tool()
async def context_show() -> dict[str, Any]:
    """現在のプロジェクト情報を取得。"""
    return {"project_id": None, "project_name": None, "_stub": True}


@mcp.tool()
async def kpi_show() -> dict[str, Any]:
    """Quality KPIs (5 件) のロールアップを取得。"""
    return {"kpis": [], "_stub": True}


@mcp.tool()
async def notification_list() -> dict[str, Any]:
    """通知一覧を取得 (keys_only DTO)。"""
    return {"notifications": [], "_stub": True}


@mcp.tool()
async def notification_resolve(notification_id: str) -> dict[str, Any]:
    """通知を解決済みにする。"""
    return {"notification_id": notification_id, "resolved": True, "_stub": True}
