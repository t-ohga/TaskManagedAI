"""ADR-00039: AgentRun role_facet endpoint のテスト (C-4, read-only).

- route 登録 + `/{run_id}` より **前** に定義される route ordering
  (UUID detail に食われて 422 にならないこと)
- response schema が role_id / count / status のみ (raw secret なし)
- status query は `AgentRunStatus` Literal で検証され、不正値は FastAPI が 422
- **SQL introspection** (Codex R1): capturing session で endpoint を呼び、compile した SQL に
  tenant 境界 / role_id null 除外 / active-scope (soft-deleted ticket 除外) / status predicate が
  含まれることを assert する。predicate 削除を no-DB で catch する (full な seed-based DB negative は
  CI Compose postgres で実行、host dev からは conftest の test-password 不一致で実行不可)。
"""

from __future__ import annotations

import asyncio
from typing import cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api import agent_runs as agent_runs_api
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
        dev_login_cookie_secret="test-cookie-secret-for-role-facet-api",
    )


def test_role_facet_route_is_registered() -> None:
    app = create_app(_settings())
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/v1/agent_runs/role_facet" in paths


def test_role_facet_route_registered_before_run_id_detail() -> None:
    # FastAPI は定義順照合。role_facet が /{run_id} より後だと UUID detail に食われ 422 になる
    # (ADR-00039 R2、route ordering)。
    app = create_app(_settings())
    paths = [getattr(route, "path", None) for route in app.routes]
    assert paths.index("/api/v1/agent_runs/role_facet") < paths.index(
        "/api/v1/agent_runs/{run_id}"
    )


def test_role_facet_response_schema_has_no_secret_fields() -> None:
    entry_fields = set(agent_runs_api.RoleFacetEntry.model_fields.keys())
    assert entry_fields == {"role_id", "count"}
    resp_fields = set(agent_runs_api.RoleFacetResponse.model_fields.keys())
    assert resp_fields == {"roles", "status"}
    for forbidden in ("secret", "token_hash", "api_key", "provider_key", "capability"):
        assert not any(forbidden in f for f in entry_fields | resp_fields)


def test_role_facet_query_applies_tenant_active_scope_and_null_exclusion() -> None:
    # status 省略時: tenant 境界 + role_id null 除外 + active-scope (soft-deleted ticket bound 除外)
    # が SQL に含まれ、status predicate は含まれないこと (ADR-00039 R1 / Codex R1)。
    session = _CapturingSession()
    asyncio.run(
        agent_runs_api.role_facet_endpoint(
            status_value=None,
            actor_id=uuid4(),
            tenant_id=1,
            session=cast(AsyncSession, session),
        )
    )
    assert len(session.statements) == 1
    sql = _compiled_sql(session.statements[0])
    assert "agent_runs.tenant_id =" in sql
    assert "agent_runs.role_id IS NOT NULL" in sql
    # soft_deleted_ticket_run_exclusion(): NOT EXISTS (... tickets.deleted_at IS NOT NULL)
    assert "tickets.deleted_at IS NOT NULL" in sql
    assert "GROUP BY agent_runs.role_id" in sql
    # status 省略時は status predicate を含めない (tenant-wide facet)。
    assert "agent_runs.status =" not in sql


def test_role_facet_query_applies_status_predicate_when_filtered() -> None:
    # status 指定時: list endpoint と同じ status predicate を含めること (status-scoped facet)。
    session = _CapturingSession()
    asyncio.run(
        agent_runs_api.role_facet_endpoint(
            status_value="running",
            actor_id=uuid4(),
            tenant_id=1,
            session=cast(AsyncSession, session),
        )
    )
    sql = _compiled_sql(session.statements[0])
    assert "agent_runs.status =" in sql
    # active-scope は status 指定時も維持。
    assert "tickets.deleted_at IS NOT NULL" in sql
