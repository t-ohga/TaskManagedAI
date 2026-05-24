"""SP-008 Batch C: GitHub webhook service boundary tests."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import cast
from uuid import UUID

import pytest

from backend.app.db.models.secret_ref import SecretRefStatus
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.services.repoproxy.webhook_service import (
    GITHUB_WEBHOOK_DENIED_AUDIT_EVENT_TYPE,
    GITHUB_WEBHOOK_REPLAY_WINDOW_SECONDS,
    GITHUB_WEBHOOK_VERIFIED_AUDIT_EVENT_TYPE,
    WEBHOOK_HMAC_FAILED_AUDIT_EVENT_TYPE,
    GitHubWebhookReasonCode,
    GitHubWebhookRequest,
    GitHubWebhookVerifier,
    WebhookSecretCandidate,
    WebhookSecretCandidates,
)

TENANT_ID = 1
INSTALLATION_ID = 123456
DELIVERY_ID = "4c1109fa-2cde-11ef-8b6d-7b0d4a9e2b12"
CURRENT_SECRET_REF_ID = UUID("00000000-0000-4000-8000-00000000d001")
PREVIOUS_SECRET_REF_ID = UUID("00000000-0000-4000-8000-00000000d002")
CURRENT_SECRET = b"current-webhook-secret"
PREVIOUS_SECRET = b"previous-webhook-secret"
PAYLOAD = b'{"action":"opened","number":42}'


class _FakeSecretResolver:
    def __init__(self, candidates: WebhookSecretCandidates) -> None:
        self.candidates = candidates
        self.calls: list[dict[str, int]] = []

    async def resolve_webhook_secrets(
        self,
        *,
        tenant_id: int,
        installation_id: int,
    ) -> WebhookSecretCandidates:
        self.calls.append(
            {"tenant_id": tenant_id, "installation_id": installation_id}
        )
        return self.candidates


class _FakeReplayStore:
    def __init__(self, *, claim_result: bool = True) -> None:
        self.claim_result = claim_result
        self.calls: list[dict[str, object]] = []

    async def claim_once(self, *, key: str, ttl_seconds: int) -> bool:
        self.calls.append({"key": key, "ttl_seconds": ttl_seconds})
        return self.claim_result


class _FakeAuditSink:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def append(
        self,
        *,
        tenant_id: int,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        assert_no_raw_secret(payload, path="$webhook_audit")
        self.calls.append(
            {"tenant_id": tenant_id, "event_type": event_type, "payload": payload}
        )


def _signature(secret: bytes, payload: bytes = PAYLOAD) -> str:
    return "sha256=" + hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _current_candidate(
    *,
    secret: bytes = CURRENT_SECRET,
    status: str = "active",
) -> WebhookSecretCandidate:
    return WebhookSecretCandidate(
        secret_ref_id=CURRENT_SECRET_REF_ID,
        version="v2",
        status=cast(SecretRefStatus, status),
        secret=secret,
    )


def _previous_candidate(
    *,
    secret: bytes = PREVIOUS_SECRET,
    status: str = "deprecated",
) -> WebhookSecretCandidate:
    return WebhookSecretCandidate(
        secret_ref_id=PREVIOUS_SECRET_REF_ID,
        version="v1",
        status=cast(SecretRefStatus, status),
        secret=secret,
    )


def _request(
    *,
    signature_header: str | None = None,
    delivery_id: str | None = DELIVERY_ID,
    payload: bytes = PAYLOAD,
    installation_id: int = INSTALLATION_ID,
) -> GitHubWebhookRequest:
    return GitHubWebhookRequest(
        tenant_id=TENANT_ID,
        installation_id=installation_id,
        delivery_id=delivery_id,
        payload=payload,
        signature_header=signature_header or _signature(CURRENT_SECRET, payload),
    )


def _service(
    *,
    candidates: WebhookSecretCandidates | None = None,
    replay: _FakeReplayStore | None = None,
    audit: _FakeAuditSink | None = None,
) -> tuple[GitHubWebhookVerifier, _FakeSecretResolver, _FakeReplayStore, _FakeAuditSink]:
    resolver = _FakeSecretResolver(
        candidates
        or WebhookSecretCandidates(current=_current_candidate(), previous=None)
    )
    replay_store = replay or _FakeReplayStore()
    audit_sink = audit or _FakeAuditSink()
    return (
        GitHubWebhookVerifier(
            secret_resolver=resolver,
            replay_store=replay_store,
            audit_sink=audit_sink,
        ),
        resolver,
        replay_store,
        audit_sink,
    )


@pytest.mark.asyncio
async def test_current_active_secret_accepts_and_claims_replay_after_hmac() -> None:
    verifier, resolver, replay, audit = _service()

    result = await verifier.verify(_request())

    assert result.accepted is True
    assert result.reason_code == GitHubWebhookReasonCode.ACCEPTED
    assert result.audit_event_type == GITHUB_WEBHOOK_VERIFIED_AUDIT_EVENT_TYPE
    assert result.matched_secret_ref_id == CURRENT_SECRET_REF_ID
    assert result.matched_secret_version == "v2"
    assert resolver.calls == [
        {"tenant_id": TENANT_ID, "installation_id": INSTALLATION_ID}
    ]
    assert replay.calls == [
        {
            "key": (
                "github-webhook:"
                f"{TENANT_ID}:{INSTALLATION_ID}:"
                f"{hashlib.sha256(DELIVERY_ID.encode('utf-8')).hexdigest()}"
            ),
            "ttl_seconds": GITHUB_WEBHOOK_REPLAY_WINDOW_SECONDS,
        }
    ]
    assert audit.calls[0]["event_type"] == GITHUB_WEBHOOK_VERIFIED_AUDIT_EVENT_TYPE


@pytest.mark.asyncio
async def test_previous_deprecated_secret_accepts_during_rotation() -> None:
    verifier, _resolver, replay, _audit = _service(
        candidates=WebhookSecretCandidates(
            current=_current_candidate(),
            previous=_previous_candidate(),
        )
    )

    result = await verifier.verify(
        _request(signature_header=_signature(PREVIOUS_SECRET))
    )

    assert result.accepted is True
    assert result.reason_code == GitHubWebhookReasonCode.ACCEPTED
    assert result.matched_secret_ref_id == PREVIOUS_SECRET_REF_ID
    assert result.matched_secret_version == "v1"
    assert len(replay.calls) == 1


@pytest.mark.asyncio
async def test_signature_mismatch_denies_without_consuming_replay_nonce() -> None:
    verifier, _resolver, replay, audit = _service()

    result = await verifier.verify(_request(signature_header=_signature(b"wrong")))

    assert result.accepted is False
    assert result.reason_code == GitHubWebhookReasonCode.SIGNATURE_MISMATCH
    assert result.audit_event_type == WEBHOOK_HMAC_FAILED_AUDIT_EVENT_TYPE
    assert replay.calls == []
    assert audit.calls[0]["event_type"] == WEBHOOK_HMAC_FAILED_AUDIT_EVENT_TYPE


@pytest.mark.asyncio
async def test_replay_duplicate_denies_after_valid_signature() -> None:
    verifier, _resolver, replay, audit = _service(
        replay=_FakeReplayStore(claim_result=False)
    )

    result = await verifier.verify(_request())

    assert result.accepted is False
    assert result.reason_code == GitHubWebhookReasonCode.REPLAY_DETECTED
    assert result.audit_event_type == GITHUB_WEBHOOK_DENIED_AUDIT_EVENT_TYPE
    assert len(replay.calls) == 1
    assert audit.calls[0]["event_type"] == GITHUB_WEBHOOK_DENIED_AUDIT_EVENT_TYPE


@pytest.mark.asyncio
async def test_previous_secret_must_be_deprecated_to_be_accepted() -> None:
    verifier, _resolver, replay, _audit = _service(
        candidates=WebhookSecretCandidates(
            current=_current_candidate(),
            previous=_previous_candidate(status="active"),
        )
    )

    result = await verifier.verify(
        _request(signature_header=_signature(PREVIOUS_SECRET))
    )

    assert result.accepted is False
    assert result.reason_code == GitHubWebhookReasonCode.PREVIOUS_SECRET_STATUS_INVALID
    assert replay.calls == []


@pytest.mark.asyncio
async def test_malformed_signature_does_not_probe_previous_secret_status() -> None:
    verifier, _resolver, replay, _audit = _service(
        candidates=WebhookSecretCandidates(
            current=_current_candidate(),
            previous=_previous_candidate(status="active"),
        )
    )

    result = await verifier.verify(_request(signature_header="sha256=abc123"))

    assert result.accepted is False
    assert result.reason_code == GitHubWebhookReasonCode.INVALID_SIGNATURE_FORMAT
    assert replay.calls == []


@pytest.mark.asyncio
async def test_current_secret_must_be_active() -> None:
    verifier, _resolver, replay, _audit = _service(
        candidates=WebhookSecretCandidates(
            current=_current_candidate(status="deprecated"),
            previous=None,
        )
    )

    result = await verifier.verify(_request())

    assert result.accepted is False
    assert result.reason_code == GitHubWebhookReasonCode.CURRENT_SECRET_NOT_ACTIVE
    assert replay.calls == []


@pytest.mark.asyncio
async def test_missing_delivery_id_denies_before_secret_resolution() -> None:
    verifier, resolver, replay, _audit = _service()

    result = await verifier.verify(_request(delivery_id=None))

    assert result.accepted is False
    assert result.reason_code == GitHubWebhookReasonCode.DELIVERY_ID_REQUIRED
    assert resolver.calls == []
    assert replay.calls == []


@pytest.mark.asyncio
async def test_audit_payload_redacts_delivery_signature_and_raw_secret() -> None:
    verifier, _resolver, _replay, audit = _service()

    result = await verifier.verify(
        _request(signature_header=_signature(CURRENT_SECRET))
    )

    serialized_payload = repr(result.audit_payload)
    assert DELIVERY_ID not in serialized_payload
    assert _signature(CURRENT_SECRET) not in serialized_payload
    assert CURRENT_SECRET.decode("utf-8") not in serialized_payload
    assert "signature_header" not in result.audit_payload
    assert result.audit_payload["delivery_id_hash"] == hashlib.sha256(
        DELIVERY_ID.encode("utf-8")
    ).hexdigest()
    assert audit.calls[0]["payload"] == result.audit_payload
    assert_no_raw_secret(result.audit_payload, path="$webhook_audit")


def test_secret_candidate_repr_hides_secret_bytes() -> None:
    candidate = _current_candidate(secret=b"raw-secret-value")
    assert "raw-secret-value" not in repr(candidate)


@pytest.mark.asyncio
async def test_audit_payload_values_are_json_serializable() -> None:
    verifier, _resolver, _replay, _audit = _service()

    result = await verifier.verify(_request())

    json.dumps(result.audit_payload, sort_keys=True)


def test_replay_window_must_be_positive() -> None:
    resolver = _FakeSecretResolver(
        WebhookSecretCandidates(current=_current_candidate(), previous=None)
    )
    replay = _FakeReplayStore()
    with pytest.raises(ValueError, match="replay_window_seconds"):
        GitHubWebhookVerifier(
            secret_resolver=resolver,
            replay_store=replay,
            replay_window_seconds=0,
        )
