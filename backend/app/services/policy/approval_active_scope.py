"""ADR-00037 R18 (Codex adversarial): approval の soft-delete/archive active-scope。

Q-3 bulk soft-delete / Q-4 archive **後** に残る既存 approval_request は、作成時の actionable
チェック (bridge_approval_request_create) を通過済みでも、その後 ticket / project が削除・凍結される
と stale になる。**承認 (approve) は削除済 work への human authorization を付与する** ため、decision
chokepoint と inbox read path で bound ticket の active-scope を再検証して fail-closed にする。

- approval の `resource_ref` が ``ticket:<uuid>`` の場合のみ対象 (他形式は ticket soft-delete と無関係)。
- soft-delete は **可逆** なので status は変えず (invalidated 化しない)、decide 時 guard + 一覧 filter で
  動的に隠す。restore で ticket が active へ戻れば approval も再び承認可能になる。
- 承認 (approve) は block、却下 (reject) は cleanup のため許可 (本 helper は approve 経路でのみ raise)。
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.project import Project
from backend.app.db.models.ticket import Ticket
from backend.app.repositories.ticket import (
    ProjectArchivedError,
    TicketNotActionableError,
    TicketRepository,
)

_TICKET_RESOURCE_PREFIX = "ticket:"


def parse_ticket_resource_ref(resource_ref: str) -> UUID | None:
    """``ticket:<uuid>`` 形式の resource_ref から ticket UUID を取り出す。非該当は None。"""
    if not resource_ref.startswith(_TICKET_RESOURCE_PREFIX):
        return None
    raw = resource_ref[len(_TICKET_RESOURCE_PREFIX) :]
    try:
        return UUID(raw)
    except (ValueError, AttributeError):
        return None


async def assert_approval_target_actionable(
    session: AsyncSession, *, tenant_id: int, resource_ref: str
) -> None:
    """approval の bound ticket が soft-deleted / project archived / 不在なら raise (fail-closed)。

    非 ticket resource_ref は no-op。soft-deleted / 不在 → ``TicketNotActionableError``、
    archived → ``ProjectArchivedError``。
    """
    ticket_id = parse_ticket_resource_ref(resource_ref)
    if ticket_id is None:
        return
    row = (
        await session.execute(
            select(Ticket.project_id, Ticket.deleted_at, Project.status)
            .join(
                Project,
                sa.and_(
                    Project.tenant_id == Ticket.tenant_id,
                    Project.id == Ticket.project_id,
                ),
            )
            .where(Ticket.tenant_id == tenant_id, Ticket.id == ticket_id)
        )
    ).one_or_none()
    if row is None:
        # resource_ref が実在 ticket を指さない (synthetic / legacy / 非 P0 経路の approval)。
        # R18 の対象は「active だった ticket が **soft-delete** された (行は残り deleted_at セット)」case
        # に限る (Q-3 soft-delete は行を物理削除しない)。row 不在は本機能の管轄外なので block しない。
        return
    project_id, deleted_at, project_status = row
    if project_status == "archived":
        raise ProjectArchivedError(project_id=project_id)
    if deleted_at is not None:
        raise TicketNotActionableError(ticket_id=str(ticket_id))


async def assert_approval_target_actionable_locked(
    session: AsyncSession, *, tenant_id: int, resource_ref: str
) -> None:
    """**approve (mutation) 用** の locking guard。R19 (Codex adversarial): 非ロック SELECT だと
    READ COMMITTED 下で「guard が active と読む → concurrent bulk_soft_delete/archive が commit →
    approve が approval を approved に UPDATE」という TOCTOU で削除済 work へ authorization を付与できる。

    bound ticket の project row を ``TicketRepository.assert_ticket_actionable`` 経由で **FOR UPDATE
    lock** し、bulk_soft_delete / archive と同じ serialization boundary で active-scope を再検証する。
    同一 transaction 内で後続の approval status UPDATE と直列化される (lock は commit まで保持)。

    非 ticket resource_ref / row 不在は管轄外 (no-op)。soft-deleted / 不在 ticket → ``TicketNotActionableError``、
    archived → ``ProjectArchivedError``。
    """
    ticket_id = parse_ticket_resource_ref(resource_ref)
    if ticket_id is None:
        return
    # project_id を解決 (project_id は immutable、deletion で変わらないため unlocked SELECT で可)。
    project_id = await session.scalar(
        select(Ticket.project_id).where(Ticket.tenant_id == tenant_id, Ticket.id == ticket_id)
    )
    if project_id is None:
        return  # resource_ref が実在 ticket を指さない (synthetic / legacy) → 管轄外
    # project row を FOR UPDATE lock し、lock 下で ticket active + project active を再検証する。
    await TicketRepository(session).assert_ticket_actionable(
        tenant_id, project_id, str(ticket_id)
    )


async def is_approval_target_actionable(
    session: AsyncSession, *, tenant_id: int, resource_ref: str
) -> bool:
    """read path (inbox list / detail) 用。bound ticket が actionable かを bool で返す。"""
    try:
        await assert_approval_target_actionable(
            session, tenant_id=tenant_id, resource_ref=resource_ref
        )
        return True
    except (TicketNotActionableError, ProjectArchivedError):
        return False


__all__ = [
    "assert_approval_target_actionable",
    "assert_approval_target_actionable_locked",
    "is_approval_target_actionable",
    "parse_ticket_resource_ref",
]
