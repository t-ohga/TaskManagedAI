"""Server-owned approval issuance journal (SP-012 Batch C、ADR-00029、§9.9 R9 F-002).

`.claude/plans/sp012-split-brain-keyring.md` §9.9 + §9.10 で確定した server-owned
approval issuance journal + clock monotonicity attestation 実装の foundational module。

# Implementation contract

## Issuance journal schema (§9.9 R9 F-002 + §9.10 R10 F-002)

- path: `<config_dir>/approvals/issuance_journal.signed.jsonl`
- append-only、server-signed by issuance journal **issuer signing key** (Ed25519 **private key**、
  e.g. `/etc/taskhub/issuance_journal_issuer.key` config_dir 外で root-owned + 0o400 で deploy、
  対応する **verify-only public key** は `<config_dir>/issuance_journal_issuer.pub` で配備、
  loader は public key で signature verify のみ実施。private key は AI / runner / artifact /
  log に出さない、rules/secretbroker-boundary.md raw secret 非保存 invariant 遵守)
  **Codex R1 F-005 fix (P1)**: 公開鍵では署名できない、private signing key と verify-only public key を明示分離
- 各 entry の canonical schema:

```json
{
  "approval_id": "<uuid>",
  "claim_hash": "<sha256 of signed claim payload>",
  "issued_at": "<UTC iso8601、server clock>",
  "monotonic_sequence": <int>,                              // §9.10 R10 F-002 必須
  "previous_issued_at": "<UTC iso8601 of previous entry>",  // §9.10 R10 F-002 必須
  "issuer_signer_fingerprint": "<server-owned issuer key fp>",
  "previous_entry_hash": "<sha256 of prev entry canonical>",
  "key_fingerprint_at_issue": "<keyring active key fp at issue>",
  "key_status_at_issue": "active",
  "monotonic_clock_attestation": {  // §9.10 R10 F-002 必須 (Codex R1 F-003 fix)
    "source": "linux_clock_monotonic" | "tpm_clock" | "trusted_time_attestation",
    "value": <int nanoseconds>,
    "previous_value": <int nanoseconds>
  },
  "domain": "taskhub.approval_issuance_journal.v1"
}
```

## Invariants (issue path / verify path 両方で fail-closed)

1. monotonic_sequence == previous_monotonic_sequence + 1 (§9.10 R10 F-002)
2. **issued_at >= previous_issued_at - ε** (許容 clock skew ε = 5 seconds for NTP backward correction、
   Codex R1 F-001 fix (P1): 元の `issued_at >= previous_issued_at` 必須化は NTP backward correction で
   時刻が数秒戻る正常ケースを fail-closed にしていたため、`- ε` を明示。`(previous_issued_at - new issued_at) > ε`
   の場合のみ `taskhub_approval_issuance_journal_monotonic_regression_detected` で reject)
3. monotonic_clock_attestation.value > monotonic_clock_attestation.previous_value (**必須**、
   Codex R1 F-003 fix (P2): schema 記述を必須化 + invariant 3 と整合、attestation 非搭載 mode は
   `taskhub_approval_issuance_monotonic_clock_source_unavailable` で deploy 時 reject)
4. journal の previous_entry_hash chain が完全 (journal truncate / replay 検出)

## Caller-supplied `signed_at` 物理削除 (§9.9 R9 F-002)

approval issue path で:
- claim canonical payload を operator が prepare
- server-owned issue path が atomic に:
  - approval_id (UUID) 生成
  - 現在時刻取得 (server NTP-synced clock) → `issued_at`
  - 現 keyring active key fp 抽出 → `key_fingerprint_at_issue`
  - issuance_journal 末尾 entry hash 読み → `previous_entry_hash` 計算
  - issuance entry canonical → server signing key で署名 → journal append + parent fsync
- CLI が caller-supplied `--signed-at` を受け取る path は **物理削除**

## Clock monotonicity 3 mode (§9.10 R10 F-002、operator runbook §21)

- Mode A (Linux CLOCK_MONOTONIC + NTP): host clock_gettime(CLOCK_MONOTONIC) を
  `monotonic_clock_attestation.value` に記録 (host reboot で reset、reboot detection 必要)
- Mode B (TPM clock + signed attestation): TPM monotonic counter を attestation 経由
  (host reboot 耐性)
- Mode C (Remote trusted time service): NTP roughtime / TLSdate などの外部 signed attestation

P0 default は Mode A (single-host VPS で十分)、本格 fleet 運用は Mode B/C 推奨。

## Reboot detection (Mode A 専用、§9.10 R10 F-002)

- host reboot で CLOCK_MONOTONIC が reset
- reboot 後の最初の issue で previous monotonic value より new value が小さい場合 reboot 検出
- `<config_dir>/active_registry/reboot_attestation.signed.jsonl` に reboot event 記録
- operator 明示承認 (`taskhub approval issuance reboot-attest` 新規 CLI) 必須

## Implementation status

Batch C 第 2 段 (本 commit): IssuanceJournalEntry dataclass + canonical_payload + chain
integrity verify + monotonic invariants + clock attestation 3 mode foundational logic.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

# Codex PR #82 R6 pattern: rfc8785 lib + NFC normalization wrapper (active_registry と統一)
import taskhub_active_registry as _ar  # type: ignore[import-not-found]

# Issuance journal signature domain (RFC 8785 + Ed25519)
DOMAIN_ISSUANCE_JOURNAL_V1 = "taskhub.approval_issuance_journal.v1"
DOMAIN_REBOOT_ATTESTATION_V1 = "taskhub.active_registry.reboot_attestation.v1"

# Clock attestation source enum (§9.10 R10 F-002 operator runbook §21)
ClockAttestationSource = Literal[
    "linux_clock_monotonic",  # Mode A: host clock_gettime(CLOCK_MONOTONIC) + NTP
    "tpm_clock",  # Mode B: TPM monotonic counter signed attestation
    "trusted_time_attestation",  # Mode C: NTP roughtime / TLSdate external signed
]

# Default clock skew tolerance for wall-clock monotonicity (§9.10 R10 F-002)
WALL_CLOCK_SKEW_TOLERANCE_SECONDS = 5

# Issuance path constants (§9.9 R9 F-002)
ISSUANCE_JOURNAL_FILENAME = "issuance_journal.signed.jsonl"
ISSUANCE_JOURNAL_DIR_NAME = "approvals"  # under <config_dir>/

# Reboot attestation path constant (§9.10 R10 F-002 Mode A 専用)
REBOOT_ATTESTATION_FILENAME = "reboot_attestation.signed.jsonl"
REBOOT_ATTESTATION_DIR_NAME = "active_registry"  # under <config_dir>/

# Key status enum at issue time (§9.9 R9 F-002 必須 condition)
# server issue path は key.status != "active" の場合 issue refuse
ISSUE_ALLOWED_KEY_STATUS = "active"


# === MonotonicClockAttestation dataclass (§9.10 R10 F-002) ===


@dataclass(frozen=True, slots=True)
class MonotonicClockAttestation:
    """Monotonic clock attestation (§9.10 R10 F-002 必須 field).

    source は 3 mode のいずれか (Mode A: linux_clock_monotonic, Mode B: tpm_clock,
    Mode C: trusted_time_attestation)。value は nanoseconds、previous_value は前 entry の値。
    invariant: value > previous_value (wall-clock とは独立な monotonic check)。
    """

    source: str  # ClockAttestationSource enum
    value: int  # ns
    previous_value: int  # ns、前 entry の value

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "previous_value": self.previous_value,
            "source": self.source,
            "value": self.value,
        }


# === IssuanceJournalEntry dataclass (§9.9 R9 F-002) ===


@dataclass(frozen=True, slots=True)
class IssuanceJournalEntry:
    """Server-owned approval issuance journal entry (§9.9 R9 F-002 + §9.10 R10 F-002).

    Append-only、server-signed by issuance_journal_issuer signing key。
    各 entry は previous_entry_hash chain で integrity を保証、monotonic_sequence で
    serial order を強制、monotonic_clock_attestation で wall-clock rollback を独立検出。

    Invariants (issue path / verify path 両方で fail-closed):
    1. monotonic_sequence == previous_monotonic_sequence + 1
    2. issued_at >= previous_issued_at - ε (NTP backward correction tolerance ε = 5s)
    3. monotonic_clock_attestation.value > monotonic_clock_attestation.previous_value
    4. journal の previous_entry_hash chain が完全 (journal truncate / replay 検出)
    """

    approval_id: str  # UUID
    claim_hash: str  # sha256 of signed claim canonical
    issued_at: str  # UTC iso8601
    monotonic_sequence: int  # §9.10 R10 F-002 required
    previous_issued_at: str  # UTC iso8601 of previous entry (or "1970-01-01T00:00:00Z" for genesis)
    issuer_signer_fingerprint: str  # server-owned issuer key fingerprint
    previous_entry_hash: str  # 64-char hex sha256 of prev entry canonical
    key_fingerprint_at_issue: str  # keyring active key fp at issue time
    key_status_at_issue: str  # must be "active" at issue time
    monotonic_clock_attestation: MonotonicClockAttestation
    signature: str  # base64 Ed25519 over canonical_payload

    @property
    def domain(self) -> str:
        return DOMAIN_ISSUANCE_JOURNAL_V1

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "claim_hash": self.claim_hash,
            "domain": self.domain,
            "issued_at": self.issued_at,
            "issuer_signer_fingerprint": self.issuer_signer_fingerprint,
            "key_fingerprint_at_issue": self.key_fingerprint_at_issue,
            "key_status_at_issue": self.key_status_at_issue,
            "monotonic_clock_attestation": self.monotonic_clock_attestation.canonical_payload(),
            "monotonic_sequence": self.monotonic_sequence,
            "previous_entry_hash": self.previous_entry_hash,
            "previous_issued_at": self.previous_issued_at,
        }


# === Verify chain integrity ===


def verify_issuance_chain_invariants(
    *,
    new_entry: IssuanceJournalEntry,
    previous_entry: IssuanceJournalEntry | None,
) -> tuple[bool, str]:
    """Codex PR #82 R1 F-001 fix (P1): clock skew tolerance + monotonic sequence + clock attestation.

    Returns: (ok, reason_code or "")
    """
    if previous_entry is None:
        # genesis entry — must have monotonic_sequence == 1 and previous_entry_hash == "0"*64
        if new_entry.monotonic_sequence != 1:
            return False, "taskhub_approval_issuance_journal_monotonic_sequence_skip_detected"
        if new_entry.previous_entry_hash != "0" * 64:
            return False, "taskhub_approval_issuance_journal_chain_hash_mismatch"
        # monotonic_clock_attestation.value > previous_value (genesis: previous_value=0 expected)
        if new_entry.monotonic_clock_attestation.value <= new_entry.monotonic_clock_attestation.previous_value:
            return False, "taskhub_approval_issuance_journal_monotonic_regression_detected"
        return True, ""

    # non-genesis: full chain check
    # (1) monotonic_sequence increment
    if new_entry.monotonic_sequence != previous_entry.monotonic_sequence + 1:
        return False, "taskhub_approval_issuance_journal_monotonic_sequence_skip_detected"
    # (2) wall-clock: new issued_at >= previous - ε (allow ε=5s NTP backward correction)
    # iso8601 string lex compare is fine for UTC times of consistent format, but for
    # tolerance-based compare we should parse to datetime
    try:
        new_dt = _ar.validate_iso8601_utc(new_entry.issued_at)
        prev_dt = _ar.validate_iso8601_utc(previous_entry.issued_at)
    except ValueError:
        return False, "taskhub_approval_issuance_journal_entry_signature_invalid"
    skew = (prev_dt - new_dt).total_seconds()
    if skew > WALL_CLOCK_SKEW_TOLERANCE_SECONDS:
        return False, "taskhub_approval_issuance_journal_monotonic_regression_detected"
    # (3) monotonic_clock_attestation.value > previous (independent clock source)
    if new_entry.monotonic_clock_attestation.value <= new_entry.monotonic_clock_attestation.previous_value:
        return False, "taskhub_approval_issuance_journal_monotonic_regression_detected"
    if new_entry.monotonic_clock_attestation.previous_value != previous_entry.monotonic_clock_attestation.value:
        return False, "taskhub_approval_issuance_journal_monotonic_regression_detected"
    # (4) previous_entry_hash chain: new.previous_entry_hash == sha256(prev canonical minus signature)
    prev_canonical_payload = previous_entry.canonical_payload()
    prev_canonical_bytes = _ar._rfc8785_canonical_bytes(prev_canonical_payload)
    expected_prev_hash = _ar._sha256_hex(prev_canonical_bytes)
    if new_entry.previous_entry_hash != expected_prev_hash:
        return False, "taskhub_approval_issuance_journal_chain_hash_mismatch"
    # (5) previous_issued_at consistency
    if new_entry.previous_issued_at != previous_entry.issued_at:
        return False, "taskhub_approval_issuance_journal_chain_hash_mismatch"
    return True, ""


def verify_issuance_entry_signature(
    entry: IssuanceJournalEntry,
    issuer_public_key_bytes: bytes,
) -> bool:
    """Ed25519 signature verify against canonical_payload."""
    canonical = _ar._rfc8785_canonical_bytes(entry.canonical_payload())
    return _ar.verify_ed25519_signature(issuer_public_key_bytes, entry.signature, canonical)


def sign_issuance_entry(
    *,
    unsigned: IssuanceJournalEntry,
    signer: Callable[[bytes], bytes],
) -> IssuanceJournalEntry:
    """Build a signed version of an issuance entry by computing the Ed25519 signature
    over its canonical payload.
    """
    canonical = _ar._rfc8785_canonical_bytes(unsigned.canonical_payload())
    sig_bytes = signer(canonical)
    return IssuanceJournalEntry(
        approval_id=unsigned.approval_id,
        claim_hash=unsigned.claim_hash,
        issued_at=unsigned.issued_at,
        monotonic_sequence=unsigned.monotonic_sequence,
        previous_issued_at=unsigned.previous_issued_at,
        issuer_signer_fingerprint=unsigned.issuer_signer_fingerprint,
        previous_entry_hash=unsigned.previous_entry_hash,
        key_fingerprint_at_issue=unsigned.key_fingerprint_at_issue,
        key_status_at_issue=unsigned.key_status_at_issue,
        monotonic_clock_attestation=unsigned.monotonic_clock_attestation,
        signature=base64.b64encode(sig_bytes).decode("ascii"),
    )


# === Caller-supplied signed_at reject (§9.9 R9 F-002 server-owned-boundary) ===


def reject_caller_supplied_signed_at(caller_supplied: str | None) -> None:
    """server-owned approval issuance では caller-supplied signed_at は物理 deny。

    Caller (CLI) は --signed-at parameter を持たない (signature レベル削除済) が、
    transport boundary で legacy client が signed_at field を送ってきても reject する
    runtime defense。
    """
    if caller_supplied is not None and caller_supplied != "":
        raise ValueError(
            "taskhub_approval_caller_supplied_signed_at_rejected: "
            "server-owned issuance only — caller-supplied signed_at not allowed"
        )
