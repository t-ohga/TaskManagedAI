"""Sprint 12 batch 2 (BL-0140b): Ticket-to-PR smoke gold flow orchestrator.

Ticket → AgentRun → Approval → Mock Draft PR → Eval → Audit を sequential に
通すための高レベル orchestrator skeleton. 各 stage は既存 service の callable
を inject (Dependency Injection) する設計で、本 batch は **stage 順序 + 失敗時
の skip invariant + audit emission** を確立する.

実 DB / real provider / real RepoProxy は本 batch では config 不要 (caller が
mock / stub callable を inject)。real DB integration は SP-012 batch 3+ で
host migration drill + private staging E2E と統合.

Anti-Gaming invariant:
- stage 順序は固定 enum (TICKET → RUN → APPROVE → REPO → EVAL → AUDIT)
- 任意 stage skip / reorder は不可 (signature 上、6 callable を順序固定で受ける)
- 失敗 stage 以降は skipped (cascading failure を audit に正直に記録、
  途中で「成功扱い」する経路を物理削除)

Security boundary:
- orchestrator は pure (no DB / network access、injected callable が境界)
- raw secret は audit_payload に含めない (caller が redaction 済 metadata を渡す)
- approval 4 整合 (artifact_hash / diff_hash / policy_version / fingerprint)
  は injected approval_callable の責務
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

logger = logging.getLogger(__name__)

# Codex F-PR58-004 P2 adopt: AC-HARD-02 trace で error_summary に raw secret
# pattern が紛れ込む経路 (provider/SecretBroker/runner stage 失敗時の
# exception text) を redact する。`_payload_secret_scan._RAW_SECRET_PATTERNS`
# と同等の pattern を local 定義 (private import 回避 + 本 module で
# self-contained に redaction を完結).
_SECRET_REDACT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_api_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("anthropic_api_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("github_installation_token", re.compile(r"ghs_[A-Za-z0-9]{20,}")),
    ("github_oauth_token", re.compile(r"gho_[A-Za-z0-9]{20,}")),
    ("github_personal_token", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    ("tailscale_auth_key", re.compile(r"tskey-[a-z0-9]{16,}-[a-z0-9]{16,}")),
    ("age_private_key", re.compile(r"AGE-SECRET-KEY-1[A-Z0-9]{50,}")),
    ("pem_private_key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")),
)


def _redact_secret_summary(raw: str, *, max_len: int = 200) -> str:
    """error_summary 文字列から raw secret pattern を `[REDACTED:<kind>]` に置換.

    Codex F-PR58-004 P2 adopt: provider / SecretBroker / runner stage が
    raw key を含む exception を raise した場合、redaction なしに
    `error_summary` に格納すると AC-HARD-02 違反.

    Args:
        raw: 元の exception message
        max_len: 最終 truncation 上限 (default 200 文字)

    Returns:
        redacted + truncated string (caller が SmokeStageResult.error_summary
        に格納する想定)
    """
    redacted = raw
    for hit_kind, pattern in _SECRET_REDACT_PATTERNS:
        redacted = pattern.sub(f"[REDACTED:{hit_kind}]", redacted)
    return redacted[:max_len]


class SmokeStage(StrEnum):
    """6 stage gold flow (固定順序、reorder 禁止)."""

    TICKET = "ticket"
    RUN = "run"
    APPROVE = "approve"
    REPO = "repo"
    EVAL = "eval"
    AUDIT = "audit"


# 固定順序 tuple (Anti-Gaming、caller / test / audit で 1 source of truth)
SMOKE_STAGE_ORDER: tuple[SmokeStage, ...] = (
    SmokeStage.TICKET,
    SmokeStage.RUN,
    SmokeStage.APPROVE,
    SmokeStage.REPO,
    SmokeStage.EVAL,
    SmokeStage.AUDIT,
)


class TicketToPrSmokeError(RuntimeError):
    """Ticket-to-PR smoke flow failure."""


@dataclass(frozen=True, slots=True)
class SmokeStageResult:
    """単一 stage の実行結果 (frozen、append-only)。

    Codex F-PR58-001 P2 adopt: `metadata` は `MappingProxyType` (immutable
    Mapping view) として保存し、downstream の audit/report caller による
    in-place mutation を物理削除する.
    """

    stage: SmokeStage
    status: str  # "succeeded" / "failed" / "skipped"
    duration_ms: int
    error_code: str | None = None
    error_summary: str | None = None
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True, slots=True)
class TicketToPrSmokeResult:
    """Gold flow 全体結果 (frozen、append-only)."""

    stage_count: int
    succeeded_count: int
    failed_count: int
    skipped_count: int
    overall_success: bool
    stages: tuple[SmokeStageResult, ...]


# stage callable contract: 入力 = previous stage の metadata (dict)、出力 =
# 当該 stage の metadata (dict). 例外は TicketToPrSmokeError として伝播.
StageCallable = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


async def run_ticket_to_pr_smoke(
    *,
    ticket_callable: StageCallable,
    run_callable: StageCallable,
    approve_callable: StageCallable,
    repo_callable: StageCallable,
    eval_callable: StageCallable,
    audit_callable: StageCallable,
    initial_context: dict[str, Any] | None = None,
) -> TicketToPrSmokeResult:
    """6 stage gold flow を sequential に実行.

    各 stage は previous stage の metadata を入力として受け、自身の metadata を
    返す。失敗 stage 以降は **skipped** として記録 (cascading failure を正直に
    audit、途中で false success に経路を物理削除).

    Args:
        ticket_callable: Ticket fixture preparation (e.g. seed Ticket row)
        run_callable: AgentRun orchestrator (provider call + validate + lint)
        approve_callable: ApprovalDecisionService (human approval simulation)
        repo_callable: RepoProxy / GitHubAppAdapter (Mock Draft PR open)
        eval_callable: Eval runner (AC-KPI / AC-HARD evaluate)
        audit_callable: AuditEvent emission (raw secret なし、final audit)
        initial_context: 初期 metadata (default = empty dict)

    Returns:
        TicketToPrSmokeResult with 6 stages + overall_success.
    """

    import time

    context = dict(initial_context or {})
    stages: list[SmokeStageResult] = []
    first_failure_seen = False

    callables: dict[SmokeStage, StageCallable] = {
        SmokeStage.TICKET: ticket_callable,
        SmokeStage.RUN: run_callable,
        SmokeStage.APPROVE: approve_callable,
        SmokeStage.REPO: repo_callable,
        SmokeStage.EVAL: eval_callable,
        SmokeStage.AUDIT: audit_callable,
    }

    for stage in SMOKE_STAGE_ORDER:
        # Codex F-PR58-002 P1 adopt: AUDIT stage は failure 時でも実行する
        # (audit truth invariant、cascading failure を audit emit で記録).
        # それ以外の stage は cascading skip (false success を物理削除).
        if first_failure_seen and stage is not SmokeStage.AUDIT:
            stages.append(
                SmokeStageResult(
                    stage=stage,
                    status="skipped",
                    duration_ms=0,
                    error_code="cascaded_skip",
                    error_summary="previous stage failed; skipping to preserve audit truth",
                    metadata=MappingProxyType({}),
                )
            )
            continue

        callable_fn = callables[stage]
        start_ns = time.monotonic_ns()
        try:
            # Codex F-PR58-003 P2 adopt: defensive copy で in-place mutation
            # を阻止 (stage callable が context を直接書き換えても、 cumulative
            # context は orchestrator の管理下に残り、metadata channel を bypass
            # した経路を物理削除).
            stage_metadata = await callable_fn(dict(context))
        except TicketToPrSmokeError as exc:
            duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000
            logger.warning(
                "ticket_to_pr_smoke_stage_failed",
                extra={"stage": stage.value, "error_type": "TicketToPrSmokeError"},
            )
            # Codex F-PR58-004 P2 adopt: error_summary redaction (AC-HARD-02).
            stages.append(
                SmokeStageResult(
                    stage=stage,
                    status="failed",
                    duration_ms=int(duration_ms),
                    error_code="stage_failed",
                    error_summary=_redact_secret_summary(str(exc)),
                    metadata=MappingProxyType({}),
                )
            )
            first_failure_seen = True
            continue
        except Exception as exc:  # noqa: BLE001
            duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000
            logger.warning(
                "ticket_to_pr_smoke_stage_unexpected_error",
                extra={"stage": stage.value, "error_type": type(exc).__name__},
            )
            stages.append(
                SmokeStageResult(
                    stage=stage,
                    status="failed",
                    duration_ms=int(duration_ms),
                    error_code=type(exc).__name__,
                    error_summary=_redact_secret_summary(str(exc)),
                    metadata=MappingProxyType({}),
                )
            )
            first_failure_seen = True
            continue

        duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000
        # context に stage metadata を merge (key 衝突は new 優先、explicit)
        if not isinstance(stage_metadata, dict):
            raise TicketToPrSmokeError(
                f"stage {stage.value} returned non-dict metadata: "
                f"{type(stage_metadata).__name__}"
            )
        context.update(stage_metadata)
        # Codex F-PR58-001 P2 adopt: MappingProxyType で immutable view、
        # downstream mutation を物理削除.
        stages.append(
            SmokeStageResult(
                stage=stage,
                status="succeeded",
                duration_ms=int(duration_ms),
                error_code=None,
                error_summary=None,
                metadata=MappingProxyType(dict(stage_metadata)),
            )
        )

    succeeded = sum(1 for s in stages if s.status == "succeeded")
    failed = sum(1 for s in stages if s.status == "failed")
    skipped = sum(1 for s in stages if s.status == "skipped")

    return TicketToPrSmokeResult(
        stage_count=len(stages),
        succeeded_count=succeeded,
        failed_count=failed,
        skipped_count=skipped,
        overall_success=(failed == 0 and skipped == 0),
        stages=tuple(stages),
    )


__all__ = [
    "SMOKE_STAGE_ORDER",
    "SmokeStage",
    "SmokeStageResult",
    "StageCallable",
    "TicketToPrSmokeError",
    "TicketToPrSmokeResult",
    "run_ticket_to_pr_smoke",
]
