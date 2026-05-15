"""Codex PR #1 R1 P2 backend improvements follow-up verify tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.services.repoproxy.permission_matrix import (
    GitHubAppPermissionMatrix,
    check_no_dangerous_permissions,
)
from backend.app.services.runner.mutation_gateway import (
    PatchApplyRequest,
    _validate_allowlist,
)
from backend.app.services.runner.network_egress import (
    EgressDenyReason,
    NetworkPolicy,
    check_egress_allowed,
)


def _make_patch_request(
    *,
    target_paths: tuple[str, ...],
    workspace_root: str,
    artifact_outbox: str,
    temp_root: str,
) -> PatchApplyRequest:
    h64 = "0" * 64
    return PatchApplyRequest(
        artifact_hash=h64,
        policy_version="v1",
        provider_request_fingerprint=h64,
        repo_state_commit_sha="a" * 40,
        expected_artifact_hash=h64,
        expected_policy_version="v1",
        expected_provider_fingerprint=h64,
        expected_repo_state="a" * 40,
        policy_pass=True,
        approval_pass=True,
        target_paths=target_paths,
        argv_plan=(("patch", "-p1"),),
        workspace_root=workspace_root,
        artifact_outbox=artifact_outbox,
        temp_root=temp_root,
    )


class TestMutationGatewayWorkspaceRootResolution:
    """F-PR1-003 P2 adopt: relative target_paths を workspace_root で resolve."""

    def test_relative_path_resolved_against_workspace_root(
        self, tmp_path: Path
    ) -> None:
        workspace = tmp_path / "runner-ws"
        workspace.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()
        temp = tmp_path / "temp"
        temp.mkdir()
        (workspace / "backend").mkdir()
        (workspace / "backend" / "foo.py").write_text("x = 1")

        request = _make_patch_request(
            target_paths=("backend/foo.py",),
            workspace_root=str(workspace),
            artifact_outbox=str(outbox),
            temp_root=str(temp),
        )
        violations = _validate_allowlist(request)
        assert violations == (), (
            f"relative path under workspace_root should be allowed, got: {violations}"
        )

    def test_absolute_path_outside_workspace_violates(
        self, tmp_path: Path
    ) -> None:
        workspace = tmp_path / "runner-ws"
        workspace.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()
        temp = tmp_path / "temp"
        temp.mkdir()
        request = _make_patch_request(
            target_paths=("/etc/passwd",),
            workspace_root=str(workspace),
            artifact_outbox=str(outbox),
            temp_root=str(temp),
        )
        violations = _validate_allowlist(request)
        assert "/etc/passwd" in violations


class TestPermissionMatrixIssuesChecksDeny:
    """F-PR1-004 P2 adopt: issues / checks も must_deny."""

    def _make_matrix(
        self,
        *,
        repository_permissions: dict[str, str] | None = None,
        deny_explicit: dict[str, str] | None = None,
    ) -> GitHubAppPermissionMatrix:
        full_deny = {
            "actions": "deny",
            "workflows": "deny",
            "packages": "deny",
            "administration": "deny",
            "issues": "deny",
            "checks": "deny",
        }
        explicit = deny_explicit if deny_explicit is not None else full_deny
        return GitHubAppPermissionMatrix(
            dataset_version="test",
            repository_permissions=repository_permissions or {},
            repository_deny_explicit=explicit,
            organization_permissions={},
            account_permissions={},
            webhooks={},
            deny_actions={},
            branch_naming={},
            raw={},
        )

    def test_issues_in_repository_permissions_is_violation(self) -> None:
        matrix = self._make_matrix(repository_permissions={"issues": "read"})
        violations = check_no_dangerous_permissions(matrix)
        assert any("issues" in v for v in violations)

    def test_checks_in_repository_permissions_is_violation(self) -> None:
        matrix = self._make_matrix(repository_permissions={"checks": "write"})
        violations = check_no_dangerous_permissions(matrix)
        assert any("checks" in v for v in violations)

    def test_missing_issues_explicit_deny_is_violation(self) -> None:
        matrix = self._make_matrix(
            deny_explicit={
                "actions": "deny",
                "workflows": "deny",
                "packages": "deny",
                "administration": "deny",
            }
        )
        violations = check_no_dangerous_permissions(matrix)
        assert any("issues" in v for v in violations)
        assert any("checks" in v for v in violations)


class TestNetworkEgressLocalhostDeny:
    """F-PR1-006 P2 adopt: localhost hostname を allowlist より前に deny."""

    @pytest.mark.parametrize(
        "host_url",
        [
            "http://localhost",
            "http://localhost:80",
            "http://Localhost/",
            "http://localhost.localdomain/",
            "http://ip6-localhost/",
        ],
    )
    def test_localhost_denied_in_allowlist_mode(self, host_url: str) -> None:
        policy = NetworkPolicy.allowlist(
            hosts=frozenset({"localhost", "api.example.com"}),
            ports=frozenset({80, 443}),
        )
        result = check_egress_allowed(host_url, policy)
        assert result is not None, f"localhost variant must be denied: {host_url}"
        assert result.reason == EgressDenyReason.LOOPBACK_DENIED

    def test_non_localhost_hostname_still_allowed(self) -> None:
        policy = NetworkPolicy.allowlist(
            hosts=frozenset({"api.openai.com"}),
            ports=frozenset({443}),
        )
        result = check_egress_allowed("https://api.openai.com/v1/models", policy)
        assert result is None, f"api.openai.com should be allowed, got {result}"
