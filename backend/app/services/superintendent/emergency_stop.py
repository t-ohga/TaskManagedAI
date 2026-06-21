"""Emergency-stop latch service (SP-PHASE1 B3、ADR-00048 §B/B-1/B-3/A-4/A-5/A-6/A-7/A-8/A-10)。

human-only な「全 AI 即停止」安全弁の latch + run block/resume を実装する。本 service が担うのは
**latch 設定 + 新規活動 deny の根拠 + active run の block + clear/resume** までで、cross-process な
in-flight subprocess の実 SIGKILL は B4 supervisor の責務 (本 service は Redis wake **publish stub**
の枠と DB latch のみ)。

中核 invariant:
- **advisory lock 直列化 (A-7/B-1)**: engage/clear は ``pg_advisory_xact_lock(hashtextextended(
  'superintendent-emergency-stop:' || tenant_id, 0))`` を transaction 入口で取得し、latch check と
  side effect (latch row 作成 / run block) を同一 critical section で線形化する (TOCTOU 防止、spawn と
  同 lock を共有して claim が必ず latch を見る)。
- **generation CAS (B-3)**: clear は ``expected_generation`` 一致時のみ成功 (stale clear reject)。
- **state 復元 (A-5/B-3)**: block 時に ``pre_stop_status`` を保存し、clear で復元表通りに戻す
  (一律 running にせず approval/diff/policy gate を skip しない)。block source / resume 復元先は
  ``running``/``policy_linted``/``diff_ready``/``waiting_approval`` に限定 (state machine A-5)。
- **event witness (B1)**: block は ``emergency_stop_engaged`` event、resume は
  ``emergency_stop_resumed`` event で AgentRunEvent に append (status update と同一 transaction)。
- **active_registry gate bypass (A-3)**: engage/clear commit は host-freeze gate を bypass する。
- raw secret / pid / token を audit / response に出さない (assert_no_raw_secret、pid は audit 非含)。

transaction 境界 / commit は **caller (endpoint)** が制御する。本 service は flush までで commit しない
(advisory lock を engage→block (→ caller commit) まで transaction-scoped に保持する、A-1 と同思想)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.active_registry_mutation_gate import mark_emergency_stop_bypass
from backend.app.db.models.actor import Actor
from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.audit_event import AuditEvent
from backend.app.db.models.superintendent_emergency_stop import SuperintendentEmergencyStop
from backend.app.domain.agent_runtime.run_mode import RunMode
from backend.app.domain.agent_runtime.status import AgentRunStatus
from backend.app.domain.superintendent.emergency_stop_reason import (
    EmergencyStopReasonCode,
)
from backend.app.repositories.agent_run_event import append_event
from backend.app.services.agent_runtime.state_machine import validate_transition
from backend.app.services.orchestrator._shared import ensure_tenant_context, utc_now

#: A-5: emergency block 可能 (= resume 復元先) な status (state machine の正当 block source)。
#: それ以外の非 block-source / terminal / 既 blocked は status 遷移させず latch 任せ。
_BLOCK_SOURCE_STATUSES: tuple[AgentRunStatus, ...] = (
    "running",
    "policy_linted",
    "diff_ready",
    "waiting_approval",
)


class EmergencyStopEngagedError(RuntimeError):
    """emergency-stop latch が engaged のため新規活動を deny した (fail-closed)。

    spawn / choke point (B5) が latch engaged を観測したときに raise する。``reason_code`` は
    ``emergency_stop_engaged`` (A-6 独立 application reason_code)。
    """

    reason_code: EmergencyStopReasonCode = "emergency_stop_engaged"

    def __init__(self, tenant_id: int) -> None:
        super().__init__(
            f"emergency-stop latch engaged for tenant {tenant_id}; new activity denied"
        )
        self.tenant_id = tenant_id


@dataclass(frozen=True, slots=True)
class EmergencyStopLatch:
    """active emergency-stop latch の view (raw secret / pid を含まない)。"""

    id: UUID
    tenant_id: int
    generation: int
    engaged_at: datetime
    engaged_by_actor_id: UUID


@dataclass(frozen=True, slots=True)
class EngageResult:
    engaged: bool
    blocked_run_count: int
    generation: int
    engaged_at: datetime
    #: 既 active latch を観測して冪等 no-op だったか (二重 engage)。
    already_engaged: bool


@dataclass(frozen=True, slots=True)
class ClearResult:
    cleared: bool
    resumed_run_count: int
    generation: int
    cleared_at: datetime


class EmergencyStopServiceError(RuntimeError):
    """operator / generation など precondition 違反 (caller が HTTP 4xx に写像する)。"""


class StaleGenerationError(EmergencyStopServiceError):
    """clear の expected_generation が active latch generation と一致しない (B-3 CAS、409)。"""


class NotEngagedError(EmergencyStopServiceError):
    """clear 対象の active latch が存在しない (409)。"""


class EmergencyStopService:
    """tenant-scoped emergency-stop latch の engage / clear / is_engaged。

    全 query は tenant-scoped。status update + event append は同一 transaction (core.md §11)。
    advisory lock は transaction-scoped (commit/rollback で解放)。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- advisory lock (A-7、codebase 既存形式 hashtextextended 統一) ---

    async def _acquire_tenant_lock(self, tenant_id: int) -> None:
        await self._session.execute(
            sa.text("select pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"superintendent-emergency-stop:{tenant_id}"},
        )

    # --- operator gate (engage/clear 共通、A-10 owner gate と整合) ---

    async def _assert_human_operator(self, *, tenant_id: int, actor_id: UUID) -> None:
        """DB 上の actor_type=='human' を確認 (kill switch human-only、kill_switch.py 準拠)。

        operator authentication / owner identity の検証は API 層 ``require_emergency_stop_operator``
        が担う (authenticated session + configured owner)。本 service の DB gate は最終防衛として
        actor が human であることを確認し、agent/service/provider/github_app による直接呼出を deny。
        """
        actor_type = await self._session.scalar(
            sa.select(Actor.actor_type).where(
                Actor.tenant_id == tenant_id,
                Actor.id == actor_id,
            )
        )
        if actor_type != "human":
            raise EmergencyStopServiceError(
                "emergency-stop operator must reference a human actor."
            )

    # --- latch query ---

    async def _active_latch(self, tenant_id: int) -> SuperintendentEmergencyStop | None:
        row: SuperintendentEmergencyStop | None = await self._session.scalar(
            sa.select(SuperintendentEmergencyStop).where(
                SuperintendentEmergencyStop.tenant_id == tenant_id,
                SuperintendentEmergencyStop.cleared_at.is_(None),
            )
        )
        return row

    async def is_engaged(self, tenant_id: int) -> bool:
        """active latch が存在するか (fail-closed latch check の bool 形、B5 choke point 用)。"""
        await ensure_tenant_context(self._session, tenant_id)
        row = await self._active_latch(tenant_id)
        return row is not None

    async def get_active(self, tenant_id: int) -> EmergencyStopLatch | None:
        await ensure_tenant_context(self._session, tenant_id)
        row = await self._active_latch(tenant_id)
        if row is None:
            return None
        return EmergencyStopLatch(
            id=row.id,
            tenant_id=row.tenant_id,
            generation=row.generation,
            engaged_at=row.engaged_at,
            engaged_by_actor_id=row.engaged_by_actor_id,
        )

    async def _max_generation(self, tenant_id: int) -> int:
        result = await self._session.scalar(
            sa.select(sa.func.coalesce(sa.func.max(SuperintendentEmergencyStop.generation), 0))
            .where(SuperintendentEmergencyStop.tenant_id == tenant_id)
        )
        return int(result or 0)

    # --- engage ---

    async def engage(
        self,
        *,
        tenant_id: int,
        operator_actor_id: UUID,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> EngageResult:
        """latch を engage し、active run を block する (advisory lock 下、B/B-1/A-5)。

        - active latch が既にあれば **冪等 no-op** (同一 latch を返す、二重 engage)。
        - 新規 engage 時は generation = (前 active の generation) + 1 (active が無ければ max+1)。
        - active run (running/policy_linted/diff_ready/waiting_approval) を ``blocked`` へ遷移し、
          ``emergency_stop_engaged`` event を append、``pre_stop_status`` に元 status を保存する。
        - 非 block-source/terminal/既 blocked は status 遷移させず latch 任せ (A-5)。
        - audit (``emergency_stop_engaged``、actor/tenant/generation/blocked_run_count、raw 値なし)。
        - commit は caller (advisory lock を block まで保持)。host-freeze gate を bypass (A-3)。
        """
        await ensure_tenant_context(self._session, tenant_id)
        mark_emergency_stop_bypass(self._session)  # A-3: freeze gate bypass。
        await self._assert_human_operator(tenant_id=tenant_id, actor_id=operator_actor_id)
        await self._acquire_tenant_lock(tenant_id)

        resolved_now = now or utc_now()

        existing = await self._active_latch(tenant_id)
        if existing is not None:
            # 冪等 no-op (二重 engage): 既 active latch を返す。新 row / block は作らない。
            return EngageResult(
                engaged=True,
                blocked_run_count=0,
                generation=existing.generation,
                engaged_at=existing.engaged_at,
                already_engaged=True,
            )

        generation = await self._max_generation(tenant_id) + 1
        latch = SuperintendentEmergencyStop(
            tenant_id=tenant_id,
            generation=generation,
            engaged_at=resolved_now,
            engaged_by_actor_id=operator_actor_id,
            reason=reason,
        )
        self._session.add(latch)
        await self._session.flush()

        blocked_run_count = await self._block_active_runs(
            tenant_id=tenant_id,
            operator_actor_id=operator_actor_id,
            generation=generation,
            now=resolved_now,
        )

        await self._emit_audit(
            tenant_id=tenant_id,
            actor_id=operator_actor_id,
            reason_code="emergency_stop_engaged",
            generation=generation,
            run_count=blocked_run_count,
            reason=reason,
        )
        return EngageResult(
            engaged=True,
            blocked_run_count=blocked_run_count,
            generation=generation,
            engaged_at=resolved_now,
            already_engaged=False,
        )

    async def _block_active_runs(
        self,
        *,
        tenant_id: int,
        operator_actor_id: UUID,
        generation: int,
        now: datetime,
    ) -> int:
        """block source state の active run を ``blocked`` へ遷移 + pre_stop_status 保存 + event。

        ``validate_transition`` で各 (from -> blocked) edge を **run の実 run_mode で** 検証し (state
        machine 逸脱防止 + shadow confinement 保全、LOW-3)、status update と
        ``emergency_stop_engaged`` event append を同一 transaction で行う。FOR UPDATE で row を lock し
        並行 transition (engage 中の通常進行) と線形化する。

        event の ``idempotency_key`` は ``...:{run_id}:{generation}`` で **engage cycle ごとに unique**
        (HIGH fix)。``generation`` は latch の monotonic CAS 値 (deterministic、timestamp 不使用)。
        constant key だと engage→clear→engage の 2 回目で同一 run 再 block 時に partial unique
        ``(tenant_id, run_id, idempotency_key)`` の UniqueViolation → engage transaction 全 rollback →
        latch 巻き戻り = kill switch fail-open になる。generation を key に混ぜて回避する。
        """
        rows = (
            await self._session.execute(
                sa.select(AgentRun.id, AgentRun.status, AgentRun.run_mode)
                .where(
                    AgentRun.tenant_id == tenant_id,
                    AgentRun.status.in_(_BLOCK_SOURCE_STATUSES),
                )
                .with_for_update()
            )
        ).all()

        blocked = 0
        for run_id, from_status, run_mode in rows:
            from_state: AgentRunStatus = from_status
            mode: RunMode = run_mode
            # state machine 逸脱を防ぐ (block source 以外は select で除外済だが二重防御)。
            # run の実 run_mode で検証し shadow confinement guard を保全する (LOW-3)。
            validate_transition(from_state, "blocked", run_mode=mode)
            await self._session.execute(
                sa.update(AgentRun)
                .where(
                    AgentRun.tenant_id == tenant_id,
                    AgentRun.id == run_id,
                    AgentRun.status == from_state,
                )
                .values(
                    status="blocked",
                    blocked_reason="runtime_blocked",
                    pre_stop_status=from_state,
                    updated_at=now,
                )
            )
            await append_event(
                self._session,
                tenant_id=tenant_id,
                run_id=run_id,
                event_type="emergency_stop_engaged",
                actor_id=operator_actor_id,
                payload={
                    "engaged_by_actor_id": str(operator_actor_id),
                    "pre_stop_status": from_state,
                    "blocked_reason": "runtime_blocked",
                    "engaged_at": now.isoformat(),
                    "generation": generation,
                },
                # HIGH: engage cycle ごとに unique (generation = monotonic CAS、deterministic)。
                # constant key は engage→clear→engage の 2 回目で UniqueViolation → fail-open。
                idempotency_key=f"emergency-stop-engage:{run_id}:{generation}",
            )
            blocked += 1
        return blocked

    # --- clear / resume ---

    async def clear(
        self,
        *,
        tenant_id: int,
        operator_actor_id: UUID,
        expected_generation: int,
        now: datetime | None = None,
    ) -> ClearResult:
        """latch を clear し block 中 run を pre_stop_status へ復元する (advisory lock + CAS、B-3/A-5)。

        - active latch が無ければ ``NotEngagedError`` (409)。
        - ``expected_generation`` が active latch の generation と不一致なら ``StaleGenerationError``
          (409、stale clear reject)。
        - ``cleared_at`` / ``cleared_by_actor_id`` を set し latch を解除。
        - block 中 (status='blocked' + blocked_reason='runtime_blocked' + pre_stop_status not null) の
          run を ``pre_stop_status`` へ復元 (一律 running 禁止、gate skip 防止)、``emergency_stop_resumed``
          event を append、``pre_stop_status`` を NULL に戻す。
        - audit (``emergency_stop_resumed``、raw 値なし)。
        """
        await ensure_tenant_context(self._session, tenant_id)
        mark_emergency_stop_bypass(self._session)  # A-3。
        await self._assert_human_operator(tenant_id=tenant_id, actor_id=operator_actor_id)
        await self._acquire_tenant_lock(tenant_id)

        resolved_now = now or utc_now()
        latch = await self._active_latch(tenant_id)
        if latch is None:
            raise NotEngagedError(
                f"no active emergency-stop latch for tenant {tenant_id}."
            )
        if latch.generation != expected_generation:
            raise StaleGenerationError(
                "emergency-stop generation mismatch "
                f"(expected {expected_generation}, active {latch.generation})."
            )

        latch.cleared_at = resolved_now
        latch.cleared_by_actor_id = operator_actor_id
        await self._session.flush()

        resumed_run_count = await self._resume_blocked_runs(
            tenant_id=tenant_id,
            operator_actor_id=operator_actor_id,
            generation=latch.generation,
            now=resolved_now,
        )

        await self._emit_audit(
            tenant_id=tenant_id,
            actor_id=operator_actor_id,
            reason_code="emergency_stop_resumed",
            generation=latch.generation,
            run_count=resumed_run_count,
            reason=None,
        )
        return ClearResult(
            cleared=True,
            resumed_run_count=resumed_run_count,
            generation=latch.generation,
            cleared_at=resolved_now,
        )

    async def _resume_blocked_runs(
        self,
        *,
        tenant_id: int,
        operator_actor_id: UUID,
        generation: int,
        now: datetime,
    ) -> int:
        """emergency-stop で block された run を pre_stop_status へ復元する (B-3/A-5)。

        emergency-stop block の識別: status='blocked' + blocked_reason='runtime_blocked' +
        pre_stop_status IS NOT NULL。pre_stop_status へ run の実 run_mode で ``validate_transition``
        復元し (shadow confinement guard 保全、LOW-3)、``emergency_stop_resumed`` event を append、
        pre_stop_status を NULL に戻す。

        resume event の ``idempotency_key`` も engage と同じく generation 混入で **cycle ごとに unique**
        (deterministic、engage 側 HIGH fix と一貫。timestamp に依存しない)。
        """
        rows = (
            await self._session.execute(
                sa.select(AgentRun.id, AgentRun.pre_stop_status, AgentRun.run_mode)
                .where(
                    AgentRun.tenant_id == tenant_id,
                    AgentRun.status == "blocked",
                    AgentRun.blocked_reason == "runtime_blocked",
                    AgentRun.pre_stop_status.is_not(None),
                )
                .with_for_update()
            )
        ).all()

        resumed = 0
        for run_id, pre_stop_status, run_mode in rows:
            target: AgentRunStatus = pre_stop_status
            mode: RunMode = run_mode
            # blocked -> pre_stop_status の復元 edge を run の実 run_mode で検証 (gate skip 防止 +
            # shadow confinement guard 保全、LOW-3)。
            validate_transition("blocked", target, run_mode=mode)
            await self._session.execute(
                sa.update(AgentRun)
                .where(
                    AgentRun.tenant_id == tenant_id,
                    AgentRun.id == run_id,
                    AgentRun.status == "blocked",
                    AgentRun.blocked_reason == "runtime_blocked",
                )
                .values(
                    status=target,
                    blocked_reason=None,
                    pre_stop_status=None,
                    updated_at=now,
                )
            )
            await append_event(
                self._session,
                tenant_id=tenant_id,
                run_id=run_id,
                event_type="emergency_stop_resumed",
                actor_id=operator_actor_id,
                payload={
                    "resumed_by_actor_id": str(operator_actor_id),
                    "restored_status": target,
                    "resumed_at": now.isoformat(),
                    "generation": generation,
                },
                idempotency_key=f"emergency-stop-resume:{run_id}:{generation}",
            )
            resumed += 1
        return resumed

    # --- audit ---

    async def _emit_audit(
        self,
        *,
        tenant_id: int,
        actor_id: UUID,
        reason_code: EmergencyStopReasonCode,
        generation: int,
        run_count: int,
        reason: str | None,
    ) -> None:
        """emergency-stop decision を audit_events に append (raw secret / pid / token 非含)。

        payload は actor / tenant / generation / run_count / reason_code のみ。reason (operator 入力)
        は free-text のため AuditEvent の JSONB を insert する前に raw secret scan で防御する。
        pid / lease token 等 supervision metadata は audit に出さない (B4 で kill 時も同方針)。
        """
        payload: dict[str, object] = {
            "rls_ready": True,
            "reason_code": reason_code,
            "generation": generation,
            "run_count": run_count,
        }
        if reason is not None:
            payload["operator_reason"] = reason
        # raw secret / token / pid を audit に残さない (AgentRunEvent と同 scanner)。
        from backend.app.repositories._payload_secret_scan import assert_no_raw_secret

        assert_no_raw_secret(payload, path="$emergency_stop_audit")
        self._session.add(
            AuditEvent(
                tenant_id=tenant_id,
                event_type="config_changed",
                actor_id=actor_id,
                event_payload=payload,
            )
        )


__all__ = [
    "ClearResult",
    "EmergencyStopEngagedError",
    "EmergencyStopLatch",
    "EmergencyStopService",
    "EmergencyStopServiceError",
    "EngageResult",
    "NotEngagedError",
    "StaleGenerationError",
]
