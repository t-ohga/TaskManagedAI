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
from backend.app.db.models.project import Project
from backend.app.domain.policy.autonomy_level import AutonomyLevel
from backend.app.services.policy.autonomy_profile_resolver import (
    resolve_autonomy_policy_profile,
)


class AutonomyExpectationMismatch(Exception):
    """Compare-and-swap baseline mismatch.

    Codex adversarial R9 (HIGH): autonomy_level は AI 権限制御。stale な baseline からの
    re-escalation を防ぐ CAS は、endpoint wrapper ではなく **実際の mutation 境界**
    (本 service) で強制する。caller (API endpoint / 内部 caller / 将来の MCP / job すべて) は
    ``expected_autonomy_level`` を必ず渡し、row lock 後の current と不一致なら本例外で拒否する。
    """

    def __init__(self, *, expected: str, actual: str) -> None:
        super().__init__(
            f"expected autonomy_level {expected!r} but current value is {actual!r}"
        )
        self.expected = expected
        self.actual = actual


@dataclass(frozen=True)
class AutonomyUpdateResult:
    """update_autonomy_level の結果。

    ``previous_autonomy_level`` と ``changed`` を返し、endpoint が実遷移時のみ audit する
    判断に使う (no-op では audit を残さない)。
    """

    project: Project
    previous_autonomy_level: AutonomyLevel
    changed: bool


class ProjectAutonomySettingsService:
    """Server-owned autonomy settings writer (compare-and-swap 強制).

    Generic ``ProjectRepository`` rejects both ``autonomy_level`` and
    ``policy_profile`` payloads. This service is the narrow settings surface
    that accepts only caller-visible ``autonomy_level`` and resolves
    ``policy_profile`` internally. CAS (``expected_autonomy_level``) を必須引数として
    持ち、stale baseline からの AI 権限 re-escalation を signature レベルで防ぐ。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def update_autonomy_level(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        autonomy_level: AutonomyLevel,
        expected_autonomy_level: AutonomyLevel,
    ) -> AutonomyUpdateResult | None:
        """autonomy_level を compare-and-swap で更新する。

        - project 不在: ``None`` を返す。
        - ``expected_autonomy_level`` が row lock 後の current と不一致: ``AutonomyExpectationMismatch``。
        - それ以外: 更新し ``AutonomyUpdateResult`` を返す (commit は呼び出し側が行う)。
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

        previous_autonomy_level: AutonomyLevel = project.autonomy_level
        # compare-and-swap: stale な baseline からの re-escalation を拒否する。
        if previous_autonomy_level != expected_autonomy_level:
            raise AutonomyExpectationMismatch(
                expected=expected_autonomy_level,
                actual=previous_autonomy_level,
            )

        resolution = resolve_autonomy_policy_profile(
            autonomy_level,
            runtime_enabled=False,
        )
        changed = previous_autonomy_level != resolution.autonomy_level
        project.autonomy_level = resolution.autonomy_level
        project.policy_profile = resolution.policy_profile
        await self.session.flush()
        await self.session.refresh(project)
        return AutonomyUpdateResult(
            project=project,
            previous_autonomy_level=previous_autonomy_level,
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
    "AutonomyExpectationMismatch",
    "AutonomyUpdateResult",
    "ProjectAutonomySettingsService",
]
