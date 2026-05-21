---
id: "ADR-00029"
title: "Approval Verify Keyring Rotation (keyring + signed manifest + dual-trust + bootstrap + lifecycle vs compromise + server-owned approval issuance journal + config_dir snapshot rollback defense)"
status: "proposed"
created_at: "2026-05-21"
updated_at: "2026-05-21"
decision_target: "PR #75-#80 で確立した `approval-verify-key.pub` single-key 体制を keyring (`approval-verify-keys.d/<fingerprint>.pub` + `approval-verify-keyring.signed.json` signed manifest) へ拡張: overlap 期間 dual-trust verify + lifecycle expiry (deprecated) vs compromise revocation (revoked) 区別 + signed candidate manifest + atomic install + server-owned approval issuance journal + immutable approval artifact archive + `/etc/taskhub/keyring_state.head.signed` non-rollback state anchor + clock monotonicity attestation"
sprint_ref:
  - "SP-012_p0_acceptance"
adr_gate_criteria:
  - "#6 (Secrets 管理方式): `approval-verify-key.pub` single key → keyring + signed manifest + dual-trust の transition"
  - "#3 (API 契約 / event schema): approval issue 経路に `issuance_journal.signed.jsonl` 追加 + caller-supplied `signed_at` 物理削除"
  - "#2 (DB schema — 意味的に): approval verification predicate (authorization_verify vs audit_verify) の分離 + journal による server-owned issued_at 確立"
co_accepted_with:
  - "ADR-00028 (Split-Brain Second Line of Defense、co-accepted): cutover signer fingerprint allowlist と keyring rotation で生成される signer fingerprint set は相互依存、両 ADR 同時 accepted"
  - "SP-012_p0_acceptance must_ship 2 件 (本 ADR と co-accepted、SP-012 Batch A 着手前に accepted 化必須)"
related_adrs:
  - "ADR-00021 (Host-Portable Deployment、accepted、§14.1 PGA-F-002 detached signature: 既存 single-key keyring 体制を拡張)"
  - "ADR-00022 (Dev Login Cookie Secure Attribute、accepted、cookie 暗号化 key rotation との対比、本 ADR は approval signing key rotation 専用)"
related_documents:
  - "`.claude/plans/sp012-split-brain-keyring.md` §3.A (signed_approval keyring loader) + §3.C (keyring rotation CLI) + §6.2 (key format contract) + §6.5 (lifecycle vs compromise 規約) + §9.3 (R1 adopt) + §9.4 (R2 adopt) + §9.5 (R3 adopt) + §9.8 (R8 adopt) + §9.9 (R9 adopt)"
  - "`docs/基本設計/06_秘密管理設計.md` (DD-06) SOPS + age secret 管理境界"
---

最終更新: 2026-05-21

# ADR-00029: Approval Verify Keyring Rotation

## 1. 背景

PR #75 (Sprint SP-022 T02 Phase 1) で `approval-verify-key.pub` (Ed25519 public key、single key) による approval signature verify を確立した。PR #76-#80 で BackupApprovalClaim / RestoreRollbackApprovalClaim / RemoteHostsApprovalClaim / BackupApprovalClaim 6-field 化 等の destructive operation approval を追加し、いずれも同 single key で verify している。

この single-key 体制は次の問題を抱える:

1. **Key rotation 不可能**: 既存 PR #75-#80 で署名された全 approval record は同 key に依存、key 漏洩時の rotation は record 全件再署名が必要 (実質不可能)
2. **Lifetime expiry policy 不在**: NIST SP 800-57 推奨の signing key lifetime (Ed25519: 1-3 年) policy を強制する mechanism なし
3. **Compromise response 不在**: key 漏洩時の emergency revocation 経路なし、operator が key file を削除しても past audit verify が不可能になる (audit history loss)
4. **Authorization verify vs audit verify の predicate 混在**: 期限切れ key で署名された新規 destructive approval が同 verify path で通過 (deprecated_at 後の新規署名 reject 条件不在)
5. **caller-supplied `signed_at` の backdate 攻撃**: payload 内の `signed_at` を期限内へ backdate するだけで key validity すり抜け
6. **`<config_dir>` 全体 snapshot rollback で pre-rotation snapshot 復活可能**: filesystem snapshot 攻撃で旧 manifest generation + 旧 revocation tombstone head を再受理

