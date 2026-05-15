"""Sprint 7 BL-0077: runner mutation gateway tests."""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Sequence

import pytest

from backend.app.services.runner import mutation_gateway as gateway
from backend.app.services.runner.dangerous_command import (
    DangerousCommandDenyReason,
    DangerousCommandViolation,
)
from backend.app.services.runner.forbidden_path import (
    ForbiddenPathDenyReason,
    ForbiddenPathViolation,
)
from backend.app.services.runner.mutation_gateway import (
    MutationGatewayDecision,
    MutationGatewayDenyReason,
    PatchApplyRequest,
    enforce_runner_mutation_gateway,
)

EXPECTED_DENY_REASONS = (
    "policy_not_passed",
    "approval_not_passed",
    "artifact_hash_mismatch",
    "policy_version_mismatch",
    "provider_fingerprint_mismatch",
    "repo_state_mismatch",
    "forbidden_path",
    "dangerous_command",
    "empty_patch",
    "path_outside_allowlist",
    # Codex SP7 audit F-SP7-004 adopt
    "force_denied",
)


def _hash_text(text: str = "patch") -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_request(**overrides: object) -> PatchApplyRequest:
    artifact_hash = _hash_text()
    values = {
        "artifact_hash": artifact_hash,
        "policy_version": "runner-policy@2026-05-13",
        "provider_request_fingerprint": "provider-fp-001",
        "repo_state_commit_sha": "a" * 40,
        "expected_artifact_hash": artifact_hash,
        "expected_policy_version": "runner-policy@2026-05-13",
        "expected_provider_fingerprint": "provider-fp-001",
        "expected_repo_state": "a" * 40,
        "policy_pass": True,
        "approval_pass": True,
        "target_paths": ("backend/app/services/runner/file.py",),
        "argv_plan": (("python", "-m", "pytest", "tests/runner"),),
        # Codex SP7 R1 F-002 adopt: allowlist (relative path も cwd base で
        # resolve されるため、test fixture では cwd 配下を allow root にする)。
        "workspace_root": ".",
        "artifact_outbox": ".",
        "temp_root": "/tmp",  # noqa: S108 - test fixture only
    }
    values.update(overrides)
    return PatchApplyRequest(**values)


def _assert_deny(
    request: PatchApplyRequest,
    expected_reason: MutationGatewayDenyReason,
) -> MutationGatewayDecision:
    decision = enforce_runner_mutation_gateway(request)

    assert decision.allow is False
    assert decision.deny_reason is expected_reason
    return decision


def test_mutation_gateway_deny_reason_enum_exhaustive() -> None:
    """MutationGatewayDenyReason は gateway gate の監査 reason を固定する。"""

    assert tuple(reason.value for reason in MutationGatewayDenyReason) == EXPECTED_DENY_REASONS


def test_allow_when_all_gates_pass() -> None:
    """policy / approval / 4 整合 / path / command が全て clean なら許可する。"""

    decision = enforce_runner_mutation_gateway(_make_request())

    assert decision.allow is True
    assert decision.deny_reason is None
    assert decision.forbidden_path_violations == ()
    assert decision.dangerous_command_violations == ()


def test_deny_when_policy_not_passed() -> None:
    """policy gate が未通過なら最初に拒否する。"""

    decision = _assert_deny(
        _make_request(policy_pass=False),
        MutationGatewayDenyReason.POLICY_NOT_PASSED,
    )

    assert decision.forbidden_path_violations == ()
    assert decision.dangerous_command_violations == ()


def test_deny_when_approval_not_passed() -> None:
    """policy が OK でも approval gate が未通過なら拒否する。"""

    _assert_deny(
        _make_request(approval_pass=False),
        MutationGatewayDenyReason.APPROVAL_NOT_PASSED,
    )


def test_deny_when_artifact_hash_mismatch() -> None:
    """approval record の artifact hash と request hash が不一致なら拒否する。"""

    _assert_deny(
        _make_request(artifact_hash="b" * 64),
        MutationGatewayDenyReason.ARTIFACT_HASH_MISMATCH,
    )


def test_deny_when_policy_version_mismatch() -> None:
    """approval 時点の policy_version と実行時 policy_version が違えば拒否する。"""

    _assert_deny(
        _make_request(policy_version="runner-policy@stale"),
        MutationGatewayDenyReason.POLICY_VERSION_MISMATCH,
    )


def test_deny_when_provider_fingerprint_mismatch() -> None:
    """provider request fingerprint が approval record と違えば拒否する。"""

    _assert_deny(
        _make_request(provider_request_fingerprint="provider-fp-stale"),
        MutationGatewayDenyReason.PROVIDER_FINGERPRINT_MISMATCH,
    )


