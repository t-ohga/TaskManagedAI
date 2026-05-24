"""GitHub webhook verification service boundary for RepoProxy."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from backend.app.db.models.secret_ref import SecretRefStatus
from backend.app.services.repoproxy.webhook_hmac import (
    WebhookVerificationResult,
    verify_github_webhook_signature,
)

GITHUB_WEBHOOK_REPLAY_WINDOW_SECONDS = 3600
GITHUB_WEBHOOK_VERIFIED_AUDIT_EVENT_TYPE = "github_webhook_verified"
GITHUB_WEBHOOK_DENIED_AUDIT_EVENT_TYPE = "github_webhook_denied"
WEBHOOK_HMAC_FAILED_AUDIT_EVENT_TYPE = "webhook_hmac_failed"


class GitHubWebhookReasonCode(StrEnum):
    """Service-level webhook verification result codes."""

    ACCEPTED = "accepted"
    DELIVERY_ID_REQUIRED = "delivery_id_required"
    INSTALLATION_ID_REQUIRED = "installation_id_required"
    SECRET_NOT_FOUND = "secret_not_found"  # noqa: S105
    CURRENT_SECRET_NOT_ACTIVE = "current_secret_not_active"  # noqa: S105
    PREVIOUS_SECRET_STATUS_INVALID = "previous_secret_status_invalid"  # noqa: S105
    EMPTY_PAYLOAD = "empty_payload"
    EMPTY_SECRET = "empty_secret"  # noqa: S105
    INVALID_SIGNATURE_FORMAT = "invalid_signature_format"
    SIGNATURE_ALGORITHM_UNSUPPORTED = "signature_algorithm_unsupported"
    SIGNATURE_MISMATCH = "signature_mismatch"
    REPLAY_DETECTED = "replay_detected"


@dataclass(frozen=True, slots=True)
class GitHubWebhookRequest:
    """Raw GitHub webhook input needed by the service boundary."""

    tenant_id: int
    installation_id: int
    delivery_id: str | None
    payload: bytes
    signature_header: str | None


@dataclass(frozen=True, slots=True)
class WebhookSecretCandidate:
    """SecretBroker-resolved webhook secret candidate.

    ``secret`` is intentionally hidden from ``repr`` so exceptions or test
    diffs do not echo the raw HMAC secret.
    """

    secret_ref_id: UUID
    version: str
    status: SecretRefStatus
    secret: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class WebhookSecretCandidates:
    """Current and optional previous webhook secret candidates."""

    current: WebhookSecretCandidate | None
    previous: WebhookSecretCandidate | None = None


@dataclass(frozen=True, slots=True)
class GitHubWebhookVerificationResult:
    """Final service-level verification result and redacted audit payload."""

    accepted: bool
    reason_code: GitHubWebhookReasonCode
    audit_event_type: str
    audit_payload: dict[str, object]
    matched_secret_ref_id: UUID | None = None
    matched_secret_version: str | None = None


class WebhookSecretResolver(Protocol):
    """Resolve webhook HMAC candidates through a SecretBroker-owned boundary."""

    async def resolve_webhook_secrets(
        self,
        *,
        tenant_id: int,
        installation_id: int,
    ) -> WebhookSecretCandidates: ...


class WebhookReplayStore(Protocol):
    """Atomic replay guard, normally backed by Redis SETNX + TTL."""

    async def claim_once(self, *, key: str, ttl_seconds: int) -> bool: ...


class WebhookAuditSink(Protocol):
    """Optional append-only audit sink."""

    async def append(
        self,
        *,
        tenant_id: int,
        event_type: str,
        payload: dict[str, object],
    ) -> object: ...


class GitHubWebhookVerifier:
    """Verify GitHub webhook HMAC, rotation status, replay, and audit payloads."""

    def __init__(
        self,
        *,
        secret_resolver: WebhookSecretResolver,
        replay_store: WebhookReplayStore,
        audit_sink: WebhookAuditSink | None = None,
        replay_window_seconds: int = GITHUB_WEBHOOK_REPLAY_WINDOW_SECONDS,
    ) -> None:
        if replay_window_seconds < 1:
            raise ValueError("replay_window_seconds must be positive.")
        self._secret_resolver = secret_resolver
        self._replay_store = replay_store
        self._audit_sink = audit_sink
        self._replay_window_seconds = replay_window_seconds

    async def verify(self, request: GitHubWebhookRequest) -> GitHubWebhookVerificationResult:
        """Verify one GitHub webhook request.

        The replay nonce is claimed only after a valid HMAC match so invalid
        signatures cannot consume a real delivery id.
        """

        _require_request_scope(request)
        if request.installation_id < 1:
            return await self._result(
                request=request,
                accepted=False,
                reason_code=GitHubWebhookReasonCode.INSTALLATION_ID_REQUIRED,
            )
        if not request.delivery_id:
            return await self._result(
                request=request,
                accepted=False,
                reason_code=GitHubWebhookReasonCode.DELIVERY_ID_REQUIRED,
            )

        secrets = await self._secret_resolver.resolve_webhook_secrets(
            tenant_id=request.tenant_id,
            installation_id=request.installation_id,
        )
        current = secrets.current
        if current is None:
            return await self._result(
                request=request,
                accepted=False,
                reason_code=GitHubWebhookReasonCode.SECRET_NOT_FOUND,
            )
        if current.status != "active":
            return await self._result(
                request=request,
                accepted=False,
                reason_code=GitHubWebhookReasonCode.CURRENT_SECRET_NOT_ACTIVE,
                candidate=current,
            )

        current_result = verify_github_webhook_signature(
            request.payload,
            request.signature_header,
            current.secret,
            delivery_id=request.delivery_id,
        )
        if current_result.result == WebhookVerificationResult.VALID:
            return await self._claim_replay_then_accept(request, current)
        if current_result.result != WebhookVerificationResult.SIGNATURE_MISMATCH:
            return await self._result(
                request=request,
                accepted=False,
                reason_code=_map_hmac_reason(current_result.result),
                candidate=current,
            )

        previous = secrets.previous
        if previous is not None:
            if previous.status != "deprecated":
                return await self._result(
                    request=request,
                    accepted=False,
                    reason_code=GitHubWebhookReasonCode.PREVIOUS_SECRET_STATUS_INVALID,
                    candidate=previous,
                )
            previous_result = verify_github_webhook_signature(
                request.payload,
                request.signature_header,
                previous.secret,
                delivery_id=request.delivery_id,
            )
            if previous_result.result == WebhookVerificationResult.VALID:
                return await self._claim_replay_then_accept(request, previous)

        return await self._result(
            request=request,
            accepted=False,
            reason_code=_map_hmac_reason(current_result.result),
            candidate=current,
        )

    async def _claim_replay_then_accept(
        self,
        request: GitHubWebhookRequest,
        candidate: WebhookSecretCandidate,
    ) -> GitHubWebhookVerificationResult:
        if request.delivery_id is None:
            raise RuntimeError("delivery_id must be validated before replay claim.")
        claimed = await self._replay_store.claim_once(
            key=_replay_key(
                tenant_id=request.tenant_id,
                installation_id=request.installation_id,
                delivery_id=request.delivery_id,
            ),
            ttl_seconds=self._replay_window_seconds,
        )
        if not claimed:
            return await self._result(
                request=request,
                accepted=False,
                reason_code=GitHubWebhookReasonCode.REPLAY_DETECTED,
                candidate=candidate,
            )
        return await self._result(
            request=request,
            accepted=True,
            reason_code=GitHubWebhookReasonCode.ACCEPTED,
            candidate=candidate,
        )

    async def _result(
        self,
        *,
        request: GitHubWebhookRequest,
        accepted: bool,
        reason_code: GitHubWebhookReasonCode,
        candidate: WebhookSecretCandidate | None = None,
    ) -> GitHubWebhookVerificationResult:
        audit_event_type = _audit_event_type(reason_code)
        audit_payload = _build_audit_payload(
            request=request,
            reason_code=reason_code,
            replay_window_seconds=self._replay_window_seconds,
            candidate=candidate,
        )
        if self._audit_sink is not None:
            await self._audit_sink.append(
                tenant_id=request.tenant_id,
                event_type=audit_event_type,
                payload=audit_payload,
            )
        return GitHubWebhookVerificationResult(
            accepted=accepted,
            reason_code=reason_code,
            audit_event_type=audit_event_type,
            audit_payload=audit_payload,
            matched_secret_ref_id=candidate.secret_ref_id if accepted and candidate else None,
            matched_secret_version=candidate.version if accepted and candidate else None,
        )


def _require_request_scope(request: GitHubWebhookRequest) -> None:
    if not isinstance(request.tenant_id, int) or isinstance(request.tenant_id, bool):
        raise ValueError("tenant_id must be a positive integer.")
    if request.tenant_id < 1:
        raise ValueError("tenant_id must be a positive integer.")
    if not isinstance(request.installation_id, int) or isinstance(
        request.installation_id, bool
    ):
        raise ValueError("installation_id must be a positive integer.")


def _map_hmac_reason(
    result: WebhookVerificationResult,
) -> GitHubWebhookReasonCode:
    return {
        WebhookVerificationResult.EMPTY_PAYLOAD: GitHubWebhookReasonCode.EMPTY_PAYLOAD,
        WebhookVerificationResult.EMPTY_SECRET: GitHubWebhookReasonCode.EMPTY_SECRET,
        WebhookVerificationResult.INVALID_FORMAT: (
            GitHubWebhookReasonCode.INVALID_SIGNATURE_FORMAT
        ),
        WebhookVerificationResult.ALGORITHM_UNSUPPORTED: (
            GitHubWebhookReasonCode.SIGNATURE_ALGORITHM_UNSUPPORTED
        ),
        WebhookVerificationResult.SIGNATURE_MISMATCH: (
            GitHubWebhookReasonCode.SIGNATURE_MISMATCH
        ),
        WebhookVerificationResult.VALID: GitHubWebhookReasonCode.ACCEPTED,
    }[result]


def _audit_event_type(reason_code: GitHubWebhookReasonCode) -> str:
    if reason_code == GitHubWebhookReasonCode.ACCEPTED:
        return GITHUB_WEBHOOK_VERIFIED_AUDIT_EVENT_TYPE
    if reason_code in {
        GitHubWebhookReasonCode.EMPTY_PAYLOAD,
        GitHubWebhookReasonCode.EMPTY_SECRET,
        GitHubWebhookReasonCode.INVALID_SIGNATURE_FORMAT,
        GitHubWebhookReasonCode.SIGNATURE_ALGORITHM_UNSUPPORTED,
        GitHubWebhookReasonCode.SIGNATURE_MISMATCH,
    }:
        return WEBHOOK_HMAC_FAILED_AUDIT_EVENT_TYPE
    return GITHUB_WEBHOOK_DENIED_AUDIT_EVENT_TYPE


def _build_audit_payload(
    *,
    request: GitHubWebhookRequest,
    reason_code: GitHubWebhookReasonCode,
    replay_window_seconds: int,
    candidate: WebhookSecretCandidate | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "guard": "github_webhook_hmac",
        "redacted": True,
        "reason_code": reason_code.value,
        "tenant_id": request.tenant_id,
        "installation_id": request.installation_id,
        "delivery_id_hash": _hash_optional(request.delivery_id),
        "delivery_id_present": bool(request.delivery_id),
        "signature_present": bool(request.signature_header),
        "payload_sha256": hashlib.sha256(request.payload).hexdigest(),
        "replay_window_seconds": replay_window_seconds,
    }
    if candidate is not None:
        payload["secret_ref_id"] = str(candidate.secret_ref_id)
        payload["secret_ref_version"] = candidate.version
        payload["secret_ref_status"] = candidate.status
    return payload


def _hash_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _replay_key(*, tenant_id: int, installation_id: int, delivery_id: str) -> str:
    delivery_hash = hashlib.sha256(delivery_id.encode("utf-8")).hexdigest()
    return f"github-webhook:{tenant_id}:{installation_id}:{delivery_hash}"


__all__ = [
    "GITHUB_WEBHOOK_DENIED_AUDIT_EVENT_TYPE",
    "GITHUB_WEBHOOK_REPLAY_WINDOW_SECONDS",
    "GITHUB_WEBHOOK_VERIFIED_AUDIT_EVENT_TYPE",
    "WEBHOOK_HMAC_FAILED_AUDIT_EVENT_TYPE",
    "GitHubWebhookReasonCode",
    "GitHubWebhookRequest",
    "GitHubWebhookVerificationResult",
    "GitHubWebhookVerifier",
    "WebhookAuditSink",
    "WebhookReplayStore",
    "WebhookSecretCandidate",
    "WebhookSecretCandidates",
    "WebhookSecretResolver",
]
