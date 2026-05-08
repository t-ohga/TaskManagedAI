from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from backend.app.config import Environment, Settings
from backend.app.main import create_app
from backend.app.middleware.dev_actor import (
    DEV_SESSION_COOKIE_NAME,
    create_signed_session_cookie,
    verify_signed_session_cookie,
)

pytestmark = pytest.mark.asyncio

_TEST_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:test-password@postgres:5432/taskmanagedai"
)
_TEST_REDIS_URL = "redis://redis:6379/0"
_PRODUCTION_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:prod-db-value@postgres:5432/taskmanagedai"
)
_PRODUCTION_REDIS_URL = "redis://redis:6379/0"


@pytest.fixture
def auth_settings() -> Settings:
    return _settings_for("test")


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


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _signed_cookie_with_claims(claims: dict[str, object], secret: str) -> str:
    payload_segment = _base64url_encode(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature_segment = _base64url_encode(
        hmac.new(
            secret.encode("utf-8"),
            payload_segment.encode("ascii"),
            hashlib.sha256,
        ).digest()
    )
    return f"{payload_segment}.{signature_segment}"


def _production_app_with_context_probe(settings: Settings) -> FastAPI:
    app = create_app(settings)

    @app.get("/_test/auth-context")
    async def auth_context(request: Request) -> dict[str, object]:
        return {
            "tenant_id": request.state.tenant_id,
            "actor_id": request.state.actor_id,
            "principal_id": request.state.principal_id,
            "authenticated": request.state.authenticated,
        }

    return app


async def test_dev_login_issues_signed_cookie_with_fixed_actor(
    monkeypatch: pytest.MonkeyPatch,
    auth_settings: Settings,
) -> None:
    monkeypatch.setenv("TASKMANAGEDAI_DEV_LOGIN_TOKEN", "correct-dev-login-token")
    app = create_app(auth_settings)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/auth/dev-login",
            json={"token": "correct-dev-login-token"},
            headers={"x-request-id": "auth-request"},
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "auth-request"
    assert response.json() == {
        "status": "ok",
        "actor_id": "human:default",
        "principal_type": "session",
    }

    set_cookie_headers = response.headers.get_list("set-cookie")
    assert len(set_cookie_headers) == 1
    set_cookie = set_cookie_headers[0]
    assert f"{DEV_SESSION_COOKIE_NAME}=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Path=/" in set_cookie

    cookie_value = response.cookies.get(DEV_SESSION_COOKIE_NAME)
    assert cookie_value != ""
    claims = verify_signed_session_cookie(
        cookie_value,
        secret=auth_settings.dev_login_cookie_secret,
    )
    assert claims is not None
    assert claims.actor_id == "human:default"
    assert claims.principal_type == "session"


async def test_dev_login_rejects_wrong_token_without_cookie(
    monkeypatch: pytest.MonkeyPatch,
    auth_settings: Settings,
) -> None:
    monkeypatch.setenv("TASKMANAGEDAI_DEV_LOGIN_TOKEN", "correct-dev-login-token")
    app = create_app(auth_settings)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/auth/dev-login",
            json={"token": "wrong-dev-login-token"},
        )

    assert response.status_code == 401
    assert response.json() == {
        "detail": {
            "error_code": "invalid_dev_login_token",
            "error_summary": "Development login token is invalid.",
        }
    }
    assert response.headers.get_list("set-cookie") == []


async def test_dev_login_returns_404_in_production(
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


async def test_signed_cookie_binds_request_context_actor(
    auth_settings: Settings,
) -> None:
    app = create_app(auth_settings)

    @app.get("/_test/auth-context")
    async def auth_context(request: Request) -> dict[str, object]:
        return {
            "tenant_id": request.state.tenant_id,
            "actor_id": request.state.actor_id,
            "principal_id": request.state.principal_id,
            "authenticated": request.state.authenticated,
        }

    cookie_value, _expires_at = create_signed_session_cookie(
        secret=auth_settings.dev_login_cookie_secret,
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={DEV_SESSION_COOKIE_NAME: cookie_value},
    ) as client:
        response = await client.get("/_test/auth-context")

    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": 1,
        "actor_id": "human:default",
        "principal_id": "session",
        "authenticated": True,
    }


