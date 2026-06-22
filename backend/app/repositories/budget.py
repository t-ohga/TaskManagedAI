from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.active_registry_mutation_gate import mark_emergency_stop_bypass
from backend.app.db.models.budget import Budget
from backend.app.domain.agent_runtime.budget import BudgetLevel
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.repositories.base import BaseRepository


class StaleKillSwitchClearError(RuntimeError):
    """budget global kill switch の CAS token 不一致で clear を拒否した (B6 P2-4、→ 409)。

    別 engage が割り込んで budget の ``updated_at`` が進んだ (= 古い token の stale clear)、または clear
    対象の active global budget が存在しない場合に raise する。endpoint は 409 CONFLICT に写像する。
    """


def _next_monotonic_updated_at(previous: datetime) -> datetime:
    """engage 操作ごとに **厳密に増加** する CAS token を返す (B6 P2-4)。

    ``datetime.now`` は連続呼び出しで同一 microsecond を返し得る (高速 double-submit)。CAS token が
    重複すると stale clear を検出できないため、``max(now, previous + 1μs)`` で厳密 monotonic を保証する。
    """
    now = datetime.now(tz=UTC)
    prev = previous if previous.tzinfo is not None else previous.replace(tzinfo=UTC)
    floor = prev + timedelta(microseconds=1)
    return now if now > floor else floor


def _updated_at_matches(actual: datetime, expected: datetime) -> bool:
    """CAS token (updated_at) の一致判定。tz-aware に揃えて exact 比較する (B6 P2-4)。

    DB の ``updated_at`` は tz-aware (``timestamptz``)。client が status GET で受け取った値を ISO で
    返してくるため、両者を比較する。tz-naive が来た場合は UTC とみなして揃える (fail-closed 寄りに
    厳密一致を要求し、ズレていれば stale 扱い)。
    """
    actual_utc = actual if actual.tzinfo is not None else actual.replace(tzinfo=UTC)
    expected_utc = expected if expected.tzinfo is not None else expected.replace(tzinfo=UTC)
    return actual_utc == expected_utc


_MUTABLE_FIELDS = frozenset(
    {
        "hard_usd_limit",
        "soft_usd_threshold",
        "hard_tokens_limit",
        "hard_wall_clock_ms",
        "max_retries",
        "active",
        "global_kill_switch",
    }
)


def _global_kill_switch_lock_key(tenant_id: int) -> str:
    """tenant-scoped budget global-kill-switch advisory lock の canonical key (B6 P2-2)。

    emergency-stop latch (``superintendent-emergency-stop:<tenant>``) とは **別 key** にし、両安全弁が
    互いの critical section を不要に block しないようにする。engage/clear の find-or-create + toggle は
    この同一 key で ``pg_advisory_xact_lock`` を取り、並行 first-time engage が両方 INSERT を試みて
    partial unique (``budgets_uq_global_level_active``) で 500 になる double-submit を排除する。
    """
    return f"budget-global-kill-switch:{tenant_id}"


