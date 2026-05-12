"""Sprint 6 BL-0068: 採否判定 API (adopt / reject / defer).

CLI invocation の結果 (cli_result_summary artifact) に対し、actor の
``adopt`` / ``reject`` / ``defer`` 採否判定を行い、AgentRunEvent
(``cli_decision_recorded``) と audit_events に append-only で残す。

設計 (ADR-00003 §A boundary + AI Output Boundary §1):

- ``CliDecisionVerdict`` = ``adopt`` | ``reject`` | ``defer`` の 3 種固定。
- ``adopt`` でも Ticket / repo / workflow を直接更新せず、後続 Sprint で
  policy lint / Approval / Runner / RepoProxy gate を必ず通す (本 module は
  decision 記録のみで mutation はしない)。
- ``record_decision()`` は (CliInvocationOutcome, actor_id, verdict, reason)
  を受け、``CliDecisionRecord`` を返す。caller (AgentRuntime) が同一
  transaction で AgentRunEvent + audit_events を append する。
- artifact_hash は CliInvocationOutcome に紐付く result_summary artifact の
  content_hash を caller が解決して渡す (本 module は raw content を見ない)。

server-owned-boundary §1 不変条件:

- ``actor_id`` / ``run_id`` / ``tenant_id`` は server-side で validated。
  本 module は ``[0-9a-fA-F-]{8,64}`` 形式の hex/uuid のみ受け付ける。
- ``verdict`` は Literal、enum 外は signature レベルで reject。
- ``reason`` は任意の自由文だが、raw secret pattern を含むと
  ``assert_no_raw_secret`` で reject。
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from backend.app.repositories._payload_secret_scan import (
    _PROHIBITED_PAYLOAD_KEYS,
    assert_no_raw_secret,
)
from backend.app.services.cli_artifact.redaction import redact_stream

_HEX_UUID_RE = re.compile(r"\A[0-9a-fA-F-]{8,64}\Z")
_TENANT_ID_RE = re.compile(r"\A[0-9a-zA-Z_-]{1,64}\Z")
_SHA256_HEX_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_POLICY_VERSION_RE = re.compile(r"\A[0-9a-zA-Z._-]{1,64}\Z")


class CliDecisionVerdict(StrEnum):
    ADOPT = "adopt"
    REJECT = "reject"
    DEFER = "defer"


class CliDecisionActorType(StrEnum):
    """Codex SP6B3 R1 F-005 (HIGH) adopt: 採否判定 actor は **human-only**。

    AI / service actor が自身の output を adopt できる self-approval 経路を
    signature レベルで物理削除。
    """

    HUMAN = "human"


@dataclass(frozen=True, slots=True)
class CliDecisionRecord:
    """Single 採否判定 record (append-only audit)."""

    decision_id: str  # uuid4 hex (server-side generated)
    tenant_id: str
    run_id: str
    actor_id: str
    verdict: CliDecisionVerdict
    artifact_hash: str  # SHA-256 hex of cli_result_summary artifact content
    policy_version: str
    reason: str  # actor-provided rationale (raw secret 非含、verified)
    decided_at: datetime  # UTC, server-side now()


def record_decision(
    *,
    tenant_id: str,
    run_id: str,
    actor_id: str,
    actor_type: CliDecisionActorType | str,
    verdict: CliDecisionVerdict | str,
    artifact_content: bytes,
    policy_version: str,
    reason: str,
    now: datetime | None = None,
) -> CliDecisionRecord:
    """採否判定 record を組み立てる。

    Codex SP6B3 R1 採否判定後の signature (server-owned-boundary §1):

    - ``actor_type`` は **human-only** 強制 (F-005 HIGH adopt)。AI / service
      actor の self-approval を signature レベルで物理削除。
    - ``artifact_content`` (bytes) を caller から受け取り、本 module 内で
      SHA-256 hex を **server-side 算出** (F-002 HIGH adopt)。caller-supplied
      ``artifact_hash`` 経路を物理削除。
    - ``reason`` は raw secret pattern + ``key=value`` 形式 prohibited key の
      両方で reject (F-001 CRITICAL adopt)。
    - naive datetime は reject (F-007 MEDIUM adopt)。

    Args:
        tenant_id: tenant 境界 (DB BigInteger str / hex 1-64 chars allowed)。
        run_id: AgentRun id (hex/uuid 8-64 chars).
        actor_id: human actor id (hex/uuid 8-64 chars).
        actor_type: ``human`` のみ。enum 外は reject。
        verdict: ``adopt`` | ``reject`` | ``defer``。
        artifact_content: cli_result_summary artifact の生 bytes。server-side
            で SHA-256 計算。
        policy_version: policy pack version 文字列。
        reason: 採否理由。raw secret pattern + key=value redaction を通過。
        now: tests で時間制御するための optional UTC datetime (tzinfo 必須)。

    Raises:
        ValueError: 入力 validation 違反 / raw secret detected。
    """

    if not _TENANT_ID_RE.fullmatch(tenant_id):
        raise ValueError(
            f"tenant_id must be 1-64 chars of [0-9a-zA-Z_-] (got {tenant_id!r})"
        )
    if not _HEX_UUID_RE.fullmatch(run_id):
        raise ValueError(
            f"run_id must be 8-64 chars of [0-9a-fA-F-] (got {run_id!r})"
        )
    if not _HEX_UUID_RE.fullmatch(actor_id):
        raise ValueError(
            f"actor_id must be 8-64 chars of [0-9a-fA-F-] (got {actor_id!r})"
        )
    if not _POLICY_VERSION_RE.fullmatch(policy_version):
        raise ValueError(
            "policy_version must be 1-64 chars of [0-9a-zA-Z._-] "
            f"(got {policy_version!r})"
        )

    # Codex SP6B3 R1 F-005 (HIGH) adopt: actor_type を human-only 強制。
    try:
        coerced_actor_type = (
            actor_type if isinstance(actor_type, CliDecisionActorType)
            else CliDecisionActorType(str(actor_type))
        )
    except ValueError as exc:
        raise ValueError(
            f"actor_type must be one of {sorted(CliDecisionActorType)} "
            f"(human-only, self-approval prohibited); got {actor_type!r}"
        ) from exc
    if coerced_actor_type is not CliDecisionActorType.HUMAN:
        raise ValueError(
            "actor_type must be 'human' (self-approval prohibited per "
            "Approval workflow invariant)"
        )

    # verdict enum coercion
    try:
        coerced_verdict = (
            verdict if isinstance(verdict, CliDecisionVerdict)
            else CliDecisionVerdict(str(verdict))
        )
    except ValueError as exc:
        raise ValueError(
            f"verdict must be one of {sorted(CliDecisionVerdict)} "
            f"(got {verdict!r})"
        ) from exc

    # Codex SP6B3 R1 F-002 (HIGH) adopt: artifact_hash を server-side で算出
    if not isinstance(artifact_content, (bytes, bytearray)):
        raise ValueError(
            f"artifact_content must be bytes (got {type(artifact_content).__name__})"
        )
    if not artifact_content:
        raise ValueError("artifact_content must be non-empty")
    artifact_hash = hashlib.sha256(bytes(artifact_content)).hexdigest()

    # Codex SP6B3 R1 F-001 (CRITICAL) adopt: reason scan で raw secret +
    # key=value 形式 prohibited key の **両方** を reject。
    if not isinstance(reason, str):
        raise ValueError(f"reason must be a str (got {type(reason).__name__})")
    if len(reason) > 4096:
        raise ValueError(
            f"reason must be <= 4096 chars (got {len(reason)})"
        )
    assert_no_raw_secret(reason, path="$cli_decision.reason")
    # `key=value` 形式 prohibited key の値混入も reject (redaction.py と同じ
    # pattern を共有)。
    for key in _PROHIBITED_PAYLOAD_KEYS:
        if re.search(
            rf"\b{re.escape(key)}\b\s*[=:]",
            reason,
            re.IGNORECASE,
        ):
            raise ValueError(
                f"reason contains prohibited key '{key}' followed by =/: "
                "(value injection blocked, use server-side redacted summary)"
            )
    # 追加 defense: redaction pipeline を通して、出力 redacted_text が変化
    # していたら reject (Cf/Cc/ANSI 等の bypass を防ぐ)。
    redaction = redact_stream(reason.encode("utf-8"), max_bytes=len(reason) + 1024)
    if redaction.hits or redaction.prohibited_key_hits:
        raise ValueError(
            "reason triggered redaction pipeline (raw secret / prohibited "
            f"key detected: hits={[h.pattern_kind for h in redaction.hits]} "
            f"prohibited={list(redaction.prohibited_key_hits)})"
        )

    decided_at = now or datetime.now(tz=UTC)
    if decided_at.tzinfo is None:
        raise ValueError(
            "decided_at must be timezone-aware (got naive datetime); "
            "pass tz=UTC explicitly"
        )

    return CliDecisionRecord(
        decision_id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        run_id=run_id,
        actor_id=actor_id,
        verdict=coerced_verdict,
        artifact_hash=artifact_hash,
        policy_version=policy_version,
        reason=reason,
        decided_at=decided_at,
    )


def build_cli_decision_event_payload(
    record: CliDecisionRecord,
) -> dict[str, str]:
    """``cli_decision_recorded`` AgentRunEvent payload を組み立てる。

    raw value 非含、actor / verdict / artifact_hash / policy_version /
    decided_at / reason_hash のみ。reason 自体は audit_events に保存
    (event payload には reason hash のみ載せ、structured audit table から
    raw reason を取得する 2-store pattern)。
    """

    reason_hash = hashlib.sha256(record.reason.encode("utf-8")).hexdigest()
    return {
        "decision_id": record.decision_id,
        "actor_id": record.actor_id,
        "verdict": record.verdict.value,
        "artifact_hash": record.artifact_hash,
        "policy_version": record.policy_version,
        "decided_at": record.decided_at.isoformat(),
        "reason_hash": reason_hash,
    }


def build_cli_decision_audit_payload(
    record: CliDecisionRecord,
) -> dict[str, str]:
    """audit_events 用 payload (reason raw を含む、internal audit のみ)."""

    return {
        "decision_id": record.decision_id,
        "tenant_id": record.tenant_id,
        "run_id": record.run_id,
        "actor_id": record.actor_id,
        "verdict": record.verdict.value,
        "artifact_hash": record.artifact_hash,
        "policy_version": record.policy_version,
        "reason": record.reason,
        "decided_at": record.decided_at.isoformat(),
    }


__all__ = [
    "CliDecisionActorType",
    "CliDecisionRecord",
    "CliDecisionVerdict",
    "build_cli_decision_audit_payload",
    "build_cli_decision_event_payload",
    "record_decision",
]
