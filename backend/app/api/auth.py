from __future__ import annotations

import hmac
import logging
import os
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from backend.app.config import Settings, get_settings
from backend.app.middleware.dev_actor import (
    DEFAULT_ACTOR_ID,
    DEFAULT_PRINCIPAL_TYPE,
    DEV_SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    create_signed_session_cookie,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

_DEV_LOGIN_ENVIRONMENTS = frozenset({"development", "test"})


class DevLoginRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    token: str = Field(min_length=1, max_length=4096)


class DevLoginResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"]
    actor_id: Literal["human:default"]
    principal_type: Literal["session"]


def _settings_from_request(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, Settings):
        return settings
    return get_settings()


def _ensure_dev_login_allowed(request: Request) -> Settings:
    settings = _settings_from_request(request)
    if settings.environment not in _DEV_LOGIN_ENVIRONMENTS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return settings


def _read_expected_dev_login_token() -> str:
    token = os.environ.get("TASKMANAGEDAI_DEV_LOGIN_TOKEN")
    if token is None or token.strip() == "" or "REPLACE_ME" in token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "dev_login_not_configured",
                "error_summary": "Development login token is not configured.",
            },
        )
    return token


def _token_matches(submitted_token: str, expected_token: str) -> bool:
    return hmac.compare_digest(submitted_token.encode("utf-8"), expected_token.encode("utf-8"))


@router.post(
    "/auth/dev-login",
    response_model=DevLoginResponse,
    summary="Issue a Sprint 1 development session cookie",
)
async def dev_login(
    payload: DevLoginRequest,
    request: Request,
    response: Response,
) -> DevLoginResponse:
    settings = _ensure_dev_login_allowed(request)
    expected_token = _read_expected_dev_login_token()

    if not _token_matches(payload.token.strip(), expected_token):
        logger.warning(
            "dev_login_failed",
            extra={
                "reason_code": "invalid_token",
                "request_id": getattr(request.state, "request_id", None),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "invalid_dev_login_token",
                "error_summary": "Development login token is invalid.",
            },
        )

    cookie_value, expires_at = create_signed_session_cookie(
        secret=settings.dev_login_cookie_secret,
    )
    # P0 boundary: production は HTTPS 必須 (Tailscale Serve TLS 終端) のため secure=True 固定。
    # development / test は CI Playwright が HTTP loopback (127.0.0.1:3900) で走るため、
    # Chromium が HTTP context で Secure 属性を持つ cookie を silently drop する事象を
    # 回避する目的で secure=False とする。Cookie boundary 自体は HttpOnly + SameSite=lax で
    # XSS / CSRF 防御を維持する。
    is_production = settings.environment == "production"
    response.set_cookie(
        key=DEV_SESSION_COOKIE_NAME,
        value=cookie_value,
        max_age=SESSION_TTL_SECONDS,
        expires=expires_at,
        path="/",
        secure=is_production,
        httponly=True,
        samesite="lax",
    )
    logger.info(
        "dev_login_succeeded",
        extra={
            "actor_id": DEFAULT_ACTOR_ID,
            "principal_type": DEFAULT_PRINCIPAL_TYPE,
            "request_id": getattr(request.state, "request_id", None),
        },
    )

    return DevLoginResponse(
        status="ok",
        actor_id=DEFAULT_ACTOR_ID,
        principal_type=DEFAULT_PRINCIPAL_TYPE,
    )
