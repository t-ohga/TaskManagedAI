from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from backend.app.config import Settings

DEV_SESSION_COOKIE_NAME = "taskmanagedai_session"
DEFAULT_ACTOR_ID: Literal["human:default"] = "human:default"
DEFAULT_PRINCIPAL_TYPE: Literal["session"] = "session"
SESSION_TTL_SECONDS = 60 * 60 * 12
_DEV_ACTOR_CONTEXT_ENVIRONMENTS = frozenset({"development", "test"})
_PRODUCTION_PUBLIC_PATHS = frozenset({"/auth/dev-login", "/healthz", "/readyz"})


@dataclass(frozen=True)
class DevSessionClaims:
    actor_id: Literal["human:default"]
    principal_type: Literal["session"]
    exp: int


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - (len(value) % 4)) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _claims_json(claims: DevSessionClaims) -> str:
    return json.dumps(
        {
            "actor_id": claims.actor_id,
            "exp": claims.exp,
            "principal_type": claims.principal_type,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _sign_payload(payload_segment: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        payload_segment.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return _base64url_encode(digest)


def create_signed_session_cookie(
    *,
    secret: str,
    now: datetime | None = None,
    ttl_seconds: int = SESSION_TTL_SECONDS,
) -> tuple[str, datetime]:
    issued_at = now or datetime.now(tz=UTC)
    expires_at = issued_at + timedelta(seconds=ttl_seconds)
    claims = DevSessionClaims(
        actor_id=DEFAULT_ACTOR_ID,
        principal_type=DEFAULT_PRINCIPAL_TYPE,
        exp=int(expires_at.timestamp()),
    )
    payload_segment = _base64url_encode(_claims_json(claims).encode("utf-8"))
    signature_segment = _sign_payload(payload_segment, secret)
    return f"{payload_segment}.{signature_segment}", expires_at


def _parse_claims(payload: object) -> DevSessionClaims | None:
    if not isinstance(payload, Mapping):
        return None

    actor_id = payload.get("actor_id")
    principal_type = payload.get("principal_type")
    exp = payload.get("exp")

    if actor_id != DEFAULT_ACTOR_ID or principal_type != DEFAULT_PRINCIPAL_TYPE:
        return None
    if not isinstance(exp, int):
        return None

    return DevSessionClaims(
        actor_id=DEFAULT_ACTOR_ID,
        principal_type=DEFAULT_PRINCIPAL_TYPE,
        exp=exp,
    )


def verify_signed_session_cookie(
    value: str,
    *,
    secret: str,
    now: datetime | None = None,
) -> DevSessionClaims | None:
    parts = value.split(".")
    if len(parts) != 2:
        return None

    payload_segment, signature_segment = parts
    expected_signature = _sign_payload(payload_segment, secret)
    if not hmac.compare_digest(signature_segment, expected_signature):
        return None

    try:
        payload = json.loads(_base64url_decode(payload_segment).decode("utf-8"))
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None

    claims = _parse_claims(payload)
    if claims is None:
        return None

    checked_at = now or datetime.now(tz=UTC)
    if claims.exp <= int(checked_at.timestamp()):
        return None

    return claims


def _set_authenticated_actor(
    request: Request,
    settings: Settings,
    claims: DevSessionClaims,
) -> None:
    request.state.tenant_id = settings.default_tenant_id
    request.state.actor_id = claims.actor_id
    request.state.principal_id = claims.principal_type
    request.state.authenticated = True


def _request_has_authenticated_actor(request: Request) -> bool:
    return (
        getattr(request.state, "authenticated", False) is True
        and getattr(request.state, "actor_id", None) is not None
        and getattr(request.state, "principal_id", None) is not None
    )


def _unauthenticated_response() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "detail": {
                "error_code": "unauthenticated",
                "error_summary": "Authentication is required.",
            }
        },
        headers={"cache-control": "no-store"},
    )


class DevActorContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.tenant_id = self._settings.default_tenant_id

        claims = None
        cookie_value = request.cookies.get(DEV_SESSION_COOKIE_NAME)
        if cookie_value:
            claims = verify_signed_session_cookie(
                cookie_value,
                secret=self._settings.dev_login_cookie_secret,
            )

        if claims is not None:
            _set_authenticated_actor(request, self._settings, claims)
        elif self._settings.environment in _DEV_ACTOR_CONTEXT_ENVIRONMENTS:
            request.state.actor_id = self._settings.default_actor_id
            request.state.principal_id = self._settings.default_principal_id
            request.state.authenticated = False
        else:
            request.state.actor_id = None
            request.state.principal_id = None
            request.state.authenticated = False

        return await call_next(request)


class RequireAuthenticatedActorMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        settings: Settings,
        public_paths: frozenset[str] = _PRODUCTION_PUBLIC_PATHS,
    ) -> None:
        super().__init__(app)
        self._settings = settings
        self._public_paths = public_paths

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in self._public_paths:
            return await call_next(request)

        request.state.tenant_id = self._settings.default_tenant_id

        if _request_has_authenticated_actor(request):
            return await call_next(request)

        cookie_value = request.cookies.get(DEV_SESSION_COOKIE_NAME)
        if cookie_value:
            claims = verify_signed_session_cookie(
                cookie_value,
                secret=self._settings.dev_login_cookie_secret,
            )
            if claims is not None:
                _set_authenticated_actor(request, self._settings, claims)
                return await call_next(request)

        request.state.actor_id = None
        request.state.principal_id = None
        request.state.authenticated = False
        return _unauthenticated_response()

