"""MCP → FastAPI API bridge.

Resolves session context (tenant_id, actor_id, project_id) from
MCP server state and calls backend services directly.
Server-owned fields are never accepted from MCP tool input.
"""

from __future__ import annotations

import re
import time
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.audit_event import AuditEvent
from backend.app.repositories.ticket import (
    ProjectArchivedError,
    TicketNotActionableError,
    TicketRepository,
)

MAX_LIMIT = 200


def _clamp(limit: int, offset: int) -> tuple[int, int]:
    return min(max(1, limit), MAX_LIMIT), max(0, offset)


def _title_to_slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not slug:
        slug = "ticket"
    return f"{slug}-{int(time.time()) % 100000}"


async def bridge_ticket_list(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    from sqlalchemy import text as sa_text

    from backend.app.db.models.ticket import Ticket

    # Q-3 (ADR-00037): active scope。soft-deleted ticket は MCP の count / list からも除外する
    # (repository だけでなく直接 query 経路も active-scope を適用、read path 漏れ防止)。
    count_result = await session.execute(
        sa_text(
            "SELECT count(*) FROM tickets "
            "WHERE tenant_id = :tid AND project_id = :pid AND deleted_at IS NULL"
        ),
        {"tid": tenant_id, "pid": project_id},
    )
    total = count_result.scalar() or 0

    result = await session.execute(
        select(Ticket)
        .where(
            Ticket.tenant_id == tenant_id,
            Ticket.project_id == project_id,
            Ticket.deleted_at.is_(None),
        )
        .order_by(Ticket.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    tickets = result.scalars().all()
    clamped_limit, clamped_offset = _clamp(limit, offset)
    return {
        "tickets": [
            {
                "id": str(t.id),
                "title": t.title,
                "status": t.status,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tickets
        ],
        "total": total,
        "limit": clamped_limit,
        "offset": clamped_offset,
    }


async def bridge_ticket_create(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    title: str,
    description: str = "",
) -> dict[str, Any]:
    from backend.app.mcp.context import DEFAULT_SUPERINTENDENT_ACTOR_ID

    repo = TicketRepository(session)
    # Q-4 (ADR-00037 R5 #2): create_in_project は _assert_project_active を通るため、archived project
    # への MCP 経由 ticket create は ProjectArchivedError -> 409 で fail-closed になる (base create は
    # guard を通らないので使わない、全 mutation 境界で archive freeze を enforce)。
    ticket = await repo.create_in_project(
        tenant_id,
        project_id,
        {
            "title": title,
            "slug": _title_to_slug(title),
            "description": description,
            "status": "open",
            "created_by_actor_id": DEFAULT_SUPERINTENDENT_ACTOR_ID,
        },
    )
    await session.commit()
    return {
        "ticket_id": str(ticket.id),
        "title": ticket.title,
        "status": ticket.status,
    }


async def bridge_ticket_show(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    ticket_id: UUID,
) -> dict[str, Any]:
    repo = TicketRepository(session)
    ticket = await repo.get_in_project(
        tenant_id=tenant_id, project_id=project_id, ticket_id=ticket_id
    )
    if ticket is None:
        return {"error": "not_found", "ticket_id": str(ticket_id)}
    return {
        "id": str(ticket.id),
        "title": ticket.title,
        "slug": ticket.slug,
        "status": ticket.status,
        "description": ticket.description,
        "priority": ticket.priority,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
    }


async def bridge_ticket_update(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    ticket_id: UUID,
    payload: dict[str, Any],
) -> dict[str, Any]:
    repo = TicketRepository(session)
    ticket = await repo.update_in_project(
        tenant_id=tenant_id,
        project_id=project_id,
        ticket_id=ticket_id,
        payload=payload,
    )
    if ticket is None:
        return {"error": "not_found", "ticket_id": str(ticket_id)}
    await session.commit()
    return {
        "ticket_id": str(ticket.id),
        "title": ticket.title,
        "status": ticket.status,
        "updated": True,
    }


async def bridge_run_show(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID,
) -> dict[str, Any]:
    # ADR-00037 R15 (Codex adversarial): soft-deleted ticket bound の run は default show からも隠す
    # (全 read path active-scope)。除外条件込みで取得し、該当しなければ not_found (restore で復帰)。
    from backend.app.domain.agent_runtime.active_scope import soft_deleted_ticket_run_exclusion

    result = await session.execute(
        select(AgentRun).where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.id == run_id,
            soft_deleted_ticket_run_exclusion(),
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        return {"error": "not_found", "run_id": str(run_id)}
    # Fetch children runs
    # ADR-00037 R16 (Codex adversarial): children も active-scope を適用し、soft-deleted ticket bound の
    # child run の metadata を parent show 経由で漏らさない (直接 show は not_found なのに parent から
    # 列挙できる迂回を塞ぐ)。restore で再び現れる。
    children_result = await session.execute(
        select(AgentRun.id, AgentRun.status, AgentRun.role_id).where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.parent_run_id == run_id,
            soft_deleted_ticket_run_exclusion(),
        )
    )
    children = [
        {"run_id": str(c[0]), "status": c[1], "role_id": c[2]}
        for c in children_result.fetchall()
    ]

    # ADR-00037 R12: ticket_id は server-owned column (run.ticket_id) を正本にする
    # (event payload 依存を排除、untrusted payload の混入を防ぐ)。
    ticket_id = str(run.ticket_id) if run.ticket_id is not None else None

    return {
        "run_id": str(run.id),
        "project_id": str(run.project_id),
        "status": run.status,
        "blocked_reason": run.blocked_reason,
        "error_code": run.error_code,
        "role_id": run.role_id,
        "parent_run_id": str(run.parent_run_id) if run.parent_run_id else None,
        "ticket_id": ticket_id,
        "children": children,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


async def bridge_audit_list(
    session: AsyncSession,
    *,
    tenant_id: int,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    limit, offset = _clamp(limit, offset)
    count_result = await session.execute(
        select(sa.func.count()).select_from(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id
        )
    )
    total = count_result.scalar() or 0

    result = await session.execute(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    events = result.scalars().all()
    return {
        "events": [
            {
                "id": str(e.id),
                "event_type": e.event_type,
                "actor_id": str(e.actor_id) if e.actor_id else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def bridge_approval_list(
    session: AsyncSession,
    *,
    tenant_id: int,
    status: str = "pending",
) -> dict[str, Any]:
    from backend.app.repositories.approval_request import ApprovalRequestRepository
    from backend.app.services.policy.approval_active_scope import is_approval_target_actionable

    repo = ApprovalRequestRepository(session)
    approvals = await repo.list_by_status(tenant_id=tenant_id, status=status)
    # ADR-00037 R19 (Codex adversarial): MCP read path も HTTP inbox と同じ active-scope。soft-deleted
    # ticket / archived project に bound な stale approval を一覧から除外する (AI agent への露出も塞ぐ)。
    # 非 ticket resource_ref は対象外、restore で再表示。
    visible = []
    for a in approvals:
        if await is_approval_target_actionable(
            session, tenant_id=tenant_id, resource_ref=a.resource_ref
        ):
            visible.append(a)
    return {
        "approvals": [
            {
                "id": str(a.id),
                "action_class": a.action_class,
                "status": a.status,
                # ADR-00037 R19: ApprovalRequest は created_at を持たず requested_at が作成時刻
                # (pre-existing AttributeError を本 read path 修正と併せて解消)。
                "created_at": a.requested_at.isoformat() if a.requested_at else None,
            }
            for a in visible
        ],
        "status_filter": status,
    }


async def bridge_run_create(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    ticket_id: str,
    purpose: str,
    role_id: str | None = None,
    parent_run_id: UUID | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """AgentRun を作成する run/delegation/dispatch の chokepoint。

    ADR-00037 R20 (Codex adversarial): ``commit=False`` で呼ぶと commit せず flush に留め、
    ``assert_ticket_actionable`` が取得した project FOR UPDATE lock を **呼出側の transaction commit まで
    保持**する。`bridge_delegation_create` は child run 作成と inter_agent_messages INSERT を同一 lock 下の
    1 transaction で行い、child 作成後・message INSERT 前に concurrent な bulk_soft_delete / archive が割り込む
    TOCTOU を排除するために本 flag を使う。
    """
    from backend.app.db.models.agent_run_event import AgentRunEvent
    from backend.app.mcp.context import DEFAULT_SUPERINTENDENT_ACTOR_ID

    # Q-3/Q-4 (ADR-00037 / Codex adversarial R3): soft-deleted ticket / archived project への
    # 作業開始を拒否する。run_create は run/delegation/dispatch の chokepoint (bridge_delegation_create
    # と superintendent_dispatch は本関数経由) のため、ここで guard すれば 3 経路すべてが凍結される。
    await TicketRepository(session).assert_ticket_actionable(tenant_id, project_id, ticket_id)

    # ADR-00037 R17 (Codex adversarial): parent_run_id 指定時は parent run **自体** も actionable か
    # 検証する。run_create は parent_run_id を直接受け取り persist する chokepoint であり、ここで guard
    # しないと削除済 ticket bound parent に child を attach できる (delegation_create の R16 guard 迂回 +
    # silent resurrection)。parent 不在 / 削除済 ticket / archived は TicketNotActionableError /
    # ProjectArchivedError で reject (MCP wrapper が dict 化)。
    if parent_run_id is not None:
        parent = await session.scalar(
            select(AgentRun).where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.project_id == project_id,
                AgentRun.id == parent_run_id,
            )
        )
        if parent is None:
            # parent run が (tenant, project) に存在しない (FK でも弾かれるが明示的に早期 reject)。
            raise ValueError(
                f"parent run {parent_run_id} not found in project {project_id}"
            )
        await _assert_run_ticket_actionable(session, tenant_id=tenant_id, run=parent)

    # ADR-00037 R12: ticket binding を server-owned column へ記録する (assert_ticket_actionable で
    # 検証済みのため UUID parse は安全)。guard / KPI active-scope はこの column を直読みする。
    run = AgentRun(
        tenant_id=tenant_id,
        project_id=project_id,
        ticket_id=UUID(ticket_id),
        status="queued",
        role_id=role_id,
        role_scope="project" if role_id else None,
        parent_run_id=parent_run_id,
    )
    session.add(run)
    await session.flush()

    event = AgentRunEvent(
        tenant_id=tenant_id,
        run_id=run.id,
        seq_no=1,
        event_type="run_queued",
        event_payload={
            "ticket_id": ticket_id,
            "purpose": purpose,
            "project_id": str(project_id),
            "role_id": role_id,
            "parent_run_id": str(parent_run_id) if parent_run_id else None,
        },
        actor_id=DEFAULT_SUPERINTENDENT_ACTOR_ID,
    )
    session.add(event)
    if commit:
        await session.commit()
    else:
        # commit=False: lock を保持したまま呼出側 transaction に委ねる (run.id は flush 済)。
        await session.flush()
    return {
        "run_id": str(run.id),
        "status": run.status,
        "project_id": str(project_id),
        "ticket_id": ticket_id,
        "purpose": purpose,
        "role_id": role_id,
        "parent_run_id": str(parent_run_id) if parent_run_id else None,
    }


async def bridge_run_cancel(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID,
) -> dict[str, Any]:
    result = await session.execute(
        select(AgentRun).where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.id == run_id,
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        return {"error": "not_found", "run_id": str(run_id)}

    terminal = {"completed", "failed", "cancelled", "provider_refused", "repair_exhausted"}
    if run.status in terminal:
        return {"error": "already_terminal", "run_id": str(run_id), "status": run.status}

    run.status = "cancelled"
    run.blocked_reason = None
    await session.commit()
    return {"run_id": str(run.id), "status": "cancelled"}


async def bridge_approval_show(
    session: AsyncSession,
    *,
    tenant_id: int,
    approval_id: UUID,
) -> dict[str, Any]:
    from backend.app.repositories.approval_request import ApprovalRequestRepository
    from backend.app.services.policy.approval_active_scope import is_approval_target_actionable

    repo = ApprovalRequestRepository(session)
    approval = await repo.get_by_id(tenant_id=tenant_id, id=approval_id)
    if approval is None:
        return {"error": "not_found", "approval_id": str(approval_id)}
    # ADR-00037 R19 (Codex adversarial): soft-deleted ticket / archived project に bound な approval は
    # MCP show でも not_found 扱い (HTTP detail と同じ active-scope、restore で再表示)。
    if not await is_approval_target_actionable(
        session, tenant_id=tenant_id, resource_ref=approval.resource_ref
    ):
        return {"error": "not_found", "approval_id": str(approval_id)}
    return {
        "id": str(approval.id),
        "action_class": approval.action_class,
        "status": approval.status,
        # ADR-00037 R19: pre-existing AttributeError (requester_actor_id / decider_actor_id / created_at は
        # ApprovalRequest に存在しない) を本 read path 修正と併せて正しい列名へ訂正。
        "requester_actor_id": (
            str(approval.requested_by_actor_id) if approval.requested_by_actor_id else None
        ),
        "decider_actor_id": (
            str(approval.decided_by_actor_id) if approval.decided_by_actor_id else None
        ),
        "created_at": approval.requested_at.isoformat() if approval.requested_at else None,
    }


async def bridge_notification_list(
    session: AsyncSession,
    *,
    tenant_id: int,
    actor_id: UUID,
    limit: int = 20,
) -> dict[str, Any]:
    from backend.app.repositories.notification_event import NotificationEventRepository

    repo = NotificationEventRepository(session)
    events = await repo.list_for_recipient(
        tenant_id=tenant_id, recipient_actor_id=actor_id
    )
    limited = events[:limit]
    return {
        "notifications": [
            {
                "id": str(e.id),
                "event_type": e.event_type,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in limited
        ],
        "total": len(limited),
    }


async def bridge_notification_resolve(
    session: AsyncSession,
    *,
    tenant_id: int,
    notification_id: UUID,
) -> dict[str, Any]:
    from backend.app.repositories.notification_event import NotificationEventRepository

    repo = NotificationEventRepository(session)
    event = await repo.resolve(tenant_id=tenant_id, event_id=notification_id)
    if event is None:
        return {"error": "not_found", "notification_id": str(notification_id)}
    await session.commit()
    return {"notification_id": str(event.id), "resolved": True}


async def bridge_project_list(
    session: AsyncSession,
    *,
    tenant_id: int,
) -> dict[str, Any]:
    from backend.app.repositories.project import ProjectRepository

    repo = ProjectRepository(session)
    projects = await repo.list(tenant_id=tenant_id)
    return {
        "projects": [
            {
                "id": str(p.id),
                "slug": p.slug,
                "name": p.name,
                "status": p.status,
            }
            for p in projects
        ],
        "total": len(projects),
    }


async def bridge_context_auto(
    session: AsyncSession,
    *,
    tenant_id: int,
    cwd: str,
) -> dict[str, Any]:
    import os

    from backend.app.repositories.project import ProjectRepository

    repo = ProjectRepository(session)
    projects = await repo.list(tenant_id=tenant_id)

    dir_name = os.path.basename(cwd.rstrip("/"))
    dir_name_lower = dir_name.lower().replace("_", "-").replace(" ", "-")

    for p in projects:
        if p.slug == dir_name_lower or p.slug == dir_name:
            return {
                "project_id": str(p.id),
                "project_name": p.name,
                "project_slug": p.slug,
                "matched_by": "directory_name",
            }

    for p in projects:
        if dir_name_lower in p.slug or p.slug in dir_name_lower:
            return {
                "project_id": str(p.id),
                "project_name": p.name,
                "project_slug": p.slug,
                "matched_by": "partial_match",
            }

    return {"error": "no_matching_project", "cwd": cwd, "hint": "Use project_list to find available projects"}


async def bridge_ticket_list_all(
    session: AsyncSession,
    *,
    tenant_id: int,
    status: str = "open",
    limit: int = 50,
) -> dict[str, Any]:
    from sqlalchemy import text as sa_text

    limit = min(max(1, limit), MAX_LIMIT)
    # Q-3 (ADR-00037 / Codex adversarial R2 #2): cross-project list も active scope を強制する。
    # deleted_at IS NULL を欠くと bulk soft-delete 後に削除済 ticket を MCP agent に漏らし、
    # 「soft-deleted は全 default read path から除外」invariant を破る。
    result = await session.execute(
        sa_text("""
            SELECT t.id, t.title, t.status, t.priority, t.created_at,
                   p.slug as project_slug, p.name as project_name, p.id as project_id
            FROM tickets t
            JOIN projects p ON t.project_id = p.id AND t.tenant_id = p.tenant_id
            WHERE t.tenant_id = :tenant_id AND t.status = :status
              AND t.deleted_at IS NULL
            ORDER BY t.created_at DESC
            LIMIT :limit
        """),
        {"tenant_id": tenant_id, "status": status, "limit": limit},
    )
    rows = result.fetchall()
    return {
        "tickets": [
            {
                "id": str(r[0]),
                "title": r[1],
                "status": r[2],
                "priority": r[3],
                "created_at": r[4].isoformat() if r[4] else None,
                "project_slug": r[5],
                "project_name": r[6],
                "project_id": str(r[7]),
            }
            for r in rows
        ],
        "total": len(rows),
        "status_filter": status,
    }


async def bridge_ticket_search(
    session: AsyncSession,
    *,
    tenant_id: int,
    query: str,
    limit: int = 20,
) -> dict[str, Any]:
    from sqlalchemy import text as sa_text

    query = query[:200]
    search_pattern = f"%{query}%"
    # Q-3 (ADR-00037 / Codex adversarial R2 #2): search も active scope を強制 (soft-deleted を除外)。
    result = await session.execute(
        sa_text("""
            SELECT t.id, t.title, t.status, t.priority, t.created_at,
                   p.slug as project_slug, p.name as project_name, p.id as project_id
            FROM tickets t
            JOIN projects p ON t.project_id = p.id AND t.tenant_id = p.tenant_id
            WHERE t.tenant_id = :tenant_id AND t.title ILIKE :pattern
              AND t.deleted_at IS NULL
            ORDER BY t.created_at DESC
            LIMIT :limit
        """),
        {"tenant_id": tenant_id, "pattern": search_pattern, "limit": limit},
    )
    rows = result.fetchall()
    return {
        "tickets": [
            {
                "id": str(r[0]),
                "title": r[1],
                "status": r[2],
                "priority": r[3],
                "created_at": r[4].isoformat() if r[4] else None,
                "project_slug": r[5],
                "project_name": r[6],
                "project_id": str(r[7]),
            }
            for r in rows
        ],
        "total": len(rows),
        "query": query,
    }


async def bridge_ticket_comment(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    ticket_id: UUID,
    message: str,
    actor_id: UUID,
) -> dict[str, Any]:
    from backend.app.repositories.notification_event import NotificationEventRepository

    # Q-3/Q-4 (ADR-00037 / Codex adversarial R4 #2): 削除済 ticket / archived project への comment
    # (作業ログ相当 event) を拒否する。notification_events は ticket FK を持たないため、guard が
    # 無いと削除済/存在しない/凍結 ticket にイベントを作れてしまう。
    await TicketRepository(session).assert_ticket_actionable(
        tenant_id, project_id, str(ticket_id)
    )

    repo = NotificationEventRepository(session)
    event = await repo.append(
        tenant_id=tenant_id,
        event_type="ticket_comment",
        payload={
            "project_id": str(project_id),
            "ticket_id": str(ticket_id),
            "message": message,
        },
        recipient_actor_id=actor_id,
    )
    await session.commit()
    return {
        "comment_id": str(event.id),
        "ticket_id": str(ticket_id),
        "message": message,
    }


async def bridge_ticket_link(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    source_ticket_id: UUID,
    target_ticket_id: UUID,
    relation_type: str,
) -> dict[str, Any]:
    from backend.app.repositories.ticket_relation import TicketRelationRepository

    repo = TicketRelationRepository(session)
    # Codex adversarial R5 #2: create_in_project の正しい signature (payload= は存在せず実行時
    # TypeError になっていた pre-existing bug を修正)。soft-deleted / archived guard は repository が
    # source/target の active + project active を検証する。
    relation = await repo.create_in_project(
        tenant_id=tenant_id,
        project_id=project_id,
        source_id=source_ticket_id,
        target_id=target_ticket_id,
        relation_type=relation_type,
    )
    await session.commit()
    return {
        "relation_id": str(relation.id),
        "source_ticket_id": str(source_ticket_id),
        "target_ticket_id": str(target_ticket_id),
        "relation_type": relation_type,
    }


async def bridge_run_list(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    limit: int = 20,
) -> dict[str, Any]:
    # ADR-00037 R15 (Codex adversarial): soft-deleted ticket bound の run を default 一覧から除外する
    # (全 read path active-scope)。ticket-less run は含む、restore で復帰。
    from backend.app.domain.agent_runtime.active_scope import soft_deleted_ticket_run_exclusion

    result = await session.execute(
        select(AgentRun)
        .where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.project_id == project_id,
            soft_deleted_ticket_run_exclusion(),
        )
        .order_by(AgentRun.created_at.desc())
        .limit(min(max(1, limit), MAX_LIMIT))
    )
    runs = result.scalars().all()
    return {
        "runs": [
            {
                "id": str(r.id),
                "status": r.status,
                "blocked_reason": r.blocked_reason,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in runs
        ],
        "total": len(runs),
    }


async def _assert_run_ticket_actionable(
    session: AsyncSession, *, tenant_id: int, run: AgentRun
) -> None:
    """Codex adversarial R6: 既存 run を advance させる前に binding 先 ticket が actionable か確認する。

    run→ticket binding は ``run_queued`` event payload にあるため、そこから ticket_id を解決し
    ``TicketRepository.assert_ticket_actionable`` で project active + ticket active を検証する
    (archived → ProjectArchivedError、soft-deleted → TicketNotActionableError)。bulk soft-delete /
    archive **前**に queued/running になった run が、削除/凍結後に AI 実行・コスト・結果公開へ進むのを
    防ぐ。ticket_id を解決できない run (ticket-bound でない) は guard しない。
    """
    repo = TicketRepository(session)
    # ADR-00037 R12: run→ticket binding は server-owned column (run.ticket_id) を直読みする。
    # event-payload 依存の fail-open / 非決定性 (R7 #1) を根本排除し、deterministic + fail-closed。
    if run.ticket_id is not None:
        # binding 先 ticket の active + project active を fail-closed で検証 (archived →
        # ProjectArchivedError、soft-deleted / 不在 → TicketNotActionableError)。
        await repo.assert_ticket_actionable(tenant_id, run.project_id, str(run.ticket_id))
    else:
        # ticket-less run (binding 不能な legacy / 非 ticket run): project archive freeze のみ適用。
        await repo.assert_project_active(tenant_id, run.project_id)


async def bridge_run_update(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID,
    status: str,
    summary: str = "",
) -> dict[str, Any]:
    from backend.app.db.models.agent_run_event import AgentRunEvent
    from backend.app.mcp.context import DEFAULT_SUPERINTENDENT_ACTOR_ID

    valid_statuses = {
        "running", "completed", "failed", "blocked",
        "gathering_context", "generated_artifact",
    }
    if status not in valid_statuses:
        return {"error": "invalid_status", "valid": sorted(valid_statuses)}

    result = await session.execute(
        select(AgentRun).where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.id == run_id,
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        return {"error": "not_found", "run_id": str(run_id)}

    terminal = {"completed", "failed", "cancelled", "provider_refused", "repair_exhausted"}
    if run.status in terminal:
        return {"error": "already_terminal", "run_id": str(run_id), "status": run.status}

    # Codex adversarial R6: 削除済 ticket / archived project の既存 run を advance させない (AI 実行・
    # コスト・結果公開を防ぐ)。binding 先 ticket が actionable でなければ error を返し、進行は cancel
    # (bridge_run_cancel) のみ許可する。
    try:
        await _assert_run_ticket_actionable(session, tenant_id=tenant_id, run=run)
    except (ProjectArchivedError, TicketNotActionableError) as exc:
        return {"error": str(type(exc).__name__), "run_id": str(run_id)}

    old_status = run.status
    run.status = status
    if status == "blocked":
        run.blocked_reason = "runtime_blocked"
    elif run.blocked_reason and status != "blocked":
        run.blocked_reason = None

    event_type_map = {
        "running": "context_gathered",
        "completed": "run_completed",
        "failed": "run_failed",
        "blocked": "runtime_blocked",
        "gathering_context": "context_gathered",
        "generated_artifact": "artifact_generated",
    }

    max_seq = await session.execute(
        sa.text("SELECT COALESCE(MAX(seq_no), 0) FROM agent_run_events WHERE tenant_id = :tid AND run_id = :rid"),
        {"tid": tenant_id, "rid": run_id},
    )
    next_seq = (max_seq.scalar() or 0) + 1

    event = AgentRunEvent(
        tenant_id=tenant_id,
        run_id=run_id,
        seq_no=next_seq,
        event_type=event_type_map.get(status, "context_gathered"),
        event_payload={
            "old_status": old_status,
            "new_status": status,
            "summary": summary,
        },
        actor_id=DEFAULT_SUPERINTENDENT_ACTOR_ID,
    )
    session.add(event)
    await session.commit()

    return {
        "run_id": str(run.id),
        "old_status": old_status,
        "new_status": status,
        "summary": summary,
    }


async def bridge_approval_request_create(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    ticket_id: str,
    action_class: str,
    requester_actor_id: UUID,
) -> dict[str, Any]:
    from backend.app.repositories.approval_request import ApprovalRequestRepository

    # Q-3/Q-4 (ADR-00037 / Codex adversarial R3): 削除済 ticket / archived project への承認要求を拒否
    # (削除/凍結した作業が承認 → 実行へ進むのを防ぐ)。
    await TicketRepository(session).assert_ticket_actionable(tenant_id, project_id, ticket_id)

    repo = ApprovalRequestRepository(session)
    approval = await repo.create_pending_approval(
        tenant_id=tenant_id,
        action_class=action_class,
        resource_ref=f"ticket:{ticket_id}",
        risk_level="medium",
        requested_by_actor_id=requester_actor_id,
        recipient_actor_id=requester_actor_id,
        policy_version="v1",
        artifact_hash=f"ticket:{ticket_id}",
    )
    await session.commit()
    return {
        "approval_id": str(approval.id),
        "action_class": action_class,
        "status": "pending",
        "ticket_id": ticket_id,
    }


async def bridge_delegation_create(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    parent_run_id: UUID,
    ticket_id: str,
    purpose: str,
    role_id: str,
    task_spec: dict[str, Any],
    sender_actor_id: UUID,
) -> dict[str, Any]:
    import hashlib
    import json as json_mod
    from datetime import UTC, datetime, timedelta

    # ADR-00037 R16/R17 (Codex adversarial): parent_run_id の run 自体の actionable 検証は chokepoint の
    # bridge_run_create に集約済 (削除済/不在 parent は TicketNotActionableError を raise)。delegation
    # 専用の二重 guard は撤去し single-source に統一する。
    # ADR-00037 R20 (Codex adversarial): child run 作成と inter_agent_messages INSERT を **同一 transaction・
    # 同一 project lock 下** で行う (commit=False)。bridge_run_create が内部 commit すると lock 解放後・
    # message INSERT 前に concurrent な bulk_soft_delete / archive が割り込み、stale な前提で message を
    # 作れる TOCTOU になる。commit を本関数末尾の 1 回に集約し直列化する (失敗時は child run も rollback)。
    child_run = await bridge_run_create(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        ticket_id=ticket_id,
        purpose=purpose,
        role_id=role_id,
        parent_run_id=parent_run_id,
        commit=False,
    )
    if "error" in child_run:
        return child_run

    child_run_id = UUID(child_run["run_id"])
    spec_json = json_mod.dumps(task_spec, sort_keys=True, ensure_ascii=False)
    payload_hash = hashlib.sha256(spec_json.encode()).hexdigest()

    max_seq = await session.execute(
        sa.text(
            "SELECT COALESCE(MAX(seq_no), 0) FROM inter_agent_messages "
            "WHERE tenant_id = :tid AND parent_run_id = :prid"
        ),
        {"tid": tenant_id, "prid": parent_run_id},
    )
    next_seq = (max_seq.scalar() or 0) + 1

    msg_id = uuid4()
    await session.execute(
        sa.text("""
            INSERT INTO inter_agent_messages (
                id, tenant_id, project_id, parent_run_id, child_run_id,
                sender_actor_id, sender_run_id, receiver_kind, receiver_ref,
                payload_data_class, trust_level, payload_hash, artifact_ref,
                seq_no, schema_version, idempotency_key, expires_at
            ) VALUES (
                :id, :tid, :pid, :prid, :crid,
                :said, :srid, 'agent_run', NULL,
                'internal', 'untrusted_content', :phash, :aref,
                :seq, '1.0', :ikey, :exp
            )
        """),
        {
            "id": msg_id, "tid": tenant_id, "pid": project_id,
            "prid": parent_run_id, "crid": child_run_id,
            "said": sender_actor_id, "srid": parent_run_id,
             "phash": payload_hash,
            "aref": f"task_spec:{child_run_id}",
            "seq": next_seq, "ikey": f"delegation:{parent_run_id}:{next_seq}",
            "exp": datetime.now(UTC) + timedelta(hours=24),
        },
    )
    await session.commit()

    return {
        "delegation_id": str(msg_id),
        "child_run_id": str(child_run_id),
        "parent_run_id": str(parent_run_id),
        "role_id": role_id,
        "status": "pending",
        "task_spec": task_spec,
    }


async def bridge_delegation_inbox(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID,
    limit: int = 20,
) -> dict[str, Any]:
    limit = min(max(1, limit), MAX_LIMIT)
    # ADR-00037 R17/R22 (Codex adversarial): inbox は work-queue なので、削除/凍結された work の queued
    # message を露出/消費させない。R17: parent_run / sender_run が soft-deleted ticket に bind された
    # message を除外。R22: **archived project** (project.status<>'active'、archive は ticket を soft-delete
    # しないため別 state) の message も除外する (message は project_id を直接持つ、archive freeze 後の
    # stale delegation read 露出を塞ぐ。accept は元々 archived guard で reject)。完全静的 SQL。
    result = await session.execute(
        sa.text("""
            SELECT id, sender_run_id, parent_run_id, artifact_ref, seq_no, created_at
            FROM inter_agent_messages
            WHERE tenant_id = :tid AND child_run_id = :crid AND consumed_at IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM projects p
                 WHERE p.tenant_id = inter_agent_messages.tenant_id
                   AND p.id = inter_agent_messages.project_id
                   AND p.status <> 'active'
              )
              AND NOT EXISTS (
                -- R23 (Codex adversarial): inbox の宛先である child (receiver) run 自体の ticket が
                -- soft-deleted なら、その work-queue は frozen なので message を露出しない。
                SELECT 1 FROM agent_runs cr
                  JOIN tickets cdt ON cdt.tenant_id = cr.tenant_id
                    AND cdt.project_id = cr.project_id AND cdt.id = cr.ticket_id
                    AND cdt.deleted_at IS NOT NULL
                 WHERE cr.tenant_id = inter_agent_messages.tenant_id
                   AND cr.id = inter_agent_messages.child_run_id
              )
              AND NOT EXISTS (
                SELECT 1 FROM agent_runs pr
                  JOIN tickets pdt ON pdt.tenant_id = pr.tenant_id
                    AND pdt.project_id = pr.project_id AND pdt.id = pr.ticket_id
                    AND pdt.deleted_at IS NOT NULL
                 WHERE pr.tenant_id = inter_agent_messages.tenant_id
                   AND pr.id = inter_agent_messages.parent_run_id
              )
              AND NOT EXISTS (
                SELECT 1 FROM agent_runs sr
                  JOIN tickets sdt ON sdt.tenant_id = sr.tenant_id
                    AND sdt.project_id = sr.project_id AND sdt.id = sr.ticket_id
                    AND sdt.deleted_at IS NOT NULL
                 WHERE sr.tenant_id = inter_agent_messages.tenant_id
                   AND sr.id = inter_agent_messages.sender_run_id
              )
            ORDER BY created_at DESC
            LIMIT :lim
        """),
        {"tid": tenant_id, "crid": run_id, "lim": limit},
    )
    rows = result.fetchall()
    return {
        "messages": [
            {
                "id": str(r[0]),
                "sender_run_id": str(r[1]),
                "parent_run_id": str(r[2]),
                "artifact_ref": r[3],
                "seq_no": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


async def bridge_delegation_accept(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID,
    message_id: UUID,
) -> dict[str, Any]:
    result = await session.execute(
        select(AgentRun).where(AgentRun.tenant_id == tenant_id, AgentRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        return {"error": "not_found", "run_id": str(run_id)}
    if run.status != "queued":
        return {"error": "invalid_state", "status": run.status, "expected": "queued"}

    # Codex adversarial R6: 削除済 ticket / archived project の delegation を accept (run advance +
    # message 消費) させない。
    try:
        await _assert_run_ticket_actionable(session, tenant_id=tenant_id, run=run)
    except (ProjectArchivedError, TicketNotActionableError) as exc:
        return {"error": str(type(exc).__name__), "run_id": str(run_id)}

    # ADR-00037 R17 (Codex adversarial): message の parent_run / sender_run も active-scope か検証する。
    # parent ticket が delegation_create 後・accept 前に soft-delete された場合、child ticket が active でも
    # accept できてしまう (削除済 work が queued message 経由で graph を進める timing 漏れ) のを塞ぐ。
    msg_row = await session.execute(
        sa.text(
            "SELECT parent_run_id, sender_run_id FROM inter_agent_messages "
            "WHERE tenant_id = :tid AND id = :mid AND child_run_id = :rid AND consumed_at IS NULL"
        ),
        {"tid": tenant_id, "mid": message_id, "rid": run_id},
    )
    msg = msg_row.fetchone()
    if msg is None:
        return {"error": "message_not_found_or_not_addressed_to_this_run", "run_id": str(run_id)}
    for ref_run_id in {msg[0], msg[1]}:
        if ref_run_id is None:
            continue
        ref_run = await session.scalar(
            select(AgentRun).where(AgentRun.tenant_id == tenant_id, AgentRun.id == ref_run_id)
        )
        if ref_run is None:
            return {"error": "delegation_run_not_found", "run_id": str(ref_run_id)}
        try:
            await _assert_run_ticket_actionable(session, tenant_id=tenant_id, run=ref_run)
        except (ProjectArchivedError, TicketNotActionableError) as exc:
            return {"error": str(type(exc).__name__), "run_id": str(ref_run_id)}

    consume_result = await session.execute(
        sa.text(
            "UPDATE inter_agent_messages SET consumed_at = now(), consumed_by_run_id = :rid "
            "WHERE tenant_id = :tid AND id = :mid AND child_run_id = :rid AND consumed_at IS NULL "
            "RETURNING id"
        ),
        {"tid": tenant_id, "rid": run_id, "mid": message_id},
    )
    if consume_result.fetchone() is None:
        return {"error": "message_not_found_or_not_addressed_to_this_run", "run_id": str(run_id)}

    run.status = "running"
    await session.commit()
    return {"run_id": str(run_id), "status": "running", "accepted": True}


async def bridge_delegation_submit(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID,
    parent_run_id: UUID,
    project_id: UUID,
    result_status: str,
    result_summary: str,
    result_spec: dict[str, Any],
    actor_id: UUID,
) -> dict[str, Any]:
    import hashlib
    import json as json_mod
    from datetime import UTC, datetime, timedelta

    valid = {"completed", "failed", "needs_review"}
    if result_status not in valid:
        return {"error": "invalid_status", "valid": sorted(valid)}

    result = await session.execute(
        select(AgentRun).where(AgentRun.tenant_id == tenant_id, AgentRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        return {"error": "not_found", "run_id": str(run_id)}
    if run.parent_run_id and run.parent_run_id != parent_run_id:
        return {"error": "parent_run_id_mismatch", "expected": str(run.parent_run_id)}

    # Codex adversarial R6: 削除済 ticket / archived project の delegation 結果提出 (run advance +
    # 結果公開) をさせない。
    try:
        await _assert_run_ticket_actionable(session, tenant_id=tenant_id, run=run)
    except (ProjectArchivedError, TicketNotActionableError) as exc:
        return {"error": str(type(exc).__name__), "run_id": str(run_id)}

    # ADR-00037 R26 (Codex App PR review): child だけでなく **parent run 自体** も actionable か検証する。
    # parent の ticket が delegation 後に soft-delete された場合、child active のまま result message を
    # 削除済 parent (parent_run_id 宛) に提出できてしまう (accept/review と同じ parent active-scope 漏れ)。
    parent_for_submit = await session.scalar(
        select(AgentRun).where(
            AgentRun.tenant_id == tenant_id, AgentRun.id == parent_run_id
        )
    )
    if parent_for_submit is None:
        return {"error": "parent_not_found", "parent_run_id": str(parent_run_id)}
    try:
        await _assert_run_ticket_actionable(session, tenant_id=tenant_id, run=parent_for_submit)
    except (ProjectArchivedError, TicketNotActionableError) as exc:
        return {"error": str(type(exc).__name__), "parent_run_id": str(parent_run_id)}

    run_status = "completed" if result_status == "completed" else "failed" if result_status == "failed" else "running"
    run.status = run_status

    spec_json = json_mod.dumps(result_spec, sort_keys=True, ensure_ascii=False)
    payload_hash = hashlib.sha256(spec_json.encode()).hexdigest()

    max_seq = await session.execute(
        sa.text(
            "SELECT COALESCE(MAX(seq_no), 0) FROM inter_agent_messages "
            "WHERE tenant_id = :tid AND parent_run_id = :prid"
        ),
        {"tid": tenant_id, "prid": parent_run_id},
    )
    next_seq = (max_seq.scalar() or 0) + 1

    msg_id = uuid4()
    await session.execute(
        sa.text("""
            INSERT INTO inter_agent_messages (
                id, tenant_id, project_id, parent_run_id, child_run_id,
                sender_actor_id, sender_run_id, receiver_kind, receiver_ref,
                payload_data_class, trust_level, payload_hash, artifact_ref,
                seq_no, schema_version, idempotency_key, expires_at
            ) VALUES (
                :id, :tid, :pid, :prid, :crid,
                :said, :srid, 'agent_run', NULL,
                'internal', 'untrusted_content', :phash, :aref,
                :seq, '1.0', :ikey, :exp
            )
        """),
        {
            "id": msg_id, "tid": tenant_id, "pid": project_id,
            "prid": parent_run_id, "crid": run_id,
            "said": actor_id, "srid": run_id,
            "phash": payload_hash,
            "aref": f"result:{run_id}:{result_status}",
            "seq": next_seq,
            "ikey": f"submit:{run_id}:{next_seq}",
            "exp": datetime.now(UTC) + timedelta(hours=24),
        },
    )
    await session.commit()
    return {
        "submitted": True,
        "run_id": str(run_id),
        "status": run_status,
        "result_status": result_status,
        "message_id": str(msg_id),
    }


async def bridge_delegation_review(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID,
    reviewer_run_id: UUID,
    decision: str,
    quality_score: float,
    findings: str = "",
) -> dict[str, Any]:
    valid_decisions = {"adopt", "reject"}
    if decision not in valid_decisions:
        return {"error": "invalid_decision", "valid": sorted(valid_decisions)}
    quality_score = round(max(0.0, min(1.0, quality_score)), 6)

    result = await session.execute(
        select(AgentRun).where(AgentRun.tenant_id == tenant_id, AgentRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        return {"error": "not_found", "run_id": str(run_id)}

    # Codex adversarial R10 #2: 削除済 ticket / archived project の run には review (approval_decided)
    # event を記録しない。R6 の run-transition guard 対象に delegation_review を追加し、削除/凍結した
    # 作業の review/adopt/reject 監査・進行を止める。
    try:
        await _assert_run_ticket_actionable(session, tenant_id=tenant_id, run=run)
    except (ProjectArchivedError, TicketNotActionableError) as exc:
        return {"error": str(type(exc).__name__), "run_id": str(run_id)}

    # Codex adversarial R14 #1 (bounded adopt): reviewer は同一 (tenant_id, project_id) の run のみ。
    # cross-project reviewer (同一 tenant 別 project) を弾く (core.md §8 project 境界、agent_runs は
    # 同一 project 内に閉じる)。reviewer role/scope・delegation tree 帰属・implementer 不一致の検証は
    # P0.1 approval-boundary design (ADR Gate #4) として defer、ADR-00037 残リスク § に記録。
    reviewer_result = await session.execute(
        select(AgentRun).where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.project_id == run.project_id,
            AgentRun.id == reviewer_run_id,
        )
    )
    reviewer = reviewer_result.scalar_one_or_none()
    if reviewer is None:
        return {"error": "reviewer_not_found"}
    # Codex adversarial R15 #3: reviewer run 自体が soft-deleted ticket / archived project に bind
    # されていれば reject する (active-scope 外の reviewer identity で approval_decided を捏造させない、
    # soft-delete 境界の漏れ。R14 の cross-project 境界とは別)。
    try:
        await _assert_run_ticket_actionable(session, tenant_id=tenant_id, run=reviewer)
    except (ProjectArchivedError, TicketNotActionableError) as exc:
        return {"error": str(type(exc).__name__), "reviewer_run_id": str(reviewer_run_id)}
    if reviewer.parent_run_id == run.parent_run_id and reviewer_run_id == run_id:
        return {"error": "self_review_forbidden"}

    from backend.app.db.models.agent_run_event import AgentRunEvent

    max_seq = await session.execute(
        sa.text(
            "SELECT COALESCE(MAX(seq_no), 0) FROM agent_run_events "
            "WHERE tenant_id = :tid AND run_id = :rid"
        ),
        {"tid": tenant_id, "rid": run_id},
    )
    next_seq = (max_seq.scalar() or 0) + 1

    event = AgentRunEvent(
        tenant_id=tenant_id,
        run_id=run_id,
        seq_no=next_seq,
        event_type="approval_decided",
        event_payload={
            "decision": decision,
            "quality_score": quality_score,
            "reviewer_run_id": str(reviewer_run_id),
            "findings": findings,
        },
        actor_id=UUID("00000000-0000-4000-8000-000000000001"),
    )
    session.add(event)
    await session.commit()

    return {
        "reviewed": True,
        "run_id": str(run_id),
        "decision": decision,
        "quality_score": quality_score,
    }


async def bridge_delegation_tree(
    session: AsyncSession,
    *,
    tenant_id: int,
    root_run_id: UUID,
) -> dict[str, Any]:
    # ADR-00037 R16 (Codex adversarial): seed (root) と recursive branch (child) の両方に
    # soft-deleted ticket bound 除外を入れ、delegation_tree でも active-scope を統一する
    # (削除済 root → 空集合 → not_found、削除済 child → tree から除外、restore で復帰)。
    # 完全静的 SQL (bind param :tid/:rid のみ、文字列補間なし)。
    result = await session.execute(
        sa.text("""
            WITH RECURSIVE tree AS (
                SELECT id, parent_run_id, project_id, status, role_id, 0 as depth
                FROM agent_runs
                WHERE tenant_id = :tid AND id = :rid
                  AND NOT EXISTS (
                    SELECT 1 FROM tickets dt
                     WHERE dt.tenant_id = agent_runs.tenant_id
                       AND dt.project_id = agent_runs.project_id
                       AND dt.id = agent_runs.ticket_id
                       AND dt.deleted_at IS NOT NULL
                  )
                UNION ALL
                SELECT ar.id, ar.parent_run_id, ar.project_id, ar.status, ar.role_id, t.depth + 1
                FROM agent_runs ar
                JOIN tree t ON ar.parent_run_id = t.id AND ar.tenant_id = :tid
                WHERE t.depth < 10
                  AND NOT EXISTS (
                    SELECT 1 FROM tickets dt
                     WHERE dt.tenant_id = ar.tenant_id
                       AND dt.project_id = ar.project_id
                       AND dt.id = ar.ticket_id
                       AND dt.deleted_at IS NOT NULL
                  )
            )
            SELECT id, parent_run_id, status, role_id, depth FROM tree ORDER BY depth, id
        """),
        {"tid": tenant_id, "rid": root_run_id},
    )
    rows = result.fetchall()
    if not rows:
        return {"error": "not_found", "run_id": str(root_run_id)}
    return {
        "tree": [
            {
                "run_id": str(r[0]),
                "parent_run_id": str(r[1]) if r[1] else None,
                "status": r[2],
                "role_id": r[3],
                "depth": r[4],
            }
            for r in rows
        ],
        "total_nodes": len(rows),
        "max_depth": max(r[4] for r in rows),
    }


async def bridge_delegation_cancel(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID,
) -> dict[str, Any]:
    result = await session.execute(
        sa.text("""
            WITH RECURSIVE tree AS (
                SELECT id, 0 as depth FROM agent_runs
                WHERE tenant_id = :tid AND id = :rid
                UNION ALL
                SELECT ar.id, t.depth + 1 FROM agent_runs ar
                JOIN tree t ON ar.parent_run_id = t.id AND ar.tenant_id = :tid
                WHERE t.depth < 10
            )
            UPDATE agent_runs SET status = 'cancelled', blocked_reason = NULL
            WHERE tenant_id = :tid AND id IN (SELECT id FROM tree)
              AND status NOT IN ('completed', 'failed', 'cancelled', 'provider_refused', 'repair_exhausted')
            RETURNING id
        """),
        {"tid": tenant_id, "rid": run_id},
    )
    cancelled_ids = [str(r[0]) for r in result.fetchall()]
    await session.commit()
    return {
        "cancelled": cancelled_ids,
        "count": len(cancelled_ids),
    }


async def bridge_workflow_status(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID | None = None,
) -> dict[str, Any]:
    # ADR-00037 R13 (Codex adversarial): soft-deleted ticket bound の run を workflow summary
    # 集計から除外する (cost_summary_endpoint / kpi_show と同じ active-scope read path)。
    # run.ticket_id が soft-deleted ticket (同一 tenant/project) を指す run を除外、
    # ticket-less run (ticket_id IS NULL) は含む。restore で再集計対象に戻る。
    # SQL は完全静的な隣接リテラルのみ (文字列補間なし、全値は bind param :tid/:pid)。
    if project_id:
        result = await session.execute(
            sa.text(
                "SELECT status, role_id, count(*) as cnt FROM agent_runs "
                "WHERE tenant_id = :tid AND project_id = :pid "
                "AND NOT EXISTS ("
                "SELECT 1 FROM tickets t "
                "WHERE t.tenant_id = agent_runs.tenant_id "
                "AND t.project_id = agent_runs.project_id "
                "AND t.id = agent_runs.ticket_id "
                "AND t.deleted_at IS NOT NULL"
                ") "
                "GROUP BY status, role_id ORDER BY status, role_id"
            ),
            {"tid": tenant_id, "pid": project_id},
        )
    else:
        result = await session.execute(
            sa.text(
                "SELECT status, role_id, count(*) as cnt FROM agent_runs "
                "WHERE tenant_id = :tid "
                "AND NOT EXISTS ("
                "SELECT 1 FROM tickets t "
                "WHERE t.tenant_id = agent_runs.tenant_id "
                "AND t.project_id = agent_runs.project_id "
                "AND t.id = agent_runs.ticket_id "
                "AND t.deleted_at IS NOT NULL"
                ") "
                "GROUP BY status, role_id ORDER BY status, role_id"
            ),
            {"tid": tenant_id},
        )
    rows = result.fetchall()

    total = sum(r[2] for r in rows)
    by_status: dict[str, int] = {}
    by_role: dict[str, int] = {}
    for r in rows:
        by_status[r[0]] = by_status.get(r[0], 0) + r[2]
        if r[1]:
            by_role[r[1]] = by_role.get(r[1], 0) + r[2]

    active = by_status.get("running", 0) + by_status.get("queued", 0) + by_status.get("gathering_context", 0)
    completed = by_status.get("completed", 0)
    failed = by_status.get("failed", 0)
    cancelled = by_status.get("cancelled", 0)

    return {
        "total_runs": total,
        "active": active,
        "completed": completed,
        "failed": failed,
        "cancelled": cancelled,
        "by_status": by_status,
        "by_role": by_role,
        "success_rate": round(completed / (completed + failed) * 100, 1) if (completed + failed) > 0 else 0,
    }


async def bridge_run_cost(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID,
    cost_usd: float,
    tokens_input: int,
    tokens_output: int,
) -> dict[str, Any]:
    result = await session.execute(
        select(AgentRun).where(AgentRun.tenant_id == tenant_id, AgentRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        return {"error": "not_found", "run_id": str(run_id)}

    # Codex adversarial R11: 削除済 ticket / archived project の run の cost/token を更新させない
    # (R6/R10 run-transition guard 対象に run_cost を追加、削除/凍結した作業の cost 計上・KPI 汚染を防ぐ)。
    try:
        await _assert_run_ticket_actionable(session, tenant_id=tenant_id, run=run)
    except (ProjectArchivedError, TicketNotActionableError) as exc:
        return {"error": str(type(exc).__name__), "run_id": str(run_id)}

    run.cost_usd = cost_usd
    run.tokens_input = tokens_input
    run.tokens_output = tokens_output
    await session.commit()
    return {
        "run_id": str(run.id),
        "cost_usd": cost_usd,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
    }
