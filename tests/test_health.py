from __future__ import annotations

import pytest
from httpx import AsyncClient

from backend.app.api import health as health_api
from backend.app.config import Settings

pytestmark = pytest.mark.asyncio


async def test_healthz_returns_ok(async_client: AsyncClient) -> None:
    response = await async_client.get("/healthz", headers={"x-request-id": "test-request-id"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "test-request-id"

    payload = response.json()
    assert payload == {
        "status": "ok",
        "version": "0.1.0",
        "service": "api",
    }


async def test_readyz_returns_dependency_status(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def postgres_ready(settings: Settings) -> health_api.DependencyStatus:
        assert settings.environment == "test"
        return health_api.DependencyStatus(status="ok")

    async def redis_ready(settings: Settings) -> health_api.DependencyStatus:
        assert settings.environment == "test"
        return health_api.DependencyStatus(status="ok")

    monkeypatch.setattr(health_api, "check_postgres", postgres_ready)
    monkeypatch.setattr(health_api, "check_redis", redis_ready)

    response = await async_client.get("/readyz", headers={"x-request-id": "ready-request-id"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "ready-request-id"
    assert response.json() == {
        "status": "ready",
        "version": "0.1.0",
        "service": "api",
        "dependencies": {
            "postgres": {"status": "ok"},
            "redis": {"status": "ok"},
        },
    }


async def test_readyz_returns_503_when_db_unavailable(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def postgres_unavailable(settings: Settings) -> health_api.DependencyStatus:
        assert settings.environment == "test"
        return health_api.DependencyStatus(
            status="error",
            error_code="postgres_unavailable",
            error_summary="PostgreSQL readiness check failed.",
        )

    async def redis_ready(settings: Settings) -> health_api.DependencyStatus:
        assert settings.environment == "test"
        return health_api.DependencyStatus(status="ok")

    monkeypatch.setattr(health_api, "check_postgres", postgres_unavailable)
    monkeypatch.setattr(health_api, "check_redis", redis_ready)

    response = await async_client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "version": "0.1.0",
        "service": "api",
        "dependencies": {
            "postgres": {
                "status": "error",
                "error_code": "postgres_unavailable",
                "error_summary": "PostgreSQL readiness check failed.",
            },
            "redis": {"status": "ok"},
        },
    }
