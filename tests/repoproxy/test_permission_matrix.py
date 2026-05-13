"""Sprint 8 BL-0098: GitHub App Permission Matrix tests (ADR-00011)."""

from __future__ import annotations

from backend.app.services.repoproxy.permission_matrix import (
    GitHubAppPermissionMatrix,
    check_no_dangerous_permissions,
    load_permission_matrix,
)


def test_load_permission_matrix() -> None:
    """`config/github_app_permissions.toml` が読める。"""
    matrix = load_permission_matrix()
    assert matrix.dataset_version.startswith("v2026.")


def test_minimum_permissions_only() -> None:
    """ADR-00011 §採用案: contents:write + pull_requests:write + metadata:read のみ。"""
    matrix = load_permission_matrix()
    assert matrix.repository_permissions == {
        "contents": "write",
        "pull_requests": "write",
        "metadata": "read",
    }


def test_dangerous_permissions_explicitly_denied() -> None:
    """actions / workflows / packages / administration が明示 deny される。"""
    matrix = load_permission_matrix()
    for perm in ("actions", "workflows", "packages", "administration", "issues", "checks"):
        assert (
            matrix.repository_deny_explicit.get(perm) == "deny"
        ), f"{perm} must be deny, got {matrix.repository_deny_explicit.get(perm)!r}"


def test_organization_permissions_empty() -> None:
    """P0 personal 用途のため organization permission は不要。"""
    matrix = load_permission_matrix()
    assert matrix.organization_permissions == {}


def test_account_email_denied() -> None:
    """PII (email) は deny。"""
    matrix = load_permission_matrix()
    assert matrix.account_permissions.get("email_addresses") == "deny"


def test_webhook_hmac_config() -> None:
    """Webhook HMAC SHA-256 + secret_ref + replay 1 hour window."""
    matrix = load_permission_matrix()
    assert matrix.webhooks["hmac_algorithm"] == "sha256"
    assert matrix.webhooks["hmac_header"] == "X-Hub-Signature-256"
    assert "secret://" in matrix.webhooks["secret_ref"]
    assert matrix.webhooks["replay_window_seconds"] == 3600


def test_merge_deploy_p0_deny() -> None:
    """merge / deploy が P0 期間中 deny される。"""
    matrix = load_permission_matrix()
    assert matrix.deny_actions["merge"] == "p0_deny"
    assert matrix.deny_actions["deploy"] == "p0_deny"


def test_branch_naming_codex_agent_run_only() -> None:
    """`codex/agent-run-{8-char-hex}` only + no overwrite。"""
    matrix = load_permission_matrix()
    assert matrix.branch_naming["pattern"] == "^codex/agent-run-[a-f0-9]{8}$"
    assert matrix.branch_naming["overwrite_allowed"] is False


def test_check_no_dangerous_permissions_passes() -> None:
    """current Matrix が ADR-00011 §採用案 と整合する。"""
    matrix = load_permission_matrix()
    violations = check_no_dangerous_permissions(matrix)
    assert violations == (), f"unexpected violations: {violations}"


def test_check_detects_actions_enabled() -> None:
    """Matrix が actions=write を enabled にすると violation 検出。"""
    matrix = GitHubAppPermissionMatrix(
        dataset_version="v0",
        repository_permissions={"actions": "write", "contents": "write"},
        repository_deny_explicit={
            "workflows": "deny",
            "packages": "deny",
            "administration": "deny",
        },
        deny_actions={"merge": "p0_deny", "deploy": "p0_deny"},
    )
    violations = check_no_dangerous_permissions(matrix)
    assert any("actions" in v for v in violations)


def test_check_detects_missing_deny_explicit() -> None:
    """deny_explicit から workflows が抜けると violation。"""
    matrix = GitHubAppPermissionMatrix(
        dataset_version="v0",
        repository_permissions={"contents": "write"},
        repository_deny_explicit={
            "actions": "deny",
            "packages": "deny",
            "administration": "deny",
            # workflows missing
        },
        deny_actions={"merge": "p0_deny", "deploy": "p0_deny"},
    )
    violations = check_no_dangerous_permissions(matrix)
    assert any("workflows" in v for v in violations)


def test_check_detects_merge_not_denied() -> None:
    """merge が p0_deny でないと violation。"""
    matrix = GitHubAppPermissionMatrix(
        dataset_version="v0",
        repository_permissions={"contents": "write"},
        repository_deny_explicit={
            "actions": "deny",
            "workflows": "deny",
            "packages": "deny",
            "administration": "deny",
        },
        deny_actions={"merge": "allow", "deploy": "p0_deny"},  # merge allowed
    )
    violations = check_no_dangerous_permissions(matrix)
    assert any("merge" in v for v in violations)