class BudgetRepository(BaseRepository[Budget]):
    def __init__(self, session: AsyncSession, tenant_id: int | None = None) -> None:
        super().__init__(session, Budget, tenant_id=tenant_id)

    async def get(self, tenant_id: int, id: UUID) -> Budget | None:
        return await super().get(tenant_id=tenant_id, id=id)

    async def list_active(self, tenant_id: int) -> list[Budget]:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            sa.select(Budget)
            .where(
                Budget.tenant_id == tenant_id,
                Budget.active.is_(True),
            )
            .order_by(Budget.level, Budget.created_at, Budget.id)
        )
        return list(result.scalars().all())

    async def list_effective_for_run(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        run_id: UUID,
    ) -> dict[BudgetLevel, Budget]:
        await self._ensure_tenant_context(tenant_id)

        result = await self.session.execute(
            sa.select(Budget)
            .where(
                Budget.tenant_id == tenant_id,
                Budget.active.is_(True),
                sa.or_(
                    Budget.level == "global",
                    Budget.level == "tenant",
                    sa.and_(Budget.level == "project", Budget.level_id == project_id),
                    sa.and_(Budget.level == "agent_run", Budget.level_id == run_id),
                ),
            )
            .order_by(Budget.created_at, Budget.id)
        )

        budgets: dict[BudgetLevel, Budget] = {}
        for budget in result.scalars().all():
            budgets.setdefault(budget.level, budget)
        return budgets

    async def create_with_audit(
        self,
        *,
        tenant_id: int,
        payload: dict[str, Any],
        actor_id: UUID,
    ) -> Budget:
        budget = await super().create(tenant_id=tenant_id, payload=payload)
        await AuditEventRepository(self.session).append(
            tenant_id=tenant_id,
            event_type="budget_created",
            actor_id=actor_id,
            payload={
                "budget_id": str(budget.id),
                "level": budget.level,
                "level_id": None if budget.level_id is None else str(budget.level_id),
                "active": budget.active,
            },
        )
        return budget

    async def update_active_flag(
        self,
        *,
        tenant_id: int,
        id: UUID,
        active: bool,
        actor_id: UUID,
    ) -> Budget | None:
        budget = await super().update(tenant_id=tenant_id, id=id, payload={"active": active})
        if budget is not None:
            await AuditEventRepository(self.session).append(
                tenant_id=tenant_id,
                event_type="budget_active_flag_updated",
                actor_id=actor_id,
                payload={
                    "budget_id": str(budget.id),
                    "level": budget.level,
                    "level_id": None if budget.level_id is None else str(budget.level_id),
                    "active": budget.active,
                },
            )
        return budget

    async def update_limits_with_audit(
        self,
        *,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
        actor_id: UUID,
    ) -> Budget | None:
        unexpected = sorted(set(payload) - _MUTABLE_FIELDS)
        if unexpected:
            raise ValueError(f"budget update fields are not mutable: {unexpected}")

        budget = await super().update(tenant_id=tenant_id, id=id, payload=payload)
        if budget is not None:
            await AuditEventRepository(self.session).append(
                tenant_id=tenant_id,
                event_type="budget_limits_updated",
                actor_id=actor_id,
                payload={
                    "budget_id": str(budget.id),
                    "level": budget.level,
                    "level_id": None if budget.level_id is None else str(budget.level_id),
                    "changed_fields": sorted(payload),
                },
            )
        return budget

    async def get_active_global(self, tenant_id: int) -> Budget | None:
        """active な global-level budget row を返す (SP-PHASE1 B6、ADR-00048 §A-8)。

        global budget は ``budgets_uq_global_level_active`` partial unique index で
        ``level='global' AND active=true`` が最大 1 件。``global_kill_switch`` flag を載せられるのは
        global budget のみ (``budgets_ck_global_kill_switch_only_global``)。
        """
        await self._ensure_tenant_context(tenant_id)
        budget: Budget | None = await self.session.scalar(
            sa.select(Budget).where(
                Budget.tenant_id == tenant_id,
                Budget.level == "global",
                Budget.active.is_(True),
            )
        )
        return budget

    async def _acquire_global_kill_switch_lock(self, tenant_id: int) -> None:
        """tenant-scoped budget global-kill-switch advisory lock を caller transaction で取得 (B6 P2-2)。

        ``pg_advisory_xact_lock`` は transaction-scoped (commit/rollback で解放)。engage/clear の
        find-or-create + toggle はこの lock 保持下で行い、active global budget が **未存在** のときの
        並行 first-time engage (両 request が 0-row lock の隙間で INSERT を試みて partial unique 衝突 → 500)
        を排除する。0-row ``SELECT ... FOR UPDATE`` は行を lock できないため、行不在でも線形化する advisory
        lock が必要 (emergency-stop §A-7 と同型だが別 key)。
        """
        await self.session.execute(
            sa.text("select pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": _global_kill_switch_lock_key(tenant_id)},
        )

    async def set_global_kill_switch(
        self,
        *,
        tenant_id: int,
        engaged: bool,
        actor_id: UUID,
    ) -> Budget:
        """budget global_kill_switch (コスト緊急停止) を **engage** する (SP-PHASE1 B6、ADR-00048 §A-8)。

        emergency-stop latch (human 即時全停止) とは **別目的** だが、autonomy / budget choke point で
        OR 評価される (どちらか engaged なら deny。OR 配線は B5a/B6 P2-1 で済、本 API は budget 側 flag の
        operator surface)。active な global budget が無ければ flag だけ持つ minimal global budget を
        **find-or-create** し、``global_kill_switch`` を set する。audit
        (``budget_global_kill_switch_updated``、raw 値なし)。

        並行 first-time engage は B6 P2-2 で tenant-scoped advisory lock により直列化する (0-row
        ``FOR UPDATE`` では未存在 row を lock できず partial unique で 500 になるため。advisory lock →
        find-or-create の順)。冪等: 既に同値なら no-op で row を返す (audit は engage 操作の証跡として常に残す)。
        """
        await self._ensure_tenant_context(tenant_id)
        # B6 P2-3 (A-3): operator safety stop は host-freeze 中も engage できなければならない。
        # commit を active-registry freeze gate (L3) から bypass する (emergency-stop latch と同思想)。
        mark_emergency_stop_bypass(self.session)
        # B6 P2-2: find-or-create を tenant-scoped advisory lock で直列化 (並行 first-time engage の 500 防止)。
        await self._acquire_global_kill_switch_lock(tenant_id)
        budget = await self.session.scalar(
            sa.select(Budget)
            .where(
                Budget.tenant_id == tenant_id,
                Budget.level == "global",
                Budget.active.is_(True),
            )
            .with_for_update()
        )
        if budget is None:
            budget = await super().create(
                tenant_id=tenant_id,
                payload={
                    "level": "global",
                    "level_id": None,
                    "active": True,
                    "global_kill_switch": engaged,
                },
            )
            created = True
        else:
            # B6 P2-4: CAS token (updated_at) を **engage 操作ごとに厳密 monotonic に進める**。flag 値が
            # 同値 (冪等 re-engage) でも token を進めないと「tab A が engaged を load → tab B が re-engage →
            # tab A の古い clear」で stale clear が勝ってしまう。ORM の ``onupdate`` (plain now()) は (1) net
            # change が無いと発火しない (2) 高速 double-submit で同一 microsecond を返し token が重複し得る、
            # ため explicit ``UPDATE ... RETURNING`` で書き、in-memory の値も RETURNING で同期する
            # (ORM 属性 set + onupdate override の不整合を避ける)。lock は ``with_for_update`` で保持済。
            await self._update_kill_switch(budget, engaged=engaged)
            created = False
        await AuditEventRepository(self.session).append(
            tenant_id=tenant_id,
            event_type="budget_global_kill_switch_updated",
            actor_id=actor_id,
            payload={
                "budget_id": str(budget.id),
                "level": budget.level,
                "global_kill_switch": engaged,
                "created": created,
            },
        )
        return budget

    async def _update_kill_switch(self, budget: Budget, *, engaged: bool) -> None:
        """locked budget row の ``global_kill_switch`` を set し ``updated_at`` を厳密 monotonic に進める。

        explicit ``UPDATE ... RETURNING updated_at`` で書き、in-memory ORM 属性 (``global_kill_switch`` /
        ``updated_at``) を RETURNING 値で同期する。ORM 属性代入 + ``onupdate`` (plain now()) の override が
        起こす「response とDB persisted の不整合」を回避し、CAS token が response と DB で必ず一致する。
        """
        new_updated_at = _next_monotonic_updated_at(budget.updated_at)
        result = await self.session.execute(
            sa.update(Budget)
            .where(Budget.tenant_id == budget.tenant_id, Budget.id == budget.id)
            .values(global_kill_switch=engaged, updated_at=new_updated_at)
            .returning(Budget.updated_at)
        )
        persisted_updated_at = result.scalar_one()
        budget.global_kill_switch = engaged
        budget.updated_at = persisted_updated_at

    async def clear_global_kill_switch(
        self,
        *,
        tenant_id: int,
        actor_id: UUID,
        expected_updated_at: datetime,
    ) -> Budget:
        """budget global_kill_switch を **clear** する (SP-PHASE1 B6 P2-4、CAS = stale clear reject、A-8)。

        emergency-stop latch の generation CAS と同型の楽観ロック。status GET が返す
        ``(budget_id, updated_at)`` を CAS token として要求し、別 engage が割り込んで budget の
        ``updated_at`` が進んでいたら :class:`StaleKillSwitchClearError` を raise する (→ 409)。これにより
        「tab A が engaged を load → tab B が re-engage → tab A の古い clear submit で stale clear が勝つ」
        という race を排除する (古い token の clear は最新状態を上書きしない)。

        active global budget 不在も :class:`StaleKillSwitchClearError` (clear 対象がない = stale)。clear は
        ``global_kill_switch=False`` を set。並行は advisory lock で直列化 (engage と同 key)。
        """
        await self._ensure_tenant_context(tenant_id)
        # B6 P2-3 (A-3): clear も operator safety stop の一部 (host-freeze 中も到達可能)。freeze gate bypass。
        mark_emergency_stop_bypass(self.session)
        await self._acquire_global_kill_switch_lock(tenant_id)
        budget = await self.session.scalar(
            sa.select(Budget)
            .where(
                Budget.tenant_id == tenant_id,
                Budget.level == "global",
                Budget.active.is_(True),
            )
            .with_for_update()
        )
        if budget is None:
            raise StaleKillSwitchClearError(
                "no active global budget to clear (kill switch state changed)"
            )
        # CAS: caller が load した CAS token (updated_at) が現在値と一致しない = 別 engage が割り込んだ。
        if not _updated_at_matches(budget.updated_at, expected_updated_at):
            raise StaleKillSwitchClearError(
                "global kill switch state changed since it was loaded (stale clear rejected)"
            )
        await self._update_kill_switch(budget, engaged=False)
        await AuditEventRepository(self.session).append(
            tenant_id=tenant_id,
            event_type="budget_global_kill_switch_updated",
            actor_id=actor_id,
            payload={
                "budget_id": str(budget.id),
                "level": budget.level,
                "global_kill_switch": False,
                "created": False,
            },
        )
        return budget

    async def delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Budget rows are disabled with active=false, not deleted.")

    def statement_for_delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Budget rows are disabled with active=false, not deleted.")


__all__ = ["BudgetRepository", "StaleKillSwitchClearError"]

