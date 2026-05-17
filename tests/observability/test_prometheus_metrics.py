"""Sprint 11.5 batch 0 (BL-0132): Prometheus /metrics endpoint + IP allowlist tests.

Verify items (plan v2 §6.1):
- `/metrics` endpoint 200 (allowlist IP)
- `/metrics` endpoint 403 (非 allowlist IP、H-1)
- request_duration_seconds / agent_run_total label dimensions
- cardinality 制御: actor_id は 8-char hash prefix のみ (raw reject)
- tenant_id None reject (boundary invariant)
- secret pattern hit を metric description に含めようとすると reject
- 3 別 data class dimension (合算禁止)
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from backend.app.observability.config import ObservabilitySettings
from backend.app.observability.prometheus import (
    PrometheusMetricsAccessGuard,
    PrometheusRegistry,
    create_metrics_router,
    hash_actor_id,
    setup_prometheus,
)


def _build_app(registry: PrometheusRegistry) -> FastAPI:
    app = FastAPI()
    app.add_middleware(PrometheusMetricsAccessGuard)
    app.include_router(create_metrics_router(registry))

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _settings(enabled: bool = True) -> ObservabilitySettings:
    return ObservabilitySettings(
        observability_enabled=enabled,
        prometheus_metrics_enabled=enabled,
        otel_exporter_otlp_endpoint="",
    )


def _client_for(app: FastAPI, client_host: str) -> httpx.AsyncClient:
    """`httpx.ASGITransport.client` で ASGI scope の client tuple を override.

    `starlette.testclient.TestClient` は default client.host を `"testclient"`
    (固定 string) で渡すため、IP parse 経由の middleware test に使えない.
    `httpx.ASGITransport(client=("ip", port))` で scope を build する.
    """

    transport = httpx.ASGITransport(app=app, client=(client_host, 12345))
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def test_setup_prometheus_returns_registry() -> None:
    reg = setup_prometheus(settings=_settings())
    assert reg is not None


def test_setup_prometheus_disabled_returns_none() -> None:
    reg = setup_prometheus(settings=_settings(enabled=False))
    assert reg is None


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_200_from_loopback() -> None:
    reg = PrometheusRegistry()
    app = _build_app(reg)
    async with _client_for(app, "127.0.0.1") as client:
        response = await client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_metrics_payload_contains_metric_names() -> None:
    reg = PrometheusRegistry()
    reg.record_agent_run(status="completed", payload_data_class="internal", tenant_id=1)
    app = _build_app(reg)
    async with _client_for(app, "127.0.0.1") as client:
        response = await client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert "taskmanagedai_agent_run_total" in body
    # 3 別 data class dimension (provider_call_total) は record で emit 必要.
    reg.record_provider_call(
        provider="openai",
        payload_data_class="internal",
        allowed_data_class="confidential",
        effective_allowed_data_class="internal",
        decision="allow",
        tenant_id=1,
    )
    async with _client_for(app, "127.0.0.1") as client:
        response2 = await client.get("/metrics")
    assert "taskmanagedai_provider_call_total" in response2.text


@pytest.mark.asyncio
async def test_metrics_access_guard_rejects_non_allowlist_ip() -> None:
    """Plan v2 §H-1 adopt: 非 allowlist IP (203.0.113.0/24 は TEST-NET-3) は 403."""

    reg = PrometheusRegistry()
    app = _build_app(reg)
    async with _client_for(app, "203.0.113.10") as client:
        response = await client.get("/metrics")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_metrics_access_guard_allows_tailscale_cgnat() -> None:
    """Plan v2 §H-1 adopt: Tailscale CGNAT 100.64.0.0/10 範囲は allow."""

    reg = PrometheusRegistry()
    app = _build_app(reg)
    async with _client_for(app, "100.115.27.116") as client:
        response = await client.get("/metrics")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_metrics_access_guard_rejects_public_ip() -> None:
    """8.8.8.8 (Google DNS) は allowlist 範囲外 → 403."""

    reg = PrometheusRegistry()
    app = _build_app(reg)
    async with _client_for(app, "8.8.8.8") as client:
        response = await client.get("/metrics")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_metrics_access_guard_passes_through_non_metrics_path() -> None:
    """`/metrics` 以外の path は middleware を素通り (他 endpoint への副作用なし)."""

    reg = PrometheusRegistry()
    app = _build_app(reg)
    async with _client_for(app, "203.0.113.10") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200


def test_hash_actor_id_returns_8_char_hex() -> None:
    """`actor_id` の hash は 8-char hex prefix (cardinality 制御)."""

    result = hash_actor_id("alice@example.com")
    assert len(result) == 8
    assert all(c in "0123456789abcdef" for c in result)


def test_hash_actor_id_rejects_empty() -> None:
    with pytest.raises(ValueError):
        hash_actor_id("")


def test_record_agent_run_invalid_data_class_rejected() -> None:
    reg = PrometheusRegistry()
    with pytest.raises(ValueError, match="payload_data_class"):
        reg.record_agent_run(status="completed", payload_data_class="invalid", tenant_id=1)


def test_record_provider_call_3_dimensions_required() -> None:
    """3 別 dimension (payload / allowed / effective_allowed) を別 label で記録."""

    reg = PrometheusRegistry()
    reg.record_provider_call(
        provider="openai",
        payload_data_class="internal",
        allowed_data_class="confidential",
        effective_allowed_data_class="internal",
        decision="allow",
        tenant_id=1,
    )
    # generate_latest で 3 別 label が現れることを smoke.
    body = reg.expose().decode("utf-8")
    assert 'payload_data_class="internal"' in body
    assert 'allowed_data_class="confidential"' in body
    assert 'effective_allowed_data_class="internal"' in body


def test_record_provider_call_invalid_effective_data_class_rejected() -> None:
    reg = PrometheusRegistry()
    with pytest.raises(ValueError, match="effective_allowed_data_class"):
        reg.record_provider_call(
            provider="openai",
            payload_data_class="internal",
            allowed_data_class="confidential",
            effective_allowed_data_class="bogus",
            decision="allow",
            tenant_id=1,
        )


def test_record_provider_call_tenant_id_none_rejected() -> None:
    reg = PrometheusRegistry()
    with pytest.raises(ValueError, match="tenant_id"):
        reg.record_provider_call(
            provider="openai",
            payload_data_class="public",
            allowed_data_class="public",
            effective_allowed_data_class="public",
            decision="allow",
            tenant_id=None,  # type: ignore[arg-type]
        )


def test_record_agent_run_tenant_id_none_rejected() -> None:
    reg = PrometheusRegistry()
    with pytest.raises(ValueError, match="tenant_id"):
        reg.record_agent_run(
            status="completed", payload_data_class="public", tenant_id=None  # type: ignore[arg-type]
        )
