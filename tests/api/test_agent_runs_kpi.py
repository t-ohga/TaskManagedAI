from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.api import agent_runs as agent_runs_api
from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.services.metrics.agent_run_kpi import AgentRunKpi

RUN_ID = UUID("00000000-0000-4000-8000-00000000f301")
ACTOR_ID = UUID("00000000-0000-4000-8000-00000000f302")
PROJECT_ID = UUID("00000000-0000-4000-8000-00000000f303")


def _settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        dev_login_cookie_secret="test-cookie-secret-for-agent-run-kpi-api",
    )


def test_agent_runs_kpi_route_is_registered() -> None:
    app = create_app(_settings())
    paths = {getattr(route, "path", None) for route in app.routes}

    assert "/api/v1/agent_runs/{run_id}/kpi" in paths


@pytest.mark.asyncio
async def test_agent_runs_kpi_endpoint_returns_safe_metric_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAgentRunKpiService:
        def __init__(self, session: object) -> None:
            self.session = session

        async def fetch(self, *, tenant_id: int, run_id: UUID) -> AgentRunKpi | None:
            assert tenant_id == 1
            assert run_id == RUN_ID
            return AgentRunKpi(
                tenant_id=tenant_id,
                run_id=run_id,
                project_id=PROJECT_ID,
                status="completed",
                completed_at=datetime(2026, 5, 24, 11, 0, tzinfo=UTC),
                repo_pr_opened_event_count=1,
                first_repo_pr_opened_at=datetime(2026, 5, 24, 9, 15, tzinfo=UTC),
                time_to_merge_proxy_sample_count=1,
                time_to_merge_proxy_ms=6_300_000.0,
                time_to_merge_proxy_source="repo_pr_opened_to_agent_run_completed",
            )

    app = create_app(_settings())

    async def override_session() -> AsyncIterator[object]:
        yield object()

    async def override_actor() -> UUID:
        return ACTOR_ID

    def override_tenant() -> int:
        return 1

    monkeypatch.setattr(agent_runs_api, "AgentRunKpiService", FakeAgentRunKpiService)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_actor_id] = override_actor
    app.dependency_overrides[get_tenant_id] = override_tenant
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"/api/v1/agent_runs/{RUN_ID}/kpi")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "run_id": str(RUN_ID),
        "tenant_id": 1,
        "project_id": str(PROJECT_ID),
        "status": "completed",
        "completed_at": "2026-05-24T11:00:00Z",
        "repo_pr_opened_event_count": 1,
        "first_repo_pr_opened_at": "2026-05-24T09:15:00Z",
        "time_to_merge_proxy_sample_count": 1,
        "time_to_merge_proxy_ms": 6_300_000.0,
        "time_to_merge_proxy_source": "repo_pr_opened_to_agent_run_completed",
    }
    assert "event_payload" not in payload
    assert "payload" not in payload


@pytest.mark.asyncio
async def test_agent_runs_kpi_endpoint_returns_404_for_missing_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingAgentRunKpiService:
        def __init__(self, session: object) -> None:
            self.session = session

        async def fetch(self, *, tenant_id: int, run_id: UUID) -> AgentRunKpi | None:
            return None

    app = create_app(_settings())

    async def override_session() -> AsyncIterator[object]:
        yield object()

    async def override_actor() -> UUID:
        return ACTOR_ID

    def override_tenant() -> int:
        return 1

    monkeypatch.setattr(agent_runs_api, "AgentRunKpiService", MissingAgentRunKpiService)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_actor_id] = override_actor
    app.dependency_overrides[get_tenant_id] = override_tenant
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"/api/v1/agent_runs/{RUN_ID}/kpi")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "agent run not found"
