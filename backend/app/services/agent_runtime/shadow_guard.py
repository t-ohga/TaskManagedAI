"""SP-029 shadow mode (ADR-00055) side-effect isolation guard.

shadow run (``run_mode='shadow'``) は production state を汚さない試走であり、
mutating side effect (ApprovalRequest 作成 / RepoProxy repo write /
``runner_mutation_gateway`` mutation / merge / deploy) を一切起動してはならない
(ADR-00055 §設計制約 3)。

二重防御:

1. **primary**: orchestrator が shadow run を ``schema_validated -> completed`` で
   terminal 化し、``policy_linted`` / ``diff_ready`` / ``waiting_approval`` の副作用
   stage をそもそも通らない (state machine の run_mode-gated edge、
   ``execute_shadow_completion_step``)。
2. **secondary (本 module)**: 万一 orchestrator 以外の経路が shadow run に対して
   side effect を起動しようとした場合の fail-closed guard。``assert_not_shadow`` /
   ``assert_run_id_not_shadow`` が ApprovalRequest 作成 choke point で発火する。

approval は ``repo_write`` / ``pr_open`` / runner mutation / merge / deploy すべての
前提 gate (AI Output Boundary §8、deny-by-default) であり、approval 作成を shadow
run に対して拒否すれば downstream の mutating 経路は **transitively** 封鎖される
(``approval_pass`` を得られない shadow run は ``runner_mutation_gateway`` を通過
できず、merge / deploy は P0 で deny)。本 guard は fail-closed (raise) で呼出側
transaction を rollback させ、副作用 row が永続化しないことを保証する。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run import AgentRun

SHADOW_SIDE_EFFECT_REASON_CODE = "shadow_side_effect_forbidden"


class ShadowSideEffectError(RuntimeError):
    """shadow run が mutating side effect を起動しようとしたときに raise する。

    ``run_mode='shadow'`` の run に対する ApprovalRequest 作成等の副作用は
    ADR-00055 §設計制約 3 で禁止。raise により呼出側 transaction が rollback され、
    副作用 row が永続化しないこと (fail-closed) を保証する。
    """

    def __init__(
        self,
        *,
        run_id: UUID,
        operation: str,
        reason_code: str = SHADOW_SIDE_EFFECT_REASON_CODE,
    ) -> None:
        self.run_id = run_id
        self.operation = operation
        self.reason_code = reason_code
        super().__init__(
            f"shadow run {run_id} cannot trigger mutating operation {operation!r} "
            f"(reason_code={reason_code})"
        )


def assert_not_shadow(run: AgentRun, *, operation: str) -> None:
    """``run`` が shadow run なら ``ShadowSideEffectError`` を raise する (pure)。

    production run は no-op。run_mode 列を唯一の判定源にし、caller 申告には依存
    しない (server-owned boundary)。
    """

    if run.run_mode == "shadow":
        raise ShadowSideEffectError(run_id=run.id, operation=operation)


async def assert_run_id_not_shadow(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID | None,
    operation: str,
) -> None:
    """``(tenant_id, run_id)`` の run を解決し、shadow なら fail-closed で raise。

    ``run_id is None`` (run 非紐付の side effect) と run 不在 (FK / 既存 not-found
    処理に委ねる) は guard を skip する。run_mode は DB row から解決し caller 申告を
    信頼しない。
    """

    if run_id is None:
        return
    run = await session.scalar(
        select(AgentRun).where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.id == run_id,
        )
    )
    if run is not None:
        assert_not_shadow(run, operation=operation)


__all__ = [
    "SHADOW_SIDE_EFFECT_REASON_CODE",
    "ShadowSideEffectError",
    "assert_not_shadow",
    "assert_run_id_not_shadow",
]
