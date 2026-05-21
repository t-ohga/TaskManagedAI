"""Approval verify keyring rotation (SP-012 Batch C、ADR-00029).

`.claude/plans/sp012-split-brain-keyring.md` §3.A + §3.C + §6.2 + §6.5 + §9.3-§9.9 で
確定した approval verify keyring rotation 実装の foundational module。

# Implementation contract

本 module は §9.3-§9.9 hardening contract を **canonical final spec** として実装する。

## Keyring schema (§3.A、§9.3 R1 F-006 multi-file install race fix)

- key file path: `<config_dir>/approval-verify-keys.d/<fingerprint>.pub`
  - format: `taskhub1<base64>` (Ed25519 32 bytes、§6.2 format contract)
  - filename = sha256(decoded_32_bytes) hex
  - permission: 0o400
- signed manifest path: `<config_dir>/approval-verify-keyring.signed.json`
  - root-signed by `approval_keyring_root.pub` (config_dir 外 pin、§9.3 R1 F-004)
  - entries: status / fingerprint / issued_at / expires_at / deprecated_at / revoked_at /
    revocation_reason_hash / incident_id / source ("legacy_single_key" | "keyring_rotation")
- generation directory: `<config_dir>/approval-verify-keyring.generations/<generation_id>/`
  - atomic install via `current` pointer rename (§9.3 R1 F-006)
  - dirfd + O_NOFOLLOW load (§9.3 R1 F-009 path traversal defense)

## Lifecycle (§6.5、§9.4 R2 F-005 authorization vs audit predicate 分離)

- `status: "active"`: 新規署名可、authorization_verify + audit_verify 両方 pass
- `status: "deprecated"`: 新規署名不可、authorization_verify は record_signed_at < deprecated_at
  のみ pass、audit_verify は issued_at <= signed_at < expires_at で pass
- `status: "revoked"`: signed_at 関係なく無条件 reject (audit history 維持のため entry は keep)

## KeyringRotationApprovalClaim 5 variants (§3.C.1、§9.3 R1 F-012 bootstrap 追加)

- `bootstrap`: first deployment 用、legacy `approval-verify-key.pub` を signed manifest
  initial entry として登録、legacy_not_before 必須 (§9.4 R2 F-004)
- `add_key`: 新 key entry 追加、server-owned expires_at (caller-supplied 物理削除)
- `remove_key`: status active → deprecated、in-flight check
- `revoke_key`: status active|deprecated → revoked、incident_id + revocation_reason_hash
- `commit_manifest`: signed candidate manifest を atomic install、transition policy verify

## Server-owned approval issuance journal (§9.9 R9 F-002)

- path: `<config_dir>/approvals/issuance_journal.signed.jsonl` (append-only、server-signed)
- entry schema: approval_id + claim_hash + issued_at + monotonic_sequence +
  previous_issued_at + issuer_signer_fingerprint + previous_entry_hash +
  key_fingerprint_at_issue + key_status_at_issue + monotonic_clock_attestation
- authorization_verify で journal cross-check (§9.4 R2 F-005 + §9.9 R9 F-002)

## State head anchor (§9.8 R8 F-002、ADR-00028 と共有)

- path: `/etc/taskhub/keyring_state.head.signed` (config_dir 外 monotonic state anchor)
- fields: initialized + legacy_fallback_disabled_at + latest_manifest_generation +
  latest_manifest_content_sha256 + latest_commit_log_chain_hash +
  latest_tombstone_chain_hash + latest_active_registry_epoch +
  latest_fleet_membership_generation + latest_approval_issued_at +
  latest_monotonic_sequence + latest_monotonic_clock_attestation_value +
  latest_approval_issuance_journal_chain_hash (§9.10 R10 F-002)

## Revocation tombstone denylist (§9.5 R3 F-001、rollback でも live path で維持)

- path: `<config_dir>/approval_keyring_revocation_tombstone.signed.jsonl` (append-only)
- live verifier 前段 denylist、revoked fingerprint は legacy verifier (single-key fallback
  mode) でも無条件 reject

## Implementation status

本 commit (`e23c203`) では schema constants + class skeleton のみ。
実装は次 session の Batch C で完成する。
"""

from __future__ import annotations

from typing import Literal

# Key status enum (§6.5 lifecycle vs compromise revocation 区別)
KeyStatus = Literal["active", "deprecated", "revoked"]

# KeyringRotationApprovalClaim operation enum (§3.C.1、§9.3 R1 F-012 bootstrap 追加)
KeyringOperation = Literal[
    "bootstrap",  # first deployment、legacy single key を initial entry 化
    "add_key",  # 新 key entry 追加
    "remove_key",  # active → deprecated (lifecycle expiry)
    "revoke_key",  # → revoked (compromise revocation)
    "commit_manifest",  # signed candidate manifest atomic install
]

# Manifest signature domain (RFC 8785 + Ed25519)
DOMAIN_KEYRING_MANIFEST_V1 = "taskhub.approval_verify_keyring.v1"
DOMAIN_KEYRING_INITIALIZED_V1 = "taskhub.approval_keyring_initialized.v1"
DOMAIN_REVOCATION_TOMBSTONE_V1 = "taskhub.approval_keyring_revocation_tombstone.v1"
DOMAIN_STATE_HEAD_V1 = "taskhub.keyring_state.head.v1"

# Key format prefix (§6.2 ADV R1 F-011 統一)
KEY_FORMAT_PREFIX = "taskhub1"

# Permission constants
KEY_FILE_PERMISSION = 0o400  # read-only owner
KEYRING_DIR_PERMISSION = 0o700  # owner only

# Verify path mode (§9.4 R2 F-005 authorization vs audit predicate 分離)
VerifyMode = Literal[
    "authorization_verify",  # destructive operation 実行可否判定 (status=active only)
    "audit_verify",  # historical record audit 用 (status ∈ {active, deprecated})
]

# Default lifetime / overlap policy (§3.A NIST SP 800-57 推奨)
DEFAULT_OVERLAP_DAYS = 30
DEFAULT_KEY_LIFETIME_DAYS = 365  # 1 year base、operator が runbook で延長可能
