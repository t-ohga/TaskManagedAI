from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

from backend.app.api import approval_inbox, notifications
from backend.app.api.router import api_router
from backend.app.config import Settings, get_settings
from backend.app.middleware.dev_actor import (
    DevActorContextMiddleware,
    RequireAuthenticatedActorMiddleware,
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

    if resolved_settings.environment == "development":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved_settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )

    app.include_router(api_router)
    app.include_router(approval_inbox.router)
    app.include_router(notifications.router)
    return app


app = create_app()

