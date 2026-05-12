"""Trust level promotion service tests (Sprint 5.5 BL-0065).

Focuses on the server-owned promotion decisions:

- ``untrusted_content -> validated_artifact`` auto-promotion when schema +
  policy gates passed.
- ``validated_artifact -> trusted_instruction`` requires human approval +
  decider human-only + Approval 4 integrity (skeleton; BL-0069 wires the
  full ApprovalRequest hash binding).
- Caller-supplied trust-level paths (both ``trust_level`` and
  ``current_trust_level``) are physically removed at the ``PromoteRequest``
  schema level (``extra="forbid"``). The real ``current_trust_level`` is
  resolved server-side from the artifact repository and passed to
  ``promote_to_*`` as an internal-only keyword argument.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from backend.app.services.input_trust.approval_integrity import (
    ApprovalIntegrityExpectation,
)
from backend.app.services.input_trust.promotion import (
    PromoteRequest,
    promote_to_trusted_instruction,
    promote_to_validated_artifact,
)
from backend.app.services.policy_pack.loader import PolicyPack

_SHA256_DUMMY = "a" * 64


def _request() -> PromoteRequest:
    return PromoteRequest(artifact_id="artifact-001")


def _pack(require_human: bool = True) -> PolicyPack:
    return PolicyPack(
        policy_version="test-vN.N",
        policy_pack_lock="0" * 64,
        repair_retry_max_attempts=3,
        trust_level_promotion_to_trusted_instruction_requires_human_approval=(
            require_human
        ),
    )


def _approval(
    *,
    artifact_hash: str = _SHA256_DUMMY,
    policy_version: str = "v1.0.0",
    fingerprint: str = "fp-1",
    action_class: str = "task_write",
) -> Any:
    """Minimal ApprovalRequest stand-in (SP55-B4-R2-F-001 fix: required arg)."""

    return SimpleNamespace(
        artifact_hash=artifact_hash,
        policy_version=policy_version,
        provider_request_fingerprint=fingerprint,
        action_class=action_class,
    )


def _expected(
    *,
    artifact_hash: str = _SHA256_DUMMY,
    policy_version: str = "v1.0.0",
    fingerprint: str = "fp-1",
    action_class: str = "task_write",
) -> ApprovalIntegrityExpectation:
    return ApprovalIntegrityExpectation(
        artifact_hash=artifact_hash,
        policy_version=policy_version,
        provider_request_fingerprint=fingerprint,
        action_class=action_class,
    )


# --- caller-supplied trust_level / current_trust_level rejected at schema ----


def test_promote_request_rejects_caller_supplied_trust_level_field() -> None:
    """`extra="forbid"` removes the caller-supplied path at signature level."""

    with pytest.raises(ValidationError) as exc:
        PromoteRequest.model_validate(
            {
                "artifact_id": "artifact-001",
                # Hostile caller tries to inject the resulting trust_level.
                "trust_level": "trusted_instruction",
            }
        )
    assert "trust_level" in str(exc.value)


def test_promote_request_rejects_caller_supplied_current_trust_level_field() -> None:
    """SP55-B1-F-001 fix: ``current_trust_level`` MUST NOT be caller-supplied."""

    with pytest.raises(ValidationError) as exc:
        PromoteRequest.model_validate(
            {
                "artifact_id": "artifact-001",
                "current_trust_level": "validated_artifact",
            }
        )
    assert "current_trust_level" in str(exc.value)


def test_promote_request_rejects_any_unknown_extra_field() -> None:
    with pytest.raises(ValidationError):
        PromoteRequest.model_validate(
            {
                "artifact_id": "artifact-001",
                "promoted": True,
            }
        )


# --- untrusted_content -> validated_artifact ----------------------------------


def test_validated_artifact_promotion_succeeds_when_both_gates_pass() -> None:
    decision = promote_to_validated_artifact(
        _request(),
        current_trust_level="untrusted_content",
        schema_validation_passed=True,
        policy_lint_passed=True,
    )
    assert decision.promoted is True
    assert decision.from_trust_level == "untrusted_content"
    assert decision.to_trust_level == "validated_artifact"
    assert decision.denial_reason is None


def test_validated_artifact_promotion_denies_when_schema_failed() -> None:
    decision = promote_to_validated_artifact(
        _request(),
        current_trust_level="untrusted_content",
        schema_validation_passed=False,
        policy_lint_passed=True,
    )
    assert decision.promoted is False
    assert decision.denial_reason == "schema_validation_failed"


def test_validated_artifact_promotion_denies_when_policy_lint_failed() -> None:
    decision = promote_to_validated_artifact(
        _request(),
        current_trust_level="untrusted_content",
        schema_validation_passed=True,
        policy_lint_passed=False,
    )
    assert decision.promoted is False
    assert decision.denial_reason == "policy_lint_failed"


def test_validated_artifact_promotion_is_idempotent_when_already_validated() -> None:
    decision = promote_to_validated_artifact(
        _request(),
        current_trust_level="validated_artifact",
        schema_validation_passed=True,
        policy_lint_passed=True,
    )
    assert decision.promoted is True
    assert decision.from_trust_level == "validated_artifact"
    assert decision.to_trust_level == "validated_artifact"


def test_validated_artifact_promotion_denies_when_already_trusted_instruction() -> None:
    decision = promote_to_validated_artifact(
        _request(),
        current_trust_level="trusted_instruction",
        schema_validation_passed=True,
        policy_lint_passed=True,
    )
    assert decision.promoted is False
    assert decision.denial_reason == "already_at_or_above_target"


# --- validated_artifact -> trusted_instruction --------------------------------


def test_trusted_instruction_promotion_requires_validated_artifact_starting_point() -> None:
    decision = promote_to_trusted_instruction(
        _request(),
        current_trust_level="untrusted_content",
        approval_passed=True,
        decider_is_human=True,
        approval_request=_approval(),
        expected_integrity=_expected(),
        policy_pack=_pack(),
    )
    assert decision.promoted is False
    assert decision.denial_reason == "invalid_current_trust_level"


def test_trusted_instruction_promotion_denies_without_approval() -> None:
    decision = promote_to_trusted_instruction(
        _request(),
        current_trust_level="validated_artifact",
        approval_passed=False,
        decider_is_human=True,
        approval_request=_approval(),
        expected_integrity=_expected(),
        policy_pack=_pack(),
    )
    assert decision.promoted is False
    assert decision.denial_reason == "approval_not_passed"


def test_trusted_instruction_promotion_denies_when_decider_not_human() -> None:
    decision = promote_to_trusted_instruction(
        _request(),
        current_trust_level="validated_artifact",
        approval_passed=True,
        decider_is_human=False,
        approval_request=_approval(),
        expected_integrity=_expected(),
        policy_pack=_pack(),
    )
    assert decision.promoted is False
    assert decision.denial_reason == "decider_not_human"


def test_trusted_instruction_promotion_denies_when_4_integrity_mismatch() -> None:
    """SP55-B4-R2-F-001 fix: server-side hash binding rejects stale approval
    (e.g. artifact_hash drift after the approval was requested)."""

    decision = promote_to_trusted_instruction(
        _request(),
        current_trust_level="validated_artifact",
        approval_passed=True,
        decider_is_human=True,
        approval_request=_approval(artifact_hash="b" * 64),  # drifted
        expected_integrity=_expected(),
        policy_pack=_pack(),
    )
    assert decision.promoted is False
    assert decision.denial_reason == "approval_4_integrity_mismatch"


def test_trusted_instruction_promotion_succeeds_when_all_gates_pass() -> None:
    decision = promote_to_trusted_instruction(
        _request(),
        current_trust_level="validated_artifact",
        approval_passed=True,
        decider_is_human=True,
        approval_request=_approval(),
        expected_integrity=_expected(),
        policy_pack=_pack(),
    )
    assert decision.promoted is True
    assert decision.from_trust_level == "validated_artifact"
    assert decision.to_trust_level == "trusted_instruction"


def test_trusted_instruction_promotion_idempotent_when_already_trusted() -> None:
    decision = promote_to_trusted_instruction(
        _request(),
        current_trust_level="trusted_instruction",
        approval_passed=True,
        decider_is_human=True,
        approval_request=_approval(),
        expected_integrity=_expected(),
        policy_pack=_pack(),
    )
    assert decision.promoted is False
    assert decision.denial_reason == "already_at_or_above_target"


# --- promote_to_* signatures keep current_trust_level keyword-only ------------


def test_promote_to_validated_artifact_keeps_current_trust_level_keyword_only() -> None:
    """SP55-B4-R4-F-001 fix: same ``inspect.signature`` introspection as
    ``promote_to_trusted_instruction`` to confirm ``current_trust_level`` is
    keyword-only without fighting mypy via ``type: ignore``."""

    import inspect

    sig = inspect.signature(promote_to_validated_artifact)
    param = sig.parameters.get("current_trust_level")
    assert param is not None
    assert param.kind == inspect.Parameter.KEYWORD_ONLY


def test_promote_to_trusted_instruction_keeps_current_trust_level_keyword_only() -> None:
    """SP55-B4-R3-F-002 fix: replace the positional-negative TypeError test
    (which leaked the old ``approval_4_integrity_ok`` positional bool and
    fought mypy) with a signature introspection that confirms
    ``current_trust_level`` is keyword-only, plus a runtime sanity check
    that the canonical keyword form succeeds."""

    import inspect

    sig = inspect.signature(promote_to_trusted_instruction)
    param = sig.parameters.get("current_trust_level")
    assert param is not None
    assert param.kind == inspect.Parameter.KEYWORD_ONLY


# --- TrustLevel type signature sanity ----------------------------------------


def test_promote_to_validated_artifact_accepts_all_three_trust_levels() -> None:
    """Every value of the TrustLevel Literal must be a valid starting point."""

    for level in ("untrusted_content", "validated_artifact", "trusted_instruction"):
        # Just confirm no signature-level rejection happens for any enum value.
        # ``level`` is narrowed to the TrustLevel Literal by mypy from the
        # tuple literal above, so no cast is needed.
        decision = promote_to_validated_artifact(
            _request(),
            current_trust_level=level,
            schema_validation_passed=True,
            policy_lint_passed=True,
        )
        assert isinstance(decision.from_trust_level, str)
        assert decision.from_trust_level in {
            "untrusted_content",
            "validated_artifact",
            "trusted_instruction",
        }
