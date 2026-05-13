"""Sprint 7 BL-0077: runner_mutation_gateway.

ADR-00003 §A の `runner_mutation_gateway` 本実装。policy / approval /
forbidden_path / dangerous_command の全 gate を通過した patch のみ runner
sandbox 内で apply する。

設計 (DD-04 §6.5 + AI Output Boundary §9):

- ``enforce_runner_mutation_gateway(request)`` は patch apply 前の **fail-closed**
  validator。policy_pass / approval_pass / 4 整合 hash + forbidden path 検査 +
  dangerous command 検査の全てが clean な場合のみ ``MutationGatewayDecision
  (allow=True)`` を返す。
- 何れかの gate が deny を返す場合、``allow=False`` + 個別 deny reason +
  violation details。
- 本 module は **policy enforcement (validation only)** であり mutation 自体
  は行わない (caller = RunnerAdapter が container 内 patch apply 実行)。

server-owned-boundary §1 不変条件:

- ``PatchApplyRequest.policy_pass`` / ``approval_pass`` / ``payload_hash`` は
  caller-supplied だが、本 module は **再計算しない**。caller (RunnerAdapter
  + AgentRuntime) が server-side で算出した値を渡す前提 (Sprint 7 batch 4 で
  contract test 化)。
- ``forbidden_paths`` / ``argv_plan`` は本 module 内で detect_* function を
  通して fail-closed scan。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from backend.app.services.runner.dangerous_command import (
    DangerousCommandViolation,
    detect_dangerous_command,
)
from backend.app.services.runner.forbidden_path import (
    ForbiddenPathViolation,
    resolve_and_detect,
)


class MutationGatewayDenyReason(StrEnum):
    POLICY_NOT_PASSED = "policy_not_passed"
    APPROVAL_NOT_PASSED = "approval_not_passed"
    ARTIFACT_HASH_MISMATCH = "artifact_hash_mismatch"
    POLICY_VERSION_MISMATCH = "policy_version_mismatch"
    PROVIDER_FINGERPRINT_MISMATCH = "provider_fingerprint_mismatch"
    REPO_STATE_MISMATCH = "repo_state_mismatch"
    FORBIDDEN_PATH = "forbidden_path"
    DANGEROUS_COMMAND = "dangerous_command"
    EMPTY_PATCH = "empty_patch"
    PATH_OUTSIDE_ALLOWLIST = "path_outside_allowlist"  # Codex SP7 R1 F-002


@dataclass(frozen=True, slots=True)
class PatchApplyRequest:
    """runner_mutation_gateway の入力 (caller = AgentRuntime が組み立て).

    **Codex SP7 R1 F-001 partial adopt (Sprint 8 で full)**: 現状 signature は
    bool / expected_* hash を caller-supplied で受けるが、Sprint 8 で
    `artifact_id` / `approval_id` / `policy_decision_id` / `repo_snapshot_id`
    の server-owned ID のみに変更し、gateway 内で artifact hash / policy
    version / provider fingerprint / repo_state を再取得・``hmac.compare_digest``
    比較する設計に移行する (RepoProxy / GitHub App integration と一緒に
    実装)。本 Sprint 7 では server-owned signature 化のための receive
    interface は維持しつつ、4 整合の compare を `hmac.compare_digest` に
    切り替える (Codex SP7 R1 F-012 adopt)。
    """

    # 4 整合 binding (server-side で算出した値を caller が pass)
    artifact_hash: str  # SHA-256 hex of patch artifact content
    policy_version: str
    provider_request_fingerprint: str
    repo_state_commit_sha: str

    # 4 整合 expected (Approval 4 整合の record 側、server-side validated)
    # Sprint 8 で provenance binding に移行予定 (本 dataclass の signature
    # も同時に変更)。
    expected_artifact_hash: str
    expected_policy_version: str
    expected_provider_fingerprint: str
    expected_repo_state: str

    # Gate pass markers (server-side で gate 通過判定された値)
    policy_pass: bool
    approval_pass: bool

    # Patch metadata (lint 対象)
    target_paths: tuple[str, ...]  # patch が touch する path 群
    argv_plan: tuple[tuple[str, ...], ...]  # patch apply で実行する argv 群

    # Codex SP7 R1 F-002 adopt: write-permitted path allowlist (server-side
    # で AgentRuntime が決定、caller-supplied ではない)。target_paths は
    # これらいずれかの配下である必要 (resolve 後 prefix match)。
    workspace_root: str
    artifact_outbox: str
    temp_root: str


@dataclass(frozen=True, slots=True)
class MutationGatewayDecision:
    allow: bool
    deny_reason: MutationGatewayDenyReason | None = None
    forbidden_path_violations: tuple[ForbiddenPathViolation, ...] = field(
        default_factory=tuple
    )
    dangerous_command_violations: tuple[DangerousCommandViolation, ...] = field(
        default_factory=tuple
    )


def _validate_4_integrity(
    request: PatchApplyRequest,
) -> MutationGatewayDenyReason | None:
    """Codex SP7 R1 F-012 adopt: ``hmac.compare_digest`` で constant-time
    compare、timing attack に対する hardening。"""

    import hmac  # noqa: PLC0415

    if not hmac.compare_digest(request.artifact_hash, request.expected_artifact_hash):
        return MutationGatewayDenyReason.ARTIFACT_HASH_MISMATCH
    if not hmac.compare_digest(request.policy_version, request.expected_policy_version):
        return MutationGatewayDenyReason.POLICY_VERSION_MISMATCH
    if not hmac.compare_digest(
        request.provider_request_fingerprint,
        request.expected_provider_fingerprint,
    ):
        return MutationGatewayDenyReason.PROVIDER_FINGERPRINT_MISMATCH
    if not hmac.compare_digest(
        request.repo_state_commit_sha,
        request.expected_repo_state,
    ):
        return MutationGatewayDenyReason.REPO_STATE_MISMATCH
    return None


def _validate_allowlist(
    request: PatchApplyRequest,
) -> tuple[str, ...]:
    """Codex SP7 R1 F-002 adopt: target_paths の allowlist containment 検査。

    各 target_path を ``Path.resolve()`` 後、``workspace_root`` /
    ``artifact_outbox`` / ``temp_root`` のいずれか配下にあるか確認。違反
    path を tuple で返す。
    """

    from pathlib import Path as _Path  # noqa: PLC0415

    allowed_roots = tuple(
        str(_Path(root).resolve(strict=False))
        for root in (request.workspace_root, request.artifact_outbox, request.temp_root)
        if root
    )
    violations: list[str] = []
    for path in request.target_paths:
        try:
            resolved = str(_Path(path).resolve(strict=False))
        except OSError:
            violations.append(path)
            continue
        if not any(
            resolved == root or resolved.startswith(root + "/")
            for root in allowed_roots
        ):
            violations.append(path)
    return tuple(violations)


def enforce_runner_mutation_gateway(
    request: PatchApplyRequest,
) -> MutationGatewayDecision:
    """全 gate を通過した patch のみ allow=True を返す。

    Gate 順序 (fail-closed、最初に deny を返した時点で短絡):

    1. policy_pass / approval_pass の bool check
    2. 4 整合 binding (artifact_hash / policy_version / provider_fingerprint /
       repo_state) の hash compare
    3. forbidden path scan (各 target_path に対し resolve_and_detect)
    4. dangerous command scan (各 argv に対し detect_dangerous_command)
    5. empty patch (target_paths + argv_plan が空) reject
    """

    if not request.policy_pass:
        return MutationGatewayDecision(
            allow=False,
            deny_reason=MutationGatewayDenyReason.POLICY_NOT_PASSED,
        )
    if not request.approval_pass:
        return MutationGatewayDecision(
            allow=False,
            deny_reason=MutationGatewayDenyReason.APPROVAL_NOT_PASSED,
        )

    integrity_fail = _validate_4_integrity(request)
    if integrity_fail is not None:
        return MutationGatewayDecision(
            allow=False,
            deny_reason=integrity_fail,
        )

    if not request.target_paths and not request.argv_plan:
        return MutationGatewayDecision(
            allow=False,
            deny_reason=MutationGatewayDenyReason.EMPTY_PATCH,
        )

    # Codex SP7 R1 F-002 adopt: forbidden path scan を **先** に行う (具体的な
    # security 違反は具体的な reason で返す)。allowlist 検査はその後、
    # 汎用 containment fallback として動作。
    path_violations: list[ForbiddenPathViolation] = []
    for path in request.target_paths:
        v_path = resolve_and_detect(path)
        if v_path is not None:
            path_violations.append(v_path)
    if path_violations:
        return MutationGatewayDecision(
            allow=False,
            deny_reason=MutationGatewayDenyReason.FORBIDDEN_PATH,
            forbidden_path_violations=tuple(path_violations),
        )

    # Codex SP7 R1 F-002 adopt (続): allowlist check は forbidden path scan
    # 後、dangerous command scan 前に実行。
    allowlist_violations = _validate_allowlist(request)
    if allowlist_violations:
        return MutationGatewayDecision(
            allow=False,
            deny_reason=MutationGatewayDenyReason.PATH_OUTSIDE_ALLOWLIST,
        )

    dangerous_list: list[DangerousCommandViolation] = []
    for argv in request.argv_plan:
        v_cmd = detect_dangerous_command(argv)
        if v_cmd is not None:
            dangerous_list.append(v_cmd)
    dangerous_violations = tuple(dangerous_list)
    if dangerous_violations:
        return MutationGatewayDecision(
            allow=False,
            deny_reason=MutationGatewayDenyReason.DANGEROUS_COMMAND,
            dangerous_command_violations=dangerous_violations,
        )

    return MutationGatewayDecision(allow=True)


__all__ = [
    "MutationGatewayDecision",
    "MutationGatewayDenyReason",
    "PatchApplyRequest",
    "enforce_runner_mutation_gateway",
]
