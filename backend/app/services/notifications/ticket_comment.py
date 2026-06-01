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

# message 長さ contract (REST `CreateTicketCommentRequest` の min_length=1 / max_length と一致)。
# MCP は本 helper を直接呼ぶため、REST と同一の長さ境界を write 経路で共有する (Codex R2 F-MEDIUM)。
TICKET_COMMENT_MESSAGE_MAX_LENGTH = 4000

# comment 専用 secret pattern。`assert_no_raw_secret` (project 共通) は legacy
# `sk-[A-Za-z0-9]{20,}` / `ghp_` / `gho_` / `ghs_` のみで、modern OpenAI project key
# (`sk-proj-...` 等 hyphen/underscore 含む) / GitHub fine-grained PAT / `ghu_` / `ghr_` /
# AWS access key (`AKIA...`) を見逃す。comment は user 自由入力で leak risk が高いため、
# repo の eval scanner (`services/eval/anti_gaming.py` / `loader.py` の `_RAW_SECRET_VALUE_PATTERNS`)
# と **同一の** provider-token 集合 + provider preflight (`_CANARY_PATTERNS`) と同一の canary marker を
# 追加で検証する (Codex adversarial R1/R2/R3 F-HIGH)。eval scanner との drift は
# `tests/api/test_ticket_comments.py::test_comment_secret_patterns_cover_eval_scanner` が検出する。
_COMMENT_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("github_pat", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{16,}\b")),
    ("github_fine_grained_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("secret_canary", re.compile(r"CANARY-FIXTURE-[A-Z0-9]{16,}")),
)


def assert_comment_message_safe(message: str) -> None:
    """comment message に raw secret / canary marker が無いか検証する。

    project 共通の ``assert_no_raw_secret`` (sk-ant-/ghs_/gho_/ghp_/tskey-/age/PEM 等) に加え、
    comment 専用に modern OpenAI key (hyphen/underscore 含む) / GitHub fine-grained PAT /
    secret canary を検出する。いずれか hit で ``ValueError`` を raise (REST=422、MCP=error)。
    両 write 経路 (REST POST / MCP) は本 helper を通る ``create_ticket_comment_event`` 経由のため、
    ここが secret/canary 永続化の単一防御点。長さ contract は write 専用 (read redaction では
    適用しない) のため本 function には含めない。

    Raises:
        ValueError: raw secret / canary marker / prohibited key を検出した場合。
    """
    assert_no_raw_secret({"message": message})
    for hit_kind, regex in _COMMENT_SECRET_PATTERNS:
        if regex.search(message) is not None:
            raise ValueError(
                f"comment message contains a forbidden secret pattern ({hit_kind})"
            )


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
    本 helper は **長さ contract**、**永続化前 secret scan**、**author server-owned 保存** を担保する。

    Raises:
        ValueError: message が長さ contract (1..MAX) 外、または payload (message 含む) に
            raw secret / canary / prohibited key を検出した場合。
    """
    # REST は Pydantic min_length=1/max_length で reject するが、MCP は本 helper を直接呼ぶため、
    # write 経路の単一防御点で長さ境界を共有する (空 / 巨大 comment の DB bloat 防止、R2 F-MEDIUM)。
    if not 1 <= len(message) <= TICKET_COMMENT_MESSAGE_MAX_LENGTH:
        raise ValueError(
            "comment message length must be between 1 and "
            f"{TICKET_COMMENT_MESSAGE_MAX_LENGTH} characters"
        )

    payload: dict[str, Any] = {
        "project_id": str(project_id),
        "ticket_id": str(ticket_id),
        "message": message,
        "actor_id": str(actor_id),
    }
    # raw secret / provider token / private key marker を DB / UI に流さない (fail-closed、R2-1)。
    # payload 全体を raw secret scan し、message は modern provider key / canary も検証する (R1/R2 F-HIGH)。
    assert_no_raw_secret(payload)
    assert_comment_message_safe(message)

    repo = NotificationEventRepository(session)
    return await repo.append(
        tenant_id=tenant_id,
        event_type=TICKET_COMMENT_EVENT_TYPE,
        payload=payload,
        recipient_actor_id=actor_id,
    )
