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

本 commit (`e23c203`) では schema constants + class skeleton のみ。
実装は次 session の Batch C で完成する。
"""

from __future__ import annotations

from typing import Literal

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
