"""ADR-00033: AgentRun cost_summary endpoint のテスト.

- route 登録確認
- `_cost_summary_cutoff` の range 別 cutoff 算出 (server-owned、caller-supplied date 禁止)
- response schema が cost_usd / tokens のみ (raw secret なし)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.app.api import agent_runs as agent_runs_api
from backend.app.config import Settings
from backend.app.main import create_app


def _settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        dev_login_cookie_secret="test-cookie-secret-for-cost-summary-api",
    )


def test_cost_summary_route_is_registered() -> None:
    app = create_app(_settings())
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/v1/agent_runs/cost_summary" in paths


def test_cost_summary_cutoff_all_returns_none() -> None:
    assert agent_runs_api._cost_summary_cutoff("all") is None


def test_cost_summary_cutoff_today_is_midnight_utc() -> None:
    cutoff = agent_runs_api._cost_summary_cutoff("today")
    assert cutoff is not None
    assert cutoff.tzinfo == UTC
    assert cutoff.hour == 0
    assert cutoff.minute == 0
    assert cutoff.second == 0
    assert cutoff.microsecond == 0


def test_cost_summary_cutoff_week_is_seven_days_back() -> None:
    before = datetime.now(UTC) - timedelta(days=7)
    cutoff = agent_runs_api._cost_summary_cutoff("week")
    assert cutoff is not None
    # 算出時刻のわずかなずれを許容 (±5 秒)
    assert abs((cutoff - before).total_seconds()) < 5


def test_cost_summary_cutoff_month_and_quarter_ordering() -> None:
    month = agent_runs_api._cost_summary_cutoff("month")
    quarter = agent_runs_api._cost_summary_cutoff("quarter")
    assert month is not None and quarter is not None
    # quarter (90日) は month (30日) より過去
    assert quarter < month


def test_cost_summary_response_schema_has_no_secret_fields() -> None:
    fields = set(agent_runs_api.CostSummaryResponse.model_fields.keys())
    assert fields == {
        "total_cost_usd",
        "total_tokens_input",
        "total_tokens_output",
        "run_count",
        "by_status",
        "range",
    }
    # raw secret / provider key 系の field が存在しないこと
    for forbidden in ("secret", "token_hash", "api_key", "provider_key", "capability"):
        assert not any(forbidden in f for f in fields)
