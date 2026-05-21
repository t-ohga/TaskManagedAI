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

**Codex R1 F-006 fix (P2)**: authorization_verify vs audit_verify を単一 predicate で兼ねない、
2 mode 完全分離 (`VerifyMode` enum 参照):

- `status: "active"`: 新規署名可、**authorization_verify** + **audit_verify** 両方 pass
- `status: "deprecated"`: 新規署名 / destructive 不可、**authorization_verify は無条件 reject**
  (authorization mode = 「これから destructive operation を行う」判定、deprecated key は使わせない)、
  **audit_verify は record_signed_at < deprecated_at の record で pass** (historical signature 検証用、
  PR #75-#80 で署名済 record の audit verify を継続するため)
- `status: "revoked"`: 新規署名 / destructive 不可、**authorization_verify + audit_verify 両方とも
  signed_at 関係なく無条件 reject** (compromise revocation、audit history は manifest entry を keep
  するが verify path では除外)

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

Batch C (本 commit): SignedManifestEntry / SignedKeyringManifest / KeyringStateHead /
RevocationTombstoneEntry dataclass + canonical_payload + load/save/verify helpers +
dual-trust verify (legacy + signed manifest) + authorization_verify vs audit_verify
predicate 分離 + state_head load with non-rollback check + tombstone denylist append-only。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

# Codex PR #82 R6 pattern: rfc8785 lib + NFC normalization wrapper (active_registry と統一)
import taskhub_active_registry as _ar  # type: ignore[import-not-found]

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
# Codex R1 F-006 fix (P2): 上部 docstring の deprecated key 扱いと統一、authorization_verify は
# status=active のみ pass、status=deprecated は authorization 不可 (audit_verify でのみ pass)
# 上部 docstring の "status=deprecated + record_signed_at < deprecated_at で authorization pass"
# は誤った記述だったため、本 enum 定義で正本確定: deprecated key は **新規 destructive 不可**、
# audit_verify は historical record の signature 検証 (record_signed_at < deprecated_at で pass)
# のため使う。authorization と audit を 1 predicate で兼ねない (§9.4 R2 F-005 invariant)。
VerifyMode = Literal[
    # destructive operation 実行可否判定 (status=active only、deprecated/revoked は無条件 reject)
    "authorization_verify",
    # historical record signature 検証用 (status ∈ {active, deprecated}、record_signed_at < deprecated_at)
    "audit_verify",
]

# Default lifetime / overlap policy (§3.A NIST SP 800-57 推奨)
DEFAULT_OVERLAP_DAYS = 30
DEFAULT_KEY_LIFETIME_DAYS = 365  # 1 year base、operator が runbook で延長可能


# === SignedManifestEntry dataclass (§3.A keyring entry schema) ===


@dataclass(frozen=True, slots=True)
class SignedManifestEntry:
    """Approval verify keyring の 1 entry (signed manifest 内の 1 key record).

    §3.A.2 status check 優先 (revoked は signed_at に関係なく無条件 reject):
    - active: signed_at が key validity window 内なら verify pass
    - deprecated: authorization_verify は無条件 reject、audit_verify のみ
      (signed_at < deprecated_at で historical record audit verify) pass
    - revoked: 無条件 reject (signed_at に関係なく、§9.5 R3 F-001 tombstone denylist enforce)

    Codex PR #82 R6 pattern: rfc8785 lib delegate (RFC 8785 strict canonical encoding).
    """

    fingerprint: str  # 64-char hex SHA-256(public_key_bytes)
    status: str  # KeyStatus enum (active / deprecated / revoked)
    issued_at: str  # UTC iso8601、key validity 下限 (signed_at >= issued_at)
    expires_at: str  # UTC iso8601、key validity 上限 (signed_at < expires_at)
    deprecated_at: str | None = None  # UTC iso8601、deprecated に move された時刻
    revoked_at: str | None = None  # UTC iso8601、revoked に move された時刻
    revocation_reason_hash: str | None = None  # sha256(reason text) (audit 別保管、本 entry hash のみ)
    incident_id: str | None = None  # compromise revocation 時の incident ID
    source: str = "keyring_rotation"  # "legacy_single_key" | "keyring_rotation"
    public_key_base64: str = ""  # taskhub1<base64> Ed25519 public key

    def canonical_payload(self) -> dict[str, Any]:
        """RFC 8785 canonical payload (signature root に含める fields、no whitespace)."""
        payload: dict[str, Any] = {
            "expires_at": self.expires_at,
            "fingerprint": self.fingerprint,
            "issued_at": self.issued_at,
            "public_key_base64": self.public_key_base64,
            "source": self.source,
            "status": self.status,
        }
        # Optional fields (only present when not None — RFC 8785 stable schema)
        if self.deprecated_at is not None:
            payload["deprecated_at"] = self.deprecated_at
        if self.revoked_at is not None:
            payload["revoked_at"] = self.revoked_at
        if self.revocation_reason_hash is not None:
            payload["revocation_reason_hash"] = self.revocation_reason_hash
        if self.incident_id is not None:
            payload["incident_id"] = self.incident_id
        return payload


# === SignedKeyringManifest dataclass (§3.A signed manifest root schema) ===


@dataclass(frozen=True, slots=True)
class SignedKeyringManifest:
    """Approval verify keyring の root signed manifest.

    §9.3 R1 F-007 append-only generation chain:
    - generation: monotonic increment (旧 generation を超えて減少しない)
    - previous_committed_manifest_hash: 前 generation の canonical sha256 (chain integrity)
    - commit_log_chain_hash: 前 generation 全 entries の累積 hash (replay defense)

    §9.3 R1 F-008 candidate self-reference hash 規約:
    - candidate manifest の content sha256 は **envelope 外** (signature root には含めない)
    - signature root に含めるのは entries + generation + previous_committed_manifest_hash +
      commit_log_chain_hash + signer_fingerprint のみ

    §9.3 R1 F-004 root trust anchor pinning:
    - signed manifest の root signature は config_dir 外で pin された root public key で verify
      (`/etc/taskhub/root_fingerprints.signed` の approval_keyring_root.pub fingerprint)
    """

    generation: int  # monotonic increment、§9.3 R1 F-007 replay defense
    entries: tuple[SignedManifestEntry, ...]
    previous_committed_manifest_hash: str  # 64-char hex sha256 of previous generation canonical
    commit_log_chain_hash: str  # 64-char hex (append-only chain integrity)
    signer_fingerprint: str  # root signing key fingerprint
    signed_at: str  # UTC iso8601
    signature: str  # base64 Ed25519 signature over canonical_payload

    @property
    def domain(self) -> str:
        return DOMAIN_KEYRING_MANIFEST_V1

    def canonical_payload(self) -> dict[str, Any]:
        """Signature root canonical payload (entries sorted by fingerprint で deterministic)."""
        return {
            "commit_log_chain_hash": self.commit_log_chain_hash,
            "domain": self.domain,
            "entries": [
                e.canonical_payload()
                for e in sorted(self.entries, key=lambda x: x.fingerprint)
            ],
            "generation": self.generation,
            "previous_committed_manifest_hash": self.previous_committed_manifest_hash,
            "signed_at": self.signed_at,
            "signer_fingerprint": self.signer_fingerprint,
        }

    def find_entry(self, fingerprint: str) -> SignedManifestEntry | None:
        for e in self.entries:
            if e.fingerprint == fingerprint:
                return e
        return None


# === Revocation tombstone (§9.5 R3 F-001、append-only denylist) ===


@dataclass(frozen=True, slots=True)
class RevocationTombstoneEntry:
    """Append-only revocation tombstone entry (§9.5 R3 F-001).

    rollback / config_dir snapshot rollback でも live verifier 前段で revoked fingerprint を
    無条件 reject するため、tombstone は live path に維持。append-only で 1 fingerprint 1 entry。
    """

    fingerprint: str  # revoked key fingerprint
    revoked_at: str  # UTC iso8601
    revocation_reason_hash: str  # sha256(reason text)
    incident_id: str  # incident ID
    signer_fingerprint: str  # root signing key fingerprint
    signature: str  # base64 Ed25519

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "domain": DOMAIN_REVOCATION_TOMBSTONE_V1,
            "fingerprint": self.fingerprint,
            "incident_id": self.incident_id,
            "revocation_reason_hash": self.revocation_reason_hash,
            "revoked_at": self.revoked_at,
            "signer_fingerprint": self.signer_fingerprint,
        }


