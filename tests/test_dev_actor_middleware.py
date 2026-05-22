from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from backend.app.config import Environment, Settings
from backend.app.main import create_app
from backend.app.middleware.dev_actor import (
    DEV_SESSION_COOKIE_NAME,
    DevActorContextMiddleware,
    RequireAuthenticatedActorMiddleware,
    create_signed_session_cookie,
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


def _middleware_class_names(app: FastAPI) -> set[str]:
    return {getattr(middleware.cls, "__name__", str(middleware.cls)) for middleware in app.user_middleware}


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["development", "test"])
async def test_dev_actor_context_middleware_sets_default_actor(
    environment: Environment,
) -> None:
    app = _app_with_context_probe(environment)
    assert DevActorContextMiddleware.__name__ in _middleware_class_names(app)

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

    middleware_names = _middleware_class_names(app)
    assert DevActorContextMiddleware.__name__ not in middleware_names
    assert RequireAuthenticatedActorMiddleware.__name__ in middleware_names


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
async def test_production_request_with_invalid_cookie_returns_401() -> None:
    app = _app_with_context_probe("production")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(DEV_SESSION_COOKIE_NAME, "not-a-signed-session")
        response = await client.get("/_test/request-context")

    assert response.status_code == 401
    assert response.json()["detail"] == {
        "error_code": "unauthenticated",
        "error_summary": "Authentication is required.",
    }


@pytest.mark.asyncio
async def test_production_request_with_expired_cookie_returns_401() -> None:
    settings = _settings_for("production")
    cookie_value, _ = create_signed_session_cookie(
        secret=settings.dev_login_cookie_secret,
        now=datetime(2026, 5, 22, tzinfo=UTC),
        ttl_seconds=-1,
    )
    app = _app_with_context_probe("production")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(DEV_SESSION_COOKIE_NAME, cookie_value)
        response = await client.get("/_test/request-context")

    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "unauthenticated"


@pytest.mark.asyncio
async def test_production_request_with_valid_cookie_resolves_session_actor() -> None:
    settings = _settings_for("production")
    cookie_value, _ = create_signed_session_cookie(
        secret=settings.dev_login_cookie_secret,
        now=datetime.now(tz=UTC),
        ttl_seconds=60 * 60,
    )
    app = _app_with_context_probe("production")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(DEV_SESSION_COOKIE_NAME, cookie_value)
        response = await client.get("/_test/request-context")

    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": 1,
        "actor_id": "human:default",
        "principal_id": "session",
        "authenticated": True,
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
