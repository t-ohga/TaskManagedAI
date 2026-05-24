"""GitHub App adapter boundary for broker-mediated Draft PR creation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from backend.app.services.repoproxy.repoproxy import (
    DraftPRRequest,
    DraftPRResult,
    RepoProxyDenyReason,
)
from backend.app.services.secrets.broker import (
    BrokerOperationContext,
    BrokerRedeemDenied,
    BrokerRedeemResult,
    OperationCallback,
    SecretBroker,
)

GITHUB_API_VERSION = "2022-11-28"


@dataclass(frozen=True, slots=True)
class GitHubDraftPRResponse:
    """Minimal GitHub Draft PR response shape surfaced by the transport."""

    pr_number: int
    pr_url: str
    draft: bool


class GitHubBrokeredTransport(Protocol):
    """Transport executed inside a SecretBroker redeem operation."""

    async def create_draft_pr(
        self,
        *,
        context: BrokerOperationContext,
        request: DraftPRRequest,
        api_version: str,
    ) -> GitHubDraftPRResponse: ...


class GitHubAppAdapter:
    """Broker-mediated GitHub App Draft PR adapter.

    The adapter accepts a SecretBroker capability token, not a GitHub
    installation token. The only callback-visible secret material is
    ``BrokerOperationContext.secret_handle``; raw installation tokens remain
    inside SecretBroker / transport internals.
    """

    def __init__(
        self,
        *,
        broker: SecretBroker,
        transport: GitHubBrokeredTransport,
        api_version: str = GITHUB_API_VERSION,
    ) -> None:
        self._broker = broker
        self._transport = transport
        self._api_version = api_version

    async def create_draft_pr(
        self,
        *,
        tenant_id: int,
        actor_id: UUID,
        run_id: UUID,
        capability_token: str,
        request: DraftPRRequest,
    ) -> DraftPRResult:
        approval_id = _approval_uuid_or_none(request.approval_id)
        if approval_id is None:
            return _denied(RepoProxyDenyReason.APPROVAL_NOT_GRANTED)

        async def operation(
            context: BrokerOperationContext,
        ) -> GitHubDraftPRResponse:
            return await self._transport.create_draft_pr(
                context=context,
                request=request,
                api_version=self._api_version,
            )

        operation_callback: OperationCallback[GitHubDraftPRResponse] = operation
        redeem: BrokerRedeemResult[GitHubDraftPRResponse] | BrokerRedeemDenied = (
            await self._broker.redeem_capability_token(
                tenant_id=tenant_id,
                actor_id=actor_id,
                run_id=run_id,
                raw_token=capability_token,
                requested_operation="repo.pr_open",
                target=_target_from_request(request),
                payload_hash=request.artifact_hash,
                approval_id=approval_id,
                policy_version=request.policy_version,
                operation=operation_callback,
            )
        )
        if isinstance(redeem, BrokerRedeemDenied) or redeem.operation_result is None:
            return _denied(RepoProxyDenyReason.APPROVAL_NOT_GRANTED)

        response = redeem.operation_result
        return DraftPRResult(
            pr_number=response.pr_number,
            pr_url=response.pr_url,
            draft=response.draft,
            deny_reason=None,
        )


def _target_from_request(request: DraftPRRequest) -> dict[str, object]:
    return {
        "repo_full_name": request.repo_full_name,
        "base_branch": request.base_branch,
        "head_branch": request.head_branch,
        "draft": True,
        "commit_sha": request.commit_sha,
        "repo_state_commit_sha": request.repo_state_commit_sha,
    }


def _approval_uuid_or_none(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


def _denied(reason: RepoProxyDenyReason) -> DraftPRResult:
    return DraftPRResult(
        pr_number=None,
        pr_url=None,
        draft=False,
        deny_reason=reason,
    )


__all__ = [
    "GITHUB_API_VERSION",
    "GitHubAppAdapter",
    "GitHubBrokeredTransport",
    "GitHubDraftPRResponse",
]
