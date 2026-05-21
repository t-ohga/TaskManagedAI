from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

from backend.app.api import agent_runs as agent_runs_api
from backend.app.api import approval_inbox, notifications
from backend.app.api.dependencies.active_registry_gate import (
    configure_active_registry_gate_from_settings,
)
from backend.app.api.router import api_router
from backend.app.config import Settings, get_settings
from backend.app.middleware.dev_actor import (
    DevActorContextMiddleware,
    RequireAuthenticatedActorMiddleware,
)
from backend.app.observability import (
    PrometheusMetricsAccessGuard,
    create_metrics_router,
    setup_logging,
    setup_otel,
    setup_prometheus,
)

_DEV_ACTOR_CONTEXT_ENVIRONMENTS = frozenset({"development", "test"})


class RequestIDMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, header_name: str) -> None:
        super().__init__(app)
        self._header_name = header_name

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(self._header_name, str(uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[self._header_name] = request_id
        return response


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        docs_url="/docs" if resolved_settings.environment != "production" else None,
        redoc_url=None,
    )
    app.state.settings = resolved_settings

    if resolved_settings.environment in _DEV_ACTOR_CONTEXT_ENVIRONMENTS:
        app.add_middleware(DevActorContextMiddleware, settings=resolved_settings)
    elif resolved_settings.environment == "production":
        app.add_middleware(RequireAuthenticatedActorMiddleware, settings=resolved_settings)

    app.add_middleware(RequestIDMiddleware, header_name=resolved_settings.request_id_header)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=resolved_settings.allowed_hosts)

    # Sprint 11.5 batch 0 (BL-0131 + BL-0132): /metrics endpoint への access を
    # IP allowlist (127.0.0.0/8 + ::1/128 + 100.64.0.0/10) で防御.
    # production で 0.0.0.0 bind が誤って導入されても 403 でブロック.
    app.add_middleware(PrometheusMetricsAccessGuard)

    if resolved_settings.environment == "development":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved_settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )

    # Sprint 11.5 batch 1 BL-0133: structured logging (JSON Lines) for Loki shipping.
    # observability_enabled=False で NoOp. setup_otel より先に call (logger 経由 init log を JSON 化).
    setup_logging(role="api")

    # Sprint 11.5 batch 0 BL-0131: OTel TracerProvider + auto-instrument
    # (FastAPI / httpx / SQLAlchemy / Redis). observability_enabled=False で NoOp.
    # Codex F-PR40-001 P2 adopt: instance-bound `instrument_app(app)` のため app= で渡す.
    setup_otel(role="api", app=app)

    # Sprint 11.5 batch 0 BL-0132: Prometheus metrics + /metrics endpoint mount.
    # prometheus_metrics_enabled=False で NoOp.
    prometheus_registry = setup_prometheus()
    if prometheus_registry is not None:
        from backend.app.observability.prometheus import PrometheusRequestDurationMiddleware

        app.add_middleware(PrometheusRequestDurationMiddleware, registry=prometheus_registry)
        app.include_router(create_metrics_router(prometheus_registry))

    # SP-012 §9.10 R10 F-001 + §9.4 R2 F-007: L1 active-registry write gate wiring.
    # Codex PR #85 R1 F-001 fix (P1): production wiring を実装。
    # `TASKMANAGEDAI_ACTIVE_REGISTRY_GATE_ENABLED=true` で attach。
    # disabled (default) なら no-op (development / test の既存 contract test を維持)。
    # L1 ingress 強制は本 wiring + 各 write endpoint への
    # `Depends(require_active_registry_write_authority)` で達成 (Sprint 13 で
    # 全 mutation endpoint に追加。本 PR は wiring + dependency function 提供)。
    configure_active_registry_gate_from_settings(app.state)

    app.include_router(api_router)
    app.include_router(approval_inbox.router)
    app.include_router(notifications.router)
    app.include_router(agent_runs_api.router)
    return app


app = create_app()