async def test_dev_login_contract_supports_frontend_proxy_cookie_flow(
    monkeypatch: pytest.MonkeyPatch,
    auth_settings: Settings,
) -> None:
    monkeypatch.setenv("TASKMANAGEDAI_DEV_LOGIN_TOKEN", "correct-dev-login-token")
    app = create_app(auth_settings)

    @app.get("/_test/auth-context")
    async def auth_context(request: Request) -> dict[str, object]:
        return {
            "tenant_id": request.state.tenant_id,
            "actor_id": request.state.actor_id,
            "principal_id": request.state.principal_id,
            "authenticated": request.state.authenticated,
        }

    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        login_response = await client.post(
            "/auth/dev-login",
            json={"token": "correct-dev-login-token"},
            headers={"x-request-id": "frontend-proxy-request"},
        )
        cookie_value = login_response.cookies.get(DEV_SESSION_COOKIE_NAME)
        assert cookie_value is not None
        context_response = await client.get(
            "/_test/auth-context",
            cookies={DEV_SESSION_COOKIE_NAME: cookie_value},
        )

    assert login_response.status_code == 200
    assert login_response.headers["x-request-id"] == "frontend-proxy-request"
    assert cookie_value != ""
    assert (
        verify_signed_session_cookie(
            cookie_value,
            secret=auth_settings.dev_login_cookie_secret,
        )
        is not None
    )
    assert context_response.status_code == 200
    assert context_response.json() == {
        "tenant_id": 1,
        "actor_id": "human:default",
        "principal_id": "session",
        "authenticated": True,
    }


async def test_expired_cookie_returns_401_in_production() -> None:
    settings = _settings_for("production")
    app = _production_app_with_context_probe(settings)
    expired_cookie, _expires_at = create_signed_session_cookie(
        secret=settings.dev_login_cookie_secret,
        now=datetime(2026, 5, 8, 0, 0, 0, tzinfo=UTC),
        ttl_seconds=-1,
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/_test/auth-context",
            cookies={DEV_SESSION_COOKIE_NAME: expired_cookie},
        )

    assert response.status_code == 401
    assert response.json() == {
        "detail": {
            "error_code": "unauthenticated",
            "error_summary": "Authentication is required.",
        }
    }


async def test_forged_actor_id_cookie_returns_401_in_production() -> None:
    settings = _settings_for("production")
    app = _production_app_with_context_probe(settings)
    forged_cookie = _signed_cookie_with_claims(
        {
            "actor_id": "human:forged",
            "exp": 2_000_000_000,
            "principal_type": "session",
        },
        settings.dev_login_cookie_secret,
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/_test/auth-context",
            cookies={DEV_SESSION_COOKIE_NAME: forged_cookie},
        )

    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "unauthenticated"


async def test_forged_principal_type_cookie_returns_401_in_production() -> None:
    settings = _settings_for("production")
    app = _production_app_with_context_probe(settings)
    forged_cookie = _signed_cookie_with_claims(
        {
            "actor_id": "human:default",
            "exp": 2_000_000_000,
            "principal_type": "api_key",
        },
        settings.dev_login_cookie_secret,
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/_test/auth-context",
            cookies={DEV_SESSION_COOKIE_NAME: forged_cookie},
        )

    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "unauthenticated"


async def test_tampered_cookie_does_not_verify(
    auth_settings: Settings,
) -> None:
    cookie_value, _expires_at = create_signed_session_cookie(
        secret=auth_settings.dev_login_cookie_secret,
    )

    claims = verify_signed_session_cookie(
        f"{cookie_value}tampered",
        secret=auth_settings.dev_login_cookie_secret,
    )

    assert claims is None