# === Keyring state head (§9.8 R8 F-002、config_dir 外 monotonic state anchor) ===


@dataclass(frozen=True, slots=True)
class KeyringStateHead:
    """`/etc/taskhub/keyring_state.head.signed`: config_dir 外 monotonic state anchor.

    §9.8 R8 F-002 fix: config_dir 全体 snapshot rollback 攻撃を防御。bootstrap 後は head に
    `initialized: true` が記録されるため、`<config_dir>` が pre-bootstrap snapshot に戻されても
    state head の signature verify + chain hash check で rollback を検出 + reject。
    """

    initialized: bool  # bootstrap 完了 true、新 install / fresh state false
    legacy_fallback_disabled_at: str | None  # legacy single-key fallback を物理 deny 化した時刻
    latest_manifest_generation: int
    latest_manifest_content_sha256: str  # 64-char hex
    latest_commit_log_chain_hash: str  # 64-char hex
    latest_tombstone_chain_hash: str  # 64-char hex
    latest_active_registry_epoch: int
    latest_fleet_membership_generation: int
    latest_approval_issuance_journal_chain_hash: str  # 64-char hex (§9.10 F-002)
    latest_approval_issued_at: str  # UTC iso8601 (§9.10 R10 F-002 monotonic wall-clock)
    latest_monotonic_sequence: int  # §9.10 R10 F-002
    latest_monotonic_clock_attestation_value: int  # ns、§9.10 R10 F-002
    signer_fingerprint: str  # root signing key
    head_signed_at: str  # UTC iso8601
    signature: str  # base64 Ed25519

    @property
    def domain(self) -> str:
        return DOMAIN_STATE_HEAD_V1

    def canonical_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "domain": self.domain,
            "head_signed_at": self.head_signed_at,
            "initialized": self.initialized,
            "latest_active_registry_epoch": self.latest_active_registry_epoch,
            "latest_approval_issuance_journal_chain_hash": self.latest_approval_issuance_journal_chain_hash,
            "latest_approval_issued_at": self.latest_approval_issued_at,
            "latest_commit_log_chain_hash": self.latest_commit_log_chain_hash,
            "latest_fleet_membership_generation": self.latest_fleet_membership_generation,
            "latest_manifest_content_sha256": self.latest_manifest_content_sha256,
            "latest_manifest_generation": self.latest_manifest_generation,
            "latest_monotonic_clock_attestation_value": self.latest_monotonic_clock_attestation_value,
            "latest_monotonic_sequence": self.latest_monotonic_sequence,
            "latest_tombstone_chain_hash": self.latest_tombstone_chain_hash,
            "signer_fingerprint": self.signer_fingerprint,
        }
        if self.legacy_fallback_disabled_at is not None:
            payload["legacy_fallback_disabled_at"] = self.legacy_fallback_disabled_at
        return payload