def test_deny_when_repo_state_mismatch() -> None:
    """repo_state が approval record と違えば stale approval として拒否する。"""

    _assert_deny(
        _make_request(repo_state_commit_sha="b" * 40),
        MutationGatewayDenyReason.REPO_STATE_MISMATCH,
    )


def test_deny_when_empty_patch() -> None:
    """target_paths と argv_plan が共に空なら empty patch として拒否する。"""

    _assert_deny(
        _make_request(target_paths=(), argv_plan=()),
        MutationGatewayDenyReason.EMPTY_PATCH,
    )


def test_deny_when_forbidden_path_in_target_paths() -> None:
    """target_paths に forbidden path が含まれる patch は拒否する。"""

    decision = _assert_deny(
        _make_request(target_paths=(".git/config",)),
        MutationGatewayDenyReason.FORBIDDEN_PATH,
    )

    assert len(decision.forbidden_path_violations) == 1
    assert decision.forbidden_path_violations[0].reason is (
        ForbiddenPathDenyReason.GIT_INFRASTRUCTURE
    )
    assert decision.dangerous_command_violations == ()


def test_deny_when_dangerous_command_in_argv_plan() -> None:
    """argv_plan に dangerous command が含まれる patch は拒否する。"""

    decision = _assert_deny(
        _make_request(argv_plan=(("rm", "-rf", "/"),)),
        MutationGatewayDenyReason.DANGEROUS_COMMAND,
    )

    assert decision.forbidden_path_violations == ()
    assert len(decision.dangerous_command_violations) == 1
    assert decision.dangerous_command_violations[0].reason is DangerousCommandDenyReason.RM_RF


def test_priority_policy_before_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    """policy NG 時は後続 scan を実行せず policy reason を返す。"""

    def _unexpected_path_scan(raw: str) -> ForbiddenPathViolation | None:
        raise AssertionError(f"path scan should be skipped: {raw}")

    def _unexpected_command_scan(
        argv: Sequence[str],
    ) -> DangerousCommandViolation | None:
        raise AssertionError(f"command scan should be skipped: {argv}")

    monkeypatch.setattr(gateway, "resolve_and_detect", _unexpected_path_scan)
    monkeypatch.setattr(gateway, "detect_dangerous_command", _unexpected_command_scan)

    _assert_deny(
        _make_request(
            policy_pass=False,
            approval_pass=False,
            artifact_hash="b" * 64,
            target_paths=("/repo/.git/config",),
            argv_plan=(("rm", "-rf", "/"),),
        ),
        MutationGatewayDenyReason.POLICY_NOT_PASSED,
    )


def test_priority_integrity_before_path_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    """4 整合が NG の場合は path scan より先に拒否する。"""

    def _unexpected_path_scan(raw: str) -> ForbiddenPathViolation | None:
        raise AssertionError(f"path scan should be skipped: {raw}")

    monkeypatch.setattr(gateway, "resolve_and_detect", _unexpected_path_scan)

    _assert_deny(
        _make_request(
            artifact_hash="b" * 64,
            target_paths=("/repo/.git/config",),
        ),
        MutationGatewayDenyReason.ARTIFACT_HASH_MISMATCH,
    )


def test_priority_path_before_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """forbidden path 検出時は command scan を実行せず path reason を返す。"""

    path_violation = ForbiddenPathViolation(
        raw_path=".git/config",
        canonical_path=".git/config",
        reason=ForbiddenPathDenyReason.GIT_INFRASTRUCTURE,
    )

    def _path_scan(raw: str) -> ForbiddenPathViolation:
        assert raw == ".git/config"
        return path_violation

    def _unexpected_command_scan(
        argv: Sequence[str],
    ) -> DangerousCommandViolation | None:
        raise AssertionError(f"command scan should be skipped: {argv}")

    monkeypatch.setattr(gateway, "resolve_and_detect", _path_scan)
    monkeypatch.setattr(gateway, "detect_dangerous_command", _unexpected_command_scan)

    decision = _assert_deny(
        _make_request(
            target_paths=(".git/config",),
            argv_plan=(("rm", "-rf", "/"),),
        ),
        MutationGatewayDenyReason.FORBIDDEN_PATH,
    )

    assert decision.forbidden_path_violations == (path_violation,)
    assert decision.dangerous_command_violations == ()


