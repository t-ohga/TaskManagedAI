"""Sprint 8 BL-0096: RepoProxy service module.

ADR-00011 §採用案: AgentRun 生成 patch を runner_mutation_gateway →
RepoProxy 経由でのみ branch push + Draft PR 作成できる回路。

SP-008 Batch A (2026-05-24):
- ``RepoProxy.create_draft_pr`` accepts only server-owned binding IDs
  (tenant_id + approval_id + agent_run_id). Callers can no longer provide the
  Draft PR's repo/hash/policy fields directly.
- ``DraftPRRequest`` remains the internal resolved request passed from the
  binding resolver to the transport implementation.
- Actual GitHub HTTP integration is still pending ``GitHubAppAdapter``.

server-owned-boundary §1:
- public create signature exposes only IDs.
- resolved request fields must come from ApprovalRequest + ContextSnapshot +
  repo state resolver.
- installation_token は SecretBroker 内でのみ resolve (Batch B)
- raw token は caller / AI / runner / artifact / log / audit に渡さない
"""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from backend.app.domain.agent_runtime.operation_context import canonical_json_dumps


class RepoProxyDenyReason(StrEnum):
    """RepoProxy operation deny reason enum."""

    APPROVAL_NOT_GRANTED = "approval_not_granted"
    ARTIFACT_HASH_MISMATCH = "artifact_hash_mismatch"
    POLICY_VERSION_MISMATCH = "policy_version_mismatch"
    PROVIDER_FINGERPRINT_MISMATCH = "provider_fingerprint_mismatch"
    REPO_STATE_MISMATCH = "repo_state_mismatch"
    BRANCH_PATTERN_INVALID = "branch_pattern_invalid"
    BRANCH_OVERWRITE_DENIED = "branch_overwrite_denied"
    MERGE_DENIED_P0 = "merge_denied_p0"
    DEPLOY_DENIED_P0 = "deploy_denied_p0"
    INSTALLATION_TOKEN_LEAK = "installation_token_leak"  # noqa: S105


@dataclass(frozen=True, slots=True)
class DraftPRBinding:
    """Caller-visible binding for Draft PR creation.

    The caller supplies IDs only. RepoProxy resolves the actual repo, branch,
    hash, and policy fields from server-owned state.
    """

    tenant_id: int
    approval_id: UUID
    agent_run_id: UUID


@dataclass(frozen=True, slots=True)
class DraftPRApprovalState:
    """Minimal ApprovalRequest projection used by the binding resolver."""

    id: UUID
    run_id: UUID | None
    status: str
    action_class: str
    resource_ref: str
    diff_hash: str | None
    policy_version: str
    provider_request_fingerprint: str | None


@dataclass(frozen=True, slots=True)
class DraftPRSnapshotState:
    """Minimal ContextSnapshot projection used by the binding resolver."""

    run_id: UUID
    policy_version: str
    repo_state: Mapping[str, object]
    provider_request_fingerprint: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class DraftPRRequest:
    """Internal server-resolved Draft PR creation request."""

    repo_full_name: str
    base_branch: str
    head_branch: str  # must match ^codex/agent-run-[a-f0-9]{8}$
    commit_sha: str
    artifact_hash: str  # sha256 of generated patch/diff
    policy_version: str
    provider_request_fingerprint: str
    repo_state_commit_sha: str  # current HEAD at push time
    approval_id: str  # ApprovalRequest.id (decision=approved)


@dataclass(frozen=True, slots=True)
class DraftPRResult:
    pr_number: int | None
    pr_url: str | None  # redacted to https://github.com/owner/repo/pull/N (no token)
    draft: bool
    deny_reason: RepoProxyDenyReason | None
    repo_full_name: str | None = None
    branch: str | None = None
    head_sha: str | None = None


_BRANCH_PATTERN = re.compile(r"^codex/agent-run-[a-f0-9]{8}$")
_REPO_PR_REF_RE = re.compile(
    r"^repo:(?P<repo>[^:]+/[^:]+):pr:(?P<base>[^:]+):(?P<head>[^:]+):"
    r"draft:commit:(?P<commit>[a-f0-9]{40}):state:(?P<state>[a-f0-9]{40})$"
)


