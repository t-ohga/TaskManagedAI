"""ADR-00039: me ticket_summary endpoint のテスト (D-5, read-only).

- route 登録
- response schema が ticket_total / status_counts のみ (raw secret なし)

注: tenant / project 境界 + active-scope (`Ticket.deleted_at IS NULL`) + 表示 bucket 整合の
DB 統合 negative は ADR-00039 テスト指針に従い CI (Compose postgres) で検証する。本 file は
cost_summary (ADR-00033) と同じ no-DB の contract test。
"""

from __future__ import annotations

from backend.app.api import me as me_api
from backend.app.config import Settings
from backend.app.main import create_app


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
