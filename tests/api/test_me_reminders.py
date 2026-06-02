"""A-7 (ADR-00045): me reminders / date_context endpoint のテスト (read-only, on-read).

- route 登録 (`/api/v1/me/reminders` / `/api/v1/me/date_context`)
- response schema が ADR-00045 の field のみ (raw secret なし)
- **SQL introspection**: capturing session で reminders_endpoint を呼び、compile した SQL に
  tenant 境界 / active-scope (`tickets.deleted_at IS NULL`) / active-project (`projects.status =
  'active'`) / actionable status / `due_date IS NOT NULL` / bucket 別 predicate / bucket 別 LIMIT が
  含まれることを assert する (active-scope / archived 除外 / bucket 別 cap の削除を no-DB で catch)。
  full な seed-based DB negative は CI Compose postgres で実行 (host dev は conftest test-password
  不一致で実行不可、ticket_summary test と同方針)。
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api import me as me_api
from backend.app.config import Settings
from backend.app.domain.reminders import REMINDER_UPCOMING_WINDOW_DAYS
from backend.app.main import create_app


class _CapturingResult:
    def scalars(self) -> _CapturingResult:
        return self

    def all(self) -> list[object]:
        return []


class _CapturingSession:
    """reminders_endpoint が build した SQL (scalar=count / execute=list) を捕捉する fake (no-DB)."""

    def __init__(self) -> None:
        self.scalar_statements: list[object] = []
        self.execute_statements: list[object] = []

    async def scalar(self, statement: object, *args: object, **kwargs: object) -> int:
        self.scalar_statements.append(statement)
        return 0

    async def execute(self, statement: object, *args: object, **kwargs: object) -> _CapturingResult:
        self.execute_statements.append(statement)
        return _CapturingResult()


def _compiled_sql(statement: object) -> str:
    compiled = statement.compile(compile_kwargs={"literal_binds": True})  # type: ignore[attr-defined]
    return " ".join(str(compiled).split())


def _settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        dev_login_cookie_secret="test-cookie-secret-for-reminders-api",
    )


def test_reminders_routes_are_registered() -> None:
    app = create_app(_settings())
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/v1/me/reminders" in paths
    assert "/api/v1/me/date_context" in paths


def test_reminder_response_schemas_have_no_secret_fields() -> None:
    item_fields = set(me_api.ReminderItem.model_fields.keys())
    assert item_fields == {
        "ticket_id",
        "project_id",
        "slug",
        "title",
        "status",
        "priority",
        "due_date",
        "days_until",
    }
    bucket_fields = set(me_api.ReminderBucket.model_fields.keys())
    assert bucket_fields == {"count", "truncated", "items"}
    summary_fields = set(me_api.ReminderSummaryResponse.model_fields.keys())
    assert summary_fields == {
        "reference_date",
        "threshold_days",
        "overdue",
        "due_today",
        "upcoming",
    }
    date_ctx_fields = set(me_api.DateContextResponse.model_fields.keys())
    assert date_ctx_fields == {"reference_date", "threshold_days"}
    all_fields = item_fields | bucket_fields | summary_fields | date_ctx_fields
    for forbidden in ("secret", "token", "api_key", "provider_key", "capability"):
        assert not any(forbidden in f for f in all_fields)


def test_date_context_endpoint_returns_jst_today_and_threshold() -> None:
    session = _CapturingSession()
    result = asyncio.run(
        me_api.date_context_endpoint(
            actor_id=uuid4(),
            tenant_id=1,
            session=cast(AsyncSession, session),
        )
    )
    assert isinstance(result.reference_date, date)
    assert result.threshold_days == REMINDER_UPCOMING_WINDOW_DAYS
    # date_context は純粋派生 (DB 非依存)。session を触らないこと。
    assert session.scalar_statements == []
    assert session.execute_statements == []


def test_reminders_query_applies_all_boundaries_and_per_bucket_cap() -> None:
    session = _CapturingSession()
    asyncio.run(
        me_api.reminders_endpoint(
            actor_id=uuid4(),
            tenant_id=1,
            session=cast(AsyncSession, session),
        )
    )

    # bucket (overdue / due_today / upcoming) ごとに count(scalar) + list(execute) を 1 本ずつ。
    assert len(session.scalar_statements) == 3
    assert len(session.execute_statements) == 3

    count_sql = [_compiled_sql(s) for s in session.scalar_statements]
    list_sql = [_compiled_sql(s) for s in session.execute_statements]
    all_sql = count_sql + list_sql
    combined = " || ".join(all_sql)

    # 全 query 共通の fail-closed 境界 (削除されると越境 / 削除済 / archived が混入する)。
    for sql in all_sql:
        assert "tickets.tenant_id = 1" in sql
        assert "tickets.deleted_at IS NULL" in sql  # active-scope
        assert "projects.status = 'active'" in sql  # active-project (archived 除外)
        assert "tickets.status IN ('open', 'in_progress', 'blocked', 'review')" in sql
        assert "tickets.due_date IS NOT NULL" in sql
        assert "tickets.due_date <= " in sql  # window 上限 (overdue または upcoming)
        # tenant 複合 JOIN (tickets -> projects)
        assert "tickets.tenant_id = projects.tenant_id" in sql
        assert "tickets.project_id = projects.id" in sql

    # bucket 別 predicate (compute_reminder_bucket と同一 semantics、date は literal で quote 付き)。
    assert "tickets.due_date < '" in combined  # overdue (strict less、'<=' とは別)
    assert "tickets.due_date = '" in combined  # due_today
    assert "tickets.due_date > '" in combined  # upcoming 下限

    # count は exact (cap 非依存)、list は bucket ごとに独立 LIMIT (F-001: overdue が他 bucket を枯渇させない)。
    assert all("count(*)" in sql for sql in count_sql)
    assert all("LIMIT 50" in sql for sql in list_sql)
    assert sum("LIMIT 50" in sql for sql in all_sql) == 3