class DraftPRRequestResolver(Protocol):
    """Resolve caller-visible IDs into an internal DraftPRRequest."""

    async def resolve_draft_pr_request(
        self,
        binding: DraftPRBinding,
    ) -> DraftPRRequest | RepoProxyDenyReason: ...


class RepoProxy(ABC):
    """Abstract RepoProxy interface. Mock / GitHubApp / Remote 実装を持つ。"""

    @abstractmethod
    async def create_draft_pr(self, binding: DraftPRBinding) -> DraftPRResult:
        """Create Draft PR via GitHub App. Returns DraftPRResult with pr_number
        on success or deny_reason on policy / approval / hash mismatch."""

    @abstractmethod
    async def deny_merge(self, repo_full_name: str, pr_number: int) -> DraftPRResult:
        """P0 merge denial. Always returns DENIED."""

    @abstractmethod
    async def deny_deploy(
        self, repo_full_name: str, environment: str
    ) -> DraftPRResult:
        """P0 deploy denial. Always returns DENIED."""


def validate_draft_pr_request(
    request: DraftPRRequest,
) -> RepoProxyDenyReason | None:
    """Pre-check: validate request fields before broker-mediated httpx call."""
    if not _BRANCH_PATTERN.match(request.head_branch):
        return RepoProxyDenyReason.BRANCH_PATTERN_INVALID
    return None


def build_draft_pr_request_from_server_state(
    *,
    approval: DraftPRApprovalState,
    snapshot: DraftPRSnapshotState,
) -> DraftPRRequest | RepoProxyDenyReason:
    """Build an internal DraftPRRequest from server-owned state only."""
    if approval.status != "approved":
        return RepoProxyDenyReason.APPROVAL_NOT_GRANTED
    if approval.action_class != "pr_open":
        return RepoProxyDenyReason.APPROVAL_NOT_GRANTED
    if approval.run_id != snapshot.run_id:
        return RepoProxyDenyReason.REPO_STATE_MISMATCH
    if approval.policy_version != snapshot.policy_version:
        return RepoProxyDenyReason.POLICY_VERSION_MISMATCH

    diff_hash = _sha256_or_none(approval.diff_hash)
    snapshot_diff_hash = _sha256_or_none(_string_value(snapshot.repo_state, "diff_hash"))
    if diff_hash is None or snapshot_diff_hash is None or diff_hash != snapshot_diff_hash:
        return RepoProxyDenyReason.ARTIFACT_HASH_MISMATCH

    provider_fingerprint = _sha256_or_none(approval.provider_request_fingerprint)
    snapshot_provider_fingerprint = _provider_request_fingerprint_hash(
        snapshot.provider_request_fingerprint
    )
    if (
        provider_fingerprint is None
        or snapshot_provider_fingerprint is None
        or provider_fingerprint != snapshot_provider_fingerprint
    ):
        return RepoProxyDenyReason.PROVIDER_FINGERPRINT_MISMATCH

    parsed_ref = _parse_repo_pr_resource_ref(approval.resource_ref)
    if parsed_ref is None:
        return RepoProxyDenyReason.REPO_STATE_MISMATCH

    repo_commit_sha = _git_sha_or_none(_string_value(snapshot.repo_state, "commit_sha"))
    repo_branch = _string_value(snapshot.repo_state, "branch")
    if (
        repo_commit_sha is None
        or parsed_ref["repo_state_commit_sha"] != repo_commit_sha
        or parsed_ref["base_branch"] != repo_branch
        or snapshot.repo_state.get("dirty") is not False
    ):
        return RepoProxyDenyReason.REPO_STATE_MISMATCH

    request = DraftPRRequest(
        repo_full_name=parsed_ref["repo_full_name"],
        base_branch=parsed_ref["base_branch"],
        head_branch=parsed_ref["head_branch"],
        commit_sha=parsed_ref["commit_sha"],
        artifact_hash=diff_hash,
        policy_version=approval.policy_version,
        provider_request_fingerprint=provider_fingerprint,
        repo_state_commit_sha=parsed_ref["repo_state_commit_sha"],
        approval_id=str(approval.id),
    )
    return validate_draft_pr_request(request) or request


