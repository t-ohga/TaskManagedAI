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
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.domain.artifact.trust_level import TrustLevel
from backend.app.services.policy_pack.loader import PolicyPack, get_policy_pack

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
    approval_4_integrity_ok: bool,
    policy_pack: PolicyPack | None = None,
) -> PromotionDecision:
    """Promote ``validated_artifact -> trusted_instruction`` (human approval).

    ``current_trust_level`` is an internal-only keyword argument (same
    invariant as ``promote_to_validated_artifact``).

    Sprint 5.5 BL-0065 では service skeleton として最小限の gate を実装する。
    Approval 4 整合 + decider human-only の完全な enforcement は BL-0069 で
    本 service 経由に統合され、その時点で ``approval_4_integrity_ok`` の
    判定が ``ApprovalRequest`` の artifact_hash / policy_version /
    provider_request_fingerprint / action_class hash binding として
    完成する。
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
        if not approval_4_integrity_ok:
            return _deny(
                current=current_trust_level,
                target="trusted_instruction",
                reason="approval_4_integrity_mismatch",
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
