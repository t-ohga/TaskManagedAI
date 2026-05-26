"""TaskManagedAI MCP Server — stdio transport, 15 tools.

Security invariants:
- approval_decide is human-only (not exposed)
- server-owned fields resolved from session, never from input
- raw secret / provider key never in tool response
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


# --- Read-only tools ---


@mcp.tool()
async def ticket_list(project_id: str, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """プロジェクト内のチケット一覧を取得。"""
    return {"tickets": [], "total": 0, "limit": limit, "offset": offset, "project_id": project_id}


@mcp.tool()
async def ticket_show(project_id: str, ticket_id: str) -> dict[str, Any]:
    """チケット詳細を取得。"""
    return {"ticket_id": ticket_id, "project_id": project_id}


@mcp.tool()
async def run_show(run_id: str) -> dict[str, Any]:
    """AgentRun の状態と events timeline を取得。payload は keys_only。"""
    return {"run_id": run_id, "status": "queued", "events": []}


@mcp.tool()
async def run_plan_dry_run(purpose: str, expected_artifact: str = "") -> dict[str, Any]:
    """実行計画のドライラン。実際には実行しない (response-only)。"""
    return {"purpose": purpose, "plan": [], "expected_artifact": expected_artifact}


@mcp.tool()
async def approval_list(status: str = "pending") -> dict[str, Any]:
    """承認リクエスト一覧。AI agent は閲覧のみ (decide は human-only)。"""
    return {"approvals": [], "status_filter": status}


@mcp.tool()
async def approval_show(approval_id: str) -> dict[str, Any]:
    """承認リクエスト詳細。"""
    return {"approval_id": approval_id}


@mcp.tool()
async def audit_list(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """監査ログ一覧 (keys_only、raw secret 除外)。"""
    return {"events": [], "total": 0, "limit": limit, "offset": offset}


@mcp.tool()
async def context_show() -> dict[str, Any]:
    """現在のプロジェクト情報を取得。"""
    return {"project_id": None, "project_name": None}


@mcp.tool()
async def kpi_show() -> dict[str, Any]:
    """Quality KPIs (5 件) のロールアップ。"""
    return {"kpis": []}


@mcp.tool()
async def notification_list() -> dict[str, Any]:
    """通知一覧 (keys_only DTO)。"""
    return {"notifications": []}


# --- Mutating tools ---


@mcp.tool()
async def ticket_create(
    project_id: str,
    title: str,
    description: str = "",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """新規チケットを作成。idempotency_key で重複防止。"""
    return {"ticket_id": "pending-wiring", "title": title, "project_id": project_id}


@mcp.tool()
async def ticket_update(
    project_id: str,
    ticket_id: str,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """チケットを更新。"""
    return {"ticket_id": ticket_id, "updated": True}


@mcp.tool()
async def run_create(
    project_id: str,
    ticket_id: str,
    purpose: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """AI 実行 (AgentRun) を開始。run_id を即時返却。"""
    return {"run_id": "pending-wiring", "status": "queued", "ticket_id": ticket_id}


@mcp.tool()
async def run_cancel(run_id: str) -> dict[str, Any]:
    """AgentRun をキャンセル。"""
    return {"run_id": run_id, "status": "cancelled"}


# --- Superintendent tools (SP-035) ---


@mcp.tool()
async def superintendent_agent_register(
    role_id: str, project_id: str, provider: str = "mock"
) -> dict[str, Any]:
    """Agent を登録して role を割り当てる。Superintendent only。"""
    return {"agent_id": "pending-wiring", "role_id": role_id, "state": "registered"}


@mcp.tool()
async def superintendent_agent_start(agent_id: str) -> dict[str, Any]:
    """Agent プロセスを起動する。"""
    return {"agent_id": agent_id, "state": "starting"}


@mcp.tool()
async def superintendent_agent_stop(agent_id: str) -> dict[str, Any]:
    """Agent を停止する。"""
    return {"agent_id": agent_id, "state": "stopping"}


@mcp.tool()
async def superintendent_agent_list() -> dict[str, Any]:
    """登録 agent の一覧 (role + state)。"""
    return {"agents": []}


@mcp.tool()
async def superintendent_delegation_show() -> dict[str, Any]:
    """現在の delegation policy を表示 (read-only)。"""
    from backend.app.services.superintendent.delegation_policy import POLICY_TEMPLATES

    conservative = POLICY_TEMPLATES["conservative"]
    return {
        "max_auto_approve_risk": conservative.max_auto_approve_risk,
        "max_budget_per_run": str(conservative.max_budget_per_run),
        "max_concurrent_agents": conservative.max_concurrent_agents,
        "forbidden_actions": sorted(conservative.forbidden_actions),
    }


@mcp.tool()
async def superintendent_dispatch(
    agent_id: str, ticket_id: str, action_class: str = "task_write"
) -> dict[str, Any]:
    """Ticket を agent に割り当てて AgentRun を開始。delegation policy gate 経由。"""
    return {
        "dispatched": True,
        "agent_id": agent_id,
        "ticket_id": ticket_id,
        "needs_human_approval": action_class not in ("read_only", "task_write"),
    }


@mcp.tool()
async def notification_resolve(notification_id: str) -> dict[str, Any]:
    """通知を解決済みにする。"""
    return {"notification_id": notification_id, "resolved": True}
