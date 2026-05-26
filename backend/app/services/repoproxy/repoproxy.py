"""Sprint 8 BL-0096: RepoProxy service module (skeleton + 4 整合 PENDING).

ADR-00011 §採用案: AgentRun 生成 patch を runner_mutation_gateway →
RepoProxy 経由でのみ branch push + Draft PR 作成できる回路。

**PENDING SPRINT 11** (Codex audit F-002 adopt、2026-05-13):
- 現在の ``MockRepoProxy.create_draft_pr`` は ``DraftPRRequest`` を直接受け取り、
  branch pattern + overwrite 以外は検証しない。``server-owned-boundary §3``
  4 整合 binding (artifact_hash / policy_version / provider_request_fingerprint
  / repo_state_commit_sha) の **server-side 再計算 + ApprovalRequest 照合** は
  Sprint 11 で `GitHubAppRepoProxy` 実装と一緒に追加する。
- Sprint 11 で signature は ``create_draft_pr(approval_id, agent_run_id)`` に
  refactor し、RepoProxy 内で DB / ContextSnapshot / Git ref から 4 hash を
  再計算する設計。Mock もこの service-level validator を通すよう更新予定。
- Sprint 11 で `OperationContext` の `repo.pr_open` target に
  `commit_sha` / `repo_state_commit_sha` を追加 (現状 base/head_branch のみ)。

実 GitHub API integration は ``GitHubAppAdapter`` (Sprint 11 で実装) で行う。

server-owned-boundary §1 (現状の caller-supplied リスク):
- 現状 ``DraftPRRequest`` の 9 field を caller (orchestrator) が直接渡せる。
  「server-resolved」とコメントしているが physical delete はまだ。
- Sprint 11 で signature レベル削除 + service-internal computation で完成予定。
- installation_token は SecretBroker 内でのみ resolve (Sprint 11)
- raw token は caller / AI / runner / artifact / log / audit に渡さない
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID


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
class DraftPRRequest:
    """Server-owned Draft PR creation request.

    All fields are server-resolved from AgentRun + Approval flow, NOT
    caller-supplied (server-owned-boundary §1).
    """

    repo_full_name: str
    base_branch: str
    head_branch: str  # must match ^codex/agent-run-[a-f0-9]{8}$
    commit_sha: str
    artifact_hash: str  # sha256 of generated patch
    policy_version: str
    provider_request_fingerprint: str
    repo_state_commit_sha: str  # current HEAD at push time
    approval_id: str  # ApprovalRequest.id (decision=approved)


@dataclass(frozen=True, slots=True)
class DraftPRResult:
    pr_number: int | None
    pr_url: str | None
    draft: bool
    deny_reason: RepoProxyDenyReason | None
    repo_full_name: str | None = None
    branch: str | None = None
    head_sha: str | None = None


_BRANCH_PATTERN = re.compile(r"^codex/agent-run-[a-f0-9]{8}$")


class RepoProxy(ABC):
    """Abstract RepoProxy interface. Mock / GitHubApp / Remote 実装を持つ。"""

    @abstractmethod
    async def create_draft_pr(self, request: DraftPRRequest | DraftPRBinding) -> DraftPRResult:
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
    # Other validations (approval_id, hash binding) happen at broker layer
    return None


class StaticDraftPRRequestResolver:
    """Test helper: maps (tenant_id, approval_id, run_id) to a pre-built DraftPRRequest."""

    def __init__(self, mapping: dict[tuple[int, str, str], DraftPRRequest]) -> None:
        self._mapping = mapping

    def resolve(self, tenant_id: int, approval_id: str, run_id: str) -> DraftPRRequest | None:
        return self._mapping.get((tenant_id, approval_id, run_id))


class MockRepoProxy(RepoProxy):
    """In-memory mock RepoProxy. test / dev 用、実 GitHub API は使わない。

    Sprint 11 で `GitHubAppRepoProxy` (httpx + SecretBroker broker-mediated)
    に置換。本 mock は Sprint 8 batch 5 で AgentRunEvent integration 開発時の
    test 用 + Sprint 9 UI 開発時の development stub。
    """

    def __init__(self, *, resolver: StaticDraftPRRequestResolver | None = None) -> None:
        self._next_pr_number = 1
        self._known_branches: dict[str, set[str]] = {}
        self._resolver = resolver

    async def create_draft_pr(self, request: DraftPRRequest | DraftPRBinding) -> DraftPRResult:
        # branch pattern validation
        validation_error = validate_draft_pr_request(request)  # type: ignore[arg-type]
        if validation_error is not None:
            return DraftPRResult(
                pr_number=None,
                pr_url=None,
                draft=False,
                deny_reason=validation_error,
            )

        # branch overwrite deny
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


@dataclass(frozen=True, slots=True)
class DraftPRBinding:
    tenant_id: int
    agent_run_id: str
    repo_full_name: str
    base_branch: str
    head_branch: str
    draft: bool
    approval_id: str | None = None


@dataclass(frozen=True, slots=True)
class DraftPRApprovalState:
    id: UUID | str | None = None
    run_id: UUID | str | None = None
    status: str | None = None
    action_class: str | None = None
    resource_ref: str | None = None
    approval_id: str | None = None
    artifact_hash: str | None = None
    diff_hash: str | None = None
    policy_version: str | None = None
    provider_request_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class DraftPRSnapshotState:
    repo_state_commit_sha: str | None = None
    diff_hash: str | None = None
    run_id: UUID | str | None = None
    policy_version: str | None = None
    repo_state: dict[str, Any] | None = None
    provider_request_fingerprint: str | dict[str, Any] | None = None


def build_draft_pr_request_from_server_state(
    *,
    approval: DraftPRApprovalState,
    snapshot: DraftPRSnapshotState,
) -> DraftPRRequest | RepoProxyDenyReason:
    return DraftPRRequest(
        repo_full_name="",
        base_branch="main",
        head_branch="",
        commit_sha="",
        artifact_hash=approval.artifact_hash or "",
        policy_version=approval.policy_version or "",
        provider_request_fingerprint=approval.provider_request_fingerprint or "",
        repo_state_commit_sha=snapshot.repo_state_commit_sha or "",
        approval_id=str(approval.approval_id or approval.id or ""),
    )


__all__ = [
    "DraftPRApprovalState",
    "DraftPRBinding",
    "DraftPRRequest",
    "DraftPRResult",
    "DraftPRSnapshotState",
    "MockRepoProxy",
    "RepoProxy",
    "StaticDraftPRRequestResolver",
    "RepoProxyDenyReason",
    "build_draft_pr_request_from_server_state",
    "validate_draft_pr_request",
]
