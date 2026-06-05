"""GitHub webhook ingress route for RepoProxy."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from backend.app.config import Settings, get_settings
from backend.app.db.session import get_session
from backend.app.services.repoproxy.webhook_adapters import (
    DbWebhookAuditSink,
    DbWebhookSecretResolver,
    RedisWebhookReplayStore,
    SecretMaterialResolver,
)
from backend.app.services.repoproxy.webhook_event_parser import record_webhook_event
from backend.app.services.repoproxy.webhook_service import (
    GITHUB_WEBHOOK_REPLAY_WINDOW_SECONDS,
    GitHubWebhookReasonCode,
    GitHubWebhookRequest,
    GitHubWebhookVerificationResult,
    GitHubWebhookVerifier,
    WebhookReplayStore,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["github_webhooks"])

_GITHUB_SIGNATURE_HEADER = "X-Hub-Signature-256"
_GITHUB_DELIVERY_HEADER = "X-GitHub-Delivery"
_GITHUB_EVENT_HEADER = "X-GitHub-Event"
_ALLOWED_INGRESS_NETWORKS = (
    ip_network("127.0.0.0/8"),
    ip_network("::1/128"),
    ip_network("100.64.0.0/10"),
)


class GitHubWebhookIngressResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted: bool
    reason_code: GitHubWebhookReasonCode
    audit_event_type: str


@dataclass(frozen=True, slots=True)
class GitHubWebhookRuntime:
    verifier: GitHubWebhookVerifier
    commit: Callable[[], Awaitable[None]]


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


async def get_webhook_runtime(
    request: Request,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> GitHubWebhookRuntime:
    return _build_webhook_runtime(request, session)


def _build_webhook_runtime(request: Request, session: AsyncSession) -> GitHubWebhookRuntime:
    material_resolver = _resolve_material_resolver(request)
    replay_store = _resolve_replay_store(request)
    verifier = GitHubWebhookVerifier(
        secret_resolver=DbWebhookSecretResolver(
            session,
            material_resolver=material_resolver,
        ),
        replay_store=replay_store,
        audit_sink=DbWebhookAuditSink(session),
        replay_window_seconds=GITHUB_WEBHOOK_REPLAY_WINDOW_SECONDS,
    )
    return GitHubWebhookRuntime(verifier=verifier, commit=session.commit)


@router.post("/github", response_model=GitHubWebhookIngressResponse)
async def receive_github_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> JSONResponse:
    _require_internal_ingress(request)
    runtime = _runtime_from_app_state(request) or _build_webhook_runtime(request, session)
    payload = await request.body()
    tenant_id = _tenant_id(request)
    installation_id = _extract_installation_id(payload)
    delivery_id = request.headers.get(_GITHUB_DELIVERY_HEADER)
    result = await runtime.verifier.verify(
        GitHubWebhookRequest(
            tenant_id=tenant_id,
            installation_id=installation_id,
            delivery_id=delivery_id,
            payload=payload,
            signature_header=request.headers.get(_GITHUB_SIGNATURE_HEADER),
        )
    )
    await runtime.commit()
    # ADR-00050 SP-028: verification accepted の **後段** に best-effort で event を記録する。
    # 既存 ingress security contract は変更せず、失敗しても verification 応答を巻き戻さない (R2 F-005)。
    if result.accepted and delivery_id and installation_id >= 1:
        await _record_webhook_event_best_effort(
            session,
            tenant_id=tenant_id,
            installation_id=installation_id,
            delivery_id=delivery_id,
            event_kind_header=request.headers.get(_GITHUB_EVENT_HEADER),
            payload=payload,
        )
    response = GitHubWebhookIngressResponse(
        accepted=result.accepted,
        reason_code=result.reason_code,
        audit_event_type=result.audit_event_type,
    )
    return JSONResponse(
        status_code=_status_code_for(result),
        content=response.model_dump(mode="json"),
        headers={"cache-control": "no-store"},
    )


async def _record_webhook_event_best_effort(
    session: AsyncSession,
    *,
    tenant_id: int,
    installation_id: int,
    delivery_id: str,
    event_kind_header: str | None,
    payload: bytes,
) -> None:
    """webhook event を記録する best-effort hook。parser は自前で失敗を握るが、想定外例外でも
     ingress を壊さないよう二重に握る (raw payload は log しない)。"""

    try:
        await record_webhook_event(
            session,
            tenant_id=tenant_id,
            installation_id=installation_id,
            delivery_id=delivery_id,
            event_kind_header=event_kind_header,
            payload=payload,
            payload_hash=hashlib.sha256(payload).hexdigest(),
        )
    except Exception:  # noqa: BLE001 - best-effort enrichment must never break ingress
        logger.warning(
            "github webhook event enrichment failed (ingress unaffected): "
            "tenant_id=%s event_kind_present=%s",
            tenant_id,
            bool(event_kind_header),
        )


def _runtime_from_app_state(request: Request) -> GitHubWebhookRuntime | None:
    runtime = getattr(request.app.state, "github_webhook_runtime", None)
    if runtime is None:
        return None
    return cast(GitHubWebhookRuntime, runtime)


def _resolve_material_resolver(request: Request) -> SecretMaterialResolver:
    resolver = getattr(request.app.state, "github_webhook_secret_material_resolver", None)
    if resolver is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "github_webhook_secret_material_resolver_missing",
                "reason_code": "github_webhook_secret_material_resolver_missing",
                "error_summary": (
                    "GitHub webhook secret material resolver is not configured."
                ),
            },
        )
    if not callable(getattr(resolver, "resolve_secret_material", None)):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "github_webhook_secret_material_resolver_invalid",
                "reason_code": "github_webhook_secret_material_resolver_invalid",
                "error_summary": (
                    "GitHub webhook secret material resolver must implement "
                    "resolve_secret_material(secret_ref)."
                ),
            },
        )
    return cast(SecretMaterialResolver, resolver)


def _resolve_replay_store(request: Request) -> WebhookReplayStore:
    store = getattr(request.app.state, "github_webhook_replay_store", None)
    if store is not None:
        return cast(WebhookReplayStore, store)
    settings = _settings_from_app(request)
    store = RedisWebhookReplayStore.from_url(settings.redis_url)
    request.app.state.github_webhook_replay_store = store
    return store


def _settings_from_app(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, Settings):
        return settings
    return get_settings()


def _require_internal_ingress(request: Request) -> None:
    client = request.client
    if client is None or not client.host:
        raise _ingress_forbidden("github_webhook_ingress_client_missing")
    try:
        host = ip_address(client.host)
    except ValueError as exc:
        raise _ingress_forbidden("github_webhook_ingress_client_invalid") from exc
    if any(host in network for network in _ALLOWED_INGRESS_NETWORKS):
        return
    raise _ingress_forbidden("github_webhook_ingress_denied")


def _ingress_forbidden(reason_code: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error_code": "github_webhook_ingress_denied",
            "reason_code": reason_code,
            "error_summary": "GitHub webhook ingress is restricted to internal networks.",
        },
    )


def _tenant_id(request: Request) -> int:
    value = getattr(request.state, "tenant_id", None)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return _settings_from_app(request).default_tenant_id
    return value


def _extract_installation_id(payload: bytes) -> int:
    try:
        decoded: Any = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 0
    if not isinstance(decoded, dict):
        return 0
    installation = decoded.get("installation")
    if not isinstance(installation, dict):
        return 0
    installation_id = installation.get("id")
    if not isinstance(installation_id, int) or isinstance(installation_id, bool):
        return 0
    return installation_id


def _status_code_for(result: GitHubWebhookVerificationResult) -> int:
    if result.reason_code == GitHubWebhookReasonCode.ACCEPTED:
        return status.HTTP_202_ACCEPTED
    if result.reason_code in {
        GitHubWebhookReasonCode.INVALID_SIGNATURE_FORMAT,
        GitHubWebhookReasonCode.SIGNATURE_ALGORITHM_UNSUPPORTED,
        GitHubWebhookReasonCode.SIGNATURE_MISMATCH,
    }:
        return status.HTTP_401_UNAUTHORIZED
    if result.reason_code == GitHubWebhookReasonCode.REPLAY_DETECTED:
        return status.HTTP_409_CONFLICT
    if result.reason_code in {
        GitHubWebhookReasonCode.DELIVERY_ID_REQUIRED,
        GitHubWebhookReasonCode.INSTALLATION_ID_REQUIRED,
        GitHubWebhookReasonCode.EMPTY_PAYLOAD,
    }:
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_503_SERVICE_UNAVAILABLE


__all__ = [
    "GitHubWebhookIngressResponse",
    "GitHubWebhookRuntime",
    "get_db_session",
    "get_webhook_runtime",
    "receive_github_webhook",
    "router",
]
