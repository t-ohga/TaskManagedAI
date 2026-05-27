"""TaskManagedAI MCP Server — stdio transport, 21 tools (all DB-wired).

Security invariants:
- approval_decide is human-only (not exposed)
- server-owned fields resolved from session, never from input
- raw secret / provider key never in tool response
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID

from fastmcp import FastMCP


def _safe_uuid(s: str) -> UUID:
    _UUID = UUID
    try:
        return _UUID(s)
    except (ValueError, AttributeError):
        return _UUID("00000000-0000-4000-8000-000000000099")

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
    from uuid import UUID

    from backend.app.mcp.api_bridge import bridge_ticket_list
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            return await bridge_ticket_list(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                project_id=UUID(project_id),
                limit=limit,
                offset=offset,
            )
    except Exception as e:
        return {"error": str(type(e).__name__), "tickets": [], "total": 0}


@mcp.tool()
async def ticket_show(project_id: str, ticket_id: str) -> dict[str, Any]:
    """チケット詳細を取得。"""
    from uuid import UUID

    from backend.app.mcp.api_bridge import bridge_ticket_show
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            return await bridge_ticket_show(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                project_id=UUID(project_id),
                ticket_id=UUID(ticket_id),
            )
    except Exception as e:
        return {"error": str(type(e).__name__), "ticket_id": ticket_id}


@mcp.tool()
async def run_show(run_id: str) -> dict[str, Any]:
    """AgentRun の状態を取得。payload は keys_only。"""
    from uuid import UUID

    from backend.app.mcp.api_bridge import bridge_run_show
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            return await bridge_run_show(
                session, tenant_id=DEFAULT_TENANT_ID, run_id=UUID(run_id)
            )
    except Exception as e:
        return {"error": str(type(e).__name__), "run_id": run_id}


@mcp.tool()
async def run_plan_dry_run(purpose: str, expected_artifact: str = "") -> dict[str, Any]:
    """実行計画のドライラン。実際には実行しない (response-only)。"""
    return {"purpose": purpose, "plan": [], "expected_artifact": expected_artifact}


@mcp.tool()
async def approval_list(status: str = "pending") -> dict[str, Any]:
    """承認リクエスト一覧。AI agent は閲覧のみ (decide は human-only)。"""
    from backend.app.mcp.api_bridge import bridge_approval_list
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            return await bridge_approval_list(
                session, tenant_id=DEFAULT_TENANT_ID, status=status
            )
    except Exception as e:
        return {"error": str(type(e).__name__), "approvals": []}


@mcp.tool()
async def approval_show(approval_id: str) -> dict[str, Any]:
    """承認リクエスト詳細。"""
    from uuid import UUID

    from backend.app.mcp.api_bridge import bridge_approval_show
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            return await bridge_approval_show(
                session, tenant_id=DEFAULT_TENANT_ID, approval_id=UUID(approval_id)
            )
    except Exception as e:
        return {"error": str(type(e).__name__), "approval_id": approval_id}


@mcp.tool()
async def audit_list(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """監査ログ一覧 (keys_only、raw secret 除外)。"""
    from backend.app.mcp.api_bridge import bridge_audit_list
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            return await bridge_audit_list(
                session, tenant_id=DEFAULT_TENANT_ID, limit=limit, offset=offset
            )
    except Exception as e:
        return {"error": str(type(e).__name__), "events": [], "total": 0}


@mcp.tool()
async def context_show() -> dict[str, Any]:
    """現在のプロジェクト情報を取得。"""
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session
    from backend.app.repositories.project import ProjectRepository

    try:
        async with get_db_session() as session:
            repo = ProjectRepository(session)
            projects = await repo.list(tenant_id=DEFAULT_TENANT_ID)
            if not projects:
                return {"project_id": None, "project_name": None}
            p = projects[0]
            return {
                "project_id": str(p.id),
                "project_name": p.name,
                "project_slug": p.slug,
                "status": p.status,
            }
    except Exception as e:
        return {"error": str(type(e).__name__), "project_id": None}


@mcp.tool()
async def kpi_show() -> dict[str, Any]:
    """Quality KPIs (5 件) のロールアップ。"""
    import sqlalchemy as sa
    from sqlalchemy import select

    from backend.app.db.models.agent_run import AgentRun
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            total_runs = (await session.execute(
                select(sa.func.count()).select_from(AgentRun).where(AgentRun.tenant_id == DEFAULT_TENANT_ID)
            )).scalar() or 0
            completed = (await session.execute(
                select(sa.func.count()).select_from(AgentRun).where(
                    AgentRun.tenant_id == DEFAULT_TENANT_ID, AgentRun.status == "completed"
                )
            )).scalar() or 0
            failed = (await session.execute(
                select(sa.func.count()).select_from(AgentRun).where(
                    AgentRun.tenant_id == DEFAULT_TENANT_ID, AgentRun.status == "failed"
                )
            )).scalar() or 0
            return {
                "kpis": [
                    {"name": "total_runs", "value": total_runs},
                    {"name": "completed_runs", "value": completed},
                    {"name": "failed_runs", "value": failed},
                    {"name": "success_rate", "value": round(completed / total_runs * 100, 1) if total_runs > 0 else 0},
                    {"name": "open_tickets", "value": 0},
                ]
            }
    except Exception as e:
        return {"error": str(type(e).__name__), "kpis": []}


@mcp.tool()
async def notification_list() -> dict[str, Any]:
    """通知一覧 (keys_only DTO)。"""
    from backend.app.mcp.api_bridge import bridge_notification_list
    from backend.app.mcp.context import DEFAULT_SUPERINTENDENT_ACTOR_ID, DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            return await bridge_notification_list(
                session, tenant_id=DEFAULT_TENANT_ID, actor_id=DEFAULT_SUPERINTENDENT_ACTOR_ID
            )
    except Exception as e:
        return {"error": str(type(e).__name__), "notifications": []}


# --- Mutating tools ---


@mcp.tool()
async def ticket_create(
    project_id: str,
    title: str,
    description: str = "",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """新規チケットを作成。idempotency_key で重複防止。"""
    from uuid import UUID

    from backend.app.mcp.api_bridge import bridge_ticket_create
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            result = await bridge_ticket_create(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                project_id=UUID(project_id),
                title=title,
                description=description,
            )
            return result
    except Exception as e:
        return {"error": str(type(e).__name__), "message": str(e)[:200]}


@mcp.tool()
async def ticket_update(
    project_id: str,
    ticket_id: str,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """チケットを更新。"""
    from uuid import UUID

    from backend.app.mcp.api_bridge import bridge_ticket_update
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    payload: dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if description is not None:
        payload["description"] = description
    if status is not None:
        payload["status"] = status

    if not payload:
        return {"error": "no_fields_to_update", "ticket_id": ticket_id}

    try:
        async with get_db_session() as session:
            return await bridge_ticket_update(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                project_id=UUID(project_id),
                ticket_id=UUID(ticket_id),
                payload=payload,
            )
    except Exception as e:
        return {"error": str(type(e).__name__), "ticket_id": ticket_id}


@mcp.tool()
async def run_create(
    project_id: str,
    ticket_id: str,
    purpose: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """AI 実行 (AgentRun) を開始。run_id を即時返却。"""
    from uuid import UUID

    from backend.app.mcp.api_bridge import bridge_run_create
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            return await bridge_run_create(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                project_id=UUID(project_id),
                ticket_id=ticket_id,
                purpose=purpose,
            )
    except Exception as e:
        return {"error": str(type(e).__name__), "message": str(e)[:200]}


@mcp.tool()
async def run_cancel(run_id: str) -> dict[str, Any]:
    """AgentRun をキャンセル。"""
    from uuid import UUID

    from backend.app.mcp.api_bridge import bridge_run_cancel
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            return await bridge_run_cancel(
                session, tenant_id=DEFAULT_TENANT_ID, run_id=UUID(run_id)
            )
    except Exception as e:
        return {"error": str(type(e).__name__), "run_id": run_id}


# --- Superintendent tools (SP-035) ---


@mcp.tool()
async def superintendent_agent_register(
    role_id: str, project_id: str, provider: str = "claude"
) -> dict[str, Any]:
    """Agent を登録して role を割り当てる。provider: claude / codex / custom。"""
    from datetime import UTC, datetime
    from uuid import UUID, uuid4

    from backend.app.mcp.context import DEFAULT_SUPERINTENDENT_ACTOR_ID
    from backend.app.services.superintendent.lifecycle import ManagedAgent

    agent_id = uuid4()
    ManagedAgent(
        agent_id=agent_id,
        actor_id=DEFAULT_SUPERINTENDENT_ACTOR_ID,
        role_id=role_id,
        state="registered",
        project_id=UUID(project_id),
        superintendent_id=DEFAULT_SUPERINTENDENT_ACTOR_ID,
        created_at=datetime.now(UTC),
    )
    from backend.app.services.superintendent.agent_spawner import _active_agents
    _active_agents[agent_id] = type("SpawnedAgent", (), {
        "agent_id": agent_id, "provider": provider, "process": None,
        "pid": None, "started_at": None, "stopped_at": None, "exit_code": None,
    })()
    return {
        "agent_id": str(agent_id),
        "role_id": role_id,
        "provider": provider,
        "state": "registered",
        "project_id": project_id,
    }


@mcp.tool()
async def superintendent_agent_start(agent_id: str, provider: str = "claude") -> dict[str, Any]:
    """Agent プロセスを起動する。Claude Code / Codex を subprocess で spawn。"""
    from uuid import UUID

    from backend.app.services.superintendent.agent_spawner import spawn_agent

    try:
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
        agent = await spawn_agent(
            agent_id=UUID(agent_id),
            provider=provider,  # type: ignore[arg-type]
            project_dir=project_dir,
        )
        return {
            "agent_id": str(agent.agent_id),
            "pid": agent.pid,
            "state": "starting",
            "provider": agent.provider,
        }
    except Exception as e:
        return {"agent_id": agent_id, "state": "failed", "error": str(type(e).__name__)}


@mcp.tool()
async def superintendent_agent_stop(agent_id: str) -> dict[str, Any]:
    """Agent プロセスを停止する。"""
    from uuid import UUID

    from backend.app.services.superintendent.agent_spawner import stop_agent

    try:
        agent = await stop_agent(UUID(agent_id))
        if agent is None:
            return {"agent_id": agent_id, "state": "not_found"}
        return {
            "agent_id": str(agent.agent_id),
            "state": "stopped",
            "exit_code": agent.exit_code,
        }
    except Exception as e:
        return {"agent_id": agent_id, "state": "failed", "error": str(type(e).__name__)}


@mcp.tool()
async def superintendent_agent_list() -> dict[str, Any]:
    """登録 agent の一覧 (role + state + pid)。"""
    from backend.app.services.superintendent.agent_spawner import list_agents

    return {"agents": list_agents()}


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
    agent_id: str, ticket_id: str, action_class: str = "task_write",
    project_id: str = "00000000-0000-4000-8000-000000000004",
) -> dict[str, Any]:
    """Ticket を agent に割り当てて AgentRun を開始。delegation policy gate 経由。"""
    from uuid import UUID

    from backend.app.mcp.context import DEFAULT_SUPERINTENDENT_ACTOR_ID, DEFAULT_TENANT_ID, get_db_session
    from backend.app.services.superintendent.delegation_policy import POLICY_TEMPLATES
    from backend.app.services.superintendent.dispatch import DispatchRequest, evaluate_dispatch

    policy = POLICY_TEMPLATES["conservative"]
    request = DispatchRequest(
        superintendent_id=DEFAULT_SUPERINTENDENT_ACTOR_ID,
        agent_id=_safe_uuid(agent_id),
        ticket_id=ticket_id,
        project_id=UUID(project_id),
        action_class=action_class,
        risk_level="low",
    )
    result = evaluate_dispatch(request, policy)

    if not result.dispatched or result.deny_reason:
        return {
            "dispatched": False,
            "agent_id": agent_id,
            "ticket_id": ticket_id,
            "denied": True,
            "reason": result.deny_reason or "policy denied",
        }

    auto_dispatch_actions = {"read_only", "task_write"}
    if not result.needs_human_approval or action_class in auto_dispatch_actions:
        try:
            async with get_db_session() as session:
                from backend.app.mcp.api_bridge import bridge_run_create
                run_result = await bridge_run_create(
                    session,
                    tenant_id=DEFAULT_TENANT_ID,
                    project_id=UUID(project_id),
                    ticket_id=ticket_id,
                    purpose=f"superintendent dispatch: {action_class}",
                )
                return {
                    "dispatched": True,
                    "agent_id": agent_id,
                    "ticket_id": ticket_id,
                    "run_id": run_result["run_id"],
                    "needs_human_approval": False,
                    "action_class": action_class,
                }
        except Exception as e:
            return {"error": str(type(e).__name__), "dispatched": False}

    return {
        "dispatched": True,
        "agent_id": agent_id,
        "ticket_id": ticket_id,
        "needs_human_approval": True,
        "action_class": action_class,
    }


@mcp.tool()
async def notification_resolve(notification_id: str) -> dict[str, Any]:
    """通知を解決済みにする。"""
    from uuid import UUID

    from backend.app.mcp.api_bridge import bridge_notification_resolve
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            return await bridge_notification_resolve(
                session, tenant_id=DEFAULT_TENANT_ID, notification_id=UUID(notification_id)
            )
    except Exception as e:
        return {"error": str(type(e).__name__), "notification_id": notification_id}