class MockRepoProxy(RepoProxy):
    """In-memory mock RepoProxy. test / dev 用、実 GitHub API は使わない."""

    def __init__(self, resolver: DraftPRRequestResolver | None = None) -> None:
        self._resolver = resolver
        self._next_pr_number = 1
        self._known_branches: dict[str, set[str]] = {}

    async def create_draft_pr(self, binding: DraftPRBinding) -> DraftPRResult:
        if self._resolver is None:
            return DraftPRResult(
                pr_number=None,
                pr_url=None,
                draft=False,
                deny_reason=RepoProxyDenyReason.APPROVAL_NOT_GRANTED,
            )
        resolved = await self._resolver.resolve_draft_pr_request(binding)
        if isinstance(resolved, RepoProxyDenyReason):
            return DraftPRResult(
                pr_number=None,
                pr_url=None,
                draft=False,
                deny_reason=resolved,
            )
        request = resolved

        validation_error = validate_draft_pr_request(request)
        if validation_error is not None:
            return DraftPRResult(
                pr_number=None,
                pr_url=None,
                draft=False,
                deny_reason=validation_error,
            )

        branches = self._known_branches.setdefault(request.repo_full_name, set())
        if request.head_branch in branches:
            return DraftPRResult(
                pr_number=None,
                pr_url=None,
                draft=False,
                deny_reason=RepoProxyDenyReason.BRANCH_OVERWRITE_DENIED,
            )
        branches.add(request.head_branch)

        pr_number = self._next_pr_number
        self._next_pr_number += 1
        return DraftPRResult(
            pr_number=pr_number,
            pr_url=f"https://github.com/{request.repo_full_name}/pull/{pr_number}",
            draft=True,
            deny_reason=None,
            repo_full_name=request.repo_full_name,
            branch=request.head_branch,
            head_sha=request.commit_sha,
        )

    async def deny_merge(
        self, repo_full_name: str, pr_number: int
    ) -> DraftPRResult:
        return DraftPRResult(
            pr_number=pr_number,
            pr_url=None,
            draft=True,
            deny_reason=RepoProxyDenyReason.MERGE_DENIED_P0,
        )

    async def deny_deploy(
        self, repo_full_name: str, environment: str
    ) -> DraftPRResult:
        return DraftPRResult(
            pr_number=None,
            pr_url=None,
            draft=False,
            deny_reason=RepoProxyDenyReason.DEPLOY_DENIED_P0,
        )


class StaticDraftPRRequestResolver:
    """Test/dev resolver for already server-resolved DraftPRRequest rows."""

    def __init__(
        self,
        requests: Mapping[tuple[int, UUID, UUID], DraftPRRequest | RepoProxyDenyReason],
    ) -> None:
        self._requests = dict(requests)

    async def resolve_draft_pr_request(
        self,
        binding: DraftPRBinding,
    ) -> DraftPRRequest | RepoProxyDenyReason:
        return self._requests.get(
            (binding.tenant_id, binding.approval_id, binding.agent_run_id),
            RepoProxyDenyReason.APPROVAL_NOT_GRANTED,
        )


def _parse_repo_pr_resource_ref(resource_ref: str) -> dict[str, str] | None:
    match = _REPO_PR_REF_RE.fullmatch(resource_ref)
    if match is None:
        return None
    return {
        "repo_full_name": match.group("repo"),
        "base_branch": match.group("base"),
        "head_branch": match.group("head"),
        "commit_sha": match.group("commit"),
        "repo_state_commit_sha": match.group("state"),
    }


def _provider_request_fingerprint_hash(
    provider_request_fingerprint: Mapping[str, object],
) -> str | None:
    if not provider_request_fingerprint:
        return None
    canonical_json = canonical_json_dumps(provider_request_fingerprint)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _string_value(mapping: Mapping[str, object], key: str) -> str | None:
    value = mapping.get(key)
    return value if isinstance(value, str) else None


def _sha256_or_none(value: str | None) -> str | None:
    if value is None or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        return None
    return value


def _git_sha_or_none(value: str | None) -> str | None:
    if value is None or re.fullmatch(r"[a-f0-9]{40}", value) is None:
        return None
    return value


__all__ = [
    "DraftPRApprovalState",
    "DraftPRBinding",
    "DraftPRRequest",
    "DraftPRRequestResolver",
    "DraftPRResult",
    "DraftPRSnapshotState",
    "MockRepoProxy",
    "RepoProxy",
    "RepoProxyDenyReason",
    "StaticDraftPRRequestResolver",
    "build_draft_pr_request_from_server_state",
    "validate_draft_pr_request",
]
