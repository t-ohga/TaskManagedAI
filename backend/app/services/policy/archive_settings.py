from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.project import Project, ProjectStatus


class ArchiveExpectationMismatch(Exception):
    """Q-4 (ADR-00037): archive toggle の compare-and-swap baseline mismatch。

    M-3 の autonomy CAS と同様、stale な baseline からの誤 toggle を防ぐ CAS を
    実際の mutation 境界 (本 service) で必須にする。caller (API endpoint / 内部 caller /
    将来の MCP / job すべて) は ``expected_status`` を必ず渡し、row lock 後の current と
    不一致なら本例外で拒否する (no-CAS writer を production path から排除)。
    """

    def __init__(self, *, expected: str, actual: str) -> None:
        super().__init__(
            f"expected project status {expected!r} but current value is {actual!r}"
        )
        self.expected = expected
        self.actual = actual


@dataclass(frozen=True)
class ProjectArchiveResult:
    """set_archived の結果。

    ``previous_status`` と ``changed`` を返し、endpoint が実遷移時のみ audit する判断に使う
    (no-op では audit を残さない、M-3 audit pattern と一致)。
    """

    project: Project
    previous_status: ProjectStatus
    changed: bool


class ProjectArchiveService:
    """Server-owned project archive toggle writer (compare-and-swap 強制)。

    archived <-> active は reversible な soft toggle (ADR-00037、hard delete しない)。
    archived project への child-write 凍結 (ticket create/update/import/bulk-delete/restore) は
    ``TicketRepository._assert_project_active`` が全 mutation 境界で enforce するため、本 service は
    status の CAS toggle + 実遷移判定のみを担う。audit / commit は caller (endpoint) が行う。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def set_archived(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        archived: bool,
        expected_status: ProjectStatus,
    ) -> ProjectArchiveResult | None:
        """project.status を compare-and-swap で active<->archived に切り替える。

        - project 不在: ``None`` を返す。
        - ``expected_status`` が row lock 後の current と不一致: ``ArchiveExpectationMismatch``。
        - それ以外: 更新し ``ProjectArchiveResult`` を返す (commit は呼び出し側)。
        """
        await self._ensure_tenant_context(tenant_id)
        # CAS と直列化のため row lock 付きで取得する (SELECT ... FOR UPDATE)。
        project = await self.session.scalar(
            select(Project)
            .where(
                Project.tenant_id == tenant_id,
                Project.id == project_id,
            )
            .with_for_update()
        )
        if project is None:
            return None

        previous_status: ProjectStatus = project.status
        # compare-and-swap: stale baseline からの誤 toggle (二重 archive / 競合 unarchive) を拒否。
        if previous_status != expected_status:
            raise ArchiveExpectationMismatch(
                expected=expected_status,
                actual=previous_status,
            )

        new_status: ProjectStatus = "archived" if archived else "active"
        changed = previous_status != new_status
        project.status = new_status
        await self.session.flush()
        await self.session.refresh(project)
        return ProjectArchiveResult(
            project=project,
            previous_status=previous_status,
            changed=changed,
        )

    async def _ensure_tenant_context(self, tenant_id: int) -> None:
        if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
            raise ValueError("tenant_id must be a positive integer.")
        current = await get_tenant_context(self.session)
        if current is None:
            await set_tenant_context(self.session, tenant_id)
        await assert_tenant_context(self.session, tenant_id)


__all__ = [
    "ArchiveExpectationMismatch",
    "ProjectArchiveResult",
    "ProjectArchiveService",
]
