from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api import onboarding as onboarding_api
from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.api.onboarding import router as onboarding_router
from backend.app.api.router import api_router
from backend.app.domain.policy.action_class import ActionClass
from backend.app.domain.policy.autonomy_level import AutonomyLevel
from backend.app.services.policy.autonomy_policy_engine import (
    AutonomyPolicyEngineDecision,
)

_ACTOR_ID = UUID("00000000-0000-4000-8000-000000009601")
_PROJECT_ID = UUID("00000000-0000-4000-8000-000000009602")


@dataclass(frozen=True)
class _ProjectFixture:
    id: UUID
    autonomy_level: AutonomyLevel


class _NoMutationSession:
    def add(self, *_: object, **__: object) -> None:
        raise AssertionError("onboarding dry-run endpoint must not add ORM objects")

    async def flush(self, *_: object, **__: object) -> None:
        raise AssertionError("onboarding dry-run endpoint must not flush")

    async def commit(self) -> None:
        raise AssertionError("onboarding dry-run endpoint must not commit")


def _payload(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "purpose": "Understand the safest first step.",
        "target_repo_ref": "t-ohga/TaskManagedAI",
        "expected_artifact": "Reviewed plan",
        "allowed_action_class": "read_only",
        "budget_cap": "0 USD committed",
        "starter_mode": "research_only",
    }
    values.update(overrides)
    return values


def _decision(action_class: ActionClass) -> AutonomyPolicyEngineDecision:
    return AutonomyPolicyEngineDecision(
        autonomy_level="L3",
        policy_profile="default",
        action_class=action_class,
        decision="require_approval",
        profile_resolved_effect="allow",
        require_review_artifact=False,
        reason_code="autonomy_runtime_disabled_fallback",
        profile_reason_code="policy_profile_action_effect_resolved",
        low_risk_failed_axes=(),
        override_source=None,
    )


def _build_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    app = FastAPI()
    app.include_router(onboarding_router)

    async def override_actor() -> UUID:
        return _ACTOR_ID

    async def override_tenant() -> int:
        return 1

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, _NoMutationSession())

    async def fake_current_project(
        session: AsyncSession,
        *,
        tenant_id: int,
    ) -> _ProjectFixture:
        assert tenant_id == 1
        assert isinstance(session, _NoMutationSession)
        return _ProjectFixture(id=_PROJECT_ID, autonomy_level="L3")

    monkeypatch.setattr(onboarding_api, "_resolve_current_project", fake_current_project)
    app.dependency_overrides[get_current_actor_id] = override_actor
    app.dependency_overrides[get_tenant_id] = override_tenant
    app.dependency_overrides[get_db_session] = override_session
    return app


@pytest_asyncio.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    app = _build_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def test_api_router_includes_onboarding_dry_run_route() -> None:
    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()))))
        for route in api_router.routes
    }

    assert ("/api/v1/onboarding/dry_run_plan", ("POST",)) in routes


@pytest.mark.asyncio
async def test_endpoint_returns_no_store_read_only_plan(client: AsyncClient) -> None:
    response = await client.post("/api/v1/onboarding/dry_run_plan", json=_payload())

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    plan = response.json()["dry_run_plan"]
    assert plan["starter_mode"] == "research_only"
    assert plan["requested_action_class"] == "read_only"
    assert plan["effective_action_class"] == "read_only"
    assert plan["policy_effect"] == "allow"
    assert plan["approval_required"] is False
    assert set(plan["would_create"].values()) == {False}
    assert plan["next_safe_routes"] == ["/settings", "/today", "/timeline"]


@pytest.mark.asyncio
async def test_endpoint_rejects_server_owned_fields(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/onboarding/dry_run_plan",
        json=_payload(policy_profile="caller-owned"),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "error_code": "onboarding_dry_run_invalid_schema",
        "message": "invalid onboarding dry-run request schema",
    }


@pytest.mark.asyncio
async def test_endpoint_sanitizes_schema_validation_values(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/onboarding/dry_run_plan",
        json=_payload(policy_profile="sk-" + ("A" * 24)),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "error_code": "onboarding_dry_run_invalid_schema",
        "message": "invalid onboarding dry-run request schema",
    }
    assert "sk-" not in response.text


@pytest.mark.asyncio
async def test_endpoint_sanitizes_raw_secret_rejection(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/onboarding/dry_run_plan",
        json=_payload(purpose="sk-" + ("A" * 24)),
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"] == {
        "error_code": "onboarding_dry_run_invalid_input",
        "message": "invalid onboarding dry-run request",
    }
    assert "sk-" not in response.text


@pytest.mark.asyncio
async def test_endpoint_rejects_raw_secret_before_project_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _build_app(monkeypatch)

    async def fail_if_called(session: AsyncSession, *, tenant_id: int) -> None:
        raise AssertionError("current project lookup must not run for raw-secret input")

    monkeypatch.setattr(onboarding_api, "_resolve_current_project", fail_if_called)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        response = await c.post(
            "/api/v1/onboarding/dry_run_plan",
            json=_payload(purpose="sk-" + ("A" * 24)),
        )

    assert response.status_code == 400
    assert "sk-" not in response.text


@pytest.mark.asyncio
async def test_endpoint_resolves_mutating_request_with_runtime_disabled(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_resolver(
        session: AsyncSession,
        *,
        tenant_id: int,
        autonomy_level: str,
        action_class: ActionClass,
        low_risk_input: object,
        runtime_enabled: bool,
    ) -> AutonomyPolicyEngineDecision:
        calls.append(
            {
                "tenant_id": tenant_id,
                "autonomy_level": autonomy_level,
                "action_class": action_class,
                "low_risk_input": low_risk_input,
                "runtime_enabled": runtime_enabled,
                "session_type": type(session).__name__,
            }
        )
        return _decision(action_class)

    monkeypatch.setattr(
        "backend.app.services.onboarding.dry_run_plan.resolve_autonomy_policy_action_effect",
        fake_resolver,
    )

    response = await client.post(
        "/api/v1/onboarding/dry_run_plan",
        json=_payload(
            starter_mode="draft_pr_requires_approval",
            allowed_action_class="pr_open",
        ),
    )

    assert response.status_code == 200
    plan = response.json()["dry_run_plan"]
    assert plan["requested_action_class"] == "pr_open"
    assert plan["effective_action_class"] == "pr_open"
    assert plan["policy_effect"] == "require_approval"
    assert plan["approval_required"] is True
    assert set(plan["would_create"].values()) == {False}
    assert calls == [
        {
            "tenant_id": 1,
            "autonomy_level": "L3",
            "action_class": "pr_open",
            "low_risk_input": None,
            "runtime_enabled": False,
            "session_type": "_NoMutationSession",
        }
    ]


@pytest.mark.asyncio
async def test_endpoint_returns_404_when_current_project_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _build_app(monkeypatch)

    async def missing_project(session: AsyncSession, *, tenant_id: int) -> None:
        raise onboarding_api.HTTPException(
            status_code=404,
            detail="no project found for tenant",
        )

    monkeypatch.setattr(onboarding_api, "_resolve_current_project", missing_project)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        response = await c.post("/api/v1/onboarding/dry_run_plan", json=_payload())

    assert response.status_code == 404
