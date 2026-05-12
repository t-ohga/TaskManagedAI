"""Input Trust Layer: server-owned trust_level promotion (Sprint 5.5 BL-0065).

`untrusted_content -> validated_artifact -> trusted_instruction` の 3 段階を
**server-owned** で扱う薄い decision service。caller / API endpoint /
Server Action から ``trust_level`` を直接指定する経路は **signature レベルで
物理削除** されている (SP55-B1-F-001 fix: ``current_trust_level`` も caller
入力ではなく、artifact_id をもとに server 側で repository から resolve した
値を ``promote_to_*`` の internal-only keyword argument として渡す)。

- ``promote_to_validated_artifact``: ``schema_validation_passed`` AND
  ``policy_lint_passed`` で自動昇格。どちらかが False なら deny。
- ``promote_to_trusted_instruction``: human approval 経路を要求する skeleton。
  ``policy_pack.input_trust.trust_level_promotion_to_trusted_instruction_requires_human_approval``
  が True (P0 default) の間、approval_passed が真でなければ deny。
  Approval 4 整合 + decider human-only の完全な enforcement は BL-0069 で
  本 service 経由に統合される。

ADR-00009 §Sprint 5.5 update / SP-005-5 BL-0065 設計判断 /
.claude/rules/server-owned-boundary.md §1。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.domain.artifact.trust_level import TrustLevel
from backend.app.services.input_trust.approval_integrity import (
    ApprovalIntegrityExpectation,
    verify_approval_4_integrity,
)
from backend.app.services.policy_pack.loader import PolicyPack, get_policy_pack

if TYPE_CHECKING:
    from backend.app.db.models.approval_request import ApprovalRequest

PromotionDenialReason = Literal[
    "schema_validation_failed",
    "policy_lint_failed",
    "approval_not_passed",
    "decider_not_human",
    "approval_4_integrity_mismatch",
    "caller_supplied_path_attempt",
    "already_at_or_above_target",
    "invalid_current_trust_level",
]


class PromoteRequest(BaseModel):
    """Caller-facing schema. NOTE: ``trust_level`` / ``current_trust_level`` are
    NOT exposed here.

    ``extra="forbid"`` rejects any caller-supplied trust-level field at
    schema validation time (`.claude/rules/server-owned-boundary.md` §1
    invariant). The actual ``trust_level`` AND the current trust_level used
    in the decision are resolved server-side from the artifact identified
    by ``artifact_id`` — production callers fetch the row from the artifact
    repository and pass ``current_trust_level`` as an internal-only
    keyword argument to ``promote_to_*``. BL-0067 (Sprint 5.5 batch 2)
    wires that repository lookup.
    """

    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(..., min_length=1, max_length=64)


@dataclass(frozen=True)
class PromotionDecision:
    """Server-side decision for a trust_level promotion attempt."""

    promoted: bool
    from_trust_level: TrustLevel
    to_trust_level: TrustLevel
    denial_reason: PromotionDenialReason | None = None


def _deny(
    *,
    current: TrustLevel,
    target: TrustLevel,
    reason: PromotionDenialReason,
) -> PromotionDecision:
    return PromotionDecision(
        promoted=False,
        from_trust_level=current,
        to_trust_level=target,
        denial_reason=reason,
    )


def promote_to_validated_artifact(
    request: PromoteRequest,
    *,
    current_trust_level: TrustLevel,
    schema_validation_passed: bool,
    policy_lint_passed: bool,
) -> PromotionDecision:
    """Promote ``untrusted_content -> validated_artifact`` server-side.

    ``current_trust_level`` is an internal-only keyword argument: production
    callers MUST resolve it server-side from ``request.artifact_id`` via the
    artifact repository, never from caller-supplied input.

    Both schema validation and policy lint MUST have passed. The decision
    is informational; the caller writes the new ``trust_level`` value into
    ``artifacts.trust_level`` only when ``promoted is True``.
    """

    _ = request  # artifact_id is the canonical lookup key for caller wiring
    if current_trust_level == "trusted_instruction":
        return _deny(
            current=current_trust_level,
            target="validated_artifact",
            reason="already_at_or_above_target",
        )
    if current_trust_level == "validated_artifact":
        # Idempotent no-op: caller may re-invoke after schema/policy refresh.
        return PromotionDecision(
            promoted=True,
            from_trust_level=current_trust_level,
            to_trust_level="validated_artifact",
        )
    if current_trust_level != "untrusted_content":
        return _deny(
            current=current_trust_level,
            target="validated_artifact",
            reason="invalid_current_trust_level",
        )

    if not schema_validation_passed:
        return _deny(
            current=current_trust_level,
            target="validated_artifact",
            reason="schema_validation_failed",
        )
    if not policy_lint_passed:
        return _deny(
            current=current_trust_level,
            target="validated_artifact",
            reason="policy_lint_failed",
        )

    return PromotionDecision(
        promoted=True,
        from_trust_level=current_trust_level,
        to_trust_level="validated_artifact",
    )


def promote_to_trusted_instruction(
    request: PromoteRequest,
    *,
    current_trust_level: TrustLevel,
    approval_passed: bool,
    decider_is_human: bool,
    approval_request: ApprovalRequest,
    expected_integrity: ApprovalIntegrityExpectation,
    policy_pack: PolicyPack | None = None,
) -> PromotionDecision:
    """Promote ``validated_artifact -> trusted_instruction`` (human approval).

    ``current_trust_level`` is an internal-only keyword argument (same
    invariant as ``promote_to_validated_artifact``).

    Sprint 5.5 BL-0069 (SP55-B4-R2-F-001 fix): both ``approval_request``
    and ``expected_integrity`` are **required** so the 4 integrity fields
    (artifact_hash / policy_version / provider_request_fingerprint /
    action_class) are always verified server-side. There is no legacy
    bool fallback — every caller MUST supply a real ApprovalRequest
    record. ``approval_passed`` and ``decider_is_human`` remain
    caller-supplied because they reflect the approval workflow state /
    decider Actor type which the orchestrator resolves from the
    ApprovalRequest + Actor tables before calling this service.

    Approval 4 整合 + decider human-only の完全な enforcement は本 service
    で完結し、``ApprovalRequest`` record の artifact_hash / policy_version /
    provider_request_fingerprint / action_class hash binding が drift してい
    れば deny される (stale approval invalidation)。
    ``server-owned-boundary.md §3`` (Approval 4 整合) 不変条件継続。
    """

    _ = request
    if current_trust_level == "trusted_instruction":
        return _deny(
            current=current_trust_level,
            target="trusted_instruction",
            reason="already_at_or_above_target",
        )
    if current_trust_level != "validated_artifact":
        return _deny(
            current=current_trust_level,
            target="trusted_instruction",
            reason="invalid_current_trust_level",
        )

    # SP55-B4-R2-F-001 / SP55-B4-R3-F-001 fix: server-side 4-integrity
    # verification is mandatory AND policy-independent. ``server-owned-boundary.md
    # §3`` requires that ANY of the 4 fields drifting invalidates the
    # approval; the policy toggle controls only whether human approval is
    # *additionally* required, never whether the integrity gate runs.
    if not verify_approval_4_integrity(approval_request, expected_integrity):
        return _deny(
            current=current_trust_level,
            target="trusted_instruction",
            reason="approval_4_integrity_mismatch",
        )

    pack = policy_pack if policy_pack is not None else get_policy_pack()
    if pack.trust_level_promotion_to_trusted_instruction_requires_human_approval:
        if not approval_passed:
            return _deny(
                current=current_trust_level,
                target="trusted_instruction",
                reason="approval_not_passed",
            )
        if not decider_is_human:
            return _deny(
                current=current_trust_level,
                target="trusted_instruction",
                reason="decider_not_human",
            )

    return PromotionDecision(
        promoted=True,
        from_trust_level=current_trust_level,
        to_trust_level="trusted_instruction",
    )


__all__ = [
    "PromoteRequest",
    "PromotionDecision",
    "PromotionDenialReason",
    "promote_to_trusted_instruction",
    "promote_to_validated_artifact",
]
