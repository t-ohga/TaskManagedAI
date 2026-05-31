"""Project archive-freeze 共通 guard (Codex adversarial R10 #1)。

ADR-00037 の archive freeze は ticket だけでなく **project child write 全体** (claim / evidence /
research / acceptance 等) に適用する read-only freeze である。各 child-write endpoint がこの dependency
を ``Depends`` することで、archived project への write を ``Project.status`` の FOR UPDATE lock 下で
一貫して 409 fail-closed にする。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import get_db_session, get_tenant_id
from backend.app.repositories.ticket import ProjectArchivedError, TicketRepository


async def require_active_project(
    project_id: UUID,
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> None:
    """archived project への child write を 409 で凍結する共通 guard。

    ``TicketRepository.assert_project_active`` で project row を FOR UPDATE lock しつつ active を確認し、
    archived なら ``ProjectArchivedError`` を 409 に写像する。project 不在は guard せず通す (各 endpoint
    の既存 not-found / FK 経路に委ねる)。
    """
    try:
        await TicketRepository(session).assert_project_active(tenant_id, project_id)
    except ProjectArchivedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="project is archived; unarchive it before writing to it",
        ) from exc


__all__ = ["require_active_project"]
