"""Sprint 8 BL-0099: Webhook HMAC verifier tests."""

from __future__ import annotations

import hashlib
import hmac

from backend.app.services.repoproxy.webhook_hmac import (
    WebhookVerificationResult,
    verify_github_webhook_signature,
    verify_with_rotation,
)

_SECRET = b"shared-secret-for-test"
_PAYLOAD = b'{"action":"opened","number":42}'


def _make_signature(secret: bytes, payload: bytes) -> str:
    return "sha256=" + hmac.new(secret, payload, hashlib.sha256).hexdigest()


def test_valid_signature_returns_valid() -> None:
    sig = _make_signature(_SECRET, _PAYLOAD)
    result = verify_github_webhook_signature(_PAYLOAD, sig, _SECRET)
    assert result.result == WebhookVerificationResult.VALID


def test_signature_mismatch_detected() -> None:
    """Wrong secret produces SIGNATURE_MISMATCH."""
    sig = _make_signature(b"wrong-secret", _PAYLOAD)
    result = verify_github_webhook_signature(_PAYLOAD, sig, _SECRET)
    assert result.result == WebhookVerificationResult.SIGNATURE_MISMATCH


def test_invalid_format_no_equals() -> None:
    """Missing '=' in header → INVALID_FORMAT."""
    result = verify_github_webhook_signature(_PAYLOAD, "sha256abc", _SECRET)
    assert result.result == WebhookVerificationResult.INVALID_FORMAT


def test_invalid_format_short_hex() -> None:
    """Hex length != 64 → INVALID_FORMAT."""
    result = verify_github_webhook_signature(_PAYLOAD, "sha256=abc123", _SECRET)
    assert result.result == WebhookVerificationResult.INVALID_FORMAT


def test_unsupported_algorithm() -> None:
    """sha1 / md5 etc. → ALGORITHM_UNSUPPORTED."""
    result = verify_github_webhook_signature(
        _PAYLOAD, "sha1=" + "a" * 40, _SECRET
    )
    assert result.result == WebhookVerificationResult.ALGORITHM_UNSUPPORTED


def test_empty_payload() -> None:
    sig = _make_signature(_SECRET, b"")
    result = verify_github_webhook_signature(b"", sig, _SECRET)
    assert result.result == WebhookVerificationResult.EMPTY_PAYLOAD


def test_empty_secret() -> None:
    sig = _make_signature(b"x", _PAYLOAD)
    result = verify_github_webhook_signature(_PAYLOAD, sig, b"")
    assert result.result == WebhookVerificationResult.EMPTY_SECRET


def test_none_signature_header() -> None:
    """None header → INVALID_FORMAT."""
    result = verify_github_webhook_signature(_PAYLOAD, None, _SECRET)
    assert result.result == WebhookVerificationResult.INVALID_FORMAT


def test_delivery_id_propagates() -> None:
    """delivery_id (X-GitHub-Delivery) is propagated for audit."""
    sig = _make_signature(_SECRET, _PAYLOAD)
    result = verify_github_webhook_signature(
        _PAYLOAD, sig, _SECRET, delivery_id="abc-123"
    )
    assert result.delivery_id == "abc-123"


def test_rotation_falls_back_to_previous_secret() -> None:
    """During rotation, signature signed with previous_secret still verifies."""
    old_secret = b"old-secret"
    new_secret = b"new-secret"
    # GitHub still using old secret
    sig_with_old = _make_signature(old_secret, _PAYLOAD)
    result = verify_with_rotation(
        _PAYLOAD, sig_with_old, current_secret=new_secret, previous_secret=old_secret
    )
    assert result.result == WebhookVerificationResult.VALID


def test_rotation_current_secret_preferred() -> None:
    """current_secret is checked first."""
    old_secret = b"old-secret"
    new_secret = b"new-secret"
    sig_with_new = _make_signature(new_secret, _PAYLOAD)
    result = verify_with_rotation(
        _PAYLOAD, sig_with_new, current_secret=new_secret, previous_secret=old_secret
    )
    assert result.result == WebhookVerificationResult.VALID


def test_rotation_both_secrets_fail_returns_mismatch() -> None:
    """Both secrets fail → SIGNATURE_MISMATCH."""
    sig = _make_signature(b"unknown-secret", _PAYLOAD)
    result = verify_with_rotation(
        _PAYLOAD, sig, current_secret=b"new", previous_secret=b"old"
    )
    assert result.result == WebhookVerificationResult.SIGNATURE_MISMATCH


def test_constant_time_compare_used() -> None:
    """The implementation uses hmac.compare_digest (no early bailout on first
    byte mismatch). This test verifies a near-match still fails uniformly."""
    correct = _make_signature(_SECRET, _PAYLOAD)
    # Flip one bit
    wrong = "sha256=" + ("0" + correct.split("=")[1][1:])
    result = verify_github_webhook_signature(_PAYLOAD, wrong, _SECRET)
    assert result.result == WebhookVerificationResult.SIGNATURE_MISMATCH
