"""TaskManagedAI MCP Server — stdio transport, 39 tools (all DB-wired).

Security invariants:
- approval_decide is human-only (not exposed)
- server-owned fields resolved from session, never from input
- raw secret / provider key never in tool response
"""

from __future__ import annotations

import logging
import os
from typing import Any
from uuid import UUID

from fastmcp import FastMCP

# _safe_uuid removed (H-1 fix): callers use UUID() directly with error handling

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
    valid_statuses = {"pending", "approved", "rejected", "expired", "invalidated"}
    if status not in valid_statuses:
        return {"error": "invalid_status", "valid": sorted(valid_statuses)}

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


@mcp.tool()
async def project_list() -> dict[str, Any]:
    """全プロジェクト一覧を取得。AI agent がどのプロジェクトで作業するか発見できる。"""
    from backend.app.mcp.api_bridge import bridge_project_list
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            return await bridge_project_list(session, tenant_id=DEFAULT_TENANT_ID)
    except Exception as e:
        return {"error": str(type(e).__name__), "projects": []}




@mcp.tool()
async def context_auto(cwd: str = '') -> dict[str, Any]:
    """作業ディレクトリからプロジェクトを自動検出。cwd 省略時は環境変数から推定。"""
    from backend.app.mcp.api_bridge import bridge_context_auto
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    if not cwd:
        cwd = os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd())
    try:
        async with get_db_session() as session:
            return await bridge_context_auto(session, tenant_id=DEFAULT_TENANT_ID, cwd=cwd)
    except Exception as e:
        return {'error': str(type(e).__name__), 'cwd': cwd}


@mcp.tool()
async def ticket_list_all(status: str = 'open', limit: int = 50) -> dict[str, Any]:
    """全プロジェクト横断でチケット一覧を取得。status でフィルタ。"""
    valid_statuses = {'open', 'in_progress', 'closed', 'cancelled'}
    if status not in valid_statuses:
        return {'error': 'invalid_status', 'valid': sorted(valid_statuses)}

    from backend.app.mcp.api_bridge import bridge_ticket_list_all
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            return await bridge_ticket_list_all(session, tenant_id=DEFAULT_TENANT_ID, status=status, limit=limit)
    except Exception as e:
        return {'error': str(type(e).__name__), 'tickets': []}


