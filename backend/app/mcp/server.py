"""TaskManagedAI MCP Server — stdio transport, 39 tools (all DB-wired).

Security invariants:
- approval_decide is human-only (not exposed)
- server-owned fields resolved from session, never from input
- raw secret / provider key never in tool response
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from fastmcp import FastMCP

if TYPE_CHECKING:
    from backend.app.services.superintendent.agent_spawner import SpawnedAgent

# _safe_uuid removed (H-1 fix): callers use UUID() directly with error handling

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _mcp_lifespan(_server: FastMCP) -> AsyncIterator[None]:
    """SP-PHASE1 B4 §5: MCP server (agent を spawn する host process) に supervisor loop を配線する。

    MCP ``superintendent_agent_start`` が起動した subprocess を、本 process の hybrid supervisor が
    emergency-stop engage 時に cross-process kill する (A-2「同一 host の supervisor のみ kill」)。
    Redis wake (即時) + DB latch poll (権威 fallback、Redis 障害でも kill 不能にしない) の hybrid。
    """
    from backend.app.services.superintendent.supervisor import (
        build_default_supervisor,
        start_supervisor_background_task,
    )

    supervisor = build_default_supervisor()
    task = start_supervisor_background_task(supervisor)
    logger.info("mcp_supervisor_started")
    try:
        yield
    finally:
        supervisor.stop()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        logger.info("mcp_supervisor_stopped")


mcp = FastMCP(
    "TaskManagedAI",
    instructions=(
        "TaskManagedAI は AI-native な開発タスク管理ツールです。"
        "チケット作成、AI 実行管理、承認ワークフロー、監査ログを統合管理します。"
        "approval_decide は human-only です。AI agent は承認要求の作成のみ可能です。"
    ),
    lifespan=_mcp_lifespan,
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
    from backend.app.domain.agent_runtime.active_scope import soft_deleted_ticket_run_exclusion
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session

    # ADR-00037 R12/R13/R15 (Codex adversarial): soft-deleted ticket bound の run を KPI 集計から
    # 除外する (全 read path active-scope の共通 predicate)。ticket-less run は含む。
    active_run = soft_deleted_ticket_run_exclusion()
    # SP-029 (ADR-00055 §8、Codex R10 F-2): production KPI は shadow run を除外する
    # (kpi_show の success_rate / total / completed / failed に shadow completed/failed を
    # 混入させない、REST cost_summary / eval KPI と同じ run_mode='production' active-scope)。
    production_only = AgentRun.run_mode == "production"

    try:
        async with get_db_session() as session:
            total_runs = (await session.execute(
                select(sa.func.count()).select_from(AgentRun).where(
                    AgentRun.tenant_id == DEFAULT_TENANT_ID, active_run, production_only
                )
            )).scalar() or 0
            completed = (await session.execute(
                select(sa.func.count()).select_from(AgentRun).where(
                    AgentRun.tenant_id == DEFAULT_TENANT_ID,
                    AgentRun.status == "completed",
                    active_run,
                    production_only,
                )
            )).scalar() or 0
            failed = (await session.execute(
                select(sa.func.count()).select_from(AgentRun).where(
                    AgentRun.tenant_id == DEFAULT_TENANT_ID,
                    AgentRun.status == "failed",
                    active_run,
                    production_only,
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
    from backend.app.services.superintendent.emergency_stop import EmergencyStopEngagedError

    try:
        async with get_db_session() as session:
            result = await bridge_ticket_create(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                project_id=UUID(project_id),
                title=title,
                description=description,
                idempotency_key=idempotency_key,
            )
            # ADR-00049 (Codex F-O1): 外部 side-effect (Discord 通知) も idempotent にする。
            # 真の新規作成時のみ通知する: ticket_id があり、error でなく、idempotent_replay でない。
            # 同一 idempotency_key の retry/replay や error dict 返却では通知を発火させない
            # (downstream automation が「新規 ticket」と誤認する重複を防ぐ)。
            #
            # Codex F-O2 への判定 (reject outbox / 事実 document): Discord 通知は **best-effort**
            # (下の try/except が失敗を silent に log、元から配信保証なし)。commit 後に通知が失敗し、
            # その後 replay されると本 gate で通知が抑止され通知は届かない。これは idempotency が
            # 保証する対象 (= DB resource の重複防止、F-L4 integrity) の外側であり、convenience な
            # Discord ping のために outbox + worker を導入するのは過剰と判断し reject。通知が将来
            # critical な automation trigger になる場合は ticket 作成 transaction 内 outbox 化を要検討。
            if (
                result.get("ticket_id")
                and not result.get("error")
                and not result.get("idempotent_replay")
            ):
                try:
                    from backend.app.mcp.discord_notify import notify_ticket_created
                    await notify_ticket_created(title, project_id[:8])
                except Exception:  # noqa: S110
                    logging.getLogger(__name__).debug("Discord notification skipped")
            return result
    except EmergencyStopEngagedError as e:
        # P2-4: kill-switch deny を stable application code で返す (generic internal error と区別)。
        return {"error": e.reason_code, "message": str(e)[:200]}
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
    from backend.app.services.superintendent.emergency_stop import EmergencyStopEngagedError

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
    except EmergencyStopEngagedError as e:
        return {"error": e.reason_code, "ticket_id": ticket_id}
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
    """AI 実行 (AgentRun) を開始。role_id で役割指定、parent_run_id で親子関係構築。

    SP-029 (ADR-00055): shadow run_mode は backend plumbing 完成済だが、shadow terminal
    を駆動する runtime worker (Sprint 6+) が未実装のため **MCP 表面には未公開** (公開すると
    schema_validated で stuck する。production run も同様に runtime 駆動待ち)。shadow run の
    作成は internal `bridge_run_create(run_mode='shadow')` + `shadow_mode_enabled` 経由のみ
    (runtime driver と同時に公開する、Codex SP-029 R5 F-1)。
    """
    from backend.app.mcp.api_bridge import bridge_run_create
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session
    from backend.app.services.superintendent.emergency_stop import EmergencyStopEngagedError

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
                idempotency_key=idempotency_key,
            )
    except EmergencyStopEngagedError as e:
        return {"error": e.reason_code, "message": str(e)[:200]}
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
    from backend.app.services.superintendent.emergency_stop import EmergencyStopEngagedError

    try:
        async with get_db_session() as session:
            return await bridge_ticket_comment(
                session, tenant_id=DEFAULT_TENANT_ID, project_id=UUID(project_id),
                ticket_id=UUID(ticket_id), message=message, actor_id=DEFAULT_SUPERINTENDENT_ACTOR_ID,
            )
    except EmergencyStopEngagedError as e:
        return {'error': e.reason_code, 'ticket_id': ticket_id}
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
    from backend.app.services.superintendent.emergency_stop import EmergencyStopEngagedError

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
    except EmergencyStopEngagedError as e:
        return {'error': e.reason_code}
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
    from backend.app.services.superintendent.emergency_stop import EmergencyStopEngagedError

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
    except EmergencyStopEngagedError as e:
        return {"error": e.reason_code, "run_id": run_id}
    except Exception as e:
        return {"error": str(type(e).__name__), "run_id": run_id}


@mcp.tool()
async def approval_request_create(
    project_id: str, ticket_id: str, action_class: str = "repo_write",
) -> dict[str, Any]:
    """承認リクエストを作成。AI agent は作成のみ可能 (決裁は human-only)。"""
    from backend.app.mcp.api_bridge import bridge_approval_request_create
    from backend.app.mcp.context import DEFAULT_SUPERINTENDENT_ACTOR_ID, DEFAULT_TENANT_ID, get_db_session
    from backend.app.services.superintendent.emergency_stop import EmergencyStopEngagedError

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
    except EmergencyStopEngagedError as e:
        return {"error": e.reason_code, "message": str(e)[:200]}
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
    from backend.app.services.superintendent.emergency_stop import EmergencyStopEngagedError

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
    except EmergencyStopEngagedError as e:
        return {"error": e.reason_code, "message": str(e)[:200]}
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
    from backend.app.services.superintendent.emergency_stop import EmergencyStopEngagedError

    try:
        async with get_db_session() as session:
            return await bridge_delegation_accept(
                session, tenant_id=DEFAULT_TENANT_ID,
                run_id=UUID(run_id), message_id=UUID(message_id),
            )
    except (ValueError, AttributeError):
        return {"error": "invalid_uuid"}
    except EmergencyStopEngagedError as e:
        return {"error": e.reason_code, "message": str(e)[:200]}
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
    from backend.app.services.superintendent.emergency_stop import EmergencyStopEngagedError

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
    except EmergencyStopEngagedError as e:
        return {"error": e.reason_code, "message": str(e)[:200]}
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
    from backend.app.services.superintendent.emergency_stop import EmergencyStopEngagedError

    try:
        async with get_db_session() as session:
            return await bridge_delegation_review(
                session, tenant_id=DEFAULT_TENANT_ID,
                run_id=UUID(run_id), reviewer_run_id=UUID(reviewer_run_id),
                decision=decision, quality_score=quality_score, findings=findings,
            )
    except (ValueError, AttributeError):
        return {"error": "invalid_uuid"}
    except EmergencyStopEngagedError as e:
        return {"error": e.reason_code, "message": str(e)[:200]}
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
    from backend.app.services.superintendent.emergency_stop import EmergencyStopEngagedError

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
    except EmergencyStopEngagedError as e:
        return {"error": e.reason_code, "run_id": run_id}
    except Exception as e:
        return {"error": str(type(e).__name__), "run_id": run_id}

# --- Superintendent tools (SP-035) ---


@mcp.tool()
async def superintendent_agent_register(
    role_id: str, project_id: str, provider: str = "claude"
) -> dict[str, Any]:
    """Agent を登録して role を割り当てる。provider: claude / codex / custom。

    **B5a (B4 M4 fix)**: 本 ``_register`` は process spawn しない in-process 登録 step だが、
    emergency-stop latch engaged 中の **新規 agent 登録を deny** する (kill switch の新規活動 deny 完備、
    B4 M4 defer 分を閉じる)。latch check は DB を読むため session を取得し、共有 helper
    ``assert_not_emergency_stopped`` を通す。

    **P2-6 (Codex adversarial、TOCTOU 解消)**: latch check の session を ``_active_agents`` 登録の **前**
    に閉じると、「latch check (engaged なし) → session close → engage → ``_active_agents`` append」の窓で
    engage 直後でも ``state='registered'`` を返してしまう。よって spawn (A-1) と **同一 helper・同一
    advisory lock key** の ``acquire_emergency_stop_lock`` を latch check の前に取得し、**lock 保持下で
    latch check → ``_active_agents`` append → ``session.commit()``** を 1 critical section にまとめる
    (registration が latch check と同一 lock-held window に入る)。engage は同一 key の lock を取るため、
    本 critical section 中の engage は待たされ、register は engage 完了後の latch を必ず観測して deny する。

    - **sessionless deny (fail-closed)**: session 取得失敗 = latch 確認不能 → 登録拒否。
    - **latch engaged deny**: ``EmergencyStopEngagedError`` を ``state='denied'`` 応答へ畳む。

    実 subprocess の起動と cross-process kill 配線は ``superintendent_agent_start`` (managed 経路、P1-1
    解消済) が担う。``_register`` は DB registry row を作らない (in-process ``_active_agents`` 登録のみ)。
    """
    if provider not in ("claude", "codex", "custom"):
        return {"error": "invalid_provider", "valid": ["claude", "codex", "custom"]}

    from datetime import UTC, datetime
    from uuid import UUID, uuid4

    from backend.app.mcp.context import DEFAULT_SUPERINTENDENT_ACTOR_ID, DEFAULT_TENANT_ID, get_db_session
    from backend.app.services.superintendent.agent_spawner import (
        AgentProvider,
        SpawnedAgent,
        _active_agents,
    )
    from backend.app.services.superintendent.emergency_stop import (
        EmergencyStopEngagedError,
        acquire_emergency_stop_lock,
        assert_not_emergency_stopped,
    )
    from backend.app.services.superintendent.lifecycle import ManagedAgent

    agent_id = uuid4()
    # P2-6: lock 保持下で latch check → _active_agents append → commit を 1 critical section に入れる。
    # sessionless = latch 確認不能 = 登録拒否 (fail-closed、agent_start と同方針)。
    try:
        async with get_db_session() as session:
            # P2-6: spawn と同一 key の advisory lock を latch check の **前** に取得 (TOCTOU 解消)。
            # lock は transaction-scoped のため下の commit まで保持され registration を覆う。
            await acquire_emergency_stop_lock(session, DEFAULT_TENANT_ID)
            try:
                await assert_not_emergency_stopped(session, DEFAULT_TENANT_ID)
            except EmergencyStopEngagedError:
                return {
                    "role_id": role_id,
                    "project_id": project_id,
                    "state": "denied",
                    "error": "emergency_stop_engaged",
                }
            ManagedAgent(
                agent_id=agent_id,
                actor_id=DEFAULT_SUPERINTENDENT_ACTOR_ID,
                role_id=role_id,
                state="registered",
                project_id=UUID(project_id),
                superintendent_id=DEFAULT_SUPERINTENDENT_ACTOR_ID,
                created_at=datetime.now(UTC),
            )
            # provider は上で {claude,codex,custom} に検証済 → AgentProvider literal への cast は安全。
            # P2-6: registration を latch check と同一 lock-held critical section 内で行う
            # (engage 直後の register を確実に deny する)。
            _active_agents[agent_id] = SpawnedAgent(
                agent_id=agent_id, provider=cast(AgentProvider, provider),
            )
            # commit で advisory lock を解放する (lock-held critical section の終端)。
            await session.commit()
    except Exception as e:
        return {"role_id": role_id, "state": "failed", "error": str(type(e).__name__)}

    return {
        "agent_id": str(agent_id),
        "role_id": role_id,
        "provider": provider,
        "state": "registered",
        "project_id": project_id,
    }


def _kill_spawned_orphan(agent: SpawnedAgent) -> None:
    """B4 LOW-4: commit 失敗で committed row を失った live subprocess を killpg で始末する。

    spawn は成功 (process 起動 + mark_running) したが ``session.commit()`` が freeze gate 等で reject
    された場合、DB 行は rollback で消えるが live process は残る = supervisor から見えない unkillable
    orphan。本 helper が起動済 process group を SIGKILL して orphan を残さない (best-effort、既に死亡 /
    pid 不明は no-op)。``spawn_agent_managed`` 内 compensating path と同 semantics。
    """
    import os
    import signal

    proc = agent.process
    if proc is None or proc.pid is None or proc.returncode is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass
    logging.getLogger(__name__).error(
        "agent_start_commit_failed_orphan_killed (live subprocess killed; row rolled back)",
        extra={"agent_id": str(agent.agent_id)},
    )


@mcp.tool()
async def superintendent_agent_start(
    agent_id: str,
    project_id: str,
    provider: str = "claude",
) -> dict[str, Any]:
    """Agent プロセスを起動する。Claude Code / Codex を DB-backed managed spawn で subprocess 化。

    SP-PHASE1 B4 (P1-1 fix): legacy ``spawn_agent`` (sessionless、latch 未確認 = fail-open) から
    ``spawn_agent_managed`` (A-1 ordering + advisory lock + latch fail-closed deny + ``managed_agents``
    登録) へ移行。これで本経路の agent が (a) emergency-stop latch engaged 中は **deny** (fail-closed)、
    (b) ``managed_agents`` 登録で cross-process supervisor から kill 可能になる。

    - **sessionless deny (fail-closed)**: DB session を取得できない場合は latch を確認できないため起動を
      **拒否** する (sessionless = latch 確認不能 = 起動拒否)。
    - **latch engaged deny**: ``spawn_agent_managed`` 内の latch check が engaged を観測したら
      ``EmergencyStopEngagedError`` を raise し、本 tool は ``state='denied'`` を返す。
    - **commit 境界**: ``spawn_agent_managed`` は commit しない (A-1)。本 tool が同一 transaction を
      commit し、advisory lock を spawn 完了まで保持する。
    - **P2-5: ``project_id`` は必須 (default fallback なし)**。default project への暗黙 fallback を許すと、
      非 default project に register した agent が ``project_id`` 省略時に wrong project (default) で spawn
      され managed_agents row が誤 project になる。caller は register と同一 project を明示する。
    - **P2-3: archived project は deny (active-scope)**。spawn は work-initiation のため、他経路と同様
      ``status='active'`` を要求する (archived project への subprocess 起動 + child row 作成を防ぐ)。
    """
    import sqlalchemy as sa

    from backend.app.db.models.project import Project
    from backend.app.mcp.context import DEFAULT_TENANT_ID, get_db_session
    from backend.app.services.superintendent.agent_spawner import (
        default_host_id,
        spawn_agent_managed,
    )
    from backend.app.services.superintendent.emergency_stop import (
        EmergencyStopEngagedError,
    )
    from backend.app.services.superintendent.managed_agent_registry import (
        ManagedAgentRegistry,
    )

    if provider not in ("claude", "codex", "custom"):
        return {"error": "invalid_provider", "valid": ["claude", "codex", "custom"]}

    try:
        parsed_agent_id = UUID(agent_id)
        parsed_project_id = UUID(project_id)
    except (ValueError, AttributeError):
        return {"agent_id": agent_id, "state": "failed", "error": "invalid_uuid"}

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())

    try:
        # sessionless deny: session 取得自体に失敗したら latch 確認不能 → 起動拒否 (fail-closed)。
        async with get_db_session() as session:
            try:
                # P2-3: project を実在 + **active** へ解決 (cross-tenant/不存在/archived は deny)。
                # status を取得し、None=不存在 / 'active' 以外=archived 等を区別する (active-scope)。
                project_status = await session.scalar(
                    sa.select(Project.status).where(
                        Project.tenant_id == DEFAULT_TENANT_ID,
                        Project.id == parsed_project_id,
                    )
                )
                if project_status is None:
                    return {
                        "agent_id": agent_id,
                        "state": "denied",
                        "error": "project_not_found",
                    }
                if project_status != "active":
                    # P2-3: archived 等の非 active project への spawn は deny (work-initiation freeze)。
                    return {
                        "agent_id": agent_id,
                        "state": "denied",
                        "error": "project_not_active",
                    }
                registry = ManagedAgentRegistry(session)
                try:
                    agent = await spawn_agent_managed(
                        agent_id=parsed_agent_id,
                        provider=cast(Any, provider),
                        project_dir=project_dir,
                        tenant_id=DEFAULT_TENANT_ID,
                        project_id=parsed_project_id,
                        registry=registry,
                        session=session,
                        host_id=default_host_id(),
                    )
                except EmergencyStopEngagedError:
                    # latch engaged: 新規活動 deny (fail-closed)。rollback して起動しない
                    # (advisory xact lock も rollback で解放)。
                    await session.rollback()
                    return {
                        "agent_id": agent_id,
                        "state": "denied",
                        "error": "emergency_stop_engaged",
                    }
                # A-1: spawn 完了 (running) まで保持した advisory lock を commit で解放する。
                # LOW-4 (adversarial review adopt): commit が freeze gate 等で reject されると、行は
                # rollback されるが live subprocess は残る (committed row 無しの unkillable orphan)。
                # commit 失敗時は起動済 live process を killpg で kill してから re-raise する。
                try:
                    await session.commit()
                except BaseException:
                    _kill_spawned_orphan(agent)
                    raise
            except BaseException:
                # M5 (adversarial review adopt): mid-spawn 例外でも transaction を明示 rollback し、
                # tenant advisory xact lock を解放する (自己 DoS = 以後の engage/spawn が lock 待ちで
                # 永久 block するのを防ぐ。session __aexit__ の close-rollback に依存しない)。
                with suppress(Exception):
                    await session.rollback()
                raise
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
    """Agent プロセスを停止する。

    SP-PHASE1 B4 (adversarial P2-1): managed spawn 経由で起動した agent は、process 停止後に
    ``managed_agents`` DB row を ``mark_terminal(stopped)`` する。これを怠ると通常 start→stop で row が
    ``state='running'`` 残留し、supervisor poll / ``list_active_on_host`` が死んだ process を active 扱い
    して stale / 再利用 pgid を signal し得る (P2-1 fail-open)。terminalize は best-effort で process 停止
    自体の成功は妨げない。
    """
    from uuid import UUID

    from backend.app.mcp.context import get_db_session
    from backend.app.services.superintendent.agent_spawner import stop_agent
    from backend.app.services.superintendent.managed_agent_registry import (
        ManagedAgentRegistry,
    )

    try:
        agent = await stop_agent(UUID(agent_id))
        if agent is None:
            return {"agent_id": agent_id, "state": "not_found"}
        # P2-1: managed row を terminalize (managed spawn 由来のみ。legacy / register は None)。
        if agent.managed_agent_id is not None and agent.tenant_id is not None:
            try:
                async with get_db_session() as session:
                    await ManagedAgentRegistry(session).mark_terminal(
                        tenant_id=agent.tenant_id,
                        managed_agent_id=agent.managed_agent_id,
                        state="stopped",
                    )
                    await session.commit()
            except Exception:  # noqa: BLE001 — terminalize 失敗でも process 停止は成立 (supervisor が回収)
                logging.getLogger(__name__).warning(
                    "agent_stop_managed_row_terminalize_failed",
                    extra={"agent_id": agent_id},
                )
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
    from backend.app.services.superintendent.emergency_stop import EmergencyStopEngagedError

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
        except EmergencyStopEngagedError as e:
            return {"error": e.reason_code, "dispatched": False, "ticket_id": ticket_id}
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
    except EmergencyStopEngagedError as e:
        return {"error": e.reason_code, "dispatched": False, "ticket_id": ticket_id}
    except Exception as e:
        # Codex adversarial R4: bridge_run_create の失敗 (guard 例外 ProjectArchivedError /
        # TicketNotActionableError を含む) を成功応答に変換しない。削除済 / archived ticket への
        # dispatch は error dict を返し、承認通知も dispatched:True も出さない (tool 境界で guard を
        # 尊重する)。
        return {"error": str(type(e).__name__), "dispatched": False, "ticket_id": ticket_id}
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
    from backend.app.services.superintendent.emergency_stop import EmergencyStopEngagedError

    try:
        async with get_db_session() as session:
            return await bridge_notification_resolve(
                session, tenant_id=DEFAULT_TENANT_ID, notification_id=UUID(notification_id)
            )
    except EmergencyStopEngagedError as e:
        return {"error": e.reason_code, "notification_id": notification_id}
    except Exception as e:
        return {"error": str(type(e).__name__), "notification_id": notification_id}


# SP-034 (ADR-00026): mutating tool の ingress guard (rate limit / max concurrent /
# max input bytes) を全 tool call に適用する。read tool は素通し、guard 内部エラーは fail-open。
from backend.app.mcp.middleware import MutationGuardMiddleware  # noqa: E402

mcp.add_middleware(MutationGuardMiddleware())
