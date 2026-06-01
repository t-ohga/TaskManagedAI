"""Ticket コメント作成の共通 helper (ADR-00041 N-1).

REST `POST .../comments` と MCP `bridge_ticket_comment` の両方が呼ぶ。コメントは
専用 table ではなく `notification_events` の `event_type="ticket_comment"` event として保存する
(migration なし)。

不変条件 (ADR-00041 plan-review):
- 永続化前に payload 全体を `assert_no_raw_secret` に通し、raw secret / canary hit 時は
  ``ValueError`` を raise (REST=422、MCP=error)。両経路で適用し MCP の secret bypass を塞ぐ (R2-1)。
- author を payload `actor_id` に server-owned 保存する (R1-3 / R2-2)。caller payload では上書き不可。
- `recipient_actor_id` は FK 制約のため author を設定するが、ticket_comment は全 notification read
  surface から除外されるため inbox / triage を汚染しない (R1-3 / R2-3、repository 側で除外)。
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.notification_event import NotificationEvent
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.repositories.notification_event import (
    TICKET_COMMENT_EVENT_TYPE,
    NotificationEventRepository,
)

# 一覧 response の message 長さ上限 (空 / 超過は API schema 側で 422)。
TICKET_COMMENT_MESSAGE_MAX_LENGTH = 4000

# provider preflight (`services/providers/preflight.py` の `_CANARY_PATTERNS`) と同一の
# secret canary marker。`assert_no_raw_secret` は実 secret pattern (sk-/ghp_/PEM 等) のみ検出し
# canary fixture marker を含まないため、comment 経路では canary も明示的に reject する
# (ADR-00041 secret 境界 = canary も永続化前 reject、Codex adversarial R1 F-HIGH)。
_CANARY_PATTERN = re.compile(r"CANARY-FIXTURE-[A-Z0-9]{16,}")


def assert_comment_message_safe(message: str) -> None:
    """comment message に raw secret / canary marker が無いか検証する。

    raw secret (sk-/ghp_/PEM 等) は ``assert_no_raw_secret``、secret canary
    (`CANARY-FIXTURE-...`) は provider preflight と同一 regex で検出する。どちらか hit で
    ``ValueError`` を raise (REST=422、MCP=error)。両 write 経路 (REST POST / MCP) は本 helper の
    ``create_ticket_comment_event`` を通るため、ここが secret/canary 永続化の単一防御点。

    Raises:
        ValueError: raw secret / canary marker / prohibited key を検出した場合。
    """
    assert_no_raw_secret({"message": message})
    if _CANARY_PATTERN.search(message) is not None:
        raise ValueError("comment message contains a secret canary marker")


def redact_comment_message(message: str) -> str:
    """legacy row に secret / canary が残っていても raw 表示しない defensive redaction (R2-1)。

    write 経路は ``assert_comment_message_safe`` で reject 済だが、過去に保存された row や
    将来 scanner が拡張された場合に備え、read (一覧 / activity) でも同一判定で raw 表示を止める。
    """
    try:
        assert_comment_message_safe(message)
    except ValueError:
        return "[redacted: 機密情報が検出されたため非表示]"
    return message


async def create_ticket_comment_event(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    ticket_id: UUID,
    message: str,
    actor_id: UUID,
) -> NotificationEvent:
    """ticket コメントを notification_events event として保存する。

    呼び出し側は事前に actionable guard (POST=assert_ticket_actionable) を済ませること。
    本 helper は **永続化前 secret scan** と **author server-owned 保存** を担保する。

    Raises:
        ValueError: payload (message 含む) に raw secret / canary / prohibited key を検出した場合。
    """
    payload: dict[str, Any] = {
        "project_id": str(project_id),
        "ticket_id": str(ticket_id),
        "message": message,
        "actor_id": str(actor_id),
    }
    # raw secret / provider token / private key marker を DB / UI に流さない (fail-closed、R2-1)。
    # payload 全体を raw secret scan し、message は canary marker も含めて検証する (R1 F-HIGH)。
    assert_no_raw_secret(payload)
    assert_comment_message_safe(message)

    repo = NotificationEventRepository(session)
    return await repo.append(
        tenant_id=tenant_id,
        event_type=TICKET_COMMENT_EVENT_TYPE,
        payload=payload,
        recipient_actor_id=actor_id,
    )
