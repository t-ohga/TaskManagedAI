"""Active-Registry split-brain second line of defense (SP-012 Batch B、ADR-00028).

`.claude/plans/sp012-split-brain-keyring.md` §3.B + §9.3-§9.10 で確定した split-brain
second line of defense 実装の foundational module。

# Implementation contract

本 module は §9.3-§9.10 hardening contract を **canonical final spec** として実装する。

## Marker schema (4 種、別 signature domain で分離、§9.4 R2 F-002)

- ActiveMarker (`taskhub.active_registry.active.v1`): target side cutover 後 active state、
  source_decommission_chain_hash + source_host_id + signer-host ownership binding 必須
- DecommissionMarker (`taskhub.active_registry.decommission.v1`): source side retired
  state、prev_active_chain_hash 必須 (§9.3 R1 F-013 active proof)
- PrepareMarker (`taskhub.active_registry.cutover_prepare.v1`): 2PC Phase α、cross-host
  staging artifact、lease binding 必須
- CommitMarker (`taskhub.active_registry.cutover_commit.v1`): 2PC Phase β、commit
  certificate、commit_finalization_preimage_hash + 全 host commit_confirmed_at signature
  必須 (§9.7 R6 F-001 + §9.9 R9 F-001 logic correction)

## Defense-in-depth write gate (3 layer、§9.10 R10 F-001)

- L1: FastAPI dependency (`backend/app/api/dependencies/active_registry_gate.py`)
- L2: ARQ worker startup + job dequeue (`backend/app/workers/active_registry_worker_gate.py`)
- L3: SQLAlchemy before_commit listener (`backend/app/db/active_registry_mutation_gate.py`)

## Cross-host coordination (§9.4 R2 F-003 + §9.6 R5 F-001)

- fleet-wide `cutover_lease.signed.json` (root-signed、required_host_ids 全件 prepare lock 必須)
- cutover_id uniqueness は `active_registry_fleet.signed.json` 経由 fleet-wide enforce
- immutable archived snapshot で long-term durability:
  - `cutover_lease_snapshots/<cutover_id>.signed.json`
  - `fleet_membership_snapshots/<generation>.signed.json`

## Signer-host ownership (§9.5 R3 F-002)

`active_registry_fleet.signed.json` schema:
- `host_id -> allowed_marker_signer_fingerprints` mapping (root-signed)
- `host_id -> role` (`source` / `target` / `observer`)
- `host_id -> allowed_marker_kinds` (role-based scope enforcement)

Verify path で `marker.host_id` と signer fingerprint ownership を exact match
(allowlist + ownership 二重 check)。

## Implementation status

Batch B (本 commit): marker dataclasses (ActiveMarker / DecommissionMarker / FreezeMarker /
PrepareMarker / CommitMarker / FleetMembership / CutoverLease / EpochJournalEntry) +
RFC 8785 canonical encoder + Ed25519 verify + allocate_next_epoch + trusted signer allowlist
verify を実装。R3 F-002 signer-host ownership exact match と R1 F-007 monotonic epoch chain
+ R1 F-010 signed append-only journal の foundational logic を確立。
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

# Codex PR #82 R6 fix (P1×2): rfc8785 0.1.4 (trail-of-bits) を使用して ECMAScript
# Number.prototype.toString を含む RFC 8785 strict canonicalization を実装。
# NFC normalization は rfc8785 lib に含まれないため、本 module で wrapper 層 (NFC + collision
# detection) を維持する。
import rfc8785  # type: ignore[import-not-found]

# Ed25519 dependencies are validated at import-time via taskhub_signed_approval
from cryptography.exceptions import InvalidSignature  # type: ignore[import-not-found]
from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # type: ignore[import-not-found]
    Ed25519PublicKey,
)

# SP-012 Batch B: active-registry + cutover ReasonCode (約 36 件、§9.3-§9.10 集約)
ActiveRegistryReasonCode = Literal[
    # base 11 件 (Phase 1 で確定):
    "taskhub_active_registry_split_brain_detected",
    "taskhub_active_registry_two_step_transition_violation",
    "taskhub_active_registry_signature_verify_failed",
    "taskhub_active_registry_chain_hash_mismatch",  # ADV R1 F-001 marker chain binding
    "taskhub_active_registry_signer_not_in_allowlist",  # ADV R1 F-008 + R3 F-002 ownership
    "taskhub_active_registry_epoch_counter_tampered",  # ADV R1 F-007 counter sha256/O_NOFOLLOW
    "taskhub_active_registry_epoch_replay_or_lower",  # ADV R1 F-007 same/lower epoch reject
    "taskhub_active_registry_remote_marker_unreachable",  # ADV R1 F-006 remote check
    "taskhub_cutover_two_party_control_violation",
    "taskhub_cutover_source_decommission_not_found",
    "taskhub_active_registry_epoch_journal_hash_mismatch",  # ADV R1 F-010
    # ADV2 R1 hardening (§9.3):
    "taskhub_cutover_source_host_id_mismatch",  # R1 F-011
    "taskhub_active_registry_decommission_prev_active_chain_hash_mismatch",  # R1 F-013
    "taskhub_active_registry_fleet_membership_violation",  # R1 F-014
    # ADV2 R2 hardening (§9.4):
    "taskhub_cutover_caller_supplied_actor_id_rejected",  # R2 F-001 caller-supplied actor
    "taskhub_active_registry_write_rejected_by_gate",  # R2 F-007 backend write path
    # ADV2 R3 hardening (§9.5):
    "taskhub_cutover_lease_hash_mismatch",  # R3 F-003 lease-bound commit
    "taskhub_cutover_fleet_membership_generation_drift",  # R3 F-003
    "taskhub_cutover_required_host_ids_hash_mismatch",  # R3 F-003
    "taskhub_cutover_lease_expired_at_verify_time",  # R3 F-003
    "taskhub_cutover_lease_required_host_partial_confirmation",  # R3 F-003
    # ADV2 R5 hardening (§9.6 R3 F-003 overshoot durability fix):
    "taskhub_cutover_lease_snapshot_archive_missing",  # R5 F-001 immutable archive
    "taskhub_cutover_fleet_membership_snapshot_archive_missing",  # R5 F-001
    "taskhub_active_registry_fleet_successor_transition_required",  # R5 F-001 benign drift
    # ADV2 R6 hardening (§9.7 commit-time + current fleet policy):
    "taskhub_cutover_commit_finalization_signature_invalid",  # R6 F-001 + R9 F-001 logic correction
    "taskhub_cutover_commit_confirmed_at_outside_lease_window",  # R6 F-001
    "taskhub_cutover_committed_at_after_confirmation_window_rejected",  # R6 F-001 + R9 F-001
    "taskhub_active_registry_host_removed_from_current_fleet",  # R6 F-002 compromise revocation
    "taskhub_active_registry_host_revoked_or_retired",  # R6 F-002
    "taskhub_active_registry_host_lifecycle_expired",  # R6 F-002
    "taskhub_active_registry_signer_revoked_in_current_fleet",  # R6 F-002
    "taskhub_active_registry_role_demoted_in_current_fleet",  # R6 F-002
    # ADV2 R8 hardening (§9.8 approval artifact archive):
    "taskhub_active_registry_approval_artifact_missing",  # R8 F-001
    "taskhub_active_registry_approval_claim_hash_mismatch",  # R8 F-001
    "taskhub_active_registry_approval_artifact_field_mismatch",  # R8 F-001
    # ADV2 R10 hardening (§9.10 L1+L2+L3 defense-in-depth):
    "taskhub_active_registry_worker_dequeue_rejected_by_gate",  # R10 F-001 L2
    "taskhub_active_registry_db_commit_rejected_by_gate",  # R10 F-001 L3
    "taskhub_active_registry_worker_startup_aborted",  # R10 F-001 L2 startup
    # Codex PR #82 R4 hardening:
    "taskhub_active_registry_epoch_journal_no_valid_tail_found",  # R4 F-004 (P2): journal exists but no valid tail
]

# Marker domain constants (RFC 8785 + Ed25519 signature root)
DOMAIN_ACTIVE_V1 = "taskhub.active_registry.active.v1"
DOMAIN_DECOMMISSION_V1 = "taskhub.active_registry.decommission.v1"
DOMAIN_FREEZE_V1 = "taskhub.active_registry.freeze.v1"
DOMAIN_CUTOVER_PREPARE_V1 = "taskhub.active_registry.cutover_prepare.v1"
DOMAIN_CUTOVER_COMMIT_V1 = "taskhub.active_registry.cutover_commit.v1"
DOMAIN_FLEET_MEMBERSHIP_V1 = "taskhub.active_registry.fleet_membership.v1"
DOMAIN_CUTOVER_LEASE_V1 = "taskhub.active_registry.cutover_lease.v1"
DOMAIN_EPOCH_JOURNAL_V1 = "taskhub.active_registry.epoch_journal.v1"

# Clock skew tolerance (seconds) for commit-time invariants (§9.9 R9 F-001)
COMMIT_TIME_CLOCK_SKEW_TOLERANCE_SECONDS = 60

# Host role enum (§9.5 R3 F-002 + §9.7 R6 F-002)
HostRole = Literal["source", "target", "observer", "retired"]

# Marker kind enum (§9.5 R3 F-002 role-based scope enforcement)
MarkerKind = Literal[
    "active",  # ActiveMarker
    "decommission",  # DecommissionMarker
    "freeze",  # freeze.signed (existing PR #75 backward compat)
    "cutover_prepare",  # PrepareMarker
    "cutover_commit",  # CommitMarker
]


# === RFC 8785 canonical JCS encoder (§3.B.1 + DD-06 統一) ===


def _normalize_strings_nfc(obj: Any) -> Any:  # noqa: ANN401 - JSON 任意構造の再帰正規化
    """Codex PR #82 R1 F-003 fix (P2): RFC 8785 canonical 出力前に全 string field を
    Unicode NFC (Normalization Form Canonical Composition) で正規化する。

    composed (例: \\u00e9) vs decomposed (例: e + combining acute) で hash/sign が
    異なる cross-host mismatch を avoid。

    Codex PR #82 R3 F-003 fix (P2): NFC normalization 後の dict key collision を検出。
    異なる decomposed key (例: "café" NFC + "café" NFD) が同 NFC form に collapse すると、
    dict comprehension で silent overwrite (data loss + signature mismatch) が起きる。
    collision を検出したら ValueError で fail-closed。
    """
    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)
    if isinstance(obj, dict):
        # Codex PR #82 R3 F-003 fix (P2): explicit loop with collision check
        normalized_dict: dict[Any, Any] = {}
        for k, v in obj.items():
            nk = _normalize_strings_nfc(k)
            if nk in normalized_dict:
                raise ValueError(
                    f"NFC-colliding dict keys detected during canonicalization: "
                    f"distinct source keys normalize to {nk!r}"
                )
            normalized_dict[nk] = _normalize_strings_nfc(v)
        return normalized_dict
    if isinstance(obj, list):
        return [_normalize_strings_nfc(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_normalize_strings_nfc(v) for v in obj)
    return obj


# RFC 8785 I-JSON number range constraint (Codex PR #82 R4 F-005、参考定数 — rfc8785 lib も同等を enforce)
_IJSON_MAX_INTEGER: Final = (1 << 53) - 1  # 9007199254740991
_IJSON_MIN_INTEGER: Final = -((1 << 53) - 1)  # -9007199254740991


def _encode_number(n: int | float) -> str:
    """Codex PR #82 R6 fix (P1×2): rfc8785 lib (trail-of-bits 0.1.4) を使用して ECMAScript
    Number.prototype.toString 互換を保証。

    旧 custom implementation は次の edge case で ECMAScript と不一致だった:
    - R6 F-001: 2.7159992154358246e+18 を `str(int(n))` で encode → "2715999215435824640"
      ECMAScript ToString → "2715999215435824600" (shortest decimal that round-trips to the
      same double)。`str(int(n))` は actual stored value を出すが、ECMAScript は shortest
      decimal を選ぶため不一致。
    - R6 F-002: 2.559738902941283e-06 を `repr` で encode → "2.559738902941283e-06"
      ECMAScript ToString → "0.000002559738902941283" (fixed notation for 1e-6 ≤ |n| < 1e21)。

    rfc8785 lib は上記両 case を正しく ECMAScript ToString 通り出力する。NaN/Inf は
    FloatDomainError、oversize int は IntegerDomainError で reject。

    本 wrapper では:
    - bool guard (Python の bool is subclass of int だが JSON では true/false token を使用)
    - int / float の domain validation を caller-facing ValueError に統一 (rfc8785 の
      FloatDomainError / IntegerDomainError は raise pattern が異なるため caller の error
      handling で wrapping)
    """
    if isinstance(n, bool):
        raise TypeError("bool must be encoded as JSON true/false, not number")
    try:
        # rfc8785.dumps wraps a value list to canonical bytes; we extract the single value bytes
        encoded = rfc8785.dumps([n])
    except rfc8785.IntegerDomainError as e:
        raise ValueError(
            f"RFC 8785 / I-JSON integer out of IEEE-754 double-precision range "
            f"(allowed: ±{_IJSON_MAX_INTEGER}, got: {n})"
        ) from e
    except rfc8785.FloatDomainError as e:
        raise ValueError(f"RFC 8785 forbids non-finite numbers: {n!r}") from e
    # encoded = b'[<number>]', strip the brackets
    return encoded[1:-1].decode("utf-8")


def _rfc8785_canonical_bytes(payload: Any) -> bytes:  # noqa: ANN401
    """RFC 8785 strict JCS canonical JSON encoder (Codex PR #82 R6 fix).

    rfc8785 lib (trail-of-bits 0.1.4) を delegate:
    - UTF-16 code-unit sort on object keys (RFC 8785 §3.2.3)
    - ECMAScript Number.toString number serialization (§3.2.2.3) — R6 F-001 + F-002 fix
    - I-JSON integer range constraint (§3.2.2.4) — R4 F-005
    - JSON string escape (\\uXXXX for control chars)
    - no whitespace separators
    - UTF-8 output

    本 wrapper は NFC normalization + collision detection を pre-process として実施
    (rfc8785 lib は NFC を行わないため):
    - NFC normalization on all strings (R1 F-003)
    - NFC dict key collision detection (R3 F-003) — fail-closed ValueError
    """
    normalized = _normalize_strings_nfc(payload)
    try:
        return rfc8785.dumps(normalized)
    except rfc8785.IntegerDomainError as e:
        raise ValueError(f"RFC 8785 / I-JSON integer out of IEEE-754 double-precision range: {e}") from e
    except rfc8785.FloatDomainError as e:
        raise ValueError(f"RFC 8785 forbids non-finite numbers: {e}") from e


def _sha256_hex(data: bytes) -> str:
    """SHA-256 hex digest (64 chars lowercase)."""
    return hashlib.sha256(data).hexdigest()


def _sha256_of_canonical(payload: dict[str, Any]) -> str:
    """canonical payload の SHA-256 hex (marker chain hash binding 用)."""
    return _sha256_hex(_rfc8785_canonical_bytes(payload))


# === Iso8601 UTC datetime validator (Codex R1 F-001 fix: ε tolerance はここでは強制しない) ===


_ISO8601_UTC_RE: Final = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$"
)


def validate_iso8601_utc(s: str) -> datetime:
    """UTC iso8601 string を strict 検証して datetime を返す。

    `taskhub_signed_approval_datetime_format_invalid` 系の reason code は呼び出し側で出す。
    """
    if not isinstance(s, str) or not _ISO8601_UTC_RE.match(s):
        raise ValueError(f"invalid UTC iso8601 datetime format: {s!r}")
    # python's fromisoformat accepts "+00:00" but not "Z" before 3.11; normalize defensively
    normalized = s.replace("Z", "+00:00") if s.endswith("Z") else s
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None or dt.utcoffset() != dt.tzinfo.utcoffset(dt):
        raise ValueError(f"datetime is not UTC-aware: {s!r}")
    return dt.astimezone(UTC)


# === Marker dataclasses (§3.B.1、§9.3 R1 F-011 source_host_id binding +
#     §9.5 R3 F-002 signer_fingerprint 必須化) ===


@dataclass(frozen=True, slots=True)
class FreezeMarker:
    """`freeze.signed`: source side 一時停止 (existing PR #75 backward compat)。

    cutover phase で `decommission.signed` に置換される (§6.1 state machine)。
    """

    host_id: str
    migration_epoch: int
    migration_epoch_issued_at: str  # UTC iso8601 (§9.3 R1 F-010)
    frozen_at: str  # UTC iso8601
    reason_summary: str
    signer_fingerprint: str
    signature: str  # base64 Ed25519 signature

    @property
    def domain(self) -> str:
        return DOMAIN_FREEZE_V1

    def canonical_payload(self) -> dict[str, Any]:
        """signature 対象 canonical payload (signature field 除外)。"""
        return {
            "domain": self.domain,
            "frozen_at": self.frozen_at,
            "host_id": self.host_id,
            "migration_epoch": self.migration_epoch,
            "migration_epoch_issued_at": self.migration_epoch_issued_at,
            "reason_summary": self.reason_summary,
            "signer_fingerprint": self.signer_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class DecommissionMarker:
    """`decommission.signed`: cutover 後 source retired (§3.B.1 + §9.3 R1 F-013)。

    prev_active_chain_hash で「source が active だった証明」を bind (§9.3 R1 F-013)。
    """

    host_id: str  # source host
    migration_epoch: int
    migration_epoch_issued_at: str  # UTC iso8601
    decommissioned_at: str  # UTC iso8601
    signer_fingerprint: str
    prev_active_chain_hash: str  # §9.3 R1 F-013、previous ActiveMarker canonical sha256
    cutover_id: str  # UUID、§9.4 R2 F-003 lease binding
    cutover_approval_id: str  # §9.3 R1 F-001 marker artifact 永続 binding
    cutover_approval_claim_hash: str  # sha256 of CutoverApprovalClaim canonical
    signature: str

    @property
    def domain(self) -> str:
        return DOMAIN_DECOMMISSION_V1

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "cutover_approval_claim_hash": self.cutover_approval_claim_hash,
            "cutover_approval_id": self.cutover_approval_id,
            "cutover_id": self.cutover_id,
            "decommissioned_at": self.decommissioned_at,
            "domain": self.domain,
            "host_id": self.host_id,
            "migration_epoch": self.migration_epoch,
            "migration_epoch_issued_at": self.migration_epoch_issued_at,
            "prev_active_chain_hash": self.prev_active_chain_hash,
            "signer_fingerprint": self.signer_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class ActiveMarker:
    """`active.signed`: target side cutover 後 active state (§3.B.1 + §9.3 R1 F-011)。

    source_decommission_chain_hash + source_host_id で「source からの cross-host transition」を
    binding (§9.3 R1 F-011 + §9.5 R3 F-002 signer-host ownership exact match)。
    """

    host_id: str  # target host
    migration_epoch: int
    migration_epoch_issued_at: str  # UTC iso8601
    activated_at: str  # UTC iso8601
    signer_fingerprint: str
    source_host_id: str  # §9.3 R1 F-011
    source_decommission_chain_hash: str  # sha256 of source DecommissionMarker canonical
    source_decommission_signer_fingerprint: str
    cutover_id: str  # UUID
    cutover_approval_id: str  # §9.3 R1 F-001
    cutover_approval_claim_hash: str
    signature: str

    @property
    def domain(self) -> str:
        return DOMAIN_ACTIVE_V1

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "activated_at": self.activated_at,
            "cutover_approval_claim_hash": self.cutover_approval_claim_hash,
            "cutover_approval_id": self.cutover_approval_id,
            "cutover_id": self.cutover_id,
            "domain": self.domain,
            "host_id": self.host_id,
            "migration_epoch": self.migration_epoch,
            "migration_epoch_issued_at": self.migration_epoch_issued_at,
            "signer_fingerprint": self.signer_fingerprint,
            "source_decommission_chain_hash": self.source_decommission_chain_hash,
            "source_decommission_signer_fingerprint": self.source_decommission_signer_fingerprint,
            "source_host_id": self.source_host_id,
        }


# === Cutover lease (§9.4 R2 F-003 fleet-wide concurrent cutover_id reject) ===


@dataclass(frozen=True, slots=True)
class CutoverLease:
    """`cutover_lease.signed.json`: fleet-wide root-signed cutover lease (§9.4 R2 F-003)。

    immutable archive 版は `cutover_lease_snapshots/<cutover_id>.signed.json` (§9.6 R5 F-001)、
    long-term durability は archive 経由で参照 (current path の lease 自然失効から独立)。
    """

    cutover_id: str  # UUID
    acquired_by_host_id: str
    required_host_ids: tuple[str, ...]  # fleet membership 全件
    prepared_host_ids: tuple[str, ...]  # lock 取得済 (initial=空、prepare phase で追加)
    lease_acquired_at: str  # UTC iso8601
    lease_expires_at: str  # UTC iso8601
    fleet_membership_generation: int  # snapshot binding
    root_signature: str  # base64 Ed25519 by root signing key

    @property
    def domain(self) -> str:
        return DOMAIN_CUTOVER_LEASE_V1

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "acquired_by_host_id": self.acquired_by_host_id,
            "cutover_id": self.cutover_id,
            "domain": self.domain,
            "fleet_membership_generation": self.fleet_membership_generation,
            "lease_acquired_at": self.lease_acquired_at,
            "lease_expires_at": self.lease_expires_at,
            "prepared_host_ids": list(self.prepared_host_ids),
            "required_host_ids": list(self.required_host_ids),
        }


# === PrepareMarker (§9.4 R2 F-002 2PC Phase α、別 signature domain) ===


@dataclass(frozen=True, slots=True)
class PrepareMarker:
    """`cutover_prepare/<cutover_id>.signed`: 2PC Phase α、cross-host staging artifact.

    §9.4 R2 F-002: PrepareMarker と CommitMarker を別 signature domain で分離
    (DOMAIN_CUTOVER_PREPARE_V1)、prepare phase の marker と commit phase の marker を暗号学的に区別。
    §9.5 R3 F-003 / §9.6 R5 F-001 / §9.7 R6 F-001: lease binding + archived snapshot hashes 必須化。
    """

    cutover_id: str  # UUID
    host_id: str  # prepare 実行 host (source or target)
    role: str  # "source" / "target"
    migration_epoch: int
    prepared_at: str  # UTC iso8601
    signer_fingerprint: str
    # §9.6 R5 F-001 + §9.7 R6 F-001 lease binding (immutable archive snapshot hashes)
    cutover_lease_snapshot_content_sha256: str  # 64-char hex
    fleet_membership_snapshot_content_sha256: str  # 64-char hex
    required_host_ids_hash: str  # 64-char hex of canonical sorted required_host_ids
    lease_acquired_at: str  # UTC iso8601 (from lease snapshot)
    lease_expires_at: str  # UTC iso8601 (from lease snapshot)
    # cutover approval binding (§9.3 R1 F-001)
    cutover_approval_id: str
    cutover_approval_claim_hash: str
    signature: str  # base64 Ed25519

    @property
    def domain(self) -> str:
        return DOMAIN_CUTOVER_PREPARE_V1

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "cutover_approval_claim_hash": self.cutover_approval_claim_hash,
            "cutover_approval_id": self.cutover_approval_id,
            "cutover_id": self.cutover_id,
            "cutover_lease_snapshot_content_sha256": self.cutover_lease_snapshot_content_sha256,
            "domain": self.domain,
            "fleet_membership_snapshot_content_sha256": self.fleet_membership_snapshot_content_sha256,
            "host_id": self.host_id,
            "lease_acquired_at": self.lease_acquired_at,
            "lease_expires_at": self.lease_expires_at,
            "migration_epoch": self.migration_epoch,
            "prepared_at": self.prepared_at,
            "required_host_ids_hash": self.required_host_ids_hash,
            "role": self.role,
            "signer_fingerprint": self.signer_fingerprint,
        }


# === HostFinalizationSignature (§9.7 R6 F-001 + §9.9 R9 F-001 commit-time signature) ===


@dataclass(frozen=True, slots=True)
class HostFinalizationSignature:
    """各 host の commit_confirmed_at + signature over commit_finalization_preimage.

    §9.7 R6 F-001: required host 全員の commit_confirmed_at 必須署名で backdate 攻撃防御。
    §9.9 R9 F-001 logic correction: commit_confirmed_at は lease window 内 + max(host_confirmed)
    <= committed_at < lease_expires_at の invariant を満たす。
    """

    host_id: str
    signer_fingerprint: str
    commit_confirmed_at: str  # UTC iso8601
    signature: str  # base64 Ed25519 over commit_finalization_preimage_hash || commit_confirmed_at

    def canonical_payload(self) -> dict[str, Any]:
        # signature 自体は含めず、verifier 側で reconstruct する canonical
        return {
            "commit_confirmed_at": self.commit_confirmed_at,
            "host_id": self.host_id,
            "signer_fingerprint": self.signer_fingerprint,
        }


# === CommitMarker (§9.4 R2 F-002 2PC Phase β、commit certificate) ===


@dataclass(frozen=True, slots=True)
class CommitMarker:
    """`cutover_commit/<cutover_id>.signed`: 2PC Phase β、commit certificate.

    §9.7 R6 F-001 + §9.9 R9 F-001 logic correction: commit_finalization_preimage_hash の構造を
    必須化 (committed_at + lease snapshot + fleet snapshot + prepare hashes + approval hashes +
    required_host_ids_hash + domain canonical hash)、required host 全員の commit_confirmed_at
    signature 必須。

    verify path invariant:
    (a) lease_acquired_at <= min(host_commit_confirmed_at)
    (b) max(host_commit_confirmed_at) <= committed_at < lease_expires_at
    (c) committed_at - max(host_commit_confirmed_at) <= ε (clock skew tolerance、default 60s)
    """

    cutover_id: str
    committed_at: str  # UTC iso8601
    source_prepare_marker_hash: str  # 64-char hex sha256 of source PrepareMarker canonical
    target_prepare_marker_hash: str  # 64-char hex sha256 of target PrepareMarker canonical
    cutover_lease_snapshot_content_sha256: str
    fleet_membership_snapshot_content_sha256: str
    required_host_ids_hash: str
    lease_acquired_at: str
    lease_expires_at: str
    cutover_approval_id: str
    cutover_approval_claim_hash: str
    commit_approval_claim_hash: str  # separate commit approval claim
    host_finalization_signatures: tuple[HostFinalizationSignature, ...]  # required hosts 全員
    commit_finalization_preimage_hash: str  # sha256 of canonical preimage
    signature: str  # base64 Ed25519 (CommitMarker self-signature)

    @property
    def domain(self) -> str:
        return DOMAIN_CUTOVER_COMMIT_V1

    def commit_finalization_preimage(self) -> dict[str, Any]:
        """commit_finalization_preimage_hash の計算対象 (signature root の重要部分).

        §9.7 R6 F-001 canonical schema:
        committed_at + lease window (acquired/expires) + lease snapshot + fleet snapshot +
        source/target prepare marker hashes + cutover/commit approval claim hashes +
        required_host_ids_hash + cutover_id + domain。

        Codex PR #84 R1 F-001 fix (P1、L579): domain field は CommitMarker domain (canonical schema) と整合。
        Codex PR #84 R3 F-002 fix (P1、L583): lease_acquired_at + lease_expires_at + cutover_id を preimage
        に含める (host signature が lease window と cutover identity に binding されるため、commit-marker
        signer が lease bounds を rewrite して同 host signature を流用する attack を排除)。
        """
        return {
            "commit_approval_claim_hash": self.commit_approval_claim_hash,
            "committed_at": self.committed_at,
            "cutover_approval_claim_hash": self.cutover_approval_claim_hash,
            "cutover_approval_id": self.cutover_approval_id,
            "cutover_id": self.cutover_id,
            "cutover_lease_snapshot_content_sha256": self.cutover_lease_snapshot_content_sha256,
            "domain": DOMAIN_CUTOVER_COMMIT_V1,
            "fleet_membership_snapshot_content_sha256": self.fleet_membership_snapshot_content_sha256,
            "lease_acquired_at": self.lease_acquired_at,
            "lease_expires_at": self.lease_expires_at,
            "required_host_ids_hash": self.required_host_ids_hash,
            "source_prepare_marker_hash": self.source_prepare_marker_hash,
            "target_prepare_marker_hash": self.target_prepare_marker_hash,
        }

    def canonical_payload(self) -> dict[str, Any]:
        """Codex PR #84 R1 F-003 fix (P1、L609): undocumented constant
        target_prepare_marker_signature_present を削除 (documented schema に無い field を
        injection することで cross-language verifier が byte mismatch する)."""
        return {
            "commit_approval_claim_hash": self.commit_approval_claim_hash,
            "commit_finalization_preimage_hash": self.commit_finalization_preimage_hash,
            "committed_at": self.committed_at,
            "cutover_approval_claim_hash": self.cutover_approval_claim_hash,
            "cutover_approval_id": self.cutover_approval_id,
            "cutover_id": self.cutover_id,
            "cutover_lease_snapshot_content_sha256": self.cutover_lease_snapshot_content_sha256,
            "domain": self.domain,
            "fleet_membership_snapshot_content_sha256": self.fleet_membership_snapshot_content_sha256,
            "host_finalization_signatures": [
                {
                    **hfs.canonical_payload(),
                    "signature": hfs.signature,  # signature は canonical に含める (collection-level)
                }
                for hfs in sorted(self.host_finalization_signatures, key=lambda h: h.host_id)
            ],
            "lease_acquired_at": self.lease_acquired_at,
            "lease_expires_at": self.lease_expires_at,
            "required_host_ids_hash": self.required_host_ids_hash,
            "source_prepare_marker_hash": self.source_prepare_marker_hash,
            "target_prepare_marker_hash": self.target_prepare_marker_hash,
        }


# === CommitMarker verify helpers (§9.7 R6 F-001 + §9.9 R9 F-001 logic correction) ===


# Codex PR #84 R3 F-002 fix (P1、L684): sentinel for opt-in to weak (structural-only)
# commit marker verification. Production deployments MUST pass an actual resolver that maps
# (host_id, signer_fingerprint) -> public key bytes. Use this sentinel ONLY in test fixtures.
def accept_unverified_commit_marker_signatures(_host_id: str, _signer_fingerprint: str) -> bytes | None:
    """SENTINEL — bypass host signature verification (test fixture only).

    Returning bytes が None means "skip cryptographic check for this host"。bytes (32-byte pub key)
    を返したら verify する。本 sentinel は全 host に対して None を返す → caller-supplied
    sentinel として明示渡しが必要 (None default は foot-gun のため廃止、required arg 化)。
    """
    return None


def verify_commit_marker_invariants(
    marker: CommitMarker,
    required_host_ids: tuple[str, ...],
    *,
    host_signer_public_key_resolver: Callable[[str, str], bytes | None],  # required (R3 F-001 fix)
    clock_skew_tolerance_seconds: int = COMMIT_TIME_CLOCK_SKEW_TOLERANCE_SECONDS,
) -> tuple[bool, str]:
    """Verify §9.7 R6 F-001 + §9.9 R9 F-001 commit-time invariants.

    Codex PR #84 R1 F-002 fix (P1、L628): marker.required_host_ids_hash と
    compute_required_host_ids_hash(required_host_ids) を exact match で verify (lease-binding
    guarantee enforcement)。
    Codex PR #84 R1 F-004 fix (P2、L650): empty required_host_ids + host_finalization_signatures
    pair の場合 set equality は pass するが max()/min() で ValueError → fail-closed reason に変換。
    Codex PR #84 R2 F-001 fix (P1、L640): compute_required_host_ids_hash が duplicate で ValueError
    raise するため、caller responsibility で normalize させる代わりに、verify 内で例外 catch
    して fail-closed reason に変換 (verify API 契約 (bool, reason_code) を保つ).
    Codex PR #84 R2 F-002 fix (P2、L646): host_finalization_signatures の duplicate host_id を
    exclusion (set で multiplicity が drop し ambiguous confirmation を許す問題)。
    Codex PR #84 R2 F-003 fix (P1、L660): host_signer_public_key_resolver kwarg を導入、
    HostFinalizationSignature.signature を cryptographically verify (commit_finalization_preimage_hash
    + commit_confirmed_at を canonical bytes として Ed25519 verify)。None なら structural-only
    weak verify (test/genesis 専用)、production deployment では必ず resolver を渡す。

    Args:
        host_signer_public_key_resolver: Optional callable (host_id, signer_fingerprint) -> pub_key_bytes | None。
            None を返したら that host の signature を skip (unknown signer)、bytes を返したら verify。
            None (callable 自体が None) は legacy weak structural-only verify (foot-gun、test only)。

    Returns: (ok, reason_code or "")
    """
    # Codex PR #84 R1 F-002 fix (P1、L628): required_host_ids_hash binding verify
    try:
        expected_hash = compute_required_host_ids_hash(required_host_ids)
    except ValueError:
        # Codex PR #84 R2 F-001 fix (P1、L640): duplicate host_ids in caller-supplied
        # required_host_ids → fail-closed instead of propagating ValueError
        return False, "taskhub_cutover_required_host_ids_hash_mismatch"
    if marker.required_host_ids_hash != expected_hash:
        return False, "taskhub_cutover_required_host_ids_hash_mismatch"

    # Codex PR #84 R2 F-002 fix (P2、L646): host_finalization_signatures に duplicate host_id があれば
    # reject (set conversion で multiplicity drop し ambiguous confirmation を許す問題)
    seen_host_ids: set[str] = set()
    for hfs in marker.host_finalization_signatures:
        if hfs.host_id in seen_host_ids:
            return False, "taskhub_cutover_lease_required_host_partial_confirmation"
        seen_host_ids.add(hfs.host_id)

    # (1) host_finalization_signatures は required_host_ids 全件分の signature を持つ
    signed_host_ids = {hfs.host_id for hfs in marker.host_finalization_signatures}
    if signed_host_ids != set(required_host_ids):
        return False, "taskhub_cutover_lease_required_host_partial_confirmation"

    # Codex PR #84 R1 F-004 fix (P2、L650): empty case 早期 reject (max/min ValueError 回避)
    if not marker.host_finalization_signatures:
        return False, "taskhub_cutover_lease_required_host_partial_confirmation"

    # parse timestamps
    try:
        lease_acquired = validate_iso8601_utc(marker.lease_acquired_at)
        lease_expires = validate_iso8601_utc(marker.lease_expires_at)
        committed = validate_iso8601_utc(marker.committed_at)
        confirmations = [
            (hfs.host_id, validate_iso8601_utc(hfs.commit_confirmed_at))
            for hfs in marker.host_finalization_signatures
        ]
    except ValueError:
        return False, "taskhub_cutover_commit_confirmed_at_outside_lease_window"

    from datetime import timedelta  # noqa: PLC0415
    skew_threshold = timedelta(seconds=clock_skew_tolerance_seconds)

    # (2) all host_commit_confirmed_at ∈ [lease_acquired_at - ε, lease_expires_at)
    # Codex PR #84 R1 F-006 fix (P2、L645): lower-bound にも ε tolerance を apply、
    # negative clock drift の正常範囲 (ε 以内) を accept。strict `lease_acquired <= conf_at` は
    # step 7 (min(host_confirmed) >= lease_acquired - ε) と矛盾するため、ここで先に許容。
    for host_id, conf_at in confirmations:
        if conf_at < (lease_acquired - skew_threshold) or conf_at >= lease_expires:
            return False, "taskhub_cutover_commit_confirmed_at_outside_lease_window"
        # silence unused host_id
        _ = host_id

    # (3) §9.9 R9 F-001 logic correction: max(host_commit_confirmed_at) <= committed_at < lease_expires_at
    max_confirmed = max(c for _, c in confirmations)
    if committed < max_confirmed:
        return False, "taskhub_cutover_committed_at_after_confirmation_window_rejected"
    if not (committed < lease_expires):
        return False, "taskhub_cutover_commit_confirmed_at_outside_lease_window"

    # (4) clock skew tolerance ε = 60s default (§9.9 R9 F-001 (c) condition)
    if committed - max_confirmed > skew_threshold:
        return False, "taskhub_cutover_committed_at_after_confirmation_window_rejected"

    # (5) min(host_commit_confirmed_at) >= lease_acquired_at - ε (negative drift tolerance)
    min_confirmed = min(c for _, c in confirmations)
    if lease_acquired - min_confirmed > skew_threshold:
        return False, "taskhub_cutover_commit_confirmed_at_outside_lease_window"

    # Codex PR #84 R2 F-003 + R3 F-002 + R3 F-003 + R3 F-004 fix (P1, L660+L583+L691+L685):
    # cryptographic signature verification を timing checks の後に実施 (cheap fail-fast、最後に
    # expensive crypto)。
    # (R3 F-003) recompute preimage hash from marker fields + verify against marker.commit_finalization_preimage_hash
    # (R3 F-002 L583) preimage は lease window + cutover_id を含む (commit_finalization_preimage())
    # (R3 F-004) resolver exception を fail-closed reason に catch
    recomputed_preimage_bytes = _rfc8785_canonical_bytes(marker.commit_finalization_preimage())
    recomputed_preimage_hash = _sha256_hex(recomputed_preimage_bytes)
    if recomputed_preimage_hash != marker.commit_finalization_preimage_hash:
        return False, "taskhub_cutover_commit_finalization_signature_invalid"

    # accept_unverified_commit_marker_signatures sentinel: signature verification を skip
    # (test/genesis bootstrap 専用)。production は実 resolver を渡す前提。
    if host_signer_public_key_resolver is accept_unverified_commit_marker_signatures:
        return True, ""

    for hfs in marker.host_finalization_signatures:
        try:
            pub = host_signer_public_key_resolver(hfs.host_id, hfs.signer_fingerprint)
        except Exception:  # noqa: BLE001 — fail-closed on resolver exception (R3 F-004)
            return False, "taskhub_cutover_commit_finalization_signature_invalid"
        if pub is None:
            return False, "taskhub_cutover_commit_finalization_signature_invalid"
        # canonical bytes binds host_id + signer_fingerprint + commit_confirmed_at + recomputed_preimage_hash
        sig_payload = _rfc8785_canonical_bytes({
            "commit_confirmed_at": hfs.commit_confirmed_at,
            "commit_finalization_preimage_hash": recomputed_preimage_hash,
            "host_id": hfs.host_id,
            "signer_fingerprint": hfs.signer_fingerprint,
        })
        if not verify_ed25519_signature(pub, hfs.signature, sig_payload):
            return False, "taskhub_cutover_commit_finalization_signature_invalid"

    return True, ""


def compute_required_host_ids_hash(required_host_ids: tuple[str, ...]) -> str:
    """canonical sort + RFC 8785 + sha256 hex (64 chars).

    §9.5 R3 F-003 cutover_required_host_ids_hash の計算で、host_id list の順序非依存
    deterministic hash を保証する。

    Codex PR #84 R1 F-005 fix (P2、L676): duplicate host_id を silent dedupe しない。
    distinct inputs (e.g., ['host-a','host-a','host-b']) と ['host-a','host-b'] が同 hash に
    collapse すると malformed/tampered lease membership array を masking する。
    duplicate 検出時は ValueError で fail-closed (caller responsibility で正規化させる)。
    """
    seen: set[str] = set()
    for hid in required_host_ids:
        if hid in seen:
            raise ValueError(
                f"taskhub_cutover_required_host_ids_hash_mismatch: "
                f"duplicate host_id detected: {hid!r}"
            )
        seen.add(hid)
    sorted_ids = sorted(required_host_ids)  # sort only (no dedupe — already verified unique)
    canonical_bytes = _rfc8785_canonical_bytes(sorted_ids)
    return _sha256_hex(canonical_bytes)


# === Fleet membership signed complete set (§9.3 R1 F-014 + §9.5 R3 F-002 ownership) ===


@dataclass(frozen=True, slots=True)
class FleetHost:
    """Fleet membership entry (§9.5 R3 F-002 signer-host ownership)."""

    host_id: str
    endpoint: str
    role: str  # "source" / "target" / "observer" / "retired" (HostRole enum)
    status: str  # "active" / "revoked" / "retired" (§9.7 R6 F-002 compromise revocation)
    allowed_marker_signer_fingerprints: tuple[str, ...]  # §9.5 R3 F-002 ownership
    allowed_marker_kinds: tuple[str, ...]  # role-based scope enforcement
    valid_from: str  # UTC iso8601
    valid_to: str  # UTC iso8601

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "allowed_marker_kinds": list(self.allowed_marker_kinds),
            "allowed_marker_signer_fingerprints": list(self.allowed_marker_signer_fingerprints),
            "endpoint": self.endpoint,
            "host_id": self.host_id,
            "role": self.role,
            "status": self.status,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
        }


@dataclass(frozen=True, slots=True)
class FleetMembership:
    """`active_registry_fleet.signed.json`: root-signed fleet complete set (§9.3 R1 F-014)。"""

    generation: int  # §9.6 R5 F-001 immutable archive key
    hosts: tuple[FleetHost, ...]
    head_signed_at: str  # UTC iso8601
    root_signature: str

    @property
    def domain(self) -> str:
        return DOMAIN_FLEET_MEMBERSHIP_V1

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "generation": self.generation,
            "head_signed_at": self.head_signed_at,
            "hosts": [h.canonical_payload() for h in self.hosts],
        }

    def find_host(self, host_id: str) -> FleetHost | None:
        for h in self.hosts:
            if h.host_id == host_id:
                return h
        return None


# === Epoch journal entry (§9.3 R1 F-010 signed append-only journal) ===


@dataclass(frozen=True, slots=True)
class EpochJournalEntry:
    """`migration_epoch.journal.signed.jsonl` の各 entry (§9.3 R1 F-010)."""

    epoch: int
    issued_at: str  # UTC iso8601
    host_id: str  # writer host
    writer_signer_fingerprint: str
    previous_entry_hash: str  # sha256 of prev entry canonical (chain integrity)
    signature: str

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "domain": DOMAIN_EPOCH_JOURNAL_V1,
            "epoch": self.epoch,
            "host_id": self.host_id,
            "issued_at": self.issued_at,
            "previous_entry_hash": self.previous_entry_hash,
            "writer_signer_fingerprint": self.writer_signer_fingerprint,
        }


# === Ed25519 signature verify (§3.A pattern と統一) ===


def verify_ed25519_signature(
    public_key_bytes: bytes,
    signature_b64: str,
    canonical_bytes: bytes,
) -> bool:
    """Ed25519 signature を canonical bytes に対して verify。

    invalid signature / malformed base64 / wrong public key length などは
    全て `False` を返し、呼び出し側で `taskhub_active_registry_signature_verify_failed`
    に変換する (fail-closed)。
    """
    if not isinstance(signature_b64, str) or len(signature_b64) == 0:
        return False
    try:
        sig_bytes = base64.b64decode(signature_b64, validate=True)
    except (ValueError, binascii_Error_proxy()):
        return False
    if len(sig_bytes) != 64:  # Ed25519 signatures are 64 bytes
        return False
    if len(public_key_bytes) != 32:  # Ed25519 public keys are 32 bytes
        return False
    try:
        key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        key.verify(sig_bytes, canonical_bytes)
        return True
    except InvalidSignature:
        return False
    except Exception:
        # 不明な暗号エラーは fail-closed (raise しない、reason_code 経由で audit)
        return False


def binascii_Error_proxy() -> type[Exception]:
    """base64.b64decode が投げる binascii.Error を import なしで取得。"""
    import binascii  # noqa: PLC0415

    return binascii.Error


# === Signer-host ownership exact match (§9.5 R3 F-002) ===


def verify_signer_host_ownership(
    fleet: FleetMembership,
    marker_host_id: str,
    marker_signer_fingerprint: str,
    marker_kind: str,
    *,
    now: datetime | None = None,  # injectable for testing; defaults to UTC now
) -> tuple[bool, str]:
    """`marker.host_id` と signer fingerprint ownership を exact match + lifecycle window check。

    Codex PR #82 R2 F-001 fix (P1): host.valid_from / valid_to の lifecycle window を
    必須 verify。expired host / not-yet-active host の signature を ownership check で通さない
    (taskhub_active_registry_host_lifecycle_expired は §9.7 R6 F-002 で既定済)。

    Returns: (ok, reason_code or "" on ok)
    """
    host = fleet.find_host(marker_host_id)
    if host is None:
        return False, "taskhub_active_registry_fleet_membership_violation"
    if host.status not in ("active",):
        return False, "taskhub_active_registry_host_revoked_or_retired"
    # Codex PR #82 R2 F-001 fix (P1): lifecycle window check
    current_time = now if now is not None else datetime.now(UTC)
    try:
        valid_from = validate_iso8601_utc(host.valid_from)
        valid_to = validate_iso8601_utc(host.valid_to)
    except ValueError:
        return False, "taskhub_active_registry_host_lifecycle_expired"
    if current_time < valid_from or current_time >= valid_to:
        return False, "taskhub_active_registry_host_lifecycle_expired"
    if marker_signer_fingerprint not in host.allowed_marker_signer_fingerprints:
        return False, "taskhub_active_registry_signer_not_in_allowlist"
    if marker_kind not in host.allowed_marker_kinds:
        return False, "taskhub_active_registry_role_demoted_in_current_fleet"
    return True, ""


# === Journal tail discovery helpers (Codex PR #82 R3 F-004 + F-005 fix) ===


def _is_structurally_valid_journal_entry(entry: Any) -> bool:  # noqa: ANN401
    """Structural validation: full EpochJournalEntry schema 必須.

    Codex PR #82 R2 F-004 fix (P1): domain + epoch + signature + writer_signer_fingerprint check.
    Codex PR #82 R5 F-003 fix (P2): epoch=bool (bool is subclass of int) を reject。
    Codex PR #82 R5 F-004 fix (P2): EpochJournalEntry full schema を検証 (host_id +
    issued_at + previous_entry_hash も必須、truncated/minimal entry を reject)。

    Ed25519 signature verify は journal_tail_verifier callable (R3 F-005) で行う。
    """
    if not isinstance(entry, dict):
        return False
    if entry.get("domain") != DOMAIN_EPOCH_JOURNAL_V1:
        return False
    # Codex PR #82 R5 F-003 fix (P2): bool is subclass of int — explicit exclusion
    epoch_val = entry.get("epoch")
    if not isinstance(epoch_val, int) or isinstance(epoch_val, bool):
        return False
    # epoch must be non-negative
    if epoch_val < 0:
        return False
    if not isinstance(entry.get("signature"), str) or not entry["signature"]:
        return False
    if not isinstance(entry.get("writer_signer_fingerprint"), str) or not entry["writer_signer_fingerprint"]:
        return False
    # Codex PR #82 R5 F-004 fix (P2): full EpochJournalEntry schema validation
    if not isinstance(entry.get("host_id"), str) or not entry["host_id"]:
        return False
    if not isinstance(entry.get("issued_at"), str) or not entry["issued_at"]:
        return False
    if not isinstance(entry.get("previous_entry_hash"), str) or not entry["previous_entry_hash"]:
        return False
    # previous_entry_hash must be 64-char hex (sha256)
    prev_hash = entry["previous_entry_hash"]
    if len(prev_hash) != 64 or not all(c in "0123456789abcdef" for c in prev_hash):
        return False
    return True


def _find_valid_journal_tail_entry(
    *,
    journal_path: Path,
    tail_verifier: Callable[[dict[str, Any]], bool] | None,
) -> dict[str, Any] | None:
    """journal file の末尾から valid entry を progressive expansion で探索。

    Codex PR #82 R3 F-004 fix (P2): 64 KiB → 256 KiB → 1 MiB → full file の progressive
    expansion で、64 KiB tail window に valid entry がなくても (large lines / corrupted tail)
    valid entry を発見できるまで遡る。journal が完全に空 / 完全に無効なら None を返し、
    caller は genesis (epoch=0) として扱う。

    Codex PR #82 R3 F-005 fix (P1): tail_verifier が指定されていれば、structural validation
    通過後に signature verify を実施。verifier=None なら legacy weak structural check のみ
    (production deployment では verifier 必須)。
    """
    # progressive expansion: 64 KiB → 256 KiB → 1 MiB → full file
    window_sizes = [64 * 1024, 256 * 1024, 1024 * 1024]
    journal_fd = os.open(str(journal_path), os.O_RDONLY | os.O_NOFOLLOW)
    try:
        stat = os.fstat(journal_fd)
        if stat.st_size == 0:
            return None
        # if file is smaller than the smallest window, read it all
        seen_offsets: set[int] = set()
        for win in [*window_sizes, stat.st_size]:
            tail_size = min(stat.st_size, win)
            start_offset = stat.st_size - tail_size
            if start_offset in seen_offsets:
                continue
            seen_offsets.add(start_offset)
            os.lseek(journal_fd, start_offset, os.SEEK_SET)
            tail_bytes = _read_all(journal_fd, tail_size + 1)
            journal_lines = tail_bytes.split(b"\n")
            # The first line may be truncated (we started mid-line), so skip it if we did
            # not start at offset 0
            iter_lines = list(reversed(journal_lines))
            if start_offset > 0 and len(iter_lines) > 0:
                # the last item in iter_lines is the first line — may be truncated
                # we'll still try, but accept that some entries may not parse
                pass
            for line in iter_lines:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    candidate = json.loads(stripped)
                except (json.JSONDecodeError, AttributeError, ValueError):
                    continue
                if not _is_structurally_valid_journal_entry(candidate):
                    continue
                # Codex PR #82 R3 F-005 fix (P1): cryptographic signature verify
                # Codex PR #82 R5 F-002 fix (P1): verifier exception (semantically incomplete /
                # unexpected format) を catch して fail-soft (この entry を skip して backward scan
                # 継続)。verifier の raise が crash-recovery を全体 block するのを防ぐ。
                try:
                    if tail_verifier is not None and not tail_verifier(candidate):
                        continue  # forged signature — skip
                except Exception:  # noqa: BLE001, S112 — fail-soft skip for verifier exceptions
                    continue
                return candidate
            if tail_size >= stat.st_size:
                break  # already read the whole file, no valid entry exists
        return None
    finally:
        os.close(journal_fd)


# === Epoch atomic counter with fcntl lock (§9.3 R1 F-007 + R1 F-010) ===


# Codex PR #82 R4 F-003 fix (P1): explicit sentinel to opt into weak (structural-only) tail
# verification. Callers MUST pass `journal_tail_verifier=accept_unverified_tail` (legacy/test
# only) or a proper Ed25519 verifier — the previous `None` default silently accepted forged
# entries based on structural fields only.
def accept_unverified_tail(_entry: dict[str, Any]) -> bool:
    """SENTINEL — accept any structurally-valid journal tail entry without cryptographic
    signature verification. **Use only in test fixtures or genesis bootstrap**. Production
    deployments MUST pass a verifier that resolves writer_signer_fingerprint to a known
    Ed25519 public key and calls verify_ed25519_signature(pubkey, entry['signature'], canonical).
    """
    return True


def allocate_next_epoch(
    counter_path: Path,
    lock_path: Path,
    journal_path: Path,
    host_id: str,
    writer_signer_fingerprint: str,
    private_key_signer: Callable[[bytes], bytes],  # callable: bytes -> bytes (Ed25519 sign)
    *,
    journal_tail_verifier: Callable[[dict[str, Any]], bool],  # required — see accept_unverified_tail
) -> tuple[int, str, EpochJournalEntry]:
    """epoch counter を atomic に増分し、signed journal entry を append。

    Pattern (§9.3 R1 F-007 + R1 F-010):
        1. lock_path に LOCK_EX|LOCK_NB を取得 (lock_path は rename 不可、安定 inode)
        2. counter_path を読込 (sha256 verify)
        3. journal_path 末尾を progressive expansion で scan、signature verifier 経由で
           valid tail entry を取得 (Codex PR #82 R3 F-004 + F-005 fix)
        4. epoch N+1 計算 + issued_at = now() を同時記録
        5. EpochJournalEntry canonical → private_key_signer で署名
        6. journal_path に append + fsync
        7. counter_path を atomic rename で書込 (epoch=N+1, sha256=self_hash)
        8. lock release

    Args:
        journal_tail_verifier: Codex PR #82 R3 F-005 fix (P1) — Ed25519 signature verifier for
            tail entries. Callable(entry_dict) -> bool. If None, only structural checks
            (domain + epoch + signature present) are performed (legacy weak verify、警告: forged
            signature string で epoch derivation steal を防げないため、production deployment では
            必ず resolver を渡す)。

    Returns: (new_epoch, issued_at_iso8601, journal_entry)
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Codex PR #82 R1 F-001 fix (P1): O_CREAT (without O_EXCL) で race-free に lock file 確保。
    # 旧実装は `if not lock_path.exists(): O_EXCL` で TOCTOU race を持っていた (loser が
    # FileExistsError で abort)。flock 自体が排他保証を行うため、lock file 作成は idempotent
    # で良い。secure permission は os.fchmod で post-create に強制。
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        # ensure secure permission even if file existed with looser mode
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            # filesystems without chmod support (rare on Linux) — accept default
            pass
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            # Codex PR #82 R2 F-002 fix (P1): counter_path を O_NOFOLLOW で open、
            # symlink swap attack (任意 JSON injection) を physical reject。
            current_epoch_from_counter = 0
            if counter_path.exists():
                cf_fd = os.open(str(counter_path), os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    raw = _read_all(cf_fd, _MARKER_MAX_BYTES)
                finally:
                    os.close(cf_fd)
                counter_doc = json.loads(raw)
                expected_sha = counter_doc.get("sha256")
                # self-referential sha256: payload minus sha256 field
                check_payload = {k: v for k, v in counter_doc.items() if k != "sha256"}
                check_canonical = _rfc8785_canonical_bytes(check_payload)
                if _sha256_hex(check_canonical) != expected_sha:
                    raise RuntimeError("taskhub_active_registry_epoch_counter_tampered")
                current_epoch_from_counter = int(counter_doc["epoch"])
            # Codex PR #82 R1 F-005 fix (P1): torn JSONL tail tolerance + backward scan で
            # 最後の valid entry を取得。crash で半分書きの partial line があっても recovery block しない。
            # Codex PR #82 R1 F-002 + F-004 fix (P1): journal tail epoch も読込み、
            # max(counter_epoch, journal_tail_epoch) + 1 で new_epoch を決定。
            # Codex PR #82 R2 F-003 fix (P2): journal tail を bounded read (末尾 64 KiB のみ)
            # で取得、O(N) full read を排除して allocation latency を一定にする。
            # Codex PR #82 R2 F-004 fix (P1): journal tail line は signature + domain validation
            # を実施してから epoch derivation に使用 (forged tail entry による replay 排除)。
            previous_entry_hash = "0" * 64  # genesis
            journal_tail_epoch = 0
            if journal_path.exists():
                # Codex PR #82 R4 F-004 fix (P2): journal が存在するが valid tail なしは
                # chain discontinuity に直結するため fail-closed。caller が genesis 状態から
                # restart したいなら journal_path を rotate / archive してから新規 file で
                # allocate を呼ぶ運用 (operator-runbook §13 で SOP 規定予定)。
                stat = os.stat(journal_path)
                if stat.st_size > 0:
                    last_entry = _find_valid_journal_tail_entry(
                        journal_path=journal_path,
                        tail_verifier=journal_tail_verifier,
                    )
                    if last_entry is None:
                        raise RuntimeError(
                            "taskhub_active_registry_epoch_journal_no_valid_tail_found"
                        )
                    last_canonical = _rfc8785_canonical_bytes(
                        {k: v for k, v in last_entry.items() if k != "signature"}
                    )
                    previous_entry_hash = _sha256_hex(last_canonical)
                    journal_tail_epoch = int(last_entry["epoch"])
            # Codex PR #82 R1 F-002 + F-004 fix (P1): epoch monotonicity は counter + journal max + 1。
            new_epoch = max(current_epoch_from_counter, journal_tail_epoch) + 1
            issued_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            # build + sign journal entry
            entry = EpochJournalEntry(
                epoch=new_epoch,
                issued_at=issued_at,
                host_id=host_id,
                writer_signer_fingerprint=writer_signer_fingerprint,
                previous_entry_hash=previous_entry_hash,
                signature="",  # filled below
            )
            entry_canonical = _rfc8785_canonical_bytes(entry.canonical_payload())
            sig_bytes = private_key_signer(entry_canonical)
            signed_entry = EpochJournalEntry(
                epoch=entry.epoch,
                issued_at=entry.issued_at,
                host_id=entry.host_id,
                writer_signer_fingerprint=entry.writer_signer_fingerprint,
                previous_entry_hash=entry.previous_entry_hash,
                signature=base64.b64encode(sig_bytes).decode("ascii"),
            )
            # Codex PR #82 R2 F-005 fix (P1): journal append を O_NOFOLLOW で実行、
            # symlink swap → arbitrary file clobbering を physical reject。
            # Codex PR #82 R2 F-007 fix (P2): journal 初回 create 時に parent dir fsync を実施、
            # crash 後の directory entry loss を防止 (append-only durability guarantee)。
            journal_path.parent.mkdir(parents=True, exist_ok=True)
            is_first_create = not journal_path.exists()
            journal_fd = os.open(
                str(journal_path),
                os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW,
                0o600,
            )
            try:
                journal_line = json.dumps(
                    {
                        **signed_entry.canonical_payload(),
                        "signature": signed_entry.signature,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8") + b"\n"
                _write_all(journal_fd, journal_line)
                os.fsync(journal_fd)
            finally:
                os.close(journal_fd)
            if is_first_create:
                # parent dir fsync for first-create directory entry durability
                jdir_fd = os.open(str(journal_path.parent), os.O_RDONLY)
                try:
                    os.fsync(jdir_fd)
                finally:
                    os.close(jdir_fd)
            # write counter atomically
            new_counter_payload = {"epoch": new_epoch, "issued_at": issued_at}
            new_counter_canonical = _rfc8785_canonical_bytes(new_counter_payload)
            new_counter_payload["sha256"] = _sha256_hex(new_counter_canonical)
            counter_tmp = counter_path.with_suffix(f".tmp.{uuid.uuid4().hex}")
            counter_path.parent.mkdir(parents=True, exist_ok=True)
            with counter_tmp.open("wb") as cf:
                cf.write(json.dumps(new_counter_payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
                cf.flush()
                os.fsync(cf.fileno())
            os.rename(str(counter_tmp), str(counter_path))
            # fsync parent dir for rename durability
            dir_fd = os.open(str(counter_path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
            return new_epoch, issued_at, signed_entry
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


# === Helper: write/read marker ===


# marker file 1 件あたりの最大 size cap (truncation defense)
_MARKER_MAX_BYTES: Final = 1024 * 1024  # 1 MiB


def _write_all(fd: int, data: bytes) -> None:
    """Codex PR #82 R1 F-007 fix (P2): os.write は短い write (short write) を返す可能性が
    あるため、全 bytes 書込めるまで loop。EINTR は OS-level で retry されるが、念のため
    write 戻り値を確認。
    """
    view = memoryview(data)
    total = 0
    while total < len(view):
        written = os.write(fd, view[total:])
        if written == 0:
            raise OSError("os.write returned 0 (disk full or unwritable fd)")
        total += written


def _read_all(fd: int, max_bytes: int) -> bytes:
    """Codex PR #82 R1 F-008 fix (P2): os.read は単発で完全 read を保証しないため、
    EOF (b"") まで loop。max_bytes 超過は OSError (truncation defense)。
    """
    chunks: list[bytes] = []
    total = 0
    chunk_size = 64 * 1024  # 64 KiB chunks
    while True:
        remaining = max_bytes - total + 1  # +1 to detect overflow
        if remaining <= 0:
            raise OSError(f"marker file exceeds max bytes limit ({max_bytes})")
        chunk = os.read(fd, min(chunk_size, remaining))
        if not chunk:
            break  # EOF
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise OSError(f"marker file exceeds max bytes limit ({max_bytes})")
    return b"".join(chunks)


def write_marker_atomic(marker_path: Path, marker_doc: dict[str, Any]) -> None:
    """marker file を atomic rename で書込 (O_NOFOLLOW + parent fsync)。

    Codex PR #82 R1 F-007 fix (P2): os.write を _write_all loop に置換、short write
    で truncated JSON が persist する race を防止。
    """
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = marker_path.with_suffix(f".tmp.{uuid.uuid4().hex}")
    canonical = _rfc8785_canonical_bytes(marker_doc)
    # Codex PR #82 R2 F-006 fix (P2): marker temp file を 0o600 (owner-only) で create、
    # rename 後も other local users から read 不可。lock file 0o600 と一貫。
    fd = os.open(str(tmp_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        _write_all(fd, canonical)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.rename(str(tmp_path), str(marker_path))
    dir_fd = os.open(str(marker_path.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def read_marker_doc(marker_path: Path) -> dict[str, Any]:
    """marker file を読込 (O_NOFOLLOW + canonical 正規化なし、1 MiB cap)。

    Codex PR #82 R1 F-008 fix (P2): os.read を _read_all loop (EOF まで) に置換、
    short read で truncated JSON decode が intermittent fail する race を防止。
    """
    fd = os.open(str(marker_path), os.O_RDONLY | os.O_NOFOLLOW)
    try:
        raw = _read_all(fd, _MARKER_MAX_BYTES)
    finally:
        os.close(fd)
    return json.loads(raw)