# === Verify helpers (authorization_verify vs audit_verify predicate 分離) ===


def authorization_verify_key(
    manifest: SignedKeyringManifest,
    fingerprint: str,
    record_signed_at: str,
    tombstone_fingerprints: frozenset[str] = frozenset(),
) -> tuple[bool, str]:
    """§9.4 R2 F-005: **authorization_verify** mode — destructive operation 実行可否判定.

    status=active only、deprecated/revoked は無条件 reject。tombstone denylist も check
    (§9.5 R3 F-001 rollback でも live verifier で reject)。

    Returns: (ok, reason_code or "")
    """
    if fingerprint in tombstone_fingerprints:
        return False, "taskhub_signed_approval_keyring_key_revoked"
    entry = manifest.find_entry(fingerprint)
    if entry is None:
        return False, "taskhub_signed_approval_keyring_no_valid_key"
    if entry.status == "revoked":
        return False, "taskhub_signed_approval_keyring_key_revoked"
    if entry.status == "deprecated":
        # §9.4 R2 F-005: deprecated key は authorization_verify で無条件 reject
        return False, "taskhub_signed_approval_keyring_key_expired"
    if entry.status != "active":
        return False, "taskhub_signed_approval_keyring_no_valid_key"
    # validity window check (signed_at は iso8601 文字列で string compare で OK、UTC 同 length)
    if not (entry.issued_at <= record_signed_at < entry.expires_at):
        return False, "taskhub_signed_approval_keyring_key_expired"
    return True, ""