本 ADR は PR #75-#80 single-key 体制を **backward compat 維持** したまま **keyring (multi-key) + lifecycle (active/deprecated/revoked) + dual-trust overlap + emergency revocation + server-owned issuance journal + config_dir snapshot rollback defense** へ拡張する。

## 2. 決定対象

1. `approval-verify-keys.d/<fingerprint>.pub` directory keyring schema (各 key file は `taskhub1<base64>` 形式 Ed25519 32 bytes、permission 0o400、filename = sha256 fingerprint hex)
2. `approval-verify-keyring.signed.json` signed manifest (root-signed by `approval_keyring_root.pub` config_dir 外 pin、entries に status / issued_at / expires_at / deprecated_at / revoked_at / revocation_reason_hash / incident_id)
3. **lifecycle expiry (deprecated) vs compromise revocation (revoked) 区別** (deprecated は audit verify 可能で keep、revoked は signed_at 関係なく無条件 reject)
4. **dual-trust verify path** (legacy `approval-verify-key.pub` + signed manifest の両方を verifier に登録、PR #75-#80 backward compat 維持)
5. **bootstrap operation** (first deployment 用、legacy single key を signed manifest initial entry として登録、`legacy_not_before` 必須署名 claim field + 既存最古 signed_at observation で validate)
6. **`KeyringRotationApprovalClaim` 5 operation variants** (add_key / remove_key / revoke_key / commit_manifest / bootstrap)
7. **server-owned expires_at** (caller-supplied `--expires-at` 物理削除、`approved_overlap_days` + `max_expires_at` を signed claim、redeem 時 server が計算)
8. **2-party-control** (decider ≠ approver、caller-supplied actor 物理削除、principal-token-fd 経路)
9. **immutable signed candidate manifest** (`.candidate` → `.signed.json` atomic install、staging path で live keyring 不変更)
10. **authorization_verify vs audit_verify predicate 分離** (authorization は status=active + `record_signed_at < deprecated_at` 必須、audit は status ∈ {active, deprecated})
11. **server-owned approval issuance journal** (`<config_dir>/approvals/issuance_journal.signed.jsonl`、append-only、`previous_entry_hash` chain + `monotonic_sequence` + server-recorded `issued_at`)
12. **immutable approval artifact archive** (`<config_dir>/active_registry/approval_archive/<approval_id>.signed.json`、append-only、O_NOFOLLOW + 0o400)
13. **`/etc/taskhub/keyring_state.head.signed`** (config_dir 外 monotonic state anchor、root-signed by separate root key、initialized / latest_manifest_generation / latest_commit_log_chain_hash / latest_tombstone_chain_hash / latest_approval_issuance_journal_chain_hash / latest_monotonic_sequence / latest_monotonic_clock_attestation_value)
14. **append-only revocation tombstone denylist** (`<config_dir>/approval_keyring_revocation_tombstone.signed.jsonl`、live path で常に enforce、rollback でも revoked fingerprint 無条件 reject)
15. **clock monotonicity attestation 3 mode** (Linux CLOCK_MONOTONIC + NTP / TPM signed attestation / Remote trusted time service、ADR-00028 と共有)

## 3. 関連 Sprint / 前提

- SP-012_p0_acceptance must_ship 2 件 (本 ADR と co-accepted、Batch A 着手前に proposed → accepted 昇格必須)
- PR #75-#80 で確立した signed approval record (single key 署名済) は本 ADR 実装後も verify pass 必須 (backward compat、bootstrap operation で signed manifest initial entry として登録)
- ADR-00028 (Split-Brain Second Line of Defense、co-accepted) と相互依存: cutover signer-host ownership binding は本 ADR の keyring から allowlist を取得

## 4. 前提 / 制約

- 本 ADR は SP-012 と **co-accepted** が原則: SP-012 accepted 化条件 = ADR-00028 + ADR-00029 両方 status=accepted (または同一 PR で co-accepted)
- ADR-00029 が rejected / superseded に戻る場合、SP-012 must_ship 2 件は **blocked** へ戻し、Batch A 着手禁止
- 不変条件 #5 (SecretBroker atomic claim) / #13 (server-owned boundary) / #1 (AI 出力直結禁止) を遵守
- `rules/secretbroker-boundary.md` raw secret 非保存 invariant を遵守 (private key は AI / runner / artifact / log に出さない、本 ADR は public key keyring のため raw secret 非保存違反なし)
- `rules/server-owned-boundary.md` §1 caller-supplied 経路禁止 invariant を遵守 (CutoverApprovalClaim / KeyringRotationApprovalClaim から caller-supplied actor / signed_at / expires_at を物理削除)
- `rules/cross-source-enum-integrity.md` §1 cross-source enum 5+ source 整合 (status enum 3 種: active / deprecated / revoked、ReasonCode 60 件全体で正本化)
- PR #75-#80 backward compat: bootstrap operation で legacy `approval-verify-key.pub` を normalize + sha256 計算 + manifest initial entry 化、`legacy_not_before` を既存最古 signed_at に固定

## 5. 選択肢

### 選択肢 A: keyring + signed manifest + dual-trust + bootstrap + lifecycle vs compromise + server-owned issuance journal + state head anchor (採用)

- multi-key keyring (`approval-verify-keys.d/<fingerprint>.pub`) + signed manifest (`approval-verify-keyring.signed.json`)
- dual-trust verify path (legacy + signed manifest 両方を verifier に登録)
- bootstrap operation (first deployment 用、legacy `approval-verify-key.pub` を signed manifest initial entry 化)
- lifecycle expiry (status=deprecated) vs compromise revocation (status=revoked) 区別
- KeyringRotationApprovalClaim 5 variants (add_key / remove_key / revoke_key / commit_manifest / bootstrap) + 2-party-control + principal-token-fd
- server-owned expires_at (caller-supplied 物理削除)
- immutable signed candidate manifest (staging path + atomic install + commit-manifest CLI で transition policy verify)
- authorization_verify vs audit_verify predicate 分離
- server-owned approval issuance journal (append-only、previous_entry_hash + monotonic_sequence + server-recorded issued_at)
- immutable approval artifact archive
- `/etc/taskhub/keyring_state.head.signed` (config_dir 外 monotonic state anchor)
- append-only revocation tombstone denylist (rollback でも revoked fingerprint 無条件 reject)
- clock monotonicity attestation 3 mode

利点:
- PR #75-#80 single-key 体制と完全 backward compat (bootstrap operation で legacy 登録)
- Key rotation 可能、NIST SP 800-57 推奨 lifetime policy 強制可能
- Compromise 対応で emergency revocation + tombstone denylist 維持
- Authorization vs audit predicate 分離で deprecated 後の新規署名 reject
- caller-supplied backdate 攻撃を server-owned issuance journal で完全防御
- config_dir snapshot rollback 攻撃を state head anchor で検出 + reject
- clock rollback 攻撃を 3 mode attestation で防御

欠点:
- 実装規模 (約 1,500 行の keyring loader + manifest + journal + CLI 5 variants)
- operator runbook §13 (keyring rotation SOP) + §17 (emergency revocation SOP) + §19 (state head deploy SOP) + §21 (clock attestation SOP) で運用手順を厳密に規定する必要
- `/etc/taskhub/keyring_state.head.signed` 配備に operator が root 権限で system file を deploy する必要 (TPM / HSM / 別 root key で署名)

### 選択肢 B: PR #75-#80 single-key 体制を維持 (現状維持、却下)

却下理由:
- Key rotation 不可能、key 漏洩で全 approval record 再署名必須 (実質不可能)
- NIST SP 800-57 推奨 lifetime policy 強制不可
- Compromise response 経路なし
- 期限切れ key で署名された新規 approval が verify pass

### 選択肢 C: SOPS-managed key rotation (SOPS + age private key rotation、却下)

- SOPS で private key encrypted secret 化 + rotation

却下理由:
- SOPS は private key の暗号化保管用途、public key keyring rotation 用途と独立 (DD-06 § 1 SOPS + age 境界)
- approval signature verify は public key で実施するため、private key rotation だけでは verify path 拡張不可
- 本 ADR は public key keyring (verify) を対象、SOPS は private key encrypted store として共存可能

## 6. 採用案 (選択肢 A)

`.claude/plans/sp012-split-brain-keyring.md` §3.A + §3.C + §9.3-§9.9 で詳細仕様確定済。実装 file 一覧:

- `scripts/taskhub_signed_approval.py` (拡張、keyring loader + signed manifest verify + dual-trust verify path + authorization_verify vs audit_verify predicate 分離 + issuance journal cross-check + state head verify)
- `scripts/taskhub_keyring.py` (新規、keyring CRUD helpers + signed manifest sign/verify + transition policy verify)
- `scripts/taskhub_admin.py` (拡張、`taskhub keyring add-key/remove-key/revoke-key/commit-manifest/bootstrap` 5 subcommand)
- `scripts/taskhub_approval_cli.py` (拡張、`--keyring-*` issue args + caller-supplied actor / signed_at / expires_at 物理削除 + principal-token-fd 経路 + issuance_journal append)
- `scripts/taskhub_approval_issuance.py` (新規、server-owned approval issue logic + journal write atomic + monotonic_sequence + clock attestation)
- `.claude/scripts/check_reason_code_coverage.sh` (新規、60 ReasonCode の 5+ source 整合 pre-commit / CI check)
- `tests/scripts/test_taskhub_keyring.py` (新規、約 50+ fixture)
- `tests/scripts/test_taskhub_signed_approval.py` (拡張、keyring + journal + state head fixture)
- `docs/deploy/operator-runbook.md` (拡張、§13 keyring rotation SOP + §17 emergency revocation SOP + §19 state head deploy SOP + §21 clock attestation SOP)
- `docs/sprints/SP-012_p0_acceptance.md` (修正、must_ship 2 件 completion section)

runtime artifact (production deploy 時に生成):
- `<config_dir>/approval-verify-keys.d/<fingerprint>.pub` (keyring key files、permission 0o400)
- `<config_dir>/approval-verify-keyring.signed.json` (signed manifest、live current)
- `<config_dir>/approval-verify-keyring.signed.json.previous` (rollback 用 archive)
- `<config_dir>/approval-verify-keyring.staging/<fingerprint>.pub.candidate` (candidate key staging)
- `<config_dir>/approval-verify-keyring.signed.json.candidate` (candidate signed manifest)
- `<config_dir>/approval_keyring_root.pub` (root verify key、本来は config_dir 外推奨だが initial deploy 簡便化のため可)
- `<config_dir>/approval_keyring_initialized.signed` (bootstrap 成功後の live marker、rollback でも remove 不可)
- `<config_dir>/approval_keyring_revocation_tombstone.signed.jsonl` (append-only revocation tombstone)
- `<config_dir>/approvals/issuance_journal.signed.jsonl` (server-owned append-only)
- `<config_dir>/active_registry/approval_archive/<approval_id>.signed.json` (immutable approval artifact)
- `<config_dir>/approval-verify-keyring.generations/<generation_id>/` (atomic install directory + current pointer)
- `/etc/taskhub/keyring_state.head.signed` (config_dir 外 monotonic state anchor、ADR-00028 と共有)
- `/etc/taskhub/root_fingerprints.signed` (config_dir 外 root fingerprint pin、approval_keyring_root.pub + active_registry_allowlist_root.pub の sha256 pin)

## 7. 却下案

選択肢 B (single-key 維持): rotation 不可能、compromise response 経路なし。

選択肢 C (SOPS rotation): SOPS は private key encrypted store、public key keyring rotation 用途と独立、共存可能だが本 ADR の対象外。

## 8. リスク

- **bootstrap operation の operator dependency**: first deployment 時に operator が物理 verify した legacy `approval-verify-key.pub` fingerprint を `expected_legacy_fingerprint` として signed manifest に登録、verify mismatch なら deploy 失敗 (operator 教育で mitigate)
- **`/etc/taskhub/keyring_state.head.signed` の root signing key 管理**: TPM / HSM / 別 root key で signing key を保管推奨だが、initial deploy 簡便化のため config_dir 外の通常 file system file でも可 (operator runbook §19 で deploy SOP 規定、root key 漏洩リスクを明示)
- **clock attestation 3 mode の運用コスト**: Mode A (Linux CLOCK_MONOTONIC) は host reboot で reset、reboot detection + attestation で補強するが、本格 fleet 運用は Mode B/C 推奨 (operator runbook §21 で trade-off 明示)
- **journal truncate 攻撃の検出 latency**: state head との chain hash 比較で検出するが、state head 更新 latency (各 issue 後の atomic update) が verify path に影響、benchmark で測定 (Batch C 完了後)

## 9. rollback 手順

1. ADR-00029 status を `proposed` → `superseded` に move、reason = "<specific failure scenario>"
2. SP-012 must_ship 2 件 status を `blocked` へ戻し、Batch A 着手禁止 (本 ADR が accepted の前提条件)
3. 既存配備 (もしあれば) は `.claude/plans/sp012-split-brain-keyring.md` §9 rollback SOP に従う:
   - bootstrap 未実行環境: 通常 revert で `approval-verify-key.pub` single key に戻る (PR #75-#80 backward compat 完全維持)
   - bootstrap 成功後環境: **§9.5 F-001 canonical 適用** (single-key fallback 復活禁止、`approval_keyring_initialized.signed` marker + tombstone denylist 維持、compromise 含む rollback は **revert ではなく append-only 新 manifest generation で rotate/revoke**)
4. emergency single-key fallback は **bootstrap 未実行環境 (head.initialized=false の signature 証明) のみ**で許可、`/etc/taskhub/keyring_state.head.signed` で `initialized=true` が記録されている環境では legacy fallback 無条件 reject
5. 24h 以内に retro Pack 起票 + 後継 ADR 草案 (proposed) を作成 (`rules/sprint-pack-adr-gate.md` §10 break-glass 例外運用準拠)

## 10. 実装対象ファイル

§6 採用案で列挙。詳細実装契約は `.claude/plans/sp012-split-brain-keyring.md` §3.A / §3.C / §6.2 / §6.5 / §9.3 / §9.4 / §9.5 / §9.8 / §9.9 を canonical 正本として参照。

## 11. テスト指針

`tests/scripts/test_taskhub_keyring.py` で約 50+ fixture (§3.D.1 + §9.3-§9.9 negative test list 集約):

- keyring loader (normal / fingerprint mismatch / signed manifest missing/tampered/signature_invalid / key file not in manifest reject / unsafe permission / symlink)
- dual-trust verify (legacy + keyring 両方 + overlap 期間)
- lifecycle (active / deprecated / revoked)
- revoked key 無条件 reject (signed_at 関係なし)
- bootstrap operation (success / with existing manifest reject / with root fingerprint mismatch reject / legacy_not_before > 既存最古 signed_at reject / legacy_not_before <= 既存最古 signed_at success)
- keyring add-key (2-party-control + caller --expires-at reject + server-owned expires_at + KeyringRotationApprovalClaim signing)
- keyring remove-key (deprecated 化 + in-flight reject + safe remove after archive)
- keyring revoke-key (incident_id + revocation_reason_hash + status=revoked + audit history keep)
- keyring commit-manifest (signed candidate verify + transition policy verify + atomic install + decider ≠ approver)
- candidate manifest transition intent binding (approval_claim_hash binding + previous_manifest_content_sha256 + candidate_manifest_content_sha256 + operation intent diff verify)
- caller-supplied actor / signed_at / expires_at の物理削除 verify (CLI signature レベル removal)
- authorization_verify vs audit_verify predicate 分離 (deprecated key after deprecated_at で authorization reject + audit pass)
- server-owned issuance journal (signature verify + claim_hash match + key_fingerprint match + chain integrity + journal issued_at で key validity 判定 + caller-supplied signed_at backdate reject)
- monotonic_sequence + monotonic_clock_attestation (wall-clock rollback within/exceeding ε / monotonic_clock independent regression / reboot without/with attestation)
- immutable approval artifact archive (missing artifact reject / random claim hash reject / mismatched field reject / archive overwrite reject)
- config_dir snapshot rollback (full rollback to pre-bootstrap reject / generation lower than head reject / tombstone truncate reject / lower epoch reject)
- legacy fallback (blocked when head.initialized=true / allowed only when head.initialized=false or head absent)
- root trust anchor pinning (pre-pinned fingerprint mismatch reject / cross-domain root reject)

T09 host migration drill (Mac → VPS、RTO ≤ 4h) で本 ADR 実装後の dual-trust 期間運用を実証、P0 Exit hard gate。
