"""Sprint 8 BL-0099: GitHub Webhook HMAC SHA-256 **low-level pure helper**.

**PENDING SPRINT 11** (Codex audit F-003 adopt、2026-05-13):
- 本 module は **HMAC 計算の low-level pure helper のみ**。SecretBroker
  mediated resolve / Redis SETNX による delivery_id replay 拒否 / previous
  secret の `deprecated|pending` status 検証 (7 日 grace window) / audit
  event emission は **Sprint 11 で service layer として実装**。
- Sprint 11 で公開境界を ``verify_github_webhook(request, secret_ref_current,
  secret_ref_previous, delivery_id)`` に refactor、current/previous secret は
  SecretBroker が内部 resolve し、delivery_id は tenant+installation 単位で
  atomic nonce 登録 (replay detection)、previous secret の status を DB
  metadata で検証する。
- 現状の ``secret: bytes`` / ``previous_secret: bytes`` 直接受け取りは
  test 用、production 経路では使わない (caller-supplied raw secret pass-through
  リスクあり)。

ADR-00011 §Webhook HMAC (将来 contract):
- GitHub から `X-Hub-Signature-256: sha256=<hex>` で送信される signature を
  `hmac.compare_digest` で constant-time 比較 (timing attack 防御) — 本 module で実装
- Webhook secret は SecretBroker 経由 resolve (`secret://sops/p0/github_webhook_hmac#v1`)
  — Sprint 11
- Replay 防止: delivery_id を Redis に 1 hour 記録、重複なら deny — Sprint 11
- Secret rotation 中は新旧 2 secret 並行 verify (grace period 7 日) — 本 module で
  低レベル helper、Sprint 11 で secret_refs.status 検証付き service layer
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from enum import StrEnum


class WebhookVerificationResult(StrEnum):
    """Webhook signature verification result enum."""

    VALID = "valid"
    INVALID_FORMAT = "invalid_format"
    SIGNATURE_MISMATCH = "signature_mismatch"
    ALGORITHM_UNSUPPORTED = "algorithm_unsupported"
    EMPTY_PAYLOAD = "empty_payload"
    EMPTY_SECRET = "empty_secret"  # noqa: S105


@dataclass(frozen=True, slots=True)
class WebhookVerification:
    """Verification result with reason code."""

    result: WebhookVerificationResult
    delivery_id: str | None = None


def verify_github_webhook_signature(
    payload: bytes,
    signature_header: str | None,
    secret: bytes,
    delivery_id: str | None = None,
) -> WebhookVerification:
    """Verify GitHub webhook signature against payload.

    Args:
        payload: raw request body bytes (exactly as received)
        signature_header: ``X-Hub-Signature-256`` header value (e.g.,
            ``sha256=abc123...``). None / empty → INVALID_FORMAT.
        secret: shared secret bytes (resolved from SecretBroker)
        delivery_id: optional ``X-GitHub-Delivery`` UUID for audit + replay

    Returns:
        WebhookVerification with result enum
    """
    if not payload:
        return WebhookVerification(
            result=WebhookVerificationResult.EMPTY_PAYLOAD,
            delivery_id=delivery_id,
        )

    if not secret:
        return WebhookVerification(
            result=WebhookVerificationResult.EMPTY_SECRET,
            delivery_id=delivery_id,
        )

    if not signature_header:
        return WebhookVerification(
            result=WebhookVerificationResult.INVALID_FORMAT,
            delivery_id=delivery_id,
        )

    # Expected format: "sha256=<64 hex chars>"
    if "=" not in signature_header:
        return WebhookVerification(
            result=WebhookVerificationResult.INVALID_FORMAT,
            delivery_id=delivery_id,
        )

    algorithm, _, provided_hex = signature_header.partition("=")
    if algorithm.lower() != "sha256":
        return WebhookVerification(
            result=WebhookVerificationResult.ALGORITHM_UNSUPPORTED,
            delivery_id=delivery_id,
        )

    if len(provided_hex) != 64:
        return WebhookVerification(
            result=WebhookVerificationResult.INVALID_FORMAT,
            delivery_id=delivery_id,
        )

    # Compute expected HMAC
    expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()

    # Constant-time compare (defeats timing attacks)
    if not hmac.compare_digest(expected, provided_hex):
        return WebhookVerification(
            result=WebhookVerificationResult.SIGNATURE_MISMATCH,
            delivery_id=delivery_id,
        )

    return WebhookVerification(
        result=WebhookVerificationResult.VALID,
        delivery_id=delivery_id,
    )


def verify_with_rotation(
    payload: bytes,
    signature_header: str | None,
    current_secret: bytes,
    previous_secret: bytes | None = None,
    delivery_id: str | None = None,
) -> WebhookVerification:
    """Verify with current + (optional) previous secret for rotation window.

    During secret rotation (max 7 days grace), GitHub may send signature
    signed with either old or new secret. Try current first, fall back to
    previous.
    """
    result = verify_github_webhook_signature(
        payload, signature_header, current_secret, delivery_id=delivery_id
    )
    if result.result == WebhookVerificationResult.VALID:
        return result
    if previous_secret:
        return verify_github_webhook_signature(
            payload, signature_header, previous_secret, delivery_id=delivery_id
        )
    return result


__all__ = [
    "WebhookVerification",
    "WebhookVerificationResult",
    "verify_github_webhook_signature",
    "verify_with_rotation",
]