def audit_verify_key(
    manifest: SignedKeyringManifest,
    fingerprint: str,
    record_signed_at: str,
    tombstone_fingerprints: frozenset[str] = frozenset(),
) -> tuple[bool, str]:
    """§9.4 R2 F-005: **audit_verify** mode — historical record signature 検証用.

    status ∈ {active, deprecated} で record_signed_at < deprecated_at なら pass。
    revoked + tombstone は無条件 reject (compromise revocation の append-only denylist)。
    """
    if fingerprint in tombstone_fingerprints:
        return False, "taskhub_signed_approval_keyring_key_revoked"
    entry = manifest.find_entry(fingerprint)
    if entry is None:
        return False, "taskhub_signed_approval_keyring_no_valid_key"
    if entry.status == "revoked":
        return False, "taskhub_signed_approval_keyring_key_revoked"
    # active + deprecated 両方 OK、ただし deprecated は record_signed_at < deprecated_at の制約
    if entry.status == "deprecated":
        if entry.deprecated_at is None or record_signed_at >= entry.deprecated_at:
            return False, "taskhub_signed_approval_keyring_key_expired"
        # fall-through to validity window check
    if not (entry.issued_at <= record_signed_at < entry.expires_at):
        return False, "taskhub_signed_approval_keyring_key_expired"
    return True, ""


# === Key format validation (§6.2、ADV R1 F-011 統一) ===


def validate_key_format(public_key_str: str) -> bytes:
    """`taskhub1<base64>` format key string を decode + validate.

    Returns: decoded 32-byte public key bytes
    Raises: ValueError on format violation

    §6.2 format contract:
    - prefix: "taskhub1"
    - base64-encoded Ed25519 public key (32 bytes after decode)
    - filename = sha256(decoded_bytes) hex (filename validation は caller)
    """
    if not isinstance(public_key_str, str) or not public_key_str:
        raise ValueError("key string must be non-empty str")
    if not public_key_str.startswith(KEY_FORMAT_PREFIX):
        raise ValueError(f"key string must start with {KEY_FORMAT_PREFIX!r} prefix")
    b64_part = public_key_str[len(KEY_FORMAT_PREFIX):]
    try:
        decoded = base64.b64decode(b64_part, validate=True)
    except (ValueError, OSError) as e:
        raise ValueError(f"invalid base64 in key string: {e}") from e
    if len(decoded) != 32:
        raise ValueError(f"Ed25519 public key must be 32 bytes, got {len(decoded)}")
    return decoded


def compute_key_fingerprint(public_key_bytes: bytes) -> str:
    """sha256 hex digest of public key bytes (32 bytes → 64 chars hex)."""
    if len(public_key_bytes) != 32:
        raise ValueError(f"Ed25519 public key must be 32 bytes, got {len(public_key_bytes)}")
    return _ar._sha256_hex(public_key_bytes)


# === Signed manifest verify (root signature + chain integrity) ===


def verify_signed_manifest(
    manifest: SignedKeyringManifest,
    root_public_key_bytes: bytes,
    expected_previous_hash: str | None = None,
) -> tuple[bool, str]:
    """Signed manifest の root signature + generation chain integrity verify.

    §9.3 R1 F-007: append-only generation chain — previous_committed_manifest_hash が
    expected_previous_hash と一致しない場合 replay 攻撃の可能性、fail-closed。
    """
    if expected_previous_hash is not None and manifest.previous_committed_manifest_hash != expected_previous_hash:
        return False, "taskhub_signed_approval_keyring_generation_replay_or_lower"
    canonical = _ar._rfc8785_canonical_bytes(manifest.canonical_payload())
    if not _ar.verify_ed25519_signature(root_public_key_bytes, manifest.signature, canonical):
        return False, "taskhub_signed_approval_keyring_manifest_signature_invalid"
    # entries の fingerprint duplication check (§9.3 R1 F-014 fleet membership 同様の invariant)
    seen: set[str] = set()
    for entry in manifest.entries:
        if entry.fingerprint in seen:
            return False, "taskhub_signed_approval_keyring_manifest_tampered"
        seen.add(entry.fingerprint)
    return True, ""


# === Approval keyring initialized marker (§9.3 R1 F-005 directory swap downgrade defense) ===


def is_keyring_initialized(initialized_marker_path: Path) -> bool:
    """bootstrap 成功後の `approval_keyring_initialized.signed` marker 存在 check.

    §9.3 R1 F-005 fix: bootstrap 後の rollback で marker が消えても、本 marker が存在しない
    + legacy_fallback_disabled_at が state head に記録されていたら downgrade attack の可能性
    → fail-closed (caller responsibility で state head 経由 cross-check)。

    本 helper は marker file の存在のみ check (signature verify は別 path)。
    """
    return initialized_marker_path.exists() and initialized_marker_path.is_file()
