"""Sprint 8 BL-0096: MockRepoProxy tests + merge/deploy P0 deny."""

from __future__ import annotations

import pytest

from backend.app.services.repoproxy.repoproxy import (
    DraftPRRequest,
    MockRepoProxy,
    RepoProxyDenyReason,
    validate_draft_pr_request,
)

_VALID_REQUEST_KWARGS: dict[str, str] = {
    "repo_full_name": "owner/repo",
    "base_branch": "main",
    "head_branch": "codex/agent-run-abcd1234",
    "commit_sha": "0" * 40,
    "artifact_hash": "f" * 64,
    "policy_version": "v2026.05.13",
    "provider_request_fingerprint": "e" * 64,
    "repo_state_commit_sha": "1" * 40,
    "approval_id": "00000000-0000-4000-8000-000000000001",
}


def _make_request(**overrides: str) -> DraftPRRequest:
    kwargs = dict(_VALID_REQUEST_KWARGS)
    kwargs.update(overrides)
    return DraftPRRequest(**kwargs)  # type: ignore[arg-type]


def test_validate_accepts_valid_branch() -> None:
    request = _make_request()
    assert validate_draft_pr_request(request) is None


def test_validate_rejects_non_codex_branch() -> None:
    request = _make_request(head_branch="main")
    assert (
        validate_draft_pr_request(request) == RepoProxyDenyReason.BRANCH_PATTERN_INVALID
    )


def test_validate_rejects_branch_with_wrong_prefix() -> None:
    request = _make_request(head_branch="feature/abcd1234")
    assert (
        validate_draft_pr_request(request) == RepoProxyDenyReason.BRANCH_PATTERN_INVALID
    )


def test_validate_rejects_non_hex_suffix() -> None:
    request = _make_request(head_branch="codex/agent-run-XXXXXXXX")
    assert (
        validate_draft_pr_request(request) == RepoProxyDenyReason.BRANCH_PATTERN_INVALID
    )


def test_validate_rejects_short_suffix() -> None:
    """8-char hex required."""
    request = _make_request(head_branch="codex/agent-run-abc")
    assert (
        validate_draft_pr_request(request) == RepoProxyDenyReason.BRANCH_PATTERN_INVALID
    )


@pytest.mark.asyncio
async def test_mock_create_draft_pr_success() -> None:
    proxy = MockRepoProxy()
    result = await proxy.create_draft_pr(_make_request())
    assert result.pr_number == 1
    assert result.draft is True
    assert result.deny_reason is None
    assert result.pr_url == "https://github.com/owner/repo/pull/1"


@pytest.mark.asyncio
async def test_mock_branch_overwrite_denied() -> None:
    """Same head_branch second push → BRANCH_OVERWRITE_DENIED."""
    proxy = MockRepoProxy()
    first = await proxy.create_draft_pr(_make_request())
    assert first.pr_number == 1
    second = await proxy.create_draft_pr(_make_request())
    assert second.pr_number is None
    assert second.deny_reason == RepoProxyDenyReason.BRANCH_OVERWRITE_DENIED


@pytest.mark.asyncio
async def test_mock_invalid_branch_denied() -> None:
    proxy = MockRepoProxy()
    result = await proxy.create_draft_pr(_make_request(head_branch="main"))
    assert result.pr_number is None
    assert result.deny_reason == RepoProxyDenyReason.BRANCH_PATTERN_INVALID


@pytest.mark.asyncio
async def test_mock_merge_always_denied_p0() -> None:
    """ADR-00011 §採用案: P0 merge は always deny。"""
    proxy = MockRepoProxy()
    result = await proxy.deny_merge("owner/repo", pr_number=42)
    assert result.deny_reason == RepoProxyDenyReason.MERGE_DENIED_P0


@pytest.mark.asyncio
async def test_mock_deploy_always_denied_p0() -> None:
    """ADR-00011 §採用案: P0 deploy は always deny。"""
    proxy = MockRepoProxy()
    result = await proxy.deny_deploy("owner/repo", environment="production")
    assert result.deny_reason == RepoProxyDenyReason.DEPLOY_DENIED_P0


@pytest.mark.asyncio
async def test_mock_distinct_branches_get_distinct_pr_numbers() -> None:
    """異 head_branch は新 PR number を発行。"""
    proxy = MockRepoProxy()
    r1 = await proxy.create_draft_pr(_make_request(head_branch="codex/agent-run-aaaaaaaa"))
    r2 = await proxy.create_draft_pr(_make_request(head_branch="codex/agent-run-bbbbbbbb"))
    assert r1.pr_number == 1
    assert r2.pr_number == 2


@pytest.mark.asyncio
async def test_repoproxy_deny_reason_enum_5plus_source() -> None:
    """RepoProxyDenyReason 全 10 enum 値の完全性。"""
    expected = {
        "approval_not_granted",
        "artifact_hash_mismatch",
        "policy_version_mismatch",
        "provider_fingerprint_mismatch",
        "repo_state_mismatch",
        "branch_pattern_invalid",
        "branch_overwrite_denied",
        "merge_denied_p0",
        "deploy_denied_p0",
        "installation_token_leak",
    }
    actual = {r.value for r in RepoProxyDenyReason}
    assert actual == expected
