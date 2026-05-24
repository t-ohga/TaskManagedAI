"""SP-008 Batch B: GitHubAppAdapter broker-mediated boundary tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID

import pytest

from backend.app.services.repoproxy.github_app_adapter import (
    GITHUB_API_VERSION,
    GitHubAppAdapter,
    GitHubDraftPRResponse,
)
from backend.app.services.repoproxy.repoproxy import (
    DraftPRRequest,
    RepoProxyDenyReason,
)
from backend.app.services.secrets.broker import (
    BrokerOperationContext,
    BrokerRedeemDenied,
    BrokerRedeemResult,
    SecretBroker,
    SecretHandle,
)

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-00000000c001")
RUN_ID = UUID("00000000-0000-4000-8000-00000000c002")
APPROVAL_ID = UUID("00000000-0000-4000-8000-00000000c003")
CAPABILITY_ID = UUID("00000000-0000-4000-8000-00000000c004")
SECRET_REF_ID = UUID("00000000-0000-4000-8000-00000000c005")
CAPABILITY_TOKEN = "unit-test-secretbroker-capability"


class _FakeBroker:
    def __init__(self, *, deny: bool = False) -> None:
        self.deny = deny
        self.calls: list[dict[str, object]] = []

    async def redeem_capability_token(
        self,
        **kwargs: object,
    ) -> BrokerRedeemResult[GitHubDraftPRResponse] | BrokerRedeemDenied:
        self.calls.append({key: value for key, value in kwargs.items() if key != "operation"})
        if self.deny:
            return BrokerRedeemDenied(
                reason_code="fingerprint_mismatch",
                requested_operation="repo.pr_open",
                capability_id=CAPABILITY_ID,
                secret_ref_id=SECRET_REF_ID,
            )

        operation = kwargs["operation"]
        assert callable(operation)
        target = cast(Mapping[str, Any], kwargs["target"])
        context = BrokerOperationContext(
            tenant_id=cast(int, kwargs["tenant_id"]),
            actor_id=cast(UUID, kwargs["actor_id"]),
            run_id=cast(UUID, kwargs["run_id"]),
            requested_operation="repo.pr_open",
            target=target,
            payload_hash=cast(str, kwargs["payload_hash"]),
            secret_handle=SecretHandle(
                secret_ref_id=SECRET_REF_ID,
                scope="github_app",
                name="installation-token",
                version="v1",
            ),
        )
        response = await operation(context)
        return BrokerRedeemResult(
            capability_id=CAPABILITY_ID,
            secret_ref_id=SECRET_REF_ID,
            requested_operation="repo.pr_open",
            operation_result=response,
        )


class _FakeTransport:
    def __init__(self) -> None:
        self.context: BrokerOperationContext | None = None
        self.request: DraftPRRequest | None = None
        self.api_version: str | None = None

    async def create_draft_pr(
        self,
        *,
        context: BrokerOperationContext,
        request: DraftPRRequest,
        api_version: str,
    ) -> GitHubDraftPRResponse:
        self.context = context
        self.request = request
        self.api_version = api_version
        return GitHubDraftPRResponse(
            pr_number=17,
            pr_url="https://github.com/owner/repo/pull/17",
            draft=True,
        )


def _request(**overrides: str) -> DraftPRRequest:
    values = {
        "repo_full_name": "owner/repo",
        "base_branch": "main",
        "head_branch": "codex/agent-run-abcd1234",
        "commit_sha": "2" * 40,
        "artifact_hash": "a" * 64,
        "policy_version": "policy-v1",
        "provider_request_fingerprint": "b" * 64,
        "repo_state_commit_sha": "1" * 40,
        "approval_id": str(APPROVAL_ID),
    }
    values.update(overrides)
    return DraftPRRequest(**values)


@pytest.mark.asyncio
async def test_adapter_redeems_repo_pr_open_and_returns_draft_pr_result() -> None:
    broker = _FakeBroker()
    transport = _FakeTransport()
    adapter = GitHubAppAdapter(
        broker=cast(SecretBroker, broker),
        transport=transport,
    )

    result = await adapter.create_draft_pr(
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        run_id=RUN_ID,
        capability_token=CAPABILITY_TOKEN,
        request=_request(),
    )

    assert result.pr_number == 17
    assert result.pr_url == "https://github.com/owner/repo/pull/17"
    assert result.draft is True
    assert result.deny_reason is None
    assert broker.calls == [
        {
            "tenant_id": TENANT_ID,
            "actor_id": ACTOR_ID,
            "run_id": RUN_ID,
            "raw_token": CAPABILITY_TOKEN,
            "requested_operation": "repo.pr_open",
            "target": {
                "repo_full_name": "owner/repo",
                "base_branch": "main",
                "head_branch": "codex/agent-run-abcd1234",
                "draft": True,
                "commit_sha": "2" * 40,
                "repo_state_commit_sha": "1" * 40,
            },
            "payload_hash": "a" * 64,
            "approval_id": APPROVAL_ID,
            "policy_version": "policy-v1",
        }
    ]
    assert transport.request == _request()
    assert transport.api_version == GITHUB_API_VERSION


@pytest.mark.asyncio
async def test_adapter_never_passes_installation_token_to_transport() -> None:
    broker = _FakeBroker()
    transport = _FakeTransport()
    adapter = GitHubAppAdapter(
        broker=cast(SecretBroker, broker),
        transport=transport,
    )

    result = await adapter.create_draft_pr(
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        run_id=RUN_ID,
        capability_token=CAPABILITY_TOKEN,
        request=_request(),
    )

    assert result.deny_reason is None
    assert transport.context is not None
    assert not hasattr(transport.context, "installation_token")
    assert not hasattr(transport.context, "capability_token")
    assert transport.context.secret_handle.secret_ref_id == SECRET_REF_ID
    assert transport.request is not None
    assert "installation_token" not in repr(transport.request)


@pytest.mark.asyncio
async def test_adapter_maps_broker_denial_to_fail_closed_result() -> None:
    adapter = GitHubAppAdapter(
        broker=cast(SecretBroker, _FakeBroker(deny=True)),
        transport=_FakeTransport(),
    )

    result = await adapter.create_draft_pr(
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        run_id=RUN_ID,
        capability_token=CAPABILITY_TOKEN,
        request=_request(),
    )

    assert result.pr_number is None
    assert result.pr_url is None
    assert result.draft is False
    assert result.deny_reason == RepoProxyDenyReason.APPROVAL_NOT_GRANTED


@pytest.mark.asyncio
async def test_adapter_rejects_invalid_approval_id_without_broker_call() -> None:
    broker = _FakeBroker()
    adapter = GitHubAppAdapter(
        broker=cast(SecretBroker, broker),
        transport=_FakeTransport(),
    )

    result = await adapter.create_draft_pr(
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        run_id=RUN_ID,
        capability_token=CAPABILITY_TOKEN,
        request=_request(approval_id="not-a-uuid"),
    )

    assert result.deny_reason == RepoProxyDenyReason.APPROVAL_NOT_GRANTED
    assert broker.calls == []


def test_github_api_version_is_pinned_to_adr_00011_value() -> None:
    assert GITHUB_API_VERSION == "2022-11-28"