def test_multiple_forbidden_paths_collected() -> None:
    """複数 target path 違反は全件集約して返す。"""

    decision = _assert_deny(
        _make_request(
            target_paths=(
                "/repo/.git/config",
                "/repo/.env.local",
            ),
        ),
        MutationGatewayDenyReason.FORBIDDEN_PATH,
    )

    assert tuple(v.reason for v in decision.forbidden_path_violations) == (
        ForbiddenPathDenyReason.GIT_INFRASTRUCTURE,
        ForbiddenPathDenyReason.ENV_FILE,
    )
    assert decision.dangerous_command_violations == ()


def test_multiple_dangerous_commands_collected() -> None:
    """複数 argv_plan 違反は全件集約して返す。"""

    decision = _assert_deny(
        _make_request(
            argv_plan=(
                ("rm", "-rf", "/"),
                ("chmod", "777", "file"),
            ),
        ),
        MutationGatewayDenyReason.DANGEROUS_COMMAND,
    )

    assert decision.forbidden_path_violations == ()
    assert tuple(v.reason for v in decision.dangerous_command_violations) == (
        DangerousCommandDenyReason.RM_RF,
        DangerousCommandDenyReason.CHMOD_777,
    )


def test_request_is_frozen() -> None:
    """PatchApplyRequest は approval binding として immutable にする。"""

    request = _make_request()

    with pytest.raises(dataclasses.FrozenInstanceError):
        request.policy_pass = False


def test_decision_is_frozen() -> None:
    """MutationGatewayDecision は監査 record として immutable にする。"""

    decision = MutationGatewayDecision(allow=True)

    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.allow = False


def test_decision_default_violations_empty_tuple() -> None:
    """decision の violation default は共有 list ではなく空 tuple とする。"""

    decision = MutationGatewayDecision(allow=False)

    assert decision.allow is False
    assert decision.deny_reason is None
    assert decision.forbidden_path_violations == ()
    assert decision.dangerous_command_violations == ()


def test_integrity_uses_constant_time_compare() -> None:
    """4 整合は完全一致だけを許可する。timing 測定は Sprint 8 hardening で扱う。"""

    exact_hash = "f" * 64
    exact = enforce_runner_mutation_gateway(
        _make_request(
            artifact_hash=exact_hash,
            expected_artifact_hash=exact_hash,
        )
    )
    almost = enforce_runner_mutation_gateway(
        _make_request(
            artifact_hash=("f" * 63) + "0",
            expected_artifact_hash=exact_hash,
        )
    )

    assert exact.allow is True
    assert exact.deny_reason is None
    assert almost.allow is False
    assert almost.deny_reason is MutationGatewayDenyReason.ARTIFACT_HASH_MISMATCH


def test_force_deny_env_blocks_all_patches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex SP7 audit F-SP7-004 adopt: RUNNER_MUTATION_GATEWAY_FORCE_DENY=true
    で全 patch apply が deny される (ADR-00008 §rollback kill switch)。

    policy/approval/4 整合/forbidden_path/dangerous_command が全て pass しても、
    env flag enabled なら gate が deny を返す。
    """
    monkeypatch.setenv("RUNNER_MUTATION_GATEWAY_FORCE_DENY", "true")
    decision = enforce_runner_mutation_gateway(_make_request())
    assert decision.allow is False
    assert decision.deny_reason is MutationGatewayDenyReason.FORCE_DENIED


@pytest.mark.parametrize(
    "flag_value",
    ["true", "1", "yes", "on", "TRUE", "Yes"],
)
def test_force_deny_accepts_multiple_truthy_values(
    monkeypatch: pytest.MonkeyPatch,
    flag_value: str,
) -> None:
    """Codex SP7 audit F-SP7-004 adopt: case-insensitive + multiple truthy values。"""
    monkeypatch.setenv("RUNNER_MUTATION_GATEWAY_FORCE_DENY", flag_value)
    decision = enforce_runner_mutation_gateway(_make_request())
    assert decision.deny_reason is MutationGatewayDenyReason.FORCE_DENIED


@pytest.mark.parametrize(
    "flag_value",
    ["false", "0", "no", "off", "", "anything-else"],
)
def test_force_deny_disabled_allows_normal_flow(
    monkeypatch: pytest.MonkeyPatch,
    flag_value: str,
) -> None:
    """flag が falsy / unset なら通常 gate flow が動作する。"""
    monkeypatch.setenv("RUNNER_MUTATION_GATEWAY_FORCE_DENY", flag_value)
    decision = enforce_runner_mutation_gateway(_make_request())
    # falsy = 通常 flow、policy/approval pass で allow される
    assert decision.allow is True

