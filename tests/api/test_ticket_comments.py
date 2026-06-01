"""ADR-00041: ticket コメント + activity timeline の contract test (N-1 / N-2).

- route 登録 (comments GET/POST + activity GET)
- response schema が message / actor_id / created_at 等のみ (raw secret field なし)
- 共通 helper の secret scan (REST / MCP 両経路で永続化前に reject、R1-2 / R2-1)
- author fallback (payload.actor_id ?? recipient_actor_id、legacy row、R2-2)
- defensive redaction (legacy secret comment を raw 表示しない、R2-1)
- direct notification-id endpoint で ticket_comment を 404 拒否 (R3-1)

注: tenant / project 越境 + active-scope (archived 許可 / deleted 拒否) + inbox/triage 非汚染の
seed-based DB negative は ADR-00041 テスト指針に従い CI Compose postgres で検証する
(host dev は conftest の test-password 不一致で実行不可)。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api import notifications as notifications_api
from backend.app.api import tickets as tickets_api
from backend.app.config import Settings
from backend.app.db.models.notification_event import NotificationEvent
from backend.app.main import create_app
from backend.app.repositories.notification_event import NotificationEventRepository
from backend.app.services.notifications.ticket_comment import (
    assert_comment_message_safe,
    create_ticket_comment_event,
    redact_comment_message,
)

# provider preflight `_CANARY_PATTERNS` と同一 marker (16 char 以上の英数字)。
_CANARY_MESSAGE = "leak CANARY-FIXTURE-ABCDEFGH01234567 here"


def _settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        dev_login_cookie_secret="test-cookie-secret-for-ticket-comments-api",
    )


def test_comment_and_activity_routes_registered() -> None:
    app = create_app(_settings())
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/v1/projects/{project_id}/tickets/{ticket_id}/comments" in paths
    assert "/api/v1/projects/{project_id}/tickets/{ticket_id}/activity" in paths


def test_comment_schema_has_no_secret_fields() -> None:
    comment_fields = set(tickets_api.TicketComment.model_fields.keys())
    assert comment_fields == {"id", "message", "actor_id", "created_at"}
    activity_fields = set(tickets_api.TicketActivityEntry.model_fields.keys())
    assert activity_fields == {
        "id",
        "type",
        "message",
        "actor_id",
        "created_at",
        "previous_status",
        "new_status",
    }
    for forbidden in ("secret", "token_hash", "api_key", "provider_key", "capability"):
        assert not any(forbidden in f for f in comment_fields | activity_fields)


@pytest.mark.parametrize(
    "secret_message",
    [
        "see key sk-abcdefghijklmnopqrstuvwxyz123",
        "token ghp_abcdefghijklmnopqrstuvwxyz12345",
    ],
)
def test_create_ticket_comment_event_rejects_raw_secret(secret_message: str) -> None:
    # 永続化前に assert_no_raw_secret が ValueError を raise するため、session に到達しない (R1-2 / R2-1)。
    dummy_session = cast(AsyncSession, object())
    with pytest.raises(ValueError):
        asyncio.run(
            create_ticket_comment_event(
                dummy_session,
                tenant_id=1,
                project_id=uuid4(),
                ticket_id=uuid4(),
                message=secret_message,
                actor_id=uuid4(),
            )
        )


def test_comment_author_prefers_payload_then_recipient_fallback() -> None:
    recipient = uuid4()
    author = uuid4()
    # payload.actor_id があればそれを使う。
    assert tickets_api._comment_author({"actor_id": str(author)}, recipient) == author
    # legacy row (payload.actor_id 無) は recipient_actor_id fallback (R2-2)。
    assert tickets_api._comment_author({}, recipient) == recipient


def test_redacted_message_hides_legacy_secret() -> None:
    assert tickets_api._redacted_message("普通のコメント") == "普通のコメント"
    redacted = tickets_api._redacted_message("leak sk-abcdefghijklmnopqrstuvwxyz123")
    assert "sk-" not in redacted
    assert "redacted" in redacted.lower() or "非表示" in redacted


def _ticket_comment_event() -> NotificationEvent:
    # _assert_not_ticket_comment は .event_type のみ参照するため軽量 stand-in で十分。
    return cast(NotificationEvent, SimpleNamespace(event_type="ticket_comment"))


def _other_event() -> NotificationEvent:
    return cast(NotificationEvent, SimpleNamespace(event_type="approval_pending"))


def test_assert_not_ticket_comment_rejects_comment_only() -> None:
    # ticket_comment は notification ではないため direct-id endpoint から 404 拒否 (R3-1)。
    with pytest.raises(HTTPException) as excinfo:
        notifications_api._assert_not_ticket_comment(_ticket_comment_event())
    assert excinfo.value.status_code == 404
    # 他 event_type は通す。
    notifications_api._assert_not_ticket_comment(_other_event())


# ── Codex adversarial R1 F-HIGH: canary marker は raw secret scanner に含まれないため、
#    comment 経路 (write / read 両方) で別途検出する。assert_no_raw_secret だけでは抜ける。

def test_assert_comment_message_safe_rejects_canary_marker() -> None:
    with pytest.raises(ValueError):
        assert_comment_message_safe(_CANARY_MESSAGE)


def test_assert_comment_message_safe_rejects_raw_secret() -> None:
    with pytest.raises(ValueError):
        assert_comment_message_safe("token ghp_abcdefghijklmnopqrstuvwxyz12345")


def test_assert_comment_message_safe_allows_clean_message() -> None:
    # clean な日本語コメントは raise しない。
    assert_comment_message_safe("レビューありがとうございます。修正しました。")


def test_create_ticket_comment_event_rejects_canary_marker() -> None:
    # write 経路 (REST/MCP 共通 helper) は canary を永続化前に reject する (session に到達しない)。
    dummy_session = cast(AsyncSession, object())
    with pytest.raises(ValueError):
        asyncio.run(
            create_ticket_comment_event(
                dummy_session,
                tenant_id=1,
                project_id=uuid4(),
                ticket_id=uuid4(),
                message=_CANARY_MESSAGE,
                actor_id=uuid4(),
            )
        )


def test_redact_comment_message_hides_canary_marker() -> None:
    # read 経路 (一覧 / activity) の legacy row defensive redaction も canary を raw 表示しない。
    redacted = redact_comment_message(_CANARY_MESSAGE)
    assert "CANARY-FIXTURE" not in redacted
    assert "redacted" in redacted.lower() or "非表示" in redacted
    # tickets.py の薄い委譲 _redacted_message も同じく canary を redaction する。
    assert "CANARY-FIXTURE" not in tickets_api._redacted_message(_CANARY_MESSAGE)


# ── Codex adversarial R1 F-MEDIUM: MCP notification_resolve が repo.resolve()→mark_read() を
#    直接呼んで ticket_comment の direct-id 拒否を迂回する経路を、repository 層の単一防御点で塞ぐ。
#    mark_read の UPDATE WHERE に event_type 除外を入れ、REST/MCP 双方で ticket_comment を claim
#    させない (host dev は DB 不可のため、生成 SQL を introspect して guard を検証)。

class _CaptureSession:
    """_ensure_tenant_context を満たしつつ execute された statement を捕捉する fake session。"""

    def __init__(self, tenant_id: int) -> None:
        self._tenant_id = tenant_id
        self.executed: list[Any] = []

    async def scalar(self, *_args: Any, **_kwargs: Any) -> str:
        # get_tenant_context / assert_tenant_context が現在 tenant を読む。
        return str(self._tenant_id)

    async def execute(self, statement: Any) -> _FakeResult:
        self.executed.append(statement)
        return _FakeResult()


class _FakeResult:
    def scalar_one_or_none(self) -> None:
        return None


def _compiled_sql(statement: Any) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


def test_mark_read_update_excludes_ticket_comment() -> None:
    session = _CaptureSession(tenant_id=1)
    repo = NotificationEventRepository(cast(AsyncSession, session))
    result = asyncio.run(repo.mark_read(tenant_id=1, event_id=uuid4()))
    assert result is None
    # 最後の execute が UPDATE (mark_read 本体)。tenant + id に加え event_type 除外があること。
    update_stmt = session.executed[-1]
    sql = _compiled_sql(update_stmt).lower()
    assert "update notification_events" in sql
    assert "event_type" in sql
    assert "ticket_comment" in sql


def test_snooze_and_resolve_delegate_to_guarded_mark_read() -> None:
    # snooze / resolve は mark_read に委譲するため、同じ event_type guard を継承する。
    for invoke in (
        lambda r: r.snooze(tenant_id=1, event_id=uuid4()),
        lambda r: r.resolve(tenant_id=1, event_id=uuid4()),
    ):
        session = _CaptureSession(tenant_id=1)
        repo = NotificationEventRepository(cast(AsyncSession, session))
        result = asyncio.run(invoke(repo))
        assert result is None
        sql = _compiled_sql(session.executed[-1]).lower()
        assert "update notification_events" in sql
        assert "ticket_comment" in sql
