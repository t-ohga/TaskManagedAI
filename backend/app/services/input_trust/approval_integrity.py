"""Sprint 5.5 BL-0069: Approval 4 integrity hash binding.

Approval 4 fields (artifact_hash + policy_version +
provider_request_fingerprint + action_class) の server-side hash 計算と
``ApprovalRequest`` record との一致 verify を提供する。

ADR-00009 §Sprint 5.5 update §「trusted_instruction 昇格境界」:

- ``validated_artifact -> trusted_instruction`` 昇格は **既存 Approval 4 整合
  + decider human-only** に依存
- 4 fields の同時一致 (artifact_hash / policy_version /
  provider_request_fingerprint / action_class) を hash binding で保証
- 不一致は invalidated (stale approval) として deny

Hash algorithm: NFC UTF-8 + JCS canonical JSON + SHA-256 (Sprint 1 で確立した
共通 fingerprint pattern と同 algorithm、cross-source enum integrity と整合)。
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.app.db.models.approval_request import ApprovalRequest

# SP55-B4-F-001 fix: artifact_hash must match the same DB CHECK as
# ``artifacts.content_hash`` (``^[0-9a-f]{64}$``). A bare length check
# previously let ``'g' * 64`` and uppercase hex pass through the service
# layer even though the DB would later reject them.
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ApprovalIntegrityExpectation:
    """Expected 4 fields snapshot at the moment of trust_level promotion.

    The orchestrator collects these from the live AgentRun / artifact /
    ContextSnapshot / action_class before calling
    ``promote_to_trusted_instruction``. The server then verifies that the
    referenced ``ApprovalRequest`` record matches all 4 fields; any
    mismatch indicates the approval is stale and must be invalidated.
    """

    artifact_hash: str
    policy_version: str
    provider_request_fingerprint: str
    action_class: str


def compute_approval_4_integrity_hash(
    *,
    artifact_hash: str,
    policy_version: str,
    provider_request_fingerprint: str,
    action_class: str,
) -> str:
    """Compute a deterministic SHA-256 hash of the 4 integrity fields.

    Used by both sides of the comparison (orchestrator collects the live
    snapshot, ApprovalRequest record carries the at-request fields) so
    drift between any of the 4 sources surfaces as a hash mismatch.

    Algorithm (matches Sprint 1 OperationContext fingerprint pattern):

    1. Build canonical dict (sorted keys)
    2. ``json.dumps`` with ``sort_keys=True`` + ``separators=(",", ":")``
       + ``ensure_ascii=False`` + ``allow_nan=False``
    3. NFC Unicode normalization
    4. SHA-256 hex digest
    """

    _require_non_empty_str("artifact_hash", artifact_hash)
    _require_non_empty_str("policy_version", policy_version)
    _require_non_empty_str(
        "provider_request_fingerprint",
        provider_request_fingerprint,
    )
    _require_non_empty_str("action_class", action_class)

    canonical = json.dumps(
        {
            "action_class": action_class,
            "artifact_hash": artifact_hash,
            "policy_version": policy_version,
            "provider_request_fingerprint": provider_request_fingerprint,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    nfc = unicodedata.normalize("NFC", canonical)
    return hashlib.sha256(nfc.encode("utf-8")).hexdigest()


def verify_approval_4_integrity(
    approval_request: ApprovalRequest,
    expected: ApprovalIntegrityExpectation,
) -> bool:
    """Return True iff the ``ApprovalRequest`` record matches all 4 fields.

    The ``ApprovalRequest`` row carries the snapshot captured at the moment
    the approval was requested. If any of the 4 fields has drifted (e.g.
    repo HEAD moved, policy was re-published, provider request fingerprint
    was re-computed for a retry), the approval becomes stale and the
    promotion must be denied.
    """

    if approval_request.artifact_hash != expected.artifact_hash:
        return False
    if approval_request.policy_version != expected.policy_version:
        return False
    if approval_request.provider_request_fingerprint != expected.provider_request_fingerprint:
        return False
    if approval_request.action_class != expected.action_class:
        return False

    # Defense-in-depth: also compare the canonical hash so drift in any one
    # field would surface here even if the column-by-column comparison was
    # silently shortened by a future refactor.
    record_hash = compute_approval_4_integrity_hash(
        artifact_hash=approval_request.artifact_hash,
        policy_version=approval_request.policy_version,
        provider_request_fingerprint=approval_request.provider_request_fingerprint,
        action_class=approval_request.action_class,
    )
    expected_hash = compute_approval_4_integrity_hash(
        artifact_hash=expected.artifact_hash,
        policy_version=expected.policy_version,
        provider_request_fingerprint=expected.provider_request_fingerprint,
        action_class=expected.action_class,
    )
    return record_hash == expected_hash


def _require_non_empty_str(field_name: str, value: object) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    if field_name == "artifact_hash" and _SHA256_HEX_RE.fullmatch(value) is None:
        raise ValueError(
            "artifact_hash must be a 64-char lowercase SHA-256 hex string "
            "(matches artifacts.content_hash CHECK constraint "
            "'^[0-9a-f]{64}$'; SP55-B4-F-001 fix)"
        )


__all__ = [
    "ApprovalIntegrityExpectation",
    "compute_approval_4_integrity_hash",
    "verify_approval_4_integrity",
]
