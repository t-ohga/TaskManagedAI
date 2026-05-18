"""Sprint 12 batch 10 (BL-0149 evidence chain): P0 acceptance audit DB write skeleton.

`P0AcceptanceAuditPayload` (batch 6) → `audit_events` ORM model 構築の pure
function. 実 DB write 経路は caller (BL-0149 sign-off endpoint / CLI) が
session.add + commit を実行する.

invariants (.claude/rules/secretbroker-boundary.md §11 + DD-04):
- raw secret / capability token 生値は event_payload に含めない (caller が事前 redact 済)
- tenant_id / actor_id / principal_id は caller が解決した値を渡す (signature レベル)
- correlation_id / trace_id は optional metadata (P0 では active observability)
- event_type は `AUDIT_EVENT_TYPE_P0_ACCEPTANCE_REPORT_GENERATED` 固定
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID, uuid4

from backend.app.db.models.audit_event import AuditEvent
from backend.app.services.eval.p0_acceptance_audit_emit import (
    AUDIT_EVENT_TYPE_P0_ACCEPTANCE_REPORT_GENERATED,
    P0AcceptanceAuditPayload,
)

# Sprint 12 batch 10 fixed contract: BL-0149 audit emit は principal_id を null
# として記録する (sign-off は principal-bound でない system-level emit). DB
# CHECK constraint `(principal_id is null) or (actor_id is not null)` 整合.
_EXPECTED_PRINCIPAL_ID: Final[None] = None


@dataclass(frozen=True, slots=True)
class P0AcceptanceAuditWriteContext:
    """Caller が解決した tenant / actor / observability context.

    DB write 自体は caller が `session.add(audit_event)` + commit で実行する.
    """

    tenant_id: int
    actor_id: UUID  # human sign-off actor (self-approval 禁止 verify は caller 責務)
    correlation_id: str | None = None
    trace_id: str | None = None
    explicit_id: UUID | None = None  # test fixture 用 (None なら uuid4 で生成)


def build_p0_acceptance_audit_event(
    *,
    payload: P0AcceptanceAuditPayload,
    context: P0AcceptanceAuditWriteContext,
) -> AuditEvent:
    """`P0AcceptanceAuditPayload` + caller context から `AuditEvent` ORM 構築.

    pure function. 実 DB write は caller が `session.add(audit_event)` 後に
    commit する責務. ORM hook (CreatedAtMixin.created_at) は DB default で
    server side timestamp が割り当てられる.

    invariant:
    - event_type は AUDIT_EVENT_TYPE_P0_ACCEPTANCE_REPORT_GENERATED 固定
    - event_payload は payload.to_dict() (raw secret 排除済)
    - principal_id=null (BL-0149 sign-off は principal-bound でない system emit)
    """
    audit_event = AuditEvent(
        id=context.explicit_id if context.explicit_id is not None else uuid4(),
        tenant_id=context.tenant_id,
        event_type=AUDIT_EVENT_TYPE_P0_ACCEPTANCE_REPORT_GENERATED,
        event_payload=payload.to_dict(),
        actor_id=context.actor_id,
        principal_id=_EXPECTED_PRINCIPAL_ID,
        correlation_id=context.correlation_id,
        trace_id=context.trace_id,
    )
    return audit_event


__all__ = [
    "P0AcceptanceAuditWriteContext",
    "build_p0_acceptance_audit_event",
]
