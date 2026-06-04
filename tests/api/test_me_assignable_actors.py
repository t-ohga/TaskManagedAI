"""A-6 (ADR-00046): me assignable-actors endpoint のテスト (read-only).

- route 登録 (`/api/v1/me/assignable-actors`) + capability gate (`task_list`)
- response schema が `{id, display_name}` / `{actors, truncated}` のみ (actor_id / secret なし、R1 F-002)
- **SQL introspection**: capturing session で endpoint を呼び、compile した SQL に tenant 境界 +
  `actor_type = 'human'` filter + 安定 order (display_name nulls last, id) + cap (LIMIT 201) が含まれる
  ことを assert する (human-only / tenant / cap の削除を no-DB で catch)。
- truncated / cap ロジック (R1 F-009): execute().all() が cap+1 件返すと truncated=True + 先頭 cap 件。
- full な seed-based DB negative は CI Compose postgres で実行 (host dev は test-password 不一致で実行不可、
  reminders / ticket_summary test と同方針)。
"""

from __future__ import annotations

import asyncio
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api import me as me_api
from backend.app.config import Settings
from backend.app.main import create_app


class _Row:
    """select(Actor.id, Actor.display_name) の 1 行 (named attribute access)."""

    def __init__(self, id: UUID, display_name: str | None) -> None:
        self.id = id
        self.display_name = display_name


class _CapturingResult:
    def __init__(self, rows: list[_Row]) -> None:
        self._rows = rows

    def all(self) -> list[_Row]:
        return self._rows


class _CapturingSession:
    """assignable_actors_endpoint が build した SQL を捕捉し、固定 rows を返す fake (no-DB)."""

    def __init__(self, rows: list[_Row] | None = None) -> None:
        self.execute_statements: list[object] = []
        self._rows = rows or []

    async def execute(
        self, statement: object, *args: object, **kwargs: object
    ) -> _CapturingResult:
        self.execute_statements.append(statement)
        return _CapturingResult(self._rows)


def _compiled_sql(statement: object) -> str:
    compiled = statement.compile(compile_kwargs={"literal_binds": True})  # type: ignore[attr-defined]
    return " ".join(str(compiled).split())


def _settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        dev_login_cookie_secret="test-cookie-secret-for-assignable-actors",
    )


def _route_capability_actions(app: object, path: str) -> list[str]:
    """route の dependency に wired された `maybe_require_cli_capability(<action>)` の action を抽出する。"""
    actions: list[str] = []
    for route in app.routes:  # type: ignore[attr-defined]
        if getattr(route, "path", None) != path:
            continue
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        for dep in dependant.dependencies:
            fn = dep.call
            closure = getattr(fn, "__closure__", None)
            if not closure:
                continue
            freevars = fn.__code__.co_freevars
            for name, cell in zip(freevars, closure, strict=False):
                if name == "required_action":
                    actions.append(cell.cell_contents)
    return actions


def test_assignable_actors_route_is_registered() -> None:
    app = create_app(_settings())
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/v1/me/assignable-actors" in paths


def test_assignable_actors_requires_task_list_capability() -> None:
    # tenant 内 human directory を返す ticket 管理 read surface のため、ticket list と同じ
    # `task_list` capability gate を必須にする (least-privilege)。
    app = create_app(_settings())
    actions = _route_capability_actions(app, "/api/v1/me/assignable-actors")
    assert "task_list" in actions


def test_assignable_actor_response_schema_is_minimal_no_secret() -> None:
    # R1 F-002: id + display_name のみ。actor_id / 内部属性 / secret を露出しない。
    actor_fields = set(me_api.AssignableActor.model_fields.keys())
    assert actor_fields == {"id", "display_name"}
    resp_fields = set(me_api.AssignableActorsResponse.model_fields.keys())
    assert resp_fields == {"actors", "truncated"}
    all_fields = actor_fields | resp_fields
    # actor_id (stable identity) を露出しないこと。
    assert "actor_id" not in all_fields
    for forbidden in ("secret", "token", "api_key", "provider_key", "capability", "auth"):
        assert not any(forbidden in f for f in all_fields)


def test_assignable_actors_query_filters_human_tenant_with_stable_order_and_cap() -> None:
    session = _CapturingSession(rows=[])
    asyncio.run(
        me_api.assignable_actors_endpoint(
            actor_id=uuid4(),
            tenant_id=1,
            session=cast(AsyncSession, session),
        )
    )
    assert len(session.execute_statements) == 1
    sql = _compiled_sql(session.execute_statements[0])
    # tenant 境界 + human-only filter (D-2 write 検証と対の read boundary)。
    assert "actors.tenant_id = 1" in sql
    assert "actors.actor_type = 'human'" in sql
    # 露出最小: id + display_name のみ SELECT (actor_id を引かない)。
    assert "actors.id" in sql
    assert "actors.display_name" in sql
    assert "actors.actor_id" not in sql
    assert "actors.auth_context_hash" not in sql
    # 安定 order (display_name nulls last, id) + cap (LIMIT 201 = limit+1 で truncated 検出)。
    assert "ORDER BY actors.display_name" in sql
    assert "NULLS LAST" in sql.upper()
    assert "actors.id" in sql.split("ORDER BY", 1)[1]
    assert "LIMIT 201" in sql


def test_assignable_actors_truncated_when_over_cap() -> None:
    # cap (200) + 1 件返ると truncated=True + 先頭 200 件に切る (R1 F-009 silent cap の可視化)。
    rows = [_Row(uuid4(), f"user-{i:03d}") for i in range(me_api.ASSIGNABLE_ACTOR_LIST_LIMIT + 1)]
    session = _CapturingSession(rows=rows)
    result = asyncio.run(
        me_api.assignable_actors_endpoint(
            actor_id=uuid4(),
            tenant_id=1,
            session=cast(AsyncSession, session),
        )
    )
    assert result.truncated is True
    assert len(result.actors) == me_api.ASSIGNABLE_ACTOR_LIST_LIMIT


def test_assignable_actors_not_truncated_within_cap() -> None:
    rows = [_Row(uuid4(), "owner"), _Row(uuid4(), None)]
    session = _CapturingSession(rows=rows)
    result = asyncio.run(
        me_api.assignable_actors_endpoint(
            actor_id=uuid4(),
            tenant_id=1,
            session=cast(AsyncSession, session),
        )
    )
    assert result.truncated is False
    assert len(result.actors) == 2
    assert result.actors[0].display_name == "owner"
    # display_name null も返せる (label は frontend が fallback)。
    assert result.actors[1].display_name is None


def test_assignable_actors_empty_is_not_truncated() -> None:
    session = _CapturingSession(rows=[])
    result = asyncio.run(
        me_api.assignable_actors_endpoint(
            actor_id=uuid4(),
            tenant_id=1,
            session=cast(AsyncSession, session),
        )
    )
    assert result.actors == []
    assert result.truncated is False
