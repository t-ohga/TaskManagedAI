"""ADR-00039: me ticket_summary endpoint のテスト (D-5, read-only).

- route 登録
- response schema が ticket_total / status_counts のみ (raw secret なし)
- **SQL introspection** (Codex R1): capturing session で endpoint を呼び、compile した SQL に
  tenant 境界 / active-scope (`Ticket.deleted_at IS NULL`) / `GROUP BY tickets.status` が含まれる
  ことを assert する。active-scope predicate 削除を no-DB で catch する (full な seed-based DB
  negative は CI Compose postgres で実行、host dev からは conftest の test-password 不一致で実行不可)。
"""

from __future__ import annotations

import asyncio
from typing import cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api import me as me_api
from backend.app.config import Settings
from backend.app.main import create_app


class _CapturingResult:
    def all(self) -> list[object]:
        return []


class _CapturingSession:
    """endpoint が build した SQL statement を捕捉する fake session (no-DB)."""

    def __init__(self) -> None:
        self.statements: list[object] = []

    async def execute(self, statement: object, *args: object, **kwargs: object) -> _CapturingResult:
        self.statements.append(statement)
        return _CapturingResult()


def _compiled_sql(statement: object) -> str:
    compiled = statement.compile(compile_kwargs={"literal_binds": False})  # type: ignore[attr-defined]
    return " ".join(str(compiled).split())


def _settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        dev_login_cookie_secret="test-cookie-secret-for-ticket-summary-api",
    )


def test_ticket_summary_route_is_registered() -> None:
    app = create_app(_settings())
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/v1/me/ticket_summary" in paths


def test_ticket_summary_response_schema_has_no_secret_fields() -> None:
    count_fields = set(me_api.TicketStatusCount.model_fields.keys())
    assert count_fields == {"status", "count"}
    resp_fields = set(me_api.TicketSummaryResponse.model_fields.keys())
    assert resp_fields == {"ticket_total", "status_counts"}
    for forbidden in ("secret", "token_hash", "api_key", "provider_key", "capability"):
        assert not any(forbidden in f for f in count_fields | resp_fields)


def test_ticket_summary_query_applies_tenant_and_active_scope() -> None:
    # tenant 境界 + active-scope (deleted_at IS NULL) + GROUP BY status が SQL に含まれること
    # (ADR-00039 R1 / Codex R1)。active-scope を消すと soft-deleted が母数に復活するため必須。
    session = _CapturingSession()
    asyncio.run(
        me_api.ticket_summary_endpoint(
            actor_id=uuid4(),
            tenant_id=1,
            session=cast(AsyncSession, session),
        )
    )
    assert len(session.statements) == 1
    sql = _compiled_sql(session.statements[0])
    assert "tickets.tenant_id =" in sql
    assert "tickets.deleted_at IS NULL" in sql
    assert "GROUP BY tickets.status" in sql
