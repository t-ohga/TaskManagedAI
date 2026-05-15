"""Sprint 8 BL-0098: GitHub App Permission Matrix tests (ADR-00011)."""

from __future__ import annotations

import pytest

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


def test_diff_against_current_clean() -> None:
    """Codex SP8 R1 F-SP8-005 adopt: current=matrix と一致なら drift なし。"""
    from backend.app.services.repoproxy.permission_matrix import _diff_against_current

    matrix = load_permission_matrix()
    current = {
        "permissions": {
            "contents": "write",
            "pull_requests": "write",
            "metadata": "read",
        }
    }
    assert _diff_against_current(matrix, current) == ()


def test_diff_against_current_detects_drift() -> None:
    """Matrix と current が drift していると violation 検出。"""
    from backend.app.services.repoproxy.permission_matrix import _diff_against_current

    matrix = load_permission_matrix()
    # contents が read になっている (matrix=write と drift)
    drifted = {
        "permissions": {
            "contents": "read",  # drift!
            "pull_requests": "write",
            "metadata": "read",
        }
    }
    drifts = _diff_against_current(matrix, drifted)
    assert any("contents" in d for d in drifts)


def test_diff_against_current_detects_dangerous_enabled() -> None:
    """Matrix で deny した actions が current で enabled なら detect。"""
    from backend.app.services.repoproxy.permission_matrix import _diff_against_current

    matrix = load_permission_matrix()
    dangerous = {
        "permissions": {
            "contents": "write",
            "pull_requests": "write",
            "metadata": "read",
            "actions": "write",  # Matrix では deny されているのに enabled
        }
    }
    drifts = _diff_against_current(matrix, dangerous)
    assert any("actions" in d for d in drifts)


@pytest.mark.parametrize(
    "unknown_perm",
    ["deployments", "statuses", "security_events", "code_review", "discussions"],
)
def test_diff_against_current_fail_closed_for_unknown_keys(unknown_perm: str) -> None:
    """Codex SP8 R2 R2-F-001 adopt: Matrix 未定義 permission が current で
    enabled なら fail-closed で drift 検出。permission overreach 防御。"""
    from backend.app.services.repoproxy.permission_matrix import _diff_against_current

    matrix = load_permission_matrix()
    # Matrix に declared でない permission が enabled
    overreach = {
        "permissions": {
            "contents": "write",
            "pull_requests": "write",
            "metadata": "read",
            unknown_perm: "write",  # Matrix で未 declare、deny にも書かれていない
        }
    }
    drifts = _diff_against_current(matrix, overreach)
    assert any(unknown_perm in d for d in drifts), (
        f"unknown permission {unknown_perm!r} overreach was not detected; "
        f"drifts = {drifts}"
    )


def test_diff_against_current_unknown_key_with_none_is_allowed() -> None:
    """Matrix 未定義でも level=none ならば OK (GitHub default)."""
    from backend.app.services.repoproxy.permission_matrix import _diff_against_current

    matrix = load_permission_matrix()
    benign = {
        "permissions": {
            "contents": "write",
            "pull_requests": "write",
            "metadata": "read",
            "deployments": "none",  # Matrix 未 declare だが disabled
            "statuses": "",
        }
    }
    drifts = _diff_against_current(matrix, benign)
    # contents/pull_requests/metadata の整合性は OK、unknown key は none/空文字 → drift なし
    assert drifts == (), f"unexpected drift: {drifts}"


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
