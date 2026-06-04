"""MCP create idempotency service (ADR-00049 SP-034)。

reservation-first algorithm:
1. ``INSERT ... ON CONFLICT DO NOTHING RETURNING id`` で reservation を予約。
2. RETURNING に row → **winner**。caller が resource を作成し ``complete_reservation`` で completed 化。
3. RETURNING 空 → **loser** (既に予約済)。``SELECT ... FOR UPDATE`` で winner の commit を待ち、
   - fingerprint 不一致 → ``IdempotencyConflictError`` (同一 key 異 payload)。
   - completed → 既存 resource を返す (新規作成しない)。
   - 未 completed (winner rollback 等の理論上稀な状態) → ``IdempotencyReservationPendingError`` (recoverable)。

``ON CONFLICT DO NOTHING`` は競合 transaction の commit/rollback まで block するため、winner が rollback
すれば loser の INSERT が成功し loser が winner に昇格する (孤立 reservation も resource も残らない)。
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.mcp_idempotency_key import (
    MCP_IDEMPOTENCY_RESOURCE_KINDS,
    MCP_IDEMPOTENCY_TOOL_NAMES,
    McpIdempotencyKey,
    McpIdempotencyResourceKind,
    McpIdempotencyToolName,
)


class IdempotencyConflictError(Exception):
    """同一 (tenant, actor, tool, key) で **異なる payload** が再送された (client error、HTTP 409 相当)。"""


class IdempotencyReservationPendingError(Exception):
    """reservation row が未 completed のまま観測された (winner in-flight / rollback、recoverable)。"""


@dataclass(frozen=True)
class ReservationWinner:
    """この caller が winner。resource を作成し ``complete_reservation`` を呼ぶ。"""

    reservation_id: UUID


@dataclass(frozen=True)
class ReservationExisting:
    """既に completed な reservation が存在。新規作成せず既存 resource を返す。"""

    resource_kind: McpIdempotencyResourceKind
    resource_id: UUID


ReservationOutcome = ReservationWinner | ReservationExisting


def compute_request_fingerprint(fields: Mapping[str, object | None]) -> str:
    """fixed-schema MCP create request の **本質 field** (server-resolved 値) から決定的 fingerprint。

    同一 idempotency_key + 異なる payload を検出するために使う。actor 申告でない値のみ渡すこと。
    raw secret を含めない。fields は str / UUID / None など str 化可能な scalar のみ。
    """
    canonical = json.dumps(
        {key: (None if value is None else str(value)) for key, value in sorted(fields.items())},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    normalized = unicodedata.normalize("NFC", canonical)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def reserve_or_lookup(
    session: AsyncSession,
    *,
    tenant_id: int,
    actor_id: UUID,
    tool_name: McpIdempotencyToolName,
    idempotency_key: str,
    request_fingerprint: str,
) -> ReservationOutcome:
    """reservation-first で winner / existing を判定する (同一 transaction 内で呼ぶ)。"""
    if tool_name not in MCP_IDEMPOTENCY_TOOL_NAMES:
        raise ValueError(f"unsupported idempotency tool_name: {tool_name!r}")

    insert_stmt = (
        pg_insert(McpIdempotencyKey)
        .values(
            tenant_id=tenant_id,
            actor_id=actor_id,
            tool_name=tool_name,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        .on_conflict_do_nothing(
            index_elements=["tenant_id", "actor_id", "tool_name", "idempotency_key"]
        )
        .returning(McpIdempotencyKey.id)
    )
    won_id = (await session.execute(insert_stmt)).scalar_one_or_none()
    if won_id is not None:
        # winner: reservation 予約成功 (created_resource_* は NULL)。caller が resource 作成 + complete。
        return ReservationWinner(reservation_id=won_id)

    # loser: 既に予約済。ON CONFLICT DO NOTHING は competitor の commit/rollback まで block するため、
    # ここに来た時点で winner は commit 済 (= completed)。FOR UPDATE で row を lock + 再検証する。
    existing = (
        await session.execute(
            select(McpIdempotencyKey)
            .where(
                McpIdempotencyKey.tenant_id == tenant_id,
                McpIdempotencyKey.actor_id == actor_id,
                McpIdempotencyKey.tool_name == tool_name,
                McpIdempotencyKey.idempotency_key == idempotency_key,
            )
            .with_for_update()
        )
    ).scalar_one()

    if existing.request_fingerprint != request_fingerprint:
        raise IdempotencyConflictError(
            f"idempotency key reused with a different payload for tool {tool_name!r}"
        )
    if existing.completed_at is None or existing.created_resource_id is None:
        # winner が in-flight / rollback の極めて稀な観測 (ON CONFLICT block 設計上は起きない)。
        # 500 ではなく recoverable error として扱い、caller は retry できる。
        raise IdempotencyReservationPendingError(
            f"idempotency reservation for tool {tool_name!r} is not yet completed"
        )
    kind = existing.created_resource_kind
    if kind not in MCP_IDEMPOTENCY_RESOURCE_KINDS:
        raise IdempotencyReservationPendingError(
            f"idempotency reservation has invalid resource kind: {kind!r}"
        )
    # DB CHECK (mcp_idempotency_keys_resource_kind_check) + 上記 in 判定で値域は保証済。
    # mypy は ``in`` で Literal へ narrow しないため cast する。
    return ReservationExisting(
        resource_kind=cast(McpIdempotencyResourceKind, kind),
        resource_id=existing.created_resource_id,
    )


async def complete_reservation(
    session: AsyncSession,
    *,
    reservation_id: UUID,
    resource_kind: McpIdempotencyResourceKind,
    resource_id: UUID,
) -> None:
    """winner が resource 作成後に reservation を completed 化する (同一 transaction 内、3 列同時 set)。

    CHECK constraint ``mcp_idempotency_keys_reservation_complete_check`` が
    created_resource_kind / created_resource_id / completed_at の 3 列同時 NOT NULL を要求するため、
    3 列を必ず一括で set する (どれか欠けると CHECK violation)。
    """
    if resource_kind not in MCP_IDEMPOTENCY_RESOURCE_KINDS:
        raise ValueError(f"unsupported idempotency resource_kind: {resource_kind!r}")
    row = await session.get(McpIdempotencyKey, reservation_id, with_for_update=True)
    if row is None:
        raise ValueError(f"idempotency reservation {reservation_id} not found")
    row.created_resource_kind = resource_kind
    row.created_resource_id = resource_id
    row.completed_at = datetime.now(UTC)
    await session.flush()
