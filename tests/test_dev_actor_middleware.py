from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from backend.app.config import Environment, Settings
from backend.app.main import create_app
from backend.app.middleware.dev_actor import (
    DevActorContextMiddleware,
    RequireAuthenticatedActorMiddleware,
)

_TEST_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:test-password@postgres:5432/taskmanagedai"
)
_TEST_REDIS_URL = "redis://:test-redis-value@redis:6379/0"
_PRODUCTION_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:prod-db-value@postgres:5432/taskmanagedai"
)
_PRODUCTION_REDIS_URL = "redis://:prod-redis-value@redis:6379/0"


def _settings_for(environment: Environment) -> Settings:
    return Settings(
        environment=environment,
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=_PRODUCTION_DATABASE_URL
        if environment == "production"
        else _TEST_DATABASE_URL,
        redis_url=_PRODUCTION_REDIS_URL if environment == "production" else _TEST_REDIS_URL,
        dev_login_cookie_secret="prod-cookie-secret"
        if environment == "production"
        else "test-cookie-secret",
    )


def _app_with_context_probe(environment: Environment) -> FastAPI:
    app = create_app(_settings_for(environment))

    @app.get("/_test/request-context")
    async def request_context(request: Request) -> dict[str, object]:
        return {
            "tenant_id": request.state.tenant_id,
            "actor_id": request.state.actor_id,
            "principal_id": request.state.principal_id,
            "authenticated": request.state.authenticated,
        }

    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["development", "test"])
async def test_dev_actor_context_middleware_sets_default_actor(
    environment: Environment,
) -> None:
    app = _app_with_context_probe(environment)
    assert any(middleware.cls is DevActorContextMiddleware for middleware in app.user_middleware)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/_test/request-context")

    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": 1,
        "actor_id": "human:default",
        "principal_id": "session",
        "authenticated": False,
    }


def test_production_startup_registers_request_level_auth_middleware() -> None:
    app = create_app(_settings_for("production"))

    assert not any(
        middleware.cls is DevActorContextMiddleware
        for middleware in app.user_middleware
    )
    assert any(
        middleware.cls is RequireAuthenticatedActorMiddleware
        for middleware in app.user_middleware
    )


@pytest.mark.asyncio
async def test_production_protected_request_without_cookie_returns_401() -> None:
    app = _app_with_context_probe("production")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/_test/request-context")

    assert response.status_code == 401
    assert response.json() == {
        "detail": {
            "error_code": "unauthenticated",
            "error_summary": "Authentication is required.",
        }
    }


@pytest.mark.asyncio
async def test_production_dev_login_route_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TASKMANAGEDAI_DEV_LOGIN_TOKEN", "correct-dev-login-token")
    app = create_app(_settings_for("production"))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/auth/dev-login",
            json={"token": "correct-dev-login-token"},
        )

    assert response.status_code == 404
    assert response.headers.get_list("set-cookie") == []


@pytest.mark.asyncio
async def test_production_denies_dev_actor_fallback_even_when_flag_is_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TASKMANAGEDAI_ALLOW_DEV_ACTOR_FALLBACK", "true")
    app = _app_with_context_probe("production")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/_test/request-context")

    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "unauthenticated"

