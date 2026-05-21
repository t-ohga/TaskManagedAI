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
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

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


def _rfc8785_canonical_bytes(payload: dict[str, Any]) -> bytes:
    """RFC 8785 strict JCS canonical JSON encoder.

    sort_keys=True + separators=(',', ':') + ensure_ascii=False + NFC UTF-8。
    nested dict は recursive に sort される (json.dumps の sort_keys=True で達成)。
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


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
) -> tuple[bool, str]:
    """`marker.host_id` と signer fingerprint ownership を exact match。

    Returns: (ok, reason_code or "" on ok)
    """
    host = fleet.find_host(marker_host_id)
    if host is None:
        return False, "taskhub_active_registry_fleet_membership_violation"
    if host.status not in ("active",):
        return False, "taskhub_active_registry_host_revoked_or_retired"
    if marker_signer_fingerprint not in host.allowed_marker_signer_fingerprints:
        return False, "taskhub_active_registry_signer_not_in_allowlist"
    if marker_kind not in host.allowed_marker_kinds:
        return False, "taskhub_active_registry_role_demoted_in_current_fleet"
    return True, ""


# === Epoch atomic counter with fcntl lock (§9.3 R1 F-007 + R1 F-010) ===


def allocate_next_epoch(
    counter_path: Path,
    lock_path: Path,
    journal_path: Path,
    host_id: str,
    writer_signer_fingerprint: str,
    private_key_signer: Callable[[bytes], bytes],  # callable: bytes -> bytes (Ed25519 sign)
) -> tuple[int, str, EpochJournalEntry]:
    """epoch counter を atomic に増分し、signed journal entry を append。

    Pattern (§9.3 R1 F-007 + R1 F-010):
        1. lock_path に LOCK_EX|LOCK_NB を取得 (lock_path は rename 不可、安定 inode)
        2. counter_path を読込 (sha256 verify)
        3. epoch N+1 計算 + issued_at = now() を同時記録
        4. journal_path の末尾 entry hash 計算 → previous_entry_hash
        5. EpochJournalEntry canonical → private_key_signer で署名
        6. journal_path に append + fsync
        7. counter_path を atomic rename で書込 (epoch=N+1, sha256=self_hash)
        8. lock release

    Returns: (new_epoch, issued_at_iso8601, journal_entry)
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # touch lock file with secure permission
    if not lock_path.exists():
        fd_create = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(fd_create)
    # acquire exclusive lock
    fd = os.open(str(lock_path), os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            # read current counter (or initialize)
            current_epoch = 0
            if counter_path.exists():
                with counter_path.open("rb") as f:
                    raw = f.read()
                counter_doc = json.loads(raw)
                expected_sha = counter_doc.get("sha256")
                # self-referential sha256: payload minus sha256 field
                check_payload = {k: v for k, v in counter_doc.items() if k != "sha256"}
                check_canonical = _rfc8785_canonical_bytes(check_payload)
                if _sha256_hex(check_canonical) != expected_sha:
                    raise RuntimeError("taskhub_active_registry_epoch_counter_tampered")
                current_epoch = int(counter_doc["epoch"])
            # allocate next epoch
            new_epoch = current_epoch + 1
            issued_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            # read journal last entry hash
            previous_entry_hash = "0" * 64  # genesis
            if journal_path.exists():
                with journal_path.open("rb") as jf:
                    last_line = b""
                    for line in jf:
                        if line.strip():
                            last_line = line
                if last_line:
                    last_entry = json.loads(last_line)
                    last_canonical = _rfc8785_canonical_bytes(
                        {k: v for k, v in last_entry.items() if k != "signature"}
                    )
                    previous_entry_hash = _sha256_hex(last_canonical)
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
            # append journal (atomic via temp file + rename is hard for jsonl;
            # use O_APPEND + fsync to maintain durability)
            journal_path.parent.mkdir(parents=True, exist_ok=True)
            with journal_path.open("ab") as jf:
                jf.write(json.dumps({
                    **signed_entry.canonical_payload(),
                    "signature": signed_entry.signature,
                }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
                jf.write(b"\n")
                jf.flush()
                os.fsync(jf.fileno())
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


def write_marker_atomic(marker_path: Path, marker_doc: dict[str, Any]) -> None:
    """marker file を atomic rename で書込 (O_NOFOLLOW + parent fsync)。"""
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = marker_path.with_suffix(f".tmp.{uuid.uuid4().hex}")
    canonical = _rfc8785_canonical_bytes(marker_doc)
    # write with restrictive permission
    fd = os.open(str(tmp_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o644)
    try:
        os.write(fd, canonical)
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
    """marker file を読込 (O_NOFOLLOW + canonical 正規化なし)。

    呼び出し側で domain + canonical_payload + signature verify を行う。
    """
    fd = os.open(str(marker_path), os.O_RDONLY | os.O_NOFOLLOW)
    try:
        raw = os.read(fd, 1024 * 1024)  # 1 MiB cap
    finally:
        os.close(fd)
    return json.loads(raw)