@mcp.tool()
async def ticket_search(query: str, limit: int = 20) -> dict[str, Any]:
    """チケットをタイトルでキーワード検索 (全プロジェクト横断)。"""
    from backend.app.mcp.api_bridge import bridge_ticket_search
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            return await bridge_ticket_search(session, tenant_id=DEFAULT_TENANT_ID, query=query, limit=limit)
    except Exception as e:
        return {'error': str(type(e).__name__), 'tickets': []}

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
            try:
                from backend.app.mcp.discord_notify import notify_ticket_created
                await notify_ticket_created(title, project_id[:8])
            except Exception:  # noqa: S110
                logging.getLogger(__name__).debug("Discord notification skipped")
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
    role_id: str | None = None,
    parent_run_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """AI 実行 (AgentRun) を開始。role_id で役割指定、parent_run_id で親子関係構築。"""
    from backend.app.mcp.api_bridge import bridge_run_create
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        parsed_ticket_id = UUID(ticket_id)
    except (ValueError, AttributeError):
        return {"error": "invalid_uuid", "field": "ticket_id"}

    parsed_parent = None
    if parent_run_id:
        try:
            parsed_parent = UUID(parent_run_id)
        except (ValueError, AttributeError):
            return {"error": "invalid_uuid", "field": "parent_run_id"}

    valid_roles = {
        "orchestrator", "dispatcher", "implementer", "reviewer",
        "researcher", "tester", "security_agent", "repair_specialist",
        "curator", "observer",
    }
    if role_id and role_id not in valid_roles:
        return {"error": "invalid_role_id", "valid": sorted(valid_roles)}

    try:
        async with get_db_session() as session:
            return await bridge_run_create(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                project_id=UUID(project_id),
                ticket_id=str(parsed_ticket_id),
                purpose=purpose,
                role_id=role_id,
                parent_run_id=parsed_parent,
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




@mcp.tool()
async def ticket_comment(project_id: str, ticket_id: str, message: str) -> dict[str, Any]:
    """チケットにコメント (作業ログ) を追記。"""
    from uuid import UUID

    from backend.app.mcp.api_bridge import bridge_ticket_comment
    from backend.app.mcp.context import DEFAULT_SUPERINTENDENT_ACTOR_ID, DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            return await bridge_ticket_comment(
                session, tenant_id=DEFAULT_TENANT_ID, project_id=UUID(project_id),
                ticket_id=UUID(ticket_id), message=message, actor_id=DEFAULT_SUPERINTENDENT_ACTOR_ID,
            )
    except Exception as e:
        return {'error': str(type(e).__name__), 'ticket_id': ticket_id}


@mcp.tool()
async def ticket_link(
    project_id: str, source_ticket_id: str, target_ticket_id: str,
    relation_type: str = 'relates_to',
) -> dict[str, Any]:
    """チケット間の依存関係を作成。relation_type: blocks / blocked_by / relates_to / depends_on / duplicates"""
    from uuid import UUID

    from backend.app.mcp.api_bridge import bridge_ticket_link
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    valid_types = {'blocks', 'blocked_by', 'relates_to', 'depends_on', 'duplicates'}
    if relation_type not in valid_types:
        return {'error': 'invalid_relation_type', 'valid': sorted(valid_types)}
    try:
        async with get_db_session() as session:
            return await bridge_ticket_link(
                session, tenant_id=DEFAULT_TENANT_ID, project_id=UUID(project_id),
                source_ticket_id=UUID(source_ticket_id), target_ticket_id=UUID(target_ticket_id),
                relation_type=relation_type,
            )
    except Exception as e:
        return {'error': str(type(e).__name__)}


@mcp.tool()
async def run_list(project_id: str, limit: int = 20) -> dict[str, Any]:
    """プロジェクト内の AgentRun 一覧。"""
    from uuid import UUID

    from backend.app.mcp.api_bridge import bridge_run_list
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            return await bridge_run_list(
                session, tenant_id=DEFAULT_TENANT_ID, project_id=UUID(project_id), limit=limit,
            )
    except Exception as e:
        return {'error': str(type(e).__name__), 'runs': []}


@mcp.tool()
async def run_update(run_id: str, status: str, summary: str = "") -> dict[str, Any]:
    """AgentRun の状態を更新。status: running/completed/failed/blocked/gathering_context/generated_artifact"""
    from backend.app.mcp.api_bridge import bridge_run_update
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            result = await bridge_run_update(
                session, tenant_id=DEFAULT_TENANT_ID, run_id=UUID(run_id),
                status=status, summary=summary,
            )
            if result.get("new_status") in ("completed", "failed"):
                try:
                    from backend.app.mcp.discord_notify import notify_run_completed
                    await notify_run_completed(run_id, status, summary)
                except Exception:  # noqa: S110
                    logging.getLogger(__name__).debug("Discord notification skipped")
            return result
    except (ValueError, AttributeError):
        return {"error": "invalid_uuid", "field": "run_id"}
    except Exception as e:
        return {"error": str(type(e).__name__), "run_id": run_id}


@mcp.tool()
async def approval_request_create(
    project_id: str, ticket_id: str, action_class: str = "repo_write",
) -> dict[str, Any]:
    """承認リクエストを作成。AI agent は作成のみ可能 (決裁は human-only)。"""
    from backend.app.mcp.api_bridge import bridge_approval_request_create
    from backend.app.mcp.context import DEFAULT_SUPERINTENDENT_ACTOR_ID, DEFAULT_TENANT_ID, get_db_session

    forbidden = {"merge", "deploy", "secret_access", "approval_decide"}
    if action_class in forbidden:
        return {"error": "forbidden_action", "action_class": action_class}

    try:
        async with get_db_session() as session:
            result = await bridge_approval_request_create(
                session, tenant_id=DEFAULT_TENANT_ID, project_id=UUID(project_id),
                ticket_id=ticket_id, action_class=action_class,
                requester_actor_id=DEFAULT_SUPERINTENDENT_ACTOR_ID,
            )
            try:
                from backend.app.mcp.discord_notify import notify_approval_needed
                await notify_approval_needed(action_class, ticket_id[:8])
            except Exception:  # noqa: S110
                logging.getLogger(__name__).debug("Discord notification skipped")
            return result
    except (ValueError, AttributeError):
        return {"error": "invalid_uuid"}
    except Exception as e:
        return {"error": str(type(e).__name__), "message": str(e)[:200]}



@mcp.tool()
async def delegation_create(
    project_id: str, parent_run_id: str, ticket_id: str,
    purpose: str, role_id: str, task_spec: str = "{}",
) -> dict[str, Any]:
    """タスク委譲を作成。親 run から子 run を spawn し、task_spec で指示を送る。"""
    import json as json_mod

    from backend.app.mcp.api_bridge import bridge_delegation_create
    from backend.app.mcp.context import DEFAULT_SUPERINTENDENT_ACTOR_ID, DEFAULT_TENANT_ID, get_db_session

    valid_roles = {
        "orchestrator", "dispatcher", "implementer", "reviewer",
        "researcher", "tester", "security_agent", "repair_specialist",
        "curator", "observer",
    }
    if role_id not in valid_roles:
        return {"error": "invalid_role_id", "valid": sorted(valid_roles)}

    try:
        spec = json_mod.loads(task_spec) if isinstance(task_spec, str) else task_spec
    except json_mod.JSONDecodeError:
        return {"error": "invalid_json", "field": "task_spec"}

    try:
        async with get_db_session() as session:
            return await bridge_delegation_create(
                session, tenant_id=DEFAULT_TENANT_ID, project_id=UUID(project_id),
                parent_run_id=UUID(parent_run_id), ticket_id=ticket_id,
                purpose=purpose, role_id=role_id, task_spec=spec,
                sender_actor_id=DEFAULT_SUPERINTENDENT_ACTOR_ID,
            )
    except (ValueError, AttributeError):
        return {"error": "invalid_uuid"}
    except Exception as e:
        return {"error": str(type(e).__name__), "message": str(e)[:200]}


@mcp.tool()
async def delegation_inbox(run_id: str, limit: int = 20) -> dict[str, Any]:
    """自分宛の未処理タスク一覧 (consumed_at IS NULL)。"""
    from backend.app.mcp.api_bridge import bridge_delegation_inbox
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            return await bridge_delegation_inbox(
                session, tenant_id=DEFAULT_TENANT_ID, run_id=UUID(run_id), limit=limit,
            )
    except (ValueError, AttributeError):
        return {"error": "invalid_uuid", "field": "run_id"}
    except Exception as e:
        return {"error": str(type(e).__name__), "messages": []}



@mcp.tool()
async def delegation_accept(run_id: str, message_id: str) -> dict[str, Any]:
    """委譲されたタスクを受諾。run を running に遷移し、メッセージを consumed にする。"""
    from backend.app.mcp.api_bridge import bridge_delegation_accept
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            return await bridge_delegation_accept(
                session, tenant_id=DEFAULT_TENANT_ID,
                run_id=UUID(run_id), message_id=UUID(message_id),
            )
    except (ValueError, AttributeError):
        return {"error": "invalid_uuid"}
    except Exception as e:
        return {"error": str(type(e).__name__), "message": str(e)[:200]}


@mcp.tool()
async def delegation_submit(
    run_id: str, parent_run_id: str, project_id: str,
    result_status: str = "completed", result_summary: str = "",
    result_spec: str = "{}",
) -> dict[str, Any]:
    """タスク結果を親に提出。result_status: completed / failed / needs_review。"""
    import json as json_mod

    from backend.app.mcp.api_bridge import bridge_delegation_submit
    from backend.app.mcp.context import DEFAULT_SUPERINTENDENT_ACTOR_ID, DEFAULT_TENANT_ID, get_db_session

    try:
        spec = json_mod.loads(result_spec) if isinstance(result_spec, str) else result_spec
    except json_mod.JSONDecodeError:
        return {"error": "invalid_json", "field": "result_spec"}

    try:
        async with get_db_session() as session:
            result = await bridge_delegation_submit(
                session, tenant_id=DEFAULT_TENANT_ID,
                run_id=UUID(run_id), parent_run_id=UUID(parent_run_id),
                project_id=UUID(project_id),
                result_status=result_status, result_summary=result_summary,
                result_spec=spec, actor_id=DEFAULT_SUPERINTENDENT_ACTOR_ID,
            )
            if result.get("submitted") and result_status in ("completed", "failed"):
                try:
                    from backend.app.mcp.discord_notify import notify_run_completed
                    await notify_run_completed(run_id, result_status, result_summary)
                except Exception:  # noqa: S110
                    logging.getLogger(__name__).debug("Discord notification skipped")
            return result
    except (ValueError, AttributeError):
        return {"error": "invalid_uuid"}
    except Exception as e:
        return {"error": str(type(e).__name__), "message": str(e)[:200]}


@mcp.tool()
async def delegation_review(
    run_id: str, reviewer_run_id: str,
    decision: str = "adopt", quality_score: float = 0.8,
    findings: str = "",
) -> dict[str, Any]:
    """レビュー結果を記録。decision: adopt / reject。quality_score: 0.0-1.0。"""
    from backend.app.mcp.api_bridge import bridge_delegation_review
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            return await bridge_delegation_review(
                session, tenant_id=DEFAULT_TENANT_ID,
                run_id=UUID(run_id), reviewer_run_id=UUID(reviewer_run_id),
                decision=decision, quality_score=quality_score, findings=findings,
            )
    except (ValueError, AttributeError):
        return {"error": "invalid_uuid"}
    except Exception as e:
        return {"error": str(type(e).__name__), "message": str(e)[:200]}



@mcp.tool()
async def delegation_tree(run_id: str) -> dict[str, Any]:
    """N 階層の delegation ツリーを表示 (再帰的 CTE)。"""
    from backend.app.mcp.api_bridge import bridge_delegation_tree
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            return await bridge_delegation_tree(
                session, tenant_id=DEFAULT_TENANT_ID, root_run_id=UUID(run_id),
            )
    except (ValueError, AttributeError):
        return {"error": "invalid_uuid", "field": "run_id"}
    except Exception as e:
        return {"error": str(type(e).__name__)}


@mcp.tool()
async def delegation_cancel(run_id: str) -> dict[str, Any]:
    """delegation をキャンセル (子 run も再帰的に cancelled)。"""
    from backend.app.mcp.api_bridge import bridge_delegation_cancel
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    try:
        async with get_db_session() as session:
            return await bridge_delegation_cancel(
                session, tenant_id=DEFAULT_TENANT_ID, run_id=UUID(run_id),
            )
    except (ValueError, AttributeError):
        return {"error": "invalid_uuid", "field": "run_id"}
    except Exception as e:
        return {"error": str(type(e).__name__)}



@mcp.tool()
async def workflow_status(project_id: str = "") -> dict[str, Any]:
    """全体のワークフロー進捗サマリー。project_id 省略で全プロジェクト横断。"""
    from backend.app.mcp.api_bridge import bridge_workflow_status
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    parsed_pid = None
    if project_id:
        try:
            parsed_pid = UUID(project_id)
        except (ValueError, AttributeError):
            return {"error": "invalid_uuid", "field": "project_id"}

    try:
        async with get_db_session() as session:
            return await bridge_workflow_status(
                session, tenant_id=DEFAULT_TENANT_ID, project_id=parsed_pid,
            )
    except Exception as e:
        return {"error": str(type(e).__name__)}



@mcp.tool()
async def run_cost(
    run_id: str, cost_usd: float = 0.0,
    tokens_input: int = 0, tokens_output: int = 0,
) -> dict[str, Any]:
    """AgentRun のコスト・トークン使用量を記録。"""
    import math

    from backend.app.mcp.api_bridge import bridge_run_cost
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    if not math.isfinite(cost_usd) or cost_usd < 0:
        return {"error": "invalid_cost", "message": "cost_usd must be finite and non-negative"}
    if tokens_input < 0 or tokens_output < 0:
        return {"error": "invalid_tokens", "message": "tokens must be non-negative"}

    try:
        async with get_db_session() as session:
            return await bridge_run_cost(
                session, tenant_id=DEFAULT_TENANT_ID, run_id=UUID(run_id),
                cost_usd=cost_usd, tokens_input=tokens_input, tokens_output=tokens_output,
            )
    except (ValueError, AttributeError):
        return {"error": "invalid_uuid", "field": "run_id"}
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
    from backend.app.services.superintendent.agent_spawner import SpawnedAgent, _active_agents
    _active_agents[agent_id] = SpawnedAgent(
        agent_id=agent_id, provider=provider,
    )
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
    from backend.app.mcp.context import DEFAULT_SUPERINTENDENT_ACTOR_ID, DEFAULT_TENANT_ID, get_db_session
    from backend.app.services.superintendent.delegation_policy import POLICY_TEMPLATES
    from backend.app.services.superintendent.dispatch import DispatchRequest, evaluate_dispatch

    try:
        parsed_agent_id = UUID(agent_id)
    except (ValueError, AttributeError):
        return {"error": "invalid_uuid", "field": "agent_id"}

    policy = POLICY_TEMPLATES["conservative"]
    request = DispatchRequest(
        superintendent_id=DEFAULT_SUPERINTENDENT_ACTOR_ID,
        agent_id=parsed_agent_id,
        ticket_id=ticket_id,
        project_id=UUID(project_id),
        action_class=action_class,
        risk_level={
            "read_only": "low", "task_write": "low",
            "repo_write": "medium", "pr_open": "medium",
        }.get(action_class, "high"),
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

    if not result.needs_human_approval:
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
                from backend.app.mcp.discord_notify import notify_dispatch
                await notify_dispatch(agent_id, ticket_id[:8], action_class)
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

    try:
        async with get_db_session() as session:
            from backend.app.mcp.api_bridge import bridge_run_create
            run_result = await bridge_run_create(
                session, tenant_id=DEFAULT_TENANT_ID,
                project_id=UUID(project_id), ticket_id=ticket_id,
                purpose=f"superintendent dispatch (awaiting approval): {action_class}",
            )
    except Exception:
        run_result = {}
    try:
        from backend.app.mcp.discord_notify import notify_approval_needed
        await notify_approval_needed(action_class, ticket_id[:8])
    except Exception:  # noqa: S110
        logging.getLogger(__name__).debug("Discord notification skipped")
    return {
        "dispatched": True,
        "agent_id": agent_id,
        "ticket_id": ticket_id,
        "run_id": run_result.get("run_id"),
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
