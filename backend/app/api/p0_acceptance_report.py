"""Sprint 12 batch 6 (BL-0149): P0 acceptance report API endpoint.

`POST /api/v1/eval/p0-acceptance-report` — caller (BL-0149 sign-off) が
7 source + required_gated_row_ids を JSON body で渡し、runner output
(report + artifact) を JSON で受け取る.

設計:
- read-only ではなく POST (caller-supplied input が必要)
- actor + tenant context dependency 必須 (admin scope)
- response は frozen Pydantic model
- runner は run_in_threadpool で event loop block 回避
"""

from __future__ import annotations

import logging
from typing import Any, Final

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from backend.app.api.approval_inbox import get_current_actor_id, get_tenant_id
from backend.app.services.eval.p0_acceptance_audit_emit import (
    P0AcceptanceAuditPayload,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/eval", tags=["eval"])


class P0AcceptanceReportResponse(BaseModel):
    """P0 acceptance report API response (frozen).

    artifact_json は P0AcceptanceArtifact 全文の dict (caller persist 用).
    audit_payload_json は audit_events.event_payload 用 dict.
    """

    model_config = ConfigDict(frozen=True)

    p0_exit_decision: bool
    deficiency_count: int
    deficiency_codes: tuple[str, ...]
    final_chain_sha256: str
    timestamp: str
    audit_payload: P0AcceptanceAuditPayload = Field(
        description=(
            "audit_events.event_payload 用 server-owned payload "
            "(caller が persist 担当)."
        )
    )


_ACTOR_DEP: Final = Depends(get_current_actor_id)
_TENANT_DEP: Final = Depends(get_tenant_id)


@router.post("/p0-acceptance-report", response_model=P0AcceptanceReportResponse)
async def post_p0_acceptance_report(
    request_body: dict[str, Any],
    _actor_id: object = _ACTOR_DEP,
    _tenant_id: int = _TENANT_DEP,
) -> P0AcceptanceReportResponse:
    """7 source を受け取り、P0 acceptance report + audit payload を返す.

    本 endpoint は **CLI / sign-off workflow からの caller-supplied 7 source**
    を verify するため POST、kpi_rollup と異なり read-only ではない.
    Actual DB persist (audit_events insert) は caller の責務 (BL-0149 step).

    Args:
        request_body: 7 source の JSON dict (mock-friendly な caller input)

    Returns:
        P0AcceptanceReportResponse with verdict + final_chain_sha256 + audit_payload.

    Raises:
        400: input validation error (drill_kind mismatch, etc.)
        500: runner internal error
    """

    # 本 endpoint は input parsing の skeleton。実 deserialization は
    # 別 batch (本 batch では runner 経路 verify が主目的、test 経由 mock OK).
    # caller (CLI / BL-0149 step) が typed Pydantic schema を渡す経路は
    # batch 6.1 で完成 (本 batch では minimum echo 路).
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "error_code": "p0_acceptance_report_endpoint_skeleton",
            "error_summary": (
                "Endpoint skeleton in batch 6; CLI/typed input schema is "
                "implemented in batch 6.1+. Use scripts/p0_acceptance_report_run.py "
                "for local verification."
            ),
        },
    )


__all__ = [
    "P0AcceptanceReportResponse",
    "router",
]
