"""SP-008: GitHub webhook ingress route tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal, cast
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api import github_webhooks
from backend.app.api.github_webhooks import GitHubWebhookRuntime
from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.services.repoproxy.webhook_service import (
    GITHUB_WEBHOOK_VERIFIED_AUDIT_EVENT_TYPE,
    WEBHOOK_HMAC_FAILED_AUDIT_EVENT_TYPE,
    GitHubWebhookReasonCode,
    GitHubWebhookRequest,
    GitHubWebhookVerificationResult,
    GitHubWebhookVerifier,
)

TENANT_ID = 1
INSTALLATION_ID = 123456
DELIVERY_ID = "7d0d55ba-2fd0-4d64-95b4-e6882e2f62d1"
SECRET_REF_ID = UUID("00000000-0000-4000-8000-00000000b001")


class _FakeVerifier:
    def __init__(self, result: GitHubWebhookVerificationResult) -> None:
        self.result = result
        self.requests: list[GitHubWebhookRequest] = []

    async def verify(self, request: GitHubWebhookRequest) -> GitHubWebhookVerificationResult:
        self.requests.append(request)
        return self.result


class _CommitRecorder:
    def __init__(self) -> None:
        self.count = 0

    async def commit(self) -> None:
        self.count += 1


def _settings(environment: Literal["test", "production"] = "test") -> Settings:
    if environment == "production":
        return Settings(
            environment="production",
            allowed_hosts=["testserver"],
            database_url="postgresql+asyncpg://prod_user:prod_pass@db.local:5432/prod",
            redis_url="redis://redis.local:6379/0",
            dev_login_cookie_secret="production-cookie-secret-for-webhooks",
        )
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        dev_login_cookie_secret="test-cookie-secret-for-github-webhooks",
    )


def _accepted_result() -> GitHubWebhookVerificationResult:
    return GitHubWebhookVerificationResult(
        accepted=True,
        reason_code=GitHubWebhookReasonCode.ACCEPTED,
        audit_event_type=GITHUB_WEBHOOK_VERIFIED_AUDIT_EVENT_TYPE,
        audit_payload={"redacted": True},
        matched_secret_ref_id=SECRET_REF_ID,
        matched_secret_version="v1",
    )


def _denied_result(reason: GitHubWebhookReasonCode) -> GitHubWebhookVerificationResult:
    return GitHubWebhookVerificationResult(
        accepted=False,
        reason_code=reason,
        audit_event_type=WEBHOOK_HMAC_FAILED_AUDIT_EVENT_TYPE,
        audit_payload={"redacted": True},
    )


def _payload() -> bytes:
    return b'{"installation":{"id":123456},"action":"opened","number":42}'


async def _override_session() -> AsyncIterator[AsyncSession]:
    yield cast(AsyncSession, object())


def _client_for(app: FastAPI, client_host: str) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, client=(client_host, 12345))
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def _install_runtime(
    app: FastAPI,
    *,
    verifier: _FakeVerifier,
    commit: _CommitRecorder,
) -> None:
    app.state.github_webhook_runtime = GitHubWebhookRuntime(
        verifier=cast(GitHubWebhookVerifier, verifier),
        commit=commit.commit,
    )


def test_github_webhook_route_is_registered() -> None:
    app = create_app(_settings())
    routes = {
        (getattr(route, "path", None), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in app.routes
    }

    assert ("/webhooks/github", ("POST",)) in routes


@pytest.mark.asyncio
async def test_github_webhook_accepts_tailscale_request_without_auth_cookie() -> None:
    app = create_app(_settings("production"))
    verifier = _FakeVerifier(_accepted_result())
    commit = _CommitRecorder()
    _install_runtime(app, verifier=verifier, commit=commit)
    app.dependency_overrides[github_webhooks.get_db_session] = _override_session
    try:
        async with _client_for(app, "100.115.27.116") as client:
            response = await client.post(
                "/webhooks/github",
                content=_payload(),
                headers={
                    "X-GitHub-Delivery": DELIVERY_ID,
                    "X-Hub-Signature-256": "sha256=" + ("a" * 64),
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    assert response.json() == {
        "accepted": True,
        "reason_code": "accepted",
        "audit_event_type": GITHUB_WEBHOOK_VERIFIED_AUDIT_EVENT_TYPE,
    }
    assert commit.count == 1
    assert len(verifier.requests) == 1
    request = verifier.requests[0]
    assert request.tenant_id == TENANT_ID
    assert request.installation_id == INSTALLATION_ID
    assert request.delivery_id == DELIVERY_ID
    assert request.payload == _payload()


@pytest.mark.asyncio
async def test_github_webhook_rejects_public_ip_even_with_forwarded_header() -> None:
    app = create_app(_settings())
    verifier = _FakeVerifier(_accepted_result())
    commit = _CommitRecorder()
    _install_runtime(app, verifier=verifier, commit=commit)
    app.dependency_overrides[github_webhooks.get_db_session] = _override_session
    try:
        async with _client_for(app, "203.0.113.10") as client:
            response = await client.post(
                "/webhooks/github",
                content=_payload(),
                headers={"X-Forwarded-For": "100.115.27.116"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"]["reason_code"] == "github_webhook_ingress_denied"
    assert verifier.requests == []
    assert commit.count == 0


@pytest.mark.asyncio
async def test_github_webhook_maps_signature_mismatch_to_401() -> None:
    app = create_app(_settings())
    verifier = _FakeVerifier(_denied_result(GitHubWebhookReasonCode.SIGNATURE_MISMATCH))
    commit = _CommitRecorder()
    _install_runtime(app, verifier=verifier, commit=commit)
    app.dependency_overrides[github_webhooks.get_db_session] = _override_session
    try:
        async with _client_for(app, "127.0.0.1") as client:
            response = await client.post(
                "/webhooks/github",
                content=_payload(),
                headers={
                    "X-GitHub-Delivery": DELIVERY_ID,
                    "X-Hub-Signature-256": "sha256=" + ("0" * 64),
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json() == {
        "accepted": False,
        "reason_code": "signature_mismatch",
        "audit_event_type": WEBHOOK_HMAC_FAILED_AUDIT_EVENT_TYPE,
    }
    assert commit.count == 1
