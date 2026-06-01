"""ADR-00039: AgentRun role_facet endpoint のテスト (C-4, read-only).

- route 登録 + `/{run_id}` より **前** に定義される route ordering
  (UUID detail に食われて 422 にならないこと)
- response schema が role_id / count / status のみ (raw secret なし)
- status query は `AgentRunStatus` Literal で検証され、不正値は FastAPI が 422

注: tenant 境界 + active-scope (`soft_deleted_ticket_run_exclusion`) + status predicate の
DB 統合 negative は ADR-00039 テスト指針に従い CI (Compose postgres) で検証する。本 file は
cost_summary (ADR-00033) と同じ no-DB の contract test。
"""

from __future__ import annotations

from backend.app.api import agent_runs as agent_runs_api
from backend.app.config import Settings
from backend.app.main import create_app


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
