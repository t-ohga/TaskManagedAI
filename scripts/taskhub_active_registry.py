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

本 commit (`e23c203`) では ReasonCode Literal + class skeleton のみ。
実装は次 session の Batch B で完成する。
"""

from __future__ import annotations

from typing import Literal

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
