"""SP-008 Batch A: server-owned RepoProxy binding tests."""

from __future__ import annotations

import hashlib
import inspect
from dataclasses import replace
from uuid import UUID

import pytest

from backend.app.domain.agent_runtime.operation_context import canonical_json_dumps
from backend.app.services.repoproxy.repoproxy import (
    DraftPRApprovalState,
    DraftPRBinding,
    DraftPRRequest,
    DraftPRSnapshotState,
    MockRepoProxy,
    RepoProxy,
    RepoProxyDenyReason,
    build_draft_pr_request_from_server_state,
)

APPROVAL_ID = UUID("00000000-0000-4000-8000-00000000a001")
RUN_ID = UUID("00000000-0000-4000-8000-00000000a002")
DIFF_HASH = "a" * 64
POLICY_VERSION = "policy-v1"
PROVIDER_PAYLOAD = {
    "model_resolved": "gpt-5.4",
    "api_version": "responses-v1",
    "sdk_version": "sdk-v1",
    "request_payload_hash": "b" * 64,
    "provider_compliance_matrix_version": "pcm-v1",
}
PROVIDER_FINGERPRINT = hashlib.sha256(
    canonical_json_dumps(PROVIDER_PAYLOAD).encode("utf-8")
).hexdigest()
BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40
RESOURCE_REF = (
    "repo:owner/repo:pr:main:codex/agent-run-abcd1234:"
    f"draft:commit:{HEAD_SHA}:state:{BASE_SHA}"
)


def _approval(**overrides: object) -> DraftPRApprovalState:
    values = {
        "id": APPROVAL_ID,
        "run_id": RUN_ID,
        "status": "approved",
        "action_class": "pr_open",
        "resource_ref": RESOURCE_REF,
        "diff_hash": DIFF_HASH,
        "policy_version": POLICY_VERSION,
        "provider_request_fingerprint": PROVIDER_FINGERPRINT,
    }
    values.update(overrides)
    return DraftPRApprovalState(**values)  # type: ignore[arg-type]


def _snapshot(**overrides: object) -> DraftPRSnapshotState:
    values = {
        "run_id": RUN_ID,
        "policy_version": POLICY_VERSION,
        "repo_state": {
            "commit_sha": BASE_SHA,
            "branch": "main",
            "dirty": False,
            "diff_hash": DIFF_HASH,
        },
        "provider_request_fingerprint": PROVIDER_PAYLOAD,
    }
    values.update(overrides)
    return DraftPRSnapshotState(**values)  # type: ignore[arg-type]


def test_repo_proxy_public_create_signature() -> None:
    params = inspect.signature(RepoProxy.create_draft_pr).parameters

    assert tuple(params) == ("self", "request")


def test_mock_repo_proxy_public_create_signature() -> None:
    params = inspect.signature(MockRepoProxy.create_draft_pr).parameters

    assert tuple(params) == ("self", "request")


def test_build_draft_pr_request_from_server_state() -> None:
    result = build_draft_pr_request_from_server_state(
        approval=_approval(),
        snapshot=_snapshot(),
    )

    assert isinstance(result, DraftPRRequest)
    assert result.base_branch == "main"
    assert result.policy_version == POLICY_VERSION
    assert result.approval_id == str(APPROVAL_ID)


def test_rejects_non_approved_approval() -> None:
    result = build_draft_pr_request_from_server_state(
        approval=_approval(status="pending"),
        snapshot=_snapshot(),
    )

    assert result == RepoProxyDenyReason.APPROVAL_NOT_GRANTED


def test_rejects_wrong_action_class() -> None:
    result = build_draft_pr_request_from_server_state(
        approval=_approval(action_class="repo_write"),
        snapshot=_snapshot(),
    )

    assert result == RepoProxyDenyReason.APPROVAL_NOT_GRANTED


def test_rejects_run_mismatch() -> None:
    result = build_draft_pr_request_from_server_state(
        approval=_approval(run_id=UUID("00000000-0000-4000-8000-00000000ffff")),
        snapshot=_snapshot(),
    )

    assert result == RepoProxyDenyReason.REPO_STATE_MISMATCH


def test_rejects_policy_version_mismatch() -> None:
    result = build_draft_pr_request_from_server_state(
        approval=_approval(policy_version="policy-v2"),
        snapshot=_snapshot(),
    )

    assert result == RepoProxyDenyReason.POLICY_VERSION_MISMATCH


def test_rejects_diff_hash_mismatch() -> None:
    snapshot = _snapshot()
    result = build_draft_pr_request_from_server_state(
        approval=_approval(),
        snapshot=replace(
            snapshot,
            repo_state={**snapshot.repo_state, "diff_hash": "c" * 64},
        ),
    )

    assert result == RepoProxyDenyReason.ARTIFACT_HASH_MISMATCH


def test_rejects_provider_fingerprint_mismatch() -> None:
    result = build_draft_pr_request_from_server_state(
        approval=_approval(provider_request_fingerprint="d" * 64),
        snapshot=_snapshot(),
    )

    assert result == RepoProxyDenyReason.PROVIDER_FINGERPRINT_MISMATCH


def test_rejects_repo_state_mismatch() -> None:
    snapshot = _snapshot()
    result = build_draft_pr_request_from_server_state(
        approval=_approval(),
        snapshot=replace(
            snapshot,
            repo_state={**snapshot.repo_state, "commit_sha": "3" * 40},
        ),
    )

    assert result == RepoProxyDenyReason.REPO_STATE_MISMATCH


def test_rejects_dirty_repo_state() -> None:
    snapshot = _snapshot()
    result = build_draft_pr_request_from_server_state(
        approval=_approval(),
        snapshot=replace(
            snapshot,
            repo_state={**snapshot.repo_state, "dirty": True},
        ),
    )

    assert result == RepoProxyDenyReason.REPO_STATE_MISMATCH


def test_rejects_invalid_head_branch_from_resource_ref() -> None:
    resource_ref = (
        "repo:owner/repo:pr:main:feature/not-agent-run:"
        f"draft:commit:{HEAD_SHA}:state:{BASE_SHA}"
    )
    result = build_draft_pr_request_from_server_state(
        approval=_approval(resource_ref=resource_ref),
        snapshot=_snapshot(),
    )

    assert result == RepoProxyDenyReason.BRANCH_PATTERN_INVALID


def test_binding_contains_expected_fields() -> None:
    binding_fields = set(DraftPRBinding.__dataclass_fields__)

    expected = {
        "tenant_id",
        "agent_run_id",
        "repo_full_name",
        "base_branch",
        "head_branch",
        "draft",
        "approval_id",
    }
    assert binding_fields == expected
    assert "artifact_hash" not in binding_fields
    assert "provider_request_fingerprint" not in binding_fields
