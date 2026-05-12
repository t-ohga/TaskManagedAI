"""Sprint 5.5 BL-0069: Approval 4 integrity hash binding tests.

Verifies the server-side 4 integrity verification of trust_level promotion:

- ``compute_approval_4_integrity_hash`` is deterministic + sensitive to each
  of the 4 fields (drift detection)
- ``verify_approval_4_integrity`` matches when all 4 fields agree, rejects
  when any one drifts
- ``promote_to_trusted_instruction`` with ``approval_request`` +
  ``expected_integrity`` overrides the caller-supplied
  ``approval_4_integrity_ok`` bool with the server-side verdict
- self-approval still denied at the service layer (defense-in-depth with
  the DB CHECK constraint ``approval_requests_ck_self_approval``)
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.services.input_trust.approval_integrity import (
    ApprovalIntegrityExpectation,
    compute_approval_4_integrity_hash,
    verify_approval_4_integrity,
)
from backend.app.services.input_trust.promotion import (
    PromoteRequest,
    promote_to_trusted_instruction,
)
from backend.app.services.policy_pack.loader import PolicyPack

_SHA256_DUMMY = "a" * 64
_SHA256_OTHER = "b" * 64


def _pack(require_human: bool = True) -> PolicyPack:
    return PolicyPack(
        policy_version="test-vN.N",
        policy_pack_lock="0" * 64,
        repair_retry_max_attempts=3,
        trust_level_promotion_to_trusted_instruction_requires_human_approval=(
            require_human
        ),
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


def _approval(
    *,
    artifact_hash: str = _SHA256_DUMMY,
    policy_version: str = "v1.0.0",
    fingerprint: str = "fp-1",
    action_class: str = "task_write",
) -> Any:
    """Minimal ApprovalRequest stand-in for service-layer unit tests.

    A ``SimpleNamespace`` is sufficient because ``verify_approval_4_integrity``
    only reads the 4 fields by attribute access. DB-bound behaviour (FK,
    CHECK constraints) is covered in the integration test in Sprint 5.5
    batch 4 DB integration suite.
    """

    return SimpleNamespace(
        artifact_hash=artifact_hash,
        policy_version=policy_version,
        provider_request_fingerprint=fingerprint,
        action_class=action_class,
    )


# ---------------------------------------------------------------------------
# compute_approval_4_integrity_hash: deterministic + drift detection.
# ---------------------------------------------------------------------------


def test_compute_hash_is_deterministic() -> None:
    a = compute_approval_4_integrity_hash(
        artifact_hash=_SHA256_DUMMY,
        policy_version="v1",
        provider_request_fingerprint="fp",
        action_class="task_write",
    )
    b = compute_approval_4_integrity_hash(
        artifact_hash=_SHA256_DUMMY,
        policy_version="v1",
        provider_request_fingerprint="fp",
        action_class="task_write",
    )
    assert a == b
    assert len(a) == 64


@pytest.mark.parametrize(
    ("kwargs_a", "kwargs_b"),
    [
        ({"artifact_hash": _SHA256_DUMMY}, {"artifact_hash": _SHA256_OTHER}),
        ({"policy_version": "v1"}, {"policy_version": "v2"}),
        ({"provider_request_fingerprint": "fp-1"}, {"provider_request_fingerprint": "fp-2"}),
        ({"action_class": "task_write"}, {"action_class": "repo_write"}),
    ],
)
def test_compute_hash_drift_detected_per_field(
    kwargs_a: dict[str, str],
    kwargs_b: dict[str, str],
) -> None:
    """Each of the 4 fields independently affects the hash."""

    base = {
        "artifact_hash": _SHA256_DUMMY,
        "policy_version": "v1",
        "provider_request_fingerprint": "fp-1",
        "action_class": "task_write",
    }
    hash_a = compute_approval_4_integrity_hash(**{**base, **kwargs_a})
    hash_b = compute_approval_4_integrity_hash(**{**base, **kwargs_b})
    assert hash_a != hash_b


def test_compute_hash_rejects_empty_artifact_hash() -> None:
    with pytest.raises(ValueError, match="artifact_hash"):
        compute_approval_4_integrity_hash(
            artifact_hash="",
            policy_version="v1",
            provider_request_fingerprint="fp",
            action_class="task_write",
        )


def test_compute_hash_rejects_non_sha256_artifact_hash() -> None:
    with pytest.raises(ValueError, match=r"SHA-256 hex"):
        compute_approval_4_integrity_hash(
            artifact_hash="short",
            policy_version="v1",
            provider_request_fingerprint="fp",
            action_class="task_write",
        )


# SP55-B4-F-001 fix: hex regex check (not just length).


@pytest.mark.parametrize(
    "bogus_hex",
    [
        "g" * 64,  # invalid hex character ('g' is outside [0-9a-f])
        "A" * 64,  # uppercase hex - must be rejected (canonical = lowercase)
        "0" * 63 + "G",  # trailing invalid char
        "0" * 63 + " ",  # trailing whitespace
        "0" * 65,  # too long but otherwise hex
    ],
)
def test_compute_hash_rejects_artifact_hash_failing_sha256_hex_regex(
    bogus_hex: str,
) -> None:
    """SP55-B4-F-001 fix: artifact_hash must match
    ``^[0-9a-f]{64}$`` (matches ``artifacts.content_hash`` DB CHECK)."""

    with pytest.raises(ValueError, match=r"SHA-256 hex"):
        compute_approval_4_integrity_hash(
            artifact_hash=bogus_hex,
            policy_version="v1",
            provider_request_fingerprint="fp",
            action_class="task_write",
        )


@pytest.mark.parametrize(
    "field_name",
    ["policy_version", "provider_request_fingerprint", "action_class"],
)
def test_compute_hash_rejects_empty_non_artifact_field(field_name: str) -> None:
    kwargs = {
        "artifact_hash": _SHA256_DUMMY,
        "policy_version": "v1",
        "provider_request_fingerprint": "fp",
        "action_class": "task_write",
        field_name: "",
    }
    with pytest.raises(ValueError, match=field_name):
        compute_approval_4_integrity_hash(**kwargs)


# ---------------------------------------------------------------------------
# verify_approval_4_integrity: drift -> False; full match -> True.
# ---------------------------------------------------------------------------


def test_verify_approval_returns_true_when_all_four_fields_match() -> None:
    approval = _approval()
    expected = _expected()
    assert verify_approval_4_integrity(approval, expected) is True


@pytest.mark.parametrize(
    "drift_field",
    ["artifact_hash", "policy_version", "provider_request_fingerprint", "action_class"],
)
def test_verify_approval_returns_false_when_any_field_drifts(drift_field: str) -> None:
    """Each of the 4 fields independently invalidates the approval."""

    approval = _approval()
    expected_kwargs: dict[str, str] = {
        "artifact_hash": _SHA256_DUMMY,
        "policy_version": "v1.0.0",
        "fingerprint": "fp-1",
        "action_class": "task_write",
    }
    # Drift one field
    drift_map = {
        "artifact_hash": ("artifact_hash", _SHA256_OTHER),
        "policy_version": ("policy_version", "v2.0.0"),
        "provider_request_fingerprint": ("fingerprint", "fp-DRIFTED"),
        "action_class": ("action_class", "repo_write"),
    }
    drift_key, drift_value = drift_map[drift_field]
    expected_kwargs[drift_key] = drift_value
    expected = _expected(**expected_kwargs)
    assert verify_approval_4_integrity(approval, expected) is False


# ---------------------------------------------------------------------------
# promote_to_trusted_instruction: server-side verification overrides caller bool.
# ---------------------------------------------------------------------------


def test_promote_with_approval_request_succeeds_when_4_fields_match() -> None:
    """SP55-B4-R2-F-001 fix: server-side verification is the SOLE gate; the
    legacy caller-supplied bool has been removed."""

    decision = promote_to_trusted_instruction(
        PromoteRequest(artifact_id="artifact-001"),
        current_trust_level="validated_artifact",
        approval_passed=True,
        decider_is_human=True,
        approval_request=_approval(),
        expected_integrity=_expected(),
        policy_pack=_pack(),
    )
    assert decision.promoted is True
    assert decision.to_trust_level == "trusted_instruction"


def test_promote_with_approval_request_denies_when_field_drifts() -> None:
    """Server-side verification denies on any of the 4 fields drifting."""

    drifted = _approval(artifact_hash=_SHA256_OTHER)
    decision = promote_to_trusted_instruction(
        PromoteRequest(artifact_id="artifact-001"),
        current_trust_level="validated_artifact",
        approval_passed=True,
        decider_is_human=True,
        approval_request=drifted,
        expected_integrity=_expected(),
        policy_pack=_pack(),
    )
    assert decision.promoted is False
    assert decision.denial_reason == "approval_4_integrity_mismatch"


def test_promote_requires_approval_request_and_expected_integrity() -> None:
    """SP55-B4-R2-F-001 fix: both ``approval_request`` and
    ``expected_integrity`` are mandatory — the legacy bool fallback was
    removed because it let callers short-circuit the server-side hash
    binding. Omitting either raises a ``TypeError`` at the signature layer."""

    with pytest.raises(TypeError):
        promote_to_trusted_instruction(  # type: ignore[call-arg]
            PromoteRequest(artifact_id="artifact-001"),
            current_trust_level="validated_artifact",
            approval_passed=True,
            decider_is_human=True,
            policy_pack=_pack(),
            # approval_request and expected_integrity missing — must raise
        )


# ---------------------------------------------------------------------------
# Policy pack interaction: human approval gate still mandatory.
# ---------------------------------------------------------------------------


def test_promote_denies_integrity_mismatch_even_when_policy_disables_human_approval() -> None:
    """SP55-B4-R3-F-001 fix: the Approval 4 integrity gate must run
    independently of the policy toggle. Even if
    ``trust_level_promotion_to_trusted_instruction_requires_human_approval``
    is False (P0.1+ auto-promotion scenario), drifted 4-integrity fields
    still invalidate the approval (server-owned-boundary.md §3)."""

    drifted = _approval(artifact_hash=_SHA256_OTHER)
    decision = promote_to_trusted_instruction(
        PromoteRequest(artifact_id="artifact-001"),
        current_trust_level="validated_artifact",
        approval_passed=True,
        decider_is_human=True,
        approval_request=drifted,
        expected_integrity=_expected(),
        policy_pack=_pack(require_human=False),  # toggle off
    )
    assert decision.promoted is False
    assert decision.denial_reason == "approval_4_integrity_mismatch"


def test_promote_with_approval_request_still_blocked_when_human_not_approved() -> None:
    """Even with 4-integrity OK + decider human, ``approval_passed=False``
    still blocks (policy_pack require_human_approval gate)."""

    decision = promote_to_trusted_instruction(
        PromoteRequest(artifact_id="artifact-001"),
        current_trust_level="validated_artifact",
        approval_passed=False,
        decider_is_human=True,
        approval_request=_approval(),
        expected_integrity=_expected(),
        policy_pack=_pack(),
    )
    assert decision.promoted is False
    assert decision.denial_reason == "approval_not_passed"


def test_promote_with_approval_request_still_blocked_when_decider_not_human() -> None:
    decision = promote_to_trusted_instruction(
        PromoteRequest(artifact_id="artifact-001"),
        current_trust_level="validated_artifact",
        approval_passed=True,
        decider_is_human=False,
        approval_request=_approval(),
        expected_integrity=_expected(),
        policy_pack=_pack(),
    )
    assert decision.promoted is False
    assert decision.denial_reason == "decider_not_human"
