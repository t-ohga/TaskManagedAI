# SP-012 must_ship 2 件 implementation plan (split-brain second line of defense + keyring rotation)

## §0 must_ship 2 件の P0 acceptance criteria 位置付け

SP022-T02 全 Phase 完遂 (PR #75/#77/#78/#79/#80 merged) で T09 host migration drill (Mac→VPS、RTO≤4h) の残 unblock 条件は **SP-012 must_ship 2 件のみ**:

1. **split-brain second line of defense**: active.signed marker chain + cutover 2-party-control + 同 migration_epoch reject negative test
2. **keyring rotation**: `approval-verify-keys.d/<fingerprint>.pub` keyring + old+new overlap 期間 dual-trust

両件完遂で:
- T09 host migration drill 実機実施可能
- **P0.1 unblock path** 開通 (SP-022 全 must_ship 完了 → P0 Exit declaration → TASKHUB_P0_1_OPENED=1 + SP-013 着手)

## §1 設計コンテキスト

### 1.1 既存実装 (PR #75-#80 累計)

- **PGA-F-002 detached signature** (PR #75): source host signing key で manifest 署名、Ed25519 raw 32-byte seed、`approval-verify-key.pub` (single key) で verify
- **PGA-F-003 active-registry skeleton** (PR #76): host_id / migration_epoch / active.signed marker mtime / decommission marker 列挙 (real flow は SP-012 で実装)
- **PGA-F-007 signed journal** (PR #76): 8-phase state machine、source/target 双方 signed journal
- **destructive_lock + canonical_for_signature** (PR #79): backup/restore/restore-rollback host-level mutual exclusion + Ed25519 + RFC 8785 canonical signing
- **BackupApprovalClaim 6 field 化 + signature root に backup_runtime_binding_fingerprint 統合** (PR #80): canonical payload に新 field 含めて signature verify、`_rfc8785_canonical_payload_bytes` で 5 → 6 field 両対応

### 1.2 SP-012 must_ship 2 件の hard gate

- **split-brain second line of defense**: PGA-F-003 active-registry の **real flow** = active.signed marker chain (source→target migration 後の source side `decommission` + target side `active`) + cutover 2-party-control (decider≠approver) + 同 migration_epoch (source/target が同 epoch で同時 active = split-brain → reject)
- **keyring rotation**: 単一 `approval-verify-key.pub` を `approval-verify-keys.d/<fingerprint>.pub` keyring に拡張 + old+new overlap 期間 dual-trust (新 key で署名された claim を verify + old key も期限内有効)

## §2 high-risk 判定 (ADR Gate Criteria 11 種)

- **Criteria 6 Secrets 管理**: keyring rotation = signing key management 変更 → **ADR 必須**
- **Criteria 8 破壊的操作**: split-brain prevention は cutover approval flow 新規導入 + `active-registry` の write 経路 → **ADR 必須** (`thaw --decommission-target` は target rollback 専用 legacy)
- **Criteria 9 広範囲リファクタ**: `taskhub_signed_approval.py` の verify path 変更 (single key → keyring) は 3+ file 横断 → **ADR 必須**

→ **ADR-00028** (split-brain second line) + **ADR-00029** (keyring rotation) 必須 (proposed 起票 → 実装着手直前に accepted 化)

## §3 scope (4 batches)

### Batch A: keyring loader + dual-trust verify (signed_approval.py 拡張)

#### 3.A.1 `approval-verify-keys.d/<fingerprint>.pub` keyring loader (ADV R1 F-004 HIGH adopt: signed manifest)

- 既存 `approval-verify-key.pub` single key 経路を維持 (backward compat、ADV R1 F-002 で virtual keyring entry 化) + 新規 `approval-verify-keys.d/` directory 経路追加
- keyring directory 検出: `<config_dir>/approval-verify-keys.d/*.pub` を scan
- ADV R4 F-002 + ADV R10 F-001 CRITICAL adopt: 各 key file format **migration 2 stage**:
  - **新規 keyring key (Batch A 実装後)**: `taskhub1<base64>` (operator が `cat` で読める text format、prefix + base64-encoded Ed25519 32 bytes)、permission 0o400 + filename = `<sha256 fingerprint of decoded 32 bytes>.pub` 規約
  - **legacy `approval-verify-key.pub` (PR #75-#80 既存配備)**: raw 32 bytes または bare base64 (現行 runbook 形式)、permission 0o600 → **本 plan で migration 後 0o400 化**。fingerprint validation は legacy file 内容を内部で normalize (raw bytes → base64 wrap or vice versa) → decode 後 32 bytes の sha256 と filename を比較
  - **backward compat 保証**: 既存 single-key 配備で keyring directory 未作成時は legacy single-key path をそのまま使う (verify-only)、keyring 移行時に signed manifest に legacy_single_key entry として登録 (ADV R2 F-002 統一)、format は legacy file 内容を **read-only normalize** (file 自体は書き換えない、operator runbook で別途 migration step 規定)
  - 新規 keyring key は `taskhub1<base64>` text format で書き出し、legacy + 新規両方を internal で normalize-decode
- key fingerprint validation: filename と content decode → sha256 が一致 (mismatch reject)
- **root trust anchor** (ADV R2 F-001 + F-005 HIGH adopt: domain 分離 + offline signer ceremony):
  - `<config_dir>/approval_keyring_root.pub` (Ed25519 pub key、offline hardware-rooted signer)、permission 0o400、`approval_keyring_root.pub.fingerprint` (sha256) を runbook §13 で operator が物理 verify (out-of-band)
  - `<config_dir>/active_registry_allowlist_root.pub` (別 root、active_registry の trusted_signers.signed.json 用)、approval keyring とは **完全分離** (cross-domain signature reject)
  - 両 root pub key は本 SP-012 must_ship 着手時に operator が手動配備 (Batch C 開始 prerequisite)、本 plan 内では「root pub の存在を assume + load 時 verify」
- **signed manifest**: `<config_dir>/approval-verify-keyring.signed.json` (ADV R1 F-004 HIGH adopt、`domain="taskhub.approval_verify_keyring.v1"`):
  ```json
  {
    "domain": "taskhub.approval_verify_keyring.v1",
    "config_version": 1,
    "issued_at": "2026-05-21T14:00:00Z",
    "keys": [
      {"fingerprint": "<sha256>", "issued_at": "...", "expires_at": "...", "revoked_at": null, "rotated_from": "<old_fingerprint or null>", "status": "active"},
      ...
    ],
    "signature": "<Ed25519 signature over canonical payload>"
  }
  ```
- manifest 自体は **`approval_keyring_root.pub` (offline hardware-rooted signer)** で署名 (循環参照禁止、keyring 内の key で manifest 自身を sign しない)
- ADV R2 F-001 HIGH adopt: keyring 更新 ceremony は **二段階**:
  1. `taskhub keyring add-key/remove-key/revoke-key` で `unsigned candidate manifest` 生成 (CLI が新 keys[] を提案)
  2. operator が offline signer で candidate manifest を sign + `<config_dir>/approval-verify-keyring.signed.json.candidate` に配置
  3. `taskhub keyring commit-manifest` で root pub signature verify 後 atomic rename で commit
  - 未署名 commit / 別 domain / 別 root 署名は fail-closed reject
- 個別 `<fingerprint>.meta.json` は廃止 (manifest に集約)、key file の存在のみで keyring entry を構成
- manifest 検証: load 時に signature verify + 各 key file の content sha256 が manifest の fingerprint と一致 (mismatch reject)
- negative tests: manifest missing / tampered / symlink / unsafe permission / expires_at extension (manifest 改ざんで expires_at 延長) / key file 単独追加 (manifest 未登録) reject

#### 3.A.2 dual-trust verify path (ADV R1 F-002 CRITICAL adopt)

- `verify_signed_approval` 内で:
  1. **keyring directory が存在する場合は legacy `approval-verify-key.pub` も signed manifest の `keys[]` に必須登録** (ADV R2 F-002 HIGH adopt、`source: "legacy_single_key"` 等)。登録なしの legacy key 単独使用は **fail-closed reject** (manifest 外の legacy key 経路を物理閉鎖)。legacy key にも issued_at / expires_at / revoked_at を同一適用
  2. keyring 全 entries (legacy 含む) で verify 試行、以下の順序で check (ADV R2 F-004 HIGH adopt: status check が時刻比較より前):
     - (a) **`status == "revoked"` は signed_at に関係なく無条件 reject** (compromise 後の backdate attack 防御、revoked_at は audit 表示用途のみ)
     - (b) `status == "active" or "deprecated"` のとき: expires_at が record signed_at 時点で有効 + record_signed_at >= issued_at を全件 check
     - `revoked_at` は時刻比較の判定対象にしない (status field で判定)、audit / reason 表示専用
  3. いずれかが PASS なら allow + extras に `verify_key_fingerprint` 記録
- keyring directory が **未作成** (rotation 開始前) の場合のみ legacy single-key path を fail-open (PR #75-#80 backward compat、SP-012 must_ship 完遂後は keyring directory 作成 → legacy も expires_at 強制)
- old+new overlap 期間: 新 key の `issued_at` から `expires_at` までは両方有効 (dual-trust)、old key の `expires_at` 経過後は **status=deprecated** で current manifest に **保持** (ADV R7 F-004 MEDIUM adopt: revoked_at は使わない、deprecated_at を記録、過去 record audit verify を維持)。manifest 上の deprecated key は eventual safe remove 可能 (separate remove-key operation で historical signed manifest archive 後)

**ADV R1 F-002 adopt 受け入れ条件**:
- `test_legacy_single_key_expired_rejected_even_when_signature_valid`: keyring directory 作成済 + legacy key の expires_at 経過後 → record_signed_at が expires_at 以降の record は legacy key で verify success でも fail-closed

#### 3.A.3 ReasonCode 拡張 (Batch A keyring subset、ADV R7 F-005 集計同期: 正本は §4.5 で全 16 件)

Batch A (keyring) で `taskhub_signed_approval.py` の ReasonCode Literal に追加する 6 件 (正本 16 件のうち keyring subset):
- `taskhub_signed_approval_keyring_key_invalid_fingerprint` (filename と content sha256 不一致)
- `taskhub_signed_approval_keyring_key_expired` (key validity window violation: signed_at < issued_at または signed_at >= expires_at、ADV R8 F-003 + R9 F-003 統一定義、active/deprecated 状態、revoked と区別。`test_keyring_new_key_record_signed_before_issued_at_reject` も同 reason)
- `taskhub_signed_approval_keyring_key_revoked` (status="revoked"、signed_at に関係なく無条件 reject、ADV R4 F-001 追加)
- `taskhub_signed_approval_keyring_no_valid_key` (keyring 全 key で verify 失敗)
- `taskhub_signed_approval_keyring_manifest_signature_invalid` (signed manifest root signature verify fail)
- `taskhub_signed_approval_keyring_manifest_tampered` (manifest fingerprint 不一致 / unknown entry)

残 10 件 (active-registry 系 + cutover 系) は Batch B で `scripts/taskhub_active_registry.py` の ReasonCode Literal に追加 (§4.5 正本参照)。

### Batch B: active-registry real flow + split-brain second line of defense

#### 3.B.1 `active.signed` marker chain (`scripts/taskhub_admin.py` + `scripts/taskhub_active_registry.py` 新規)

**ADV R1 F-001 CRITICAL adopt: ActiveMarker / DecommissionMarker schema を分離 + chain hash binding**:

**ADV R7 F-001 HIGH adopt**: subcommand naming 整理:
- `taskhub freeze --reason ...` (既存): source side 一時停止のみ、`freeze.signed` のみ生成、decommission marker は生成しない
- `taskhub thaw --decommission-target` (既存): **target rollback 用途のみ** (target active marker 削除 + source 再活性化、現行 ADR 意味維持)
- `taskhub cutover --target-host <id>` (本 plan 新規): source decommission + target active を atomic 同時生成 (本 plan の SP-012 must_ship のメイン subcommand)、approval claim 名は `CutoverApprovalClaim` (旧 ThawApprovalClaim を rename) で executor/approver actor binding 維持

DecommissionMarker (source side、**cutover phase で生成**、freeze 時ではない):
- `{domain="taskhub.active_registry.decommission.v1", host_id, migration_epoch, decommissioned_at, signer_fingerprint, signature, prev_active_chain_hash?}`
- 新 epoch、source role = retired
- canonical payload: RFC 8785 + domain separation + Ed25519

ActiveMarker (target side、cutover phase で生成):
- `{domain="taskhub.active_registry.active.v1", host_id, migration_epoch, activated_at, signer_fingerprint, signature, source_decommission_chain_hash, source_decommission_signer_fingerprint}`
- **target active marker は source decommission marker の signature root 全体の sha256 (= source_decommission_chain_hash) を canonical payload に含める**
- target active の signature verify は source decommission の signature verify を通過した後に実施 (chain order 強制)
- → marker swap / two-step transition violation / unknown chain root 攻撃を signature root レベルで物理閉鎖

trusted signer source (**ADV R1 F-008 + ADV R3 F-001 CRITICAL adopt**):
- marker 用 signer allowlist: `<config_dir>/active_registry_trusted_signers.signed.json` (ADR-00021 PGA-F-002 signer allowlist と同 domain 思想)
- 各 marker の `signer_fingerprint` が allowlist にあること + freshness rule (e.g., allowlist の有効期限 ≤ migration_epoch 発行時刻 + 1 year)
- **allowlist の signature root は `active_registry_allowlist_root.pub` のみで verify** (ADV R3 F-001 CRITICAL: root trust anchor 分離後の cross-domain verify 経路を物理閉鎖、approval keyring / approval_keyring_root.pub / approval-verify-keys.d 経由の verify は禁止)
- negative tests: unknown signer / wrong domain / allowlist missing / fingerprint expired + **`test_active_registry_allowlist_signed_by_approval_root_rejected` + `test_active_registry_allowlist_signed_by_keyring_key_rejected`** (cross-domain reject)

write 経路 (ADV R6 F-002 HIGH adopt: §6.1 state machine semantics と統一、freeze と decommission を分離):
- `taskhub freeze --reason ...`: source side で **`freeze.signed`** marker 生成 (migration-in-progress、source disabled、writes 拒否)。decommission marker はここでは生成しない
- migration 中の `freeze → backup → transfer → restore → verify` phase 完了後:
- `taskhub cutover --target-host <id>`: cutover phase で **`decommission.signed` + `active.signed` の atomic 同時生成** (source decommission marker 書込 + target active marker 書込が 1 cutover operation で完了、ADV R7 F-001 で `thaw --decommission-target` から rename + 意味分離)

**ADV2 Phase 2 R1 CRITICAL adopt 3 件**:

- **F-001 CRITICAL (cutover approval が marker artifact に永続 binding なし)**: ActiveMarker と DecommissionMarker の signature root に `cutover_approval_id` + `cutover_approval_claim_hash` を含める。読取側が marker chain だけで承認済 cutover/未承認 cutover を暗号的に区別可能にする (`CutoverApprovalClaim canonical → sha256 → marker root に bind`)。
- **F-002 CRITICAL (decommission chain hash 未存在 binding race)**: CutoverApprovalClaim は **source decommission marker の予定 chain hash (= canonical payload を事前 deterministic に計算した hash) を bind**。具体的には DecommissionMarker の signature 以外の全 field を approval 時点で確定 (host_id / migration_epoch / decommissioned_at / signer_fingerprint = source host signing key + canonical hash 計算)、approval-time の hash を `expected_decommission_hash` として claim に bind、cutover 実行時に signer が DecommissionMarker を生成 → 計算済 hash と一致 verify。
- **F-003 CRITICAL (cross-host marker atomic 失敗)**: cross-host cutover は **真の atomic 不可能** (分散 transaction)。代替として `two-phase commit pattern`:
  - Phase α (`prepare`): source 側で DecommissionMarker を staged 状態で書込 (`decommission.signed.pending`、`status: "pending_cutover"`)、target 側で ActiveMarker を staged 状態で書込 (`active.signed.pending`、`status: "pending_cutover"`)
  - Phase β (`commit`): 両 side で signed manifest 経由 atomic rename + parent fsync (`.pending` → `.signed`)、partial commit 検知 SOP は operator runbook §14 で規定 (片側 pending のまま 24h 経過 → manual recovery)
  - **`taskhub cutover` の戻り値は両 host から prepare 段階の confirmation 受領 → commit 段階の confirmation 受領** までを完了とする (RPC ロールでも file ベースの polling 経由でも実装可)
  - state machine: `freeze` → `backup` → `transfer` → `restore` → `verify` → `cutover-prepare` → `cutover-commit` → `verified-active` (cutover phase を 2 step に分解)
  - target active marker は source decommission marker の chain hash を signature root に bind
  - 2-party-control verify (decider ≠ approver)
  - 中間 state で interrupt されたら recovery SOP (operator runbook §14 で規定)

read 経路:
- `taskhub active-registry list`: 全 host の active/decommission marker 列挙 (chain hash 整合 verify)
- `taskhub status --remote <host>`: remote host の marker 状態 + migration_epoch 確認 (**ADV R1 F-006 HIGH adopt**: signed remote_hosts config 経由)

#### 3.B.2 split-brain reject negative test

- 同 `migration_epoch` で source/target 両 host に `active.signed` が同時存在 → **split-brain detected, reject**
- cutover 経路で source の `active.signed` が `decommission.signed` に置換されていない → **two-step transition violation, reject**
- 異 `signer_fingerprint` で active.signed が改ざんされた → **signature verify fail, reject**

#### 3.B.3 cutover 2-party-control (ADV R1 F-003 + R8 F-002 HIGH adopt: thaw → cutover 用語統一)

- `taskhub cutover --target-host <id>` で (ADV R7 F-001 + R8 F-002 HIGH adopt: 用語統一):
  - `--approval-id <id>` 必須 (signed approval)
  - `CutoverApprovalClaim`: `{target_host_id, migration_epoch, source_decommission_chain_hash, source_decommission_signer_fingerprint, executor_actor_id, approver_actor_id}` を signature root に含める (chain hash で source decommission marker 全体に binding)
  - **separation of duties enforcement**: signature root の `executor_actor_id != approver_actor_id` + approval issue 時に `--cutover-target-host-id` / `--cutover-migration-epoch` / `--cutover-source-decommission-chain-hash` / `--cutover-executor-actor-id` / `--cutover-approver-actor-id` を CLI 引数で受け取り、server-owned に signature root に encode
  - approval issue CLI (`scripts/taskhub_approval_cli.py`) に `--cutover-*` 引数追加 (Batch B 変更対象に追加)
  - lock-flow: `acquire_destructive_lock("cutover", ...)` + post-stop で source decommission marker chain hash 再 verify
  - test fixture: `test_cutover_decider_equals_approver_rejected_at_issue` + `test_cutover_decider_equals_approver_rejected_at_redeem` (issue / redeem 両方 separation 強制)
  - **legacy compat note**: `taskhub thaw --decommission-target` は target rollback 用途で残し、本 plan の cutover とは独立 subcommand 扱い (ADV R7 F-001 で意味分離済)

### Batch C: keyring rotation operator runbook + CLI

#### 3.C.1 `taskhub keyring add-key --pubkey <path>` (新規 CLI、ADV R1 F-005 + ADV R6 F-003 HIGH adopt)

- ADV R7 F-002 HIGH adopt: **live `approval-verify-keys.d/` には key file を一切追加しない** (verify path fail-closed window 排除)。candidate key payload と candidate manifest を staging path にのみ生成:
  - candidate key staging: `<config_dir>/approval-verify-keyring.staging/<fingerprint>.pub.candidate`
  - candidate manifest path: `<config_dir>/approval-verify-keyring.signed.json.candidate`
- 後続 offline signer 署名 → `taskhub keyring commit-manifest --signed-candidate <path>` で root verify 後、**key file set と signed manifest を同一 critical section で install/rename/fsync** (atomic install)
- 2-party-control: `--approval-id <id>` 必須、decider ≠ approver
- key file 検証: decode 後 32 bytes + filename = `<sha256>.pub` + permission 0o400 (§3.A.1 format 規約準拠)
- **`--expires-at` は CLI 引数として受け取らない** (ADV R1 F-005 HIGH adopt: server-owned)。`KeyringRotationApprovalClaim` に `approved_overlap_days` + `max_expires_at` を signed claim として含め、redeem 時に server が `issued_at + approved_overlap_days` を計算 + `max_expires_at` で cap
- approval claim **`KeyringRotationApprovalClaim` 5 operation variants** (ADV R2 F-003 + ADV R7 F-003 + ADV R12 F-003 HIGH/MEDIUM adopt):
  - **`bootstrap` (ADV R12 F-003 MEDIUM adopt、新規 first-deployment 用)**: `{operation="bootstrap", legacy_single_key_fingerprint, legacy_expected_path, initial_root_pub_fingerprint, executor_actor_id, approver_actor_id}` で signed manifest 初回作成 (previous_manifest 不在 = first deployment、legacy key を `source="legacy_single_key"` + status=active で initial 登録、approval_keyring_root.pub fingerprint を expected_root に bind)
  - first deployment scenario: `taskhub keyring bootstrap --legacy-key-path <path>` (新規 CLI) で legacy `approval-verify-key.pub` を normalize + sha256 計算 + manifest initial entry 生成 (status=active、issued_at=PR #75 配備時刻 or now()、expires_at=runbook 規定の overlap_days default)、offline signer 経由で signed manifest 化 → `commit-manifest`
  - `add_key`: `{operation="add_key", new_key_fingerprint, approved_overlap_days, max_expires_at, executor_actor_id, approver_actor_id}`
  - `remove_key`: `{operation="remove_key", target_key_fingerprint, in_flight_snapshot_hash, executor_actor_id, approver_actor_id}` (in_flight_snapshot_hash = remove 時の signed manifest全体の sha256、後続 commit-manifest で再 verify、削除対象 key が現在 active record で参照されていないことの evidence)
  - `revoke_key`: `{operation="revoke_key", target_key_fingerprint, revocation_reason_hash, incident_id, executor_actor_id, approver_actor_id}` (revocation_reason_hash = sha256(reason text)、reason text 自体は audit 経由で保管、claim には hash のみ encode で長文回避 + non-repudiation)
  - **`commit_manifest`** (ADV R7 F-003 HIGH adopt): `{operation="commit_manifest", candidate_manifest_content_sha256, previous_manifest_content_sha256, expected_root_fingerprint, executor_actor_id, approver_actor_id}` (candidate / previous content hash で commit 対象を bind、root pub fingerprint で root anchor 同一性 verify)
- redeem 側は **CLI 引数ではなく signed claim の fingerprint/reason/incident_id/content hash** を server-owned に展開 (caller-supplied は signed claim と exact match 検証のみ)、claim と CLI 引数 mismatch は fail-closed reject

#### 3.C.2 `taskhub keyring remove-key --fingerprint <fp>` (新規 CLI、ADV R6 F-003 + R10 F-003 HIGH adopt)

- ADV R10 F-003 統一 (lifecycle expiry path):
  - 通常 remove-key は **2 step lifecycle**: (1) `active → deprecated` 化 (status field 更新 + `deprecated_at` 記録、過去 record audit verify 可能で keep)、(2) deprecated 期間経過後の二次操作で manifest からの完全 safe remove (historical signed manifest archive 後)
  - 本 plan の `remove-key` CLI は **(1) deprecated 化のみ** (lifecycle 通常 expiry path、`status=deprecated` 化、manifest entry は keep)。完全 remove は archive 後の別 operation で実施 (本 plan scope 外、operator runbook で deferred SOP 規定)
  - **emergency revocation は別 CLI `revoke-key` で実施** (§3.C.3、`status=revoked` 化、ADV R6 F-004 lifecycle vs compromise 区別)
- 2-party-control: `--approval-id <id>` 必須、`KeyringRotationApprovalClaim(operation="remove_key")`
- remove 前 verify: 「現在の active record で当該 key を verify-only にしている record が存在しない」(in-flight check) → in-flight check 失敗時は deprecation を延期 (operator が overlap 期間を runbook で再評価)
- candidate manifest path: §3.C.1 と同じ、後続 commit-manifest CLI で atomic commit
- operator-runbook §13.1 で「scheduled lifecycle expiry (remove-key)」「emergency revocation (revoke-key)」の **2 SOP を別 section** に明示

#### 3.C.3 `taskhub keyring revoke-key --fingerprint <fp>` (新規 CLI、ADV R8 F-001 HIGH adopt)

- compromise / emergency response 専用 (lifecycle expiry の deprecated とは厳密分離、§6.5 lifecycle 規約参照)
- 2-party-control: `--approval-id <id>` 必須、`KeyringRotationApprovalClaim(operation="revoke_key", target_key_fingerprint, revocation_reason_hash, incident_id, executor_actor_id, approver_actor_id)`
- CLI 引数: `--fingerprint <fp>` のみ (reason text は audit 側に保管、signed claim には `revocation_reason_hash` のみ encode で non-repudiation 保証)
- candidate manifest 生成 (live keyring 不変更、§3.C.1 と同 staging path)、後続 commit-manifest で atomic install
- post-commit: 過去 record の audit verify は revoked key で **無条件 reject** (signed_at に関係なく、§3.A.2 status check 優先)

#### 3.C.4 `taskhub keyring commit-manifest --signed-candidate <path>` (新規 CLI、ADV R6 F-003 + R8 F-001 + R11 F-001 HIGH adopt)

- candidate manifest (operator が offline signer で署名済) を verify + atomic commit
- root verify: `approval_keyring_root.pub` で signature root verify、別 root / 未署名 / domain mismatch は fail-closed reject
- **candidate manifest transition intent binding (ADV R12 F-001 MEDIUM adopt)**: candidate manifest の canonical payload に `transition` object を追加:
  ```json
  {
    "transition": {
      "operation": "add_key" | "remove_key" | "revoke_key",
      "approval_id": "<id>",
      "approval_claim_hash": "<sha256 of KeyringRotationApprovalClaim canonical>",
      "previous_manifest_content_sha256": "<prev sha256>",
      "candidate_manifest_content_sha256": "<self sha256>"
    },
    "domain": "taskhub.approval_verify_keyring.v1",
    "config_version": 2, ...
  }
  ```
  - `transition.approval_claim_hash` で artifact 単体に operation intent を binding (caller が manifest を独立して使い回せない)
  - `commit-manifest` は (a) signed candidate の `transition.approval_claim_hash` を decode (b) `KeyringRotationApprovalClaim(operation="commit_manifest")` の candidate_manifest_content_sha256 と一致確認 (c) 旧 manifest content sha256 と previous_manifest_content_sha256 一致確認 (d) operation intent と diff 内容の整合確認 を全件実施、いずれか mismatch なら fail-closed reject

- **previous → candidate transition policy verify (ADV R11 F-001 HIGH adopt)**:
  - previous manifest を load + candidate manifest と diff
  - 許可される変更 (operation 別に限定):
    - `add_key`: 新 key entry 追加 (signed claim `KeyringRotationApprovalClaim(operation="add_key")` で binding 済)、`expires_at = min(issued_at + approved_overlap_days, max_expires_at)` を server 側で **再計算 + match verify** (caller-supplied expires_at は拒否)
    - `remove_key`: 既存 key の status を `active → deprecated`、`deprecated_at` 追加
    - `revoke_key`: 既存 key の status を `* → revoked`、`revoked_at` + `revocation_reason_hash` + `incident_id` 追加
  - 禁止される変更 (検出時 fail-closed reject):
    - 既存 key の `expires_at` 延長 (extension attack)
    - `revoked → active|deprecated` 復帰 (revocation 取消)
    - `deprecated → active` 逆行 (lifecycle 逆遷移)
    - signed claim と無関係の key 追加 (caller-controlled injection)
    - status field 以外の immutable field (fingerprint / issued_at / rotated_from / source) の変更
- atomic rename: `.candidate` → `.signed.json` (O_NOFOLLOW + parent fsync)
- 既存 manifest を `.signed.json.previous` に archive (rollback 用)
- 2-party-control: commit-manifest 自身も `--approval-id <id>` 必須 (decider ≠ approver、KeyringRotationApprovalClaim operation="commit_manifest")

#### 3.C.3 `docs/deploy/operator-runbook.md` §13 keyring rotation SOP

- old key (`<old_fp>.pub`) が compromise / lifetime expire / rotation schedule 到達時の手順
- new key 生成 → keyring add-key → overlap 期間 (default 30 days) で並行運用 → old key remove-key
- 緊急 revoke 経路: lifetime 短縮 + emergency rotation 手順

### Batch D: tests (46 fixture: keyring 22 + active-registry 24) + docs (ADV R6 F-005 集計同期)

#### 3.D.1 keyring tests (`tests/scripts/test_taskhub_keyring.py` 新規)

- 22 fixture (ADV R6 F-005 集計同期、§6.4 fixture name table 準拠): keyring loader normal / fingerprint mismatch / signed manifest missing/tampered/signature_invalid / key file not in manifest reject / unsafe permission / symlink / dual-trust verify (legacy + keyring) / legacy single key expired / new key signed before issued_at / **revoked key reject regardless signed_at (taskhub_signed_approval_keyring_key_revoked)** / no valid key / keyring add-key 2-party-control / caller --expires-at rejected / server-owned expires_at / remove-key in-flight reject / remove-key expired pass (deprecated) / rotation overlap dual-trust / rotation overlap expired legacy reject + new pass / emergency revoke / manifest expires_at extension reject

#### 3.D.2 active-registry tests (`tests/scripts/test_taskhub_active_registry.py` 新規)

- 24 fixture (ADV R6 F-005 集計同期、§6.4 fixture name table 準拠): active.signed marker write / read / split-brain reject (same epoch source+target active) / two-step transition violation reject / signature verify fail reject / chain hash mismatch / unknown signer / wrong domain / allowlist missing / signer fingerprint expired / epoch concurrent allocation unique / same epoch replay reject / lower epoch reject / counter tampered / crash leftover cleanup / **cutover decider equals approver rejected at issue/redeem** / source decommission not found / post-stop chain hash reverify / remote marker unreachable / remote epoch mismatch / remote dual active / cutover lock concurrent reject / cutover atomic source decommission + target active

### Batch D 統合検証

- `uv run pytest tests/scripts/` 365+ test PASS (現 319 + 新 46 fixture、ADV R6 F-005 集計同期)
- ruff All passed
- PR #80 backward compat: 既存 BackupApprovalClaim 6 field 化 + signed claim canonical payload 維持

## §4 invariant chain (must_ship 完全列)

### 4.1 ADR-00021 invariants 遵守

- §11.2 split-brain prevention 完全実装 (本 plan で active.signed marker chain + cutover 2-party-control + same-epoch reject)
- §14.1 PGA-F-002 detached signature: 既存 keyring 単一鍵 → keyring rotation 拡張 (本 plan で keyring + dual-trust)
- §14.1 PGA-F-003 active-registry: skeleton → real flow 完成 (本 plan で marker chain real I/O)

### 4.2 SecretBroker boundary 遵守

- keyring key file は `taskhub1<base64>` 形式の Ed25519 public key 32 bytes (ADV R8 F-004 MEDIUM adopt 統一: §3.A.1 + §6.2 + §4.2 同期、hex/raw 表現は plan から除去)、private key は touch しない
- key rotation 中の dual-trust 期間も signing key は **single active key** (verify-only に multi)
- audit / log / artifact に raw private key を出さない

### 4.3 server-owned boundary 遵守

- `active.signed` / `decommission.signed` marker は **server-owned write** (CLI が generate、caller が直接 write しない)
- `migration_epoch` は monotonic increment (ADV R1 F-007 + ADV R2 F-006 HIGH adopt: atomic counter file + 専用 lock file):
  - `scripts/taskhub_active_registry.py` の `allocate_next_epoch()` helper
  - **lock 対象は `<config_dir>/active_registry/migration_epoch.lock` (rename 不可、安定 inode)** で `fcntl.flock(LOCK_EX|LOCK_NB)` 取得、counter file 自体は atomic rename される (lock と counter を別 file に分離、ADV R2 F-006: lock 対象 inode が swap される race を排除)
  - lock 取得 → counter file read (sha256 verify) → write temp → fsync → atomic rename + parent fsync → lock release の順序
  - counter file content: **`{epoch: N, issued_at: "<iso8601>", sha256: <self_sha>}` JSON** (ADV R10 F-002 HIGH adopt: epoch 発行時刻を persist、signer allowlist freshness rule で参照可能、self-referential sha256 で tamper 検知)
  - allocate_next_epoch() で N+1 計算時に issued_at = now() を同時記録、active.signed marker / decommission.signed marker の signature root に `migration_epoch_issued_at` を含める (chain hash の構成要素、signer allowlist freshness verify 用)
  - signer allowlist freshness rule (ADV R10 F-002 + R11 F-003 HIGH adopt): allowlist entry に `issued_at` + `expires_at` を持ち、marker verify で **`signer_issued_at <= migration_epoch_issued_at < signer_expires_at`** を必須条件 (下限 check で retroactive signer 攻撃排除、上限 check で expired signer 排除、推測 timestamp 排除)
  - negative test 追加: `test_active_registry_signer_added_after_epoch_issued_reject` (signer issued_at > marker migration_epoch_issued_at = retroactive 攻撃 reject)
  - **concurrent allocation negative test**: 2 並列 invocation で同 epoch を返さない (mutual exclusion verify)
  - **same epoch replay reject**: 既存 epoch counter ≥ requested epoch → reject
  - **lower epoch reject**: counter file の value より低い epoch 値で marker 生成 reject
  - **counter file tamper reject**: counter file の sha256 mismatch / O_NOFOLLOW 違反 reject
  - **crash leftover temp cleanup**: `.epoch.tmp.<uuid>` 等が prev session で残留時、起動時 cleanup (mtime > 1 day で safe purge)
- keyring expires_at は **server-owned** (KeyringRotationApprovalClaim の signed approved_overlap_days + max_expires_at から server が計算、caller-supplied `--expires-at` 不可)

### 4.4 ADR Gate Criteria 遵守 (ADV R1 F-009 HIGH adopt)

ADR 必須 2 件、本 plan の Batch A 着手 **前** に accepted 化:
- `docs/adr/00028_split_brain_second_line.md` (Criteria 8 破壊的操作)
- `docs/adr/00029_approval_keyring_rotation.md` (Criteria 6 Secrets 管理)

両 ADR は `status: proposed` で起票 → 実装着手直前に `status: accepted` 昇格 (sprint-pack-adr-gate.md §12 promotion 必須要件)。
本 plan の file change list (§5) に両 ADR を含める。Batch A 開始前に accepted gate を通過しなければ implementation を開始しない (sprint-pack-adr-gate.md §10 break-glass 例外運用は本 must_ship 2 件には適用不可、Criteria 6/8/9 は break-glass 対象外)。

### 4.5 cross-source enum integrity 遵守

ReasonCode 拡張は **正本 16 件** (ADV R6 F-005 MEDIUM adopt 集計同期: §3.A.3 + §4.5 + §6.3 + §5 全 section で同一カウント):
- `taskhub_signed_approval_keyring_key_invalid_fingerprint`
- `taskhub_signed_approval_keyring_key_expired` (key validity window violation: signed_at < issued_at または signed_at >= expires_at、ADV R8 F-003 統一定義、revoked と分離)
- `taskhub_signed_approval_keyring_key_revoked` (ADV R4 F-001 CRITICAL adopt: revoked key の無条件 reject 専用 reason、expires_at 比較を通らないことを reason code level で示す)
- `taskhub_signed_approval_keyring_no_valid_key`
- `taskhub_signed_approval_keyring_manifest_signature_invalid` (ADV R1 F-004)
- `taskhub_signed_approval_keyring_manifest_tampered` (ADV R1 F-004)
- `taskhub_active_registry_split_brain_detected`
- `taskhub_active_registry_two_step_transition_violation`
- `taskhub_active_registry_signature_verify_failed`
- `taskhub_active_registry_chain_hash_mismatch` (ADV R1 F-001 marker chain binding)
- `taskhub_active_registry_signer_not_in_allowlist` (ADV R1 F-008 trusted signer source)
- `taskhub_active_registry_epoch_counter_tampered` (ADV R1 F-007 counter sha256/O_NOFOLLOW)
- `taskhub_active_registry_epoch_replay_or_lower` (ADV R1 F-007 same/lower epoch reject)
- `taskhub_active_registry_remote_marker_unreachable` (ADV R1 F-006 remote check)
- `taskhub_cutover_two_party_control_violation`
- `taskhub_cutover_source_decommission_not_found`

### 4.5 testing.md §3 弱 assertion 禁止 遵守

全 **46 test fixture** (keyring 22 + active-registry 24、ADV R6 F-005 集計同期) で:
- argv exact match
- file mode `stat.S_IMODE(...) == 0o<mode>` exact
- subprocess result returncode + stdout content 両方
- 弱 assertion 全件回避

## §5 ファイル変更一覧

### 修正 (7 scripts + 2 tests + 2 docs + 2 ADR + 1 CI script = **14 file**、ADV R6 F-005 + R7 F-005 + R8 F-005 集計同期)

| path | 影響範囲 | 行数 |
|---|---|---|
| `docs/adr/00028_split_brain_second_line.md` (新規、ADV R1 F-009 HIGH adopt) | proposed → 実装直前 accepted、ActiveMarker/DecommissionMarker chain hash binding + cutover 2-party-control + trusted signer allowlist | +250 |
| `docs/adr/00029_approval_keyring_rotation.md` (新規、ADV R1 F-009 HIGH adopt) | proposed → 実装直前 accepted、signed manifest + dual-trust + emergency revoke + server-owned expires_at | +220 |
| `scripts/taskhub_signed_approval.py` | keyring loader + signed manifest verify + dual-trust verify path + ReasonCode 6 件追加 (keyring 系: invalid_fingerprint / expired / revoked / no_valid_key / manifest_signature_invalid / manifest_tampered) + CutoverApprovalClaim + KeyringRotationApprovalClaim (4 variants: add_key/remove_key/revoke_key/commit_manifest) | +280 |
| `scripts/taskhub_admin.py` | `taskhub keyring add-key/remove-key/revoke-key/commit-manifest` + `taskhub freeze` real flow (freeze.signed のみ) + `taskhub cutover --target-host` real flow (cutover atomic source decommission + target active) + `taskhub active-registry` real flow + lock 統合 (cutover も destructive_lock 対象) | +380 |
| `scripts/taskhub_active_registry.py` (新規) | ActiveMarker/DecommissionMarker chain hash binding + write/read/verify/list + `allocate_next_epoch()` atomic + trusted_signers allowlist verify | +280 |
| `scripts/taskhub_keyring.py` (新規) | keyring CRUD helpers (add/remove/list/verify fingerprint match/signed manifest sign+verify) | +200 |
| `scripts/taskhub_approval_cli.py` (ADV R1 F-003 + F-005 + R8 F-002) | `--cutover-*` issue args + `--keyring-*` issue args (KeyringRotationApprovalClaim signing) | +120 |
| `scripts/taskhub_remote_status.py` (ADV R1 F-006) | remote host marker 取得 + signature verify + migration_epoch compare + same-epoch dual active reject | +90 |
| `scripts/taskhub_destructive_lock.py` | cutover subcommand を destructive_lock 対象に追加 (thaw --decommission-target は legacy target rollback で独立) | +20 |
| `tests/scripts/test_taskhub_keyring.py` (新規) | 22 fixture (元 18 + ADV R1 F-002/F-004/F-005 拡張 4) | +480 |
| `tests/scripts/test_taskhub_active_registry.py` (新規) | 24 fixture (元 15 + ADV R1 F-001/F-006/F-007/F-008 拡張 9) | +560 |
| `docs/sprints/SP-012_p0_acceptance.md` | must_ship 2 件 completion section 追加 | +80 |
| `docs/deploy/operator-runbook.md` | §13 keyring rotation SOP + §14 active-registry split-brain check SOP + §15 ReasonCode reason table (ADV R8 F-005 統一) + §16 ADR-00028/00029 accepted 化 SOP | +180 |

| `.claude/scripts/check_reason_code_coverage.sh` (新規、ADV R8 F-005 集計同期) | 16 ReasonCode の 5 source 整合 pre-commit / CI check | +80 |

合計: +3,170 / -10 (14 file)

## §6 verification 順序 (ADV R1 F-015 LOW adopt: mypy で全変更 file カバー)

```bash
uv run ruff check scripts/taskhub_signed_approval.py scripts/taskhub_admin.py scripts/taskhub_active_registry.py scripts/taskhub_keyring.py scripts/taskhub_approval_cli.py scripts/taskhub_remote_status.py scripts/taskhub_destructive_lock.py
uv run mypy scripts/taskhub_signed_approval.py scripts/taskhub_admin.py scripts/taskhub_active_registry.py scripts/taskhub_keyring.py scripts/taskhub_approval_cli.py scripts/taskhub_remote_status.py
uv run pytest tests/scripts/test_taskhub_keyring.py tests/scripts/test_taskhub_active_registry.py -x
uv run pytest tests/scripts/ -x  # full regression (現 319 + 新 46 = 365+ test PASS、ADV R1 F-001/F-002/F-006/F-007 拡張で 46 fixture)
```

## §6.1 state machine semantics (ADV R1 F-010 MEDIUM adopt)

freeze / decommission の semantic 分離:

- `freeze.signed` (existing PR #75 のまま): migration-in-progress / source disabled (source host 一時停止、writes 拒否)
- `decommission.signed` (本 plan で新規): cutover 後 source retired (PGA-F-003 active-registry の source side terminal state)

state transition 強制: `freeze → backup → transfer → restore → verify → cutover (= decommission + activate)`、各 phase の signed journal record で chain hash 確認 (ADV R1 F-001 のchain hash mechanism と統合)。

cutover phase は **atomic**: source `decommission.signed` 書込 + target `active.signed` 書込が 1 cutover operation で完了 (中間 state で interrupt されたら recovery SOP)。

## §6.2 key format contract (ADV R1 F-011 + ADV R11 F-001 統一)

新規 keyring pub file format を **`taskhub1<base64>` 固定** (operator が `cat` で読める + permission 0o400 でも text view 容易):
- 新規 file content: `taskhub1<base64>` (prefix + base64-encoded Ed25519 32 bytes)
- decode 後の 32 bytes の sha256 = filename `<fingerprint>.pub` の `<fingerprint>` (64 chars hex)

**legacy `approval-verify-key.pub` (PR #75-#80 既存配備) backward compat** (ADV R10 F-001 + R11 F-001 統一):
- 既存形式: **raw 32 bytes / bare base64 / taskhub1 text** のいずれか (PR #75 で raw / bare base64 が確立済)
- loader が **read-only normalize して decode** (file 内容を読込時に format detect + decoded 32 bytes に正規化)、plan 実装ではファイル自体は書き換えない (operator runbook §13.2 で別途 migration step として規定、本 plan scope 外)
- legacy file の fingerprint validation (ADV R12 F-001 HIGH adopt): legacy `approval-verify-key.pub` は **固定 filename のため fingerprint vs filename 比較は適用しない**。代わりに以下の検証:
  - 内部 normalize 後の decoded 32 bytes から sha256 を計算 → `<legacy_fingerprint>`
  - signed manifest 内の legacy_single_key entry に `expected_legacy_fingerprint: <fingerprint>` を含める (manifest registration 時に operator が物理 verify した値、本 plan で signed manifest schema 拡張)
  - load 時に decoded sha256 と manifest 内 `expected_legacy_fingerprint` を exact match (mismatch reject = legacy file の content swap 検知)
  - 新規 keyring key は `<sha256>.pub` filename convention 維持、legacy single key だけ固定名で manifest 経由 binding (両 path で fingerprint binding 強制)
- 新規 add-key 経由で書き出す key は `taskhub1<base64>` text format で統一

## §6.3 ReasonCode source manifest (ADV R1 F-012 MEDIUM adopt)

新 **16 ReasonCode** の 5 source 整合 (cross-source-enum-integrity.md §1 準拠、ADV R6 F-005 集計同期):

| source | location | enforcement |
|---|---|---|
| Python Literal | `scripts/taskhub_signed_approval.py` ReasonCode Literal + `scripts/taskhub_active_registry.py` ReasonCode Literal | mypy + pyright |
| admin CLI emit | `scripts/taskhub_admin.py` `_cmd_*` raise/print | runtime |
| pytest EXPECTED set | `tests/scripts/test_taskhub_keyring.py` `EXPECTED_KEYRING_REASON_CODES` + `tests/scripts/test_taskhub_active_registry.py` `EXPECTED_ACTIVE_REGISTRY_REASON_CODES` | set 比較 |
| operator-runbook reason table | `docs/deploy/operator-runbook.md` §15 reason table (ADV R8 F-005 統一、§16 は ADR accepted 化 SOP) | review |
| CI grep/check | `.claude/scripts/check_reason_code_coverage.sh` (本 plan で新規追加、§5 file change list 14 file 目) | pre-commit / CI |

## §6.4 test fixture name table (ADV R1 F-013 MEDIUM adopt)

### Batch D.1 keyring tests (22 fixture)

| # | test_name | expected reason_code |
|---|---|---|
| 1 | test_keyring_loader_normal_pass | (allow) |
| 2 | test_keyring_loader_fingerprint_filename_mismatch_reject | taskhub_signed_approval_keyring_key_invalid_fingerprint |
| 3 | test_keyring_loader_signed_manifest_missing_reject | taskhub_signed_approval_keyring_manifest_tampered |
| 4 | test_keyring_loader_signed_manifest_signature_invalid_reject | taskhub_signed_approval_keyring_manifest_signature_invalid |
| 5 | test_keyring_loader_key_file_not_in_manifest_reject | taskhub_signed_approval_keyring_manifest_tampered |
| 6 | test_keyring_loader_unsafe_permission_reject | taskhub_signed_approval_keyring_key_invalid_fingerprint |
| 7 | test_keyring_loader_symlink_key_file_reject | taskhub_signed_approval_keyring_key_invalid_fingerprint |
| 8 | test_keyring_dual_trust_legacy_pass_within_expires_at | (allow) |
| 9 | test_legacy_single_key_expired_rejected_even_when_signature_valid | taskhub_signed_approval_keyring_key_expired |
| 10 | test_keyring_dual_trust_new_key_pass_within_expires_at | (allow) |
| 11 | test_keyring_new_key_record_signed_before_issued_at_reject | taskhub_signed_approval_keyring_key_expired |
| 12 | test_keyring_revoked_key_reject_regardless_signed_at (ADV R4 F-001 CRITICAL adopt) | taskhub_signed_approval_keyring_key_revoked (status check が時刻比較より **前** に発火することを reason code level で verify、expired と区別) |
| 13 | test_keyring_no_valid_key_in_all_entries_reject | taskhub_signed_approval_keyring_no_valid_key |
| 14 | test_keyring_add_key_two_party_control_required | taskhub_cutover_two_party_control_violation (再利用) |
| 15 | test_keyring_add_key_caller_expires_at_rejected | (CLI usage error、--expires-at 引数なし) |
| 16 | test_keyring_add_key_server_owned_expires_at_from_approval | (allow) |
| 17 | test_keyring_remove_key_in_flight_record_reject | (custom: in-flight record reference reject) |
| 18 | test_keyring_remove_key_expired_pass (ADV R6 F-004 MEDIUM adopt) | (allow + **status=deprecated** + 後続 safe remove 対象、revocation ではない通常 lifecycle expiry。過去 record audit verify は引き続き可能) |
| 19 | test_keyring_rotation_overlap_period_dual_trust | (allow、legacy + new 両方) |
| 20 | test_keyring_rotation_overlap_expired_legacy_reject_new_pass | taskhub_signed_approval_keyring_key_expired (legacy) + allow (new) |
| 21 | test_keyring_emergency_revoke_status_revoked (ADV R4 F-001 + R10 F-003 adopt) | (allow + KeyringRotationApprovalClaim(operation="revoke_key") + status=revoked、incident_id + revocation_reason_hash 記録、以降 verify は taskhub_signed_approval_keyring_key_revoked で無条件 reject、expires_at lifetime 短縮ではなく status field で reject) |
| 22 | test_keyring_manifest_expires_at_extension_reject | taskhub_signed_approval_keyring_manifest_tampered |

### Batch D.2 active-registry tests (24 fixture)

| # | test_name | expected reason_code |
|---|---|---|
| 1 | test_active_registry_marker_write_normal_pass | (allow) |
| 2 | test_active_registry_marker_read_normal_pass | (allow) |
| 3 | test_active_registry_split_brain_same_epoch_both_active_reject | taskhub_active_registry_split_brain_detected |
| 4 | test_active_registry_two_step_violation_target_active_without_source_decommission_reject | taskhub_active_registry_two_step_transition_violation |
| 5 | test_active_registry_signature_verify_fail_reject | taskhub_active_registry_signature_verify_failed |
| 6 | test_active_registry_chain_hash_mismatch_reject | taskhub_active_registry_chain_hash_mismatch |
| 7 | test_active_registry_unknown_signer_reject | taskhub_active_registry_signer_not_in_allowlist |
| 8 | test_active_registry_wrong_domain_reject | taskhub_active_registry_signature_verify_failed |
| 9 | test_active_registry_allowlist_missing_reject | taskhub_active_registry_signer_not_in_allowlist |
| 10 | test_active_registry_signer_fingerprint_expired_reject | taskhub_active_registry_signer_not_in_allowlist |
| 11 | test_active_registry_epoch_concurrent_allocation_unique | (mutual exclusion verify、no duplicate epoch) |
| 12 | test_active_registry_epoch_same_replay_reject | taskhub_active_registry_epoch_replay_or_lower |
| 13 | test_active_registry_epoch_lower_reject | taskhub_active_registry_epoch_replay_or_lower |
| 14 | test_active_registry_epoch_counter_tampered_reject | taskhub_active_registry_epoch_counter_tampered |
| 15 | test_active_registry_epoch_crash_leftover_temp_cleanup | (allow + leftover cleaned) |
| 16 | test_cutover_decider_equals_approver_rejected_at_issue | taskhub_cutover_two_party_control_violation |
| 17 | test_cutover_decider_equals_approver_rejected_at_redeem | taskhub_cutover_two_party_control_violation |
| 18 | test_cutover_source_decommission_not_found_reject | taskhub_cutover_source_decommission_not_found |
| 19 | test_cutover_post_stop_chain_hash_reverify | (allow + post-stop verify pass) |
| 20 | test_cli_status_remote_marker_unreachable_reject | taskhub_active_registry_remote_marker_unreachable |
| 21 | test_cli_status_remote_marker_epoch_mismatch_rejected | taskhub_active_registry_split_brain_detected |
| 22 | test_cli_status_remote_same_epoch_dual_active_rejected | taskhub_active_registry_split_brain_detected |
| 23 | test_cutover_lock_held_concurrent_reject | (destructive_lock busy reject) |
| 24 | test_state_machine_cutover_atomic_source_decommission_target_active | (allow + chain hash linked) |

## §6.5 key revocation flow (ADV R1 F-014 MEDIUM adopt)

key status enum: `active | deprecated | revoked` (signed manifest 内 `status` field、ADV R6 F-004 MEDIUM adopt: lifecycle expiry と compromise response を厳密分離):

- `active`: 通常 verify use
- `deprecated`: 既存 record verify use 可、新 record signing には不可 (rotation 移行中)、`expires_at` 経過で manifest からの safe remove 対象
- `revoked`: **compromise / emergency response 専用**、signed_at に関係なく **常に reject** (audit history 維持のため key entry は manifest に keep + `status="revoked"` + `revoked_at` + `revocation_reason_hash` 記録)

**lifecycle 通常 expiry vs compromise revocation 区別**:
- 通常 expiry: `status: active → deprecated` (expires_at 経過時自動 or operator が KeyringRotationApprovalClaim(operation="remove_key") で deprecated 化、過去 record の audit verify は引き続き可能、key は eventual safe remove)
- compromise revocation: `status: active|deprecated → revoked` (operator が KeyringRotationApprovalClaim(operation="revoke_key") で incident_id + revocation_reason_hash 記録、過去 record の audit verify も無条件 reject、key entry は keep-for-audit)

revoked_at field: revocation timestamp、**audit 表示専用** (ADV R3 F-002 CRITICAL adopt: §3.A.2 の status check と統一)。verify path での判定対象にしない、signed_at/revoked_at の時刻比較は廃止。

verify path (再掲、§3.A.2 と同一):
- `status == "revoked"` は signed_at / revoked_at に **関係なく無条件 reject** (backdate attack 防御)
- `status == "active" | "deprecated"` のとき `expires_at` と `signed_at` を比較

`taskhub keyring revoke-key --fingerprint <fp>` (新規、ADV R9 F-001 HIGH adopt 統一: §3.C.3 と同じ contract):
- CLI 引数: `--fingerprint <fp>` のみ (reason text は signed claim には encode せず、audit event で保管)
- 共通必須引数: `--approval-id <id>` + KeyringRotationApprovalClaim (operation="revoke_key"、§3.C.1 4 variants 参照)
- manifest 更新 (commit-manifest 経由 atomic install): `status: "revoked"` + `revoked_at: <now>` + **`revocation_reason_hash: <sha256(reason text)>`** + `incident_id: <id>` 記録 (本文は plan / claim / manifest に保管しない、audit event のみに保管)
- 既存 record の verify は revoked status の key に対して **常に reject** (signed_at 関係なし、§3.A.2 status check 優先)
- audit event 必須 (revocation reason 本文は audit event に残す、operator-runbook §17 で revocation incident response SOP 規定、§15 reason table / §16 ADR SOP と section 番号衝突を回避)

## §7 受け入れ条件

- [ ] `uv run pytest tests/scripts/` 365+ test PASS (現 319 + 新 46、keyring 22 + active-registry 24、ADV R6 F-005 集計同期)
- [ ] keyring add-key + remove-key が 2-party-control + 0o400 permission verify で成功
- [ ] active.signed marker write/read が migration_epoch 整合 + signature verify PASS
- [ ] split-brain negative test (same epoch source+target active) で reject、`taskhub_active_registry_split_brain_detected` reason
- [ ] cutover 2-party-control violation (decider == approver) で reject、`taskhub_cutover_two_party_control_violation` reason
- [ ] keyring rotation overlap 期間で legacy + new key 両方 verify pass、expires_at 経過後 legacy reject
- [ ] PR #80 backward compat: 既存 BackupApprovalClaim 6 field 化 + signed claim canonical payload で legacy 5-field record も verify pass

## §8 ADR 必須

- **ADR-00028 split-brain second line of defense** (proposed → 実装着手直前に accepted): active.signed marker chain + cutover 2-party-control + same-epoch reject の設計判断
- **ADR-00029 keyring rotation** (proposed → 実装着手直前に accepted): `approval-verify-keys.d/<fingerprint>.pub` keyring + old+new overlap 期間 dual-trust + emergency revoke 経路

## §9 rollback (ADV R1 F-016 LOW adopt: artifact 扱い明示)

- 本 plan revert で:
  - keyring loader 経路は `approval-verify-key.pub` single key に戻る (backward compat 完全維持)
  - active.signed marker は skeleton 状態 (SP022-T08 batch 4 で start_app_services 経由は維持)
  - cutover 2-party-control は skeleton 状態
- backward compat: 既存 PR #80 までの signed_approval record + BackupApprovalClaim 6 field は revert 後も verify 可能

### 9.1 artifact (revert 時の取り扱い)

revert 時の artifact 扱い (削除ではなく **archive/quarantine**、audit trail 維持):

- `<config_dir>/approval-verify-keys.d/`: revert 後 read されない、archive 化 → `archived/approval-verify-keys.d.<timestamp>/` に rename
- `<config_dir>/approval-verify-keyring.signed.json`: archive 化 → `archived/approval-verify-keyring.signed.<timestamp>.json`
- `<config_dir>/active_registry/<host_id>/active.signed`: 削除せず keep (existing PR #76 active-registry skeleton path)
- `<config_dir>/active_registry/<host_id>/decommission.signed`: 同上
- `<config_dir>/active_registry/migration_epoch.counter`: keep (revert で counter リセット禁止、replay attack 防御)
- `<config_dir>/active_registry_trusted_signers.signed.json`: archive 化 → `archived/trusted_signers.signed.<timestamp>.json`

### 9.2 emergency revert SOP

revert 時に compromise 検知済の key / marker は manifest 上で `status=revoked` を残したまま archive (削除しない、後続 audit で revocation history 可視化)。revert 後の re-implementation 時は old fingerprint を keyring から永続排除。

## §9.3 ADV2 Phase 2 R1 HIGH 11 件 adopt (本 plan の hardening contract、Batch A-D 実装で全件反映)

R1 で検出された 14 CRITICAL+HIGH 全件 adopt 完了 (CRITICAL 3 は §3.B.1 / §6.1 で反映済、HIGH 11 件を以下に集約):

### F-004 root trust anchor pinning (HIGH security)
`approval_keyring_root.pub` と `active_registry_allowlist_root.pub` の fingerprint を **config_dir 外** で pin:
- 推奨: `/etc/taskhub/root_fingerprints.signed` (immutable system file、operator runbook で配備、または SOPS 管理 secret)
- load 時に `sha256(root_pub)` を必ず照合 (`expected_root_fingerprint` constant or env vault binding)
- negative test: `test_keyring_root_pub_swap_after_bootstrap_rejected` + `test_active_registry_allowlist_root_swap_rejected`

### F-005 keyring directory swap downgrade 防御 (HIGH security)
`<config_dir>/approval_keyring_initialized.signed` marker を bootstrap 成功時に作成:
- 一度 bootstrap が成功した config では keyring directory / signed manifest / root fingerprint の欠落を **fail-closed**
- directory missing / symlink / inode swap / manifest absent → `taskhub_signed_approval_keyring_initialized_marker_violated` で reject
- legacy single-key fallback は bootstrap marker 未存在時のみ許可

### F-006 multi-file install race (HIGH race)
`approval-verify-keyring.generations/<generation_id>/` directory 構造:
- 各 generation で key files + manifest を揃えて fsync、最後に `current` pointer (symlink or signed pointer file) を atomic rename
- loader は `current` 配下だけを dirfd + `O_NOFOLLOW` で読む (新旧混在 race 排除)
- manifest payload に `generation_id` + key file content hashes を含める

### F-007 manifest replay 防御 (HIGH security)
signed manifest に **append-only chain** を導入:
- `generation` (monotonic counter)、`previous_committed_manifest_hash`、`commit_log_chain_hash`、`committed_at` を canonical payload に含める
- `commit-manifest` は current generation + 1 のみ許可
- rollback も generation を戻さず、revoked/deprecated history を **append-only archive** に残す (`commit_log.signed.jsonl` 等)

### F-008 candidate self-reference hash 規約 (HIGH security)
`candidate_manifest_content_sha256` を **payload 外の envelope** に配置:
- canonical payload (signature root 対象) には `candidate_manifest_content_sha256` を含めない、envelope (signature 外 metadata) に置く
- もしくは canonical payload では該当 field を固定 sentinel 値 (例: `"0" * 64`) にして hash 計算後に envelope へ移動
- test fixture: `test_candidate_manifest_canonical_preimage_deterministic` で hash preimage JSON と expected hash を固定

### F-009 CLI path traversal 防御 (HIGH security)
`--pubkey <path>` / `--signed-candidate <path>` の入力制限:
- staging dir 配下の basename allowlist に限定 (絶対 path / `../` / symlink / world-writable parent / hardlink count > 1 reject)
- dirfd-relative `openat(O_NOFOLLOW)` で安全 open + `fstat` regular file + owner uid + parent mode 検証
- negative tests: `test_cli_pubkey_path_traversal_rejected` + `test_cli_signed_candidate_symlink_rejected` + `test_cli_signed_candidate_hardlink_rejected`

### F-010 epoch counter rollback trust anchor (HIGH security)
epoch counter を **signed append-only journal** に拡張:
- `<config_dir>/migration_epoch.journal.signed.jsonl` (各 entry に previous entry hash、host_id、issued_at、writer fingerprint)
- 最新 epoch hash を `<config_dir>/migration_epoch.head.signed` (root-signed) に書込、別 trust store または remote quorum へも書込
- rollback negative test: `test_epoch_counter_file_rollback_detected_by_journal_hash`

### F-011 source host identity binding (HIGH design)
`ActiveMarker` + `CutoverApprovalClaim` に必須追加:
- `source_host_id`、`source_previous_active_chain_hash`、`cutover_id` (UUID)
- source_decommission_marker 内の `host_id` と exact match (別 source decommission hash の replay 排除)
- negative test: `test_cutover_with_different_source_host_id_rejected`

### F-012 bootstrap transition policy (HIGH design)
§3.C.1 KeyringRotationApprovalClaim 5 variants の `bootstrap` を transition policy にも統合:
- bootstrap は previous_manifest absent 限定、legacy_key_fingerprint + expected_legacy_path + expected_root_fingerprint + initial_expires_at 計算を **bootstrap 専用 policy** として定義
- bootstrap fixture: `test_keyring_bootstrap_success` + `test_keyring_bootstrap_with_existing_manifest_rejected` + `test_keyring_bootstrap_with_root_fingerprint_mismatch_rejected`

### F-013 decommission active proof (HIGH design)
`DecommissionMarker` に **`prev_active_chain_hash` を必須化**:
- decommission verify で previous ActiveMarker の domain / host_id / migration_epoch / signature / allowlist freshness を検証
- source が本当に active だった証明 (retired state を勝手に作れない)
- negative tests: `test_decommission_without_previous_active_rejected` + `test_decommission_prev_active_chain_hash_mismatch_rejected`

### F-014 fleet membership signed complete set (HIGH security)
`<config_dir>/active_registry_fleet.signed.json` を導入:
- `host_id`、`endpoint`、`valid_from` / `valid_to`、`membership_generation` を root-signed で管理
- split-brain check は **fleet 全件**を対象にし、omitted host / stale membership / unreachable required host を fail-closed
- negative tests: `test_split_brain_check_omitted_host_rejected` + `test_fleet_membership_stale_generation_rejected` + `test_fleet_membership_unreachable_required_host_rejected`

### MEDIUM 4 件 (F-015〜F-018) は次 session の Phase 2 R2 polish で確定

ReasonCode 拡張は **16 件 → 24 件** に増加 (R1 採用後):
- `taskhub_signed_approval_keyring_initialized_marker_violated` (F-005)
- `taskhub_signed_approval_keyring_generation_replay_or_lower` (F-007)
- `taskhub_signed_approval_keyring_candidate_hash_envelope_mismatch` (F-008)
- `taskhub_signed_approval_cli_path_traversal_rejected` (F-009)
- `taskhub_active_registry_epoch_journal_hash_mismatch` (F-010)
- `taskhub_cutover_source_host_id_mismatch` (F-011)
- `taskhub_active_registry_decommission_prev_active_chain_hash_mismatch` (F-013)
- `taskhub_active_registry_fleet_membership_violation` (F-014)

fixture 拡張は **46 → 65 件** に増加 (新規 19 件、Batch D 拡張)。

---

## §9.4 ADV2 Phase 2 R2 HIGH 7 件 adopt (R1 adopt 後の深い設計欠陥 + 正本 drift fix)

R2 で検出された 7 件 (CRITICAL=0、HIGH 7) すべて adopt。R1 で残った deep design 論点 + R1 adopt 内容が正本テーブルに伝播してない drift を解消する hardening contract。Batch A-D 実装で本文正本テーブルと完全に同期する。

### F-001 actor binding を caller-supplied 経路から排除 (HIGH security、server-owned-boundary.md 違反 fix)

**問題**: `--cutover-executor-actor-id` / `--cutover-approver-actor-id` CLI 引数で caller が任意 actor_id を指定可能 (rules/server-owned-boundary.md §1 caller-supplied 禁止 invariant 違反)。

**fix**:
- CutoverApprovalClaim / KeyringRotationApprovalClaim signature schema で `executor_actor_id` / `approver_actor_id` を **caller 入力ではなく**、認証済み human principal (TASKHUB_APPROVAL_PRINCIPAL_TOKEN signed envelope) + 独立 approval DB row (approvals 既存 table の `decider` + `approver` 関係) から server-side で resolve
- CLI signature レベル: `--cutover-executor-actor-id` / `--cutover-approver-actor-id` parameter を **物理削除**、代わりに `--executor-principal-token-fd <fd>` / `--approver-principal-token-fd <fd>` (1 approval = 1 fd 経路、PR #79 pattern 継承)
- issue / redeem で actor_id 存在 / 権限 / human 性 / executor との不一致 / approval artifact hash binding を fail-closed verify
- negative tests: `test_cutover_caller_supplied_actor_id_rejected` + `test_cutover_executor_and_approver_same_principal_rejected` + `test_cutover_principal_token_signature_invalid_rejected`

### F-002 2PC prepare / commit artifact の暗号学的分離 (HIGH security)

**問題**: `.signed.pending` → `.signed` rename だけで commit boundary を表現、commit certificate なし、pending を local rename で committed 化可能。

**fix**:
- **PrepareMarker** と **CommitMarker** を別 signature domain (`cutover_prepare.v1` / `cutover_commit.v1`) に分離
- CommitMarker 必須 fields: `cutover_id` (UUID) / `source_prepare_marker_hash` (sha256) / `target_prepare_marker_hash` (sha256) / `source_host_confirmation_signature` / `target_host_confirmation_signature` / `commit_approval_claim_hash` / `committed_at` (UTC iso8601)
- CommitApprovalClaim を新 variant として追加 → **7 claim variants** 体系 (KeyringRotation 5 + Cutover 1 + Commit 1)
- read path: `.pending` および prepare domain の marker は常に **非 active 扱い**、commit certificate のない `.signed` rename は reject
- negative tests: `test_cutover_pending_rename_to_signed_without_commit_certificate_rejected` + `test_cutover_commit_marker_with_wrong_prepare_hash_rejected` + `test_cutover_commit_marker_without_target_host_confirmation_signature_rejected`

### F-003 fleet-wide cutover lease 導入 (HIGH race、cross-host coordination)

**問題**: `acquire_destructive_lock("cutover", ...)` は host-level advisory lock、cross-host 別 host から同時 cutover 起動で fleet 競合発生。

**fix**:
- `<config_dir>/cutover_lease.signed.json` を fleet-wide root-signed lease 化 (schema: `cutover_id` UUID / `acquired_by_host_id` / `required_host_ids` fleet membership 全件 / `prepared_host_ids` lock 取得済 / `lease_acquired_at` / `lease_expires_at` / `root_signature`)
- prepare phase で **fleet membership 全 host の prepare lock を全件取得**してから marker 生成 (rolling lock-out pattern)
- `cutover_id` uniqueness を `active_registry_fleet.signed.json` 経由で fleet-wide enforce (concurrent cutover_id reject)
- negative tests:
  - `test_concurrent_cutover_from_different_host_rejected`
  - `test_cutover_with_partial_prepare_lock_rejected` (required_host_ids 全件取得できない場合)
  - `test_cutover_with_same_source_multi_target_rejected`
  - `test_cutover_lease_expired_then_reacquire_with_new_cutover_id_required`

### F-004 legacy bootstrap の `legacy_not_before` 必須化 (HIGH design、backward compat 保護)

**問題**: bootstrap が `issued_at=now()` を許すと、既存 PR #75-#80 で legacy key で署名された approval record (record_signed_at < bootstrap 時刻) が `record_signed_at >= issued_at` 違反で全件 verify 不能化、受け入れ条件 §7 backward compat 違反。

**fix**:
- bootstrap operation の signed claim に `legacy_not_before` field を **必須化** (`legacy_issued_at` から rename)
- bootstrap 実行時に **既存 approval directory + signed journal 全走査**で最古 signed_at を観測、`legacy_not_before <= 最古 signed_at` を verify (caller が任意時刻を選べない)
- 既存 record が存在しない初期 bootstrap (new install) のみ `legacy_not_before = now()` 許可
- negative tests: `test_keyring_bootstrap_preserves_existing_legacy_records` (PR #75-#80 で署名された全 record が bootstrap 後も verify 可能) + `test_keyring_bootstrap_legacy_not_before_exceeds_oldest_signed_at_rejected`

### F-005 deprecated key の新規署名 reject enforcement (HIGH security、authorization vs audit predicate 分離)

**問題**: verify path が `active` と `deprecated` 両方を同 predicate (`issued_at <= signed_at < expires_at`) で許可、deprecated_at 後の新規署名 record も verify 通過。

**fix**:
- `signed_keyring_manifest.signed.json` schema に `deprecated_at` を **必須 field** 追加 (active key には null、deprecated/revoked key には UTC iso8601)
- verify path を 2 mode に分離:
  - **authorization_verify** (destructive operation 実行可否判定): `status=active` のみ許可、`status=deprecated` AND `record_signed_at >= deprecated_at` は reject
  - **audit_verify** (過去 record 監査用): `status ∈ {active, deprecated}` で `issued_at <= signed_at < expires_at` のみ
- CLI / backend / approval verify path で **authorization_verify** を強制、audit log / historical inspection のみ audit_verify
- negative tests: `test_deprecated_key_cannot_authorize_new_record_after_deprecated_at` + `test_deprecated_key_can_audit_historical_record_before_deprecated_at` + `test_authorization_verify_rejects_revoked_key_for_any_timestamp`

### F-006 R1 hardening の正本テーブル sync (HIGH drift fix、Batch A-D 実装の必須前提)

**問題**: R1 で §9.3 集約 adopt した 11 件 hardening が plan 本文の正本テーブルに伝播してない:
- §3 ReasonCode 表 (16 件) → **24 件に更新必須** (§9.3 で列挙済 8 件追加)
- §4.5 KeyringRotationApprovalClaim 4 variants → **5 variants** に更新必須 (bootstrap variant 追加、§3.C.1)
- §5 file list で `KeyringRotationApprovalClaim 4 variants` 言及部分 → 5 variants + Cutover/CommitApprovalClaim も明記
- §6.3 fixture 表 (46 件) → **65 → 約 77 件** (§9.3 で 19 件追加 + R2 F-002/F-003 で約 12 件追加、Batch D で確定)
- §6.4 acceptance gate 数値 → fixture 件数最終 sync
- §7 受け入れ条件 → R1+R2 hardening fixture 全件 PASS を明記

**fix (Batch D 実装で本文正本に反映、本 §9.4 は drift fix 宣言)**:
- Batch D test fixture loader 実装時に **24+2=26 ReasonCode + 全 fixture 数値 (R1+R2 累計約 77) + 7 claim variants を真の正本**とする
- §3-§7 の本文表を Batch D 実装と同時に edit (実装と整合する 1 commit、drift 再発防止)
- CI check (`tests/scripts/test_signed_approval_keyring_invariants.py`) で:
  - ReasonCode 数値 = 26
  - fixture 数値 = Batch D 実装完了時点の最終件数 (≈77)
  - claim variants 数値 = 7 (Keyring 5 + Cutover 1 + Commit 1)
- 実装 PR の自動 verify (Batch D test PASS = 正本表と実装の整合保証)

### F-007 active-registry marker と backend write path の接続 (HIGH design、enforcement point 接続)

**問題**: `freeze.signed` / `decommission.signed` が marker chain として存在しても、backend / API / service startup に write guard がなく、source host が freeze 後も実 write 可能。

**fix**:
- backend write path に **active-registry gate** を追加 (FastAPI dependency or middleware):
  - `taskhub_active_registry_gate.py` (新 module) で fleet-current active marker resolve + local host が `host_id` 一致 + `frozen=false` + `decommissioned=false` を check
  - fail-closed: local host が fleet-current active marker を持たない場合、freeze/decommission 状態の場合、remote fleet check fail の場合は 503 Service Unavailable + `taskhub_active_registry_write_rejected_by_gate` reason_code
- service startup gate: `docker-compose.yml` 起動時に active marker verify 失敗で `entrypoint` exit 1 (fail-closed)
- admin gateway (taskhub_admin.py CLI) は既に active marker check 入る予定なので、destructive subcommand 全件で gate 適用
- 変更ファイル一覧に追加 (本 plan §5):
  - `backend/app/api/dependencies/active_registry_gate.py` (新規、FastAPI dependency)
  - `backend/app/main.py` (active_registry_gate dependency wiring)
  - `docker-compose.yml` (entrypoint script で gate verify)
  - `scripts/taskhub_entrypoint_active_registry_check.sh` (新規、Docker entrypoint pre-check)
- negative tests:
  - `test_decommissioned_source_rejects_api_write` (POST /tickets が 503)
  - `test_pending_cutover_target_does_not_accept_write` (commit certificate なし target でも write reject)
  - `test_service_startup_fails_without_active_marker`
  - `test_service_startup_fails_with_frozen_marker`
  - `test_service_startup_fails_with_stale_active_marker_signature`

### R2 adopt 累計値更新

- ReasonCode: **24 → 26 件** (F-001 actor binding deny / F-007 active_registry_write_rejected_by_gate)
  - `taskhub_cutover_caller_supplied_actor_id_rejected` (F-001)
  - `taskhub_active_registry_write_rejected_by_gate` (F-007)
- ApprovalClaim variants: **5 → 7 variants** (KeyringRotation 5 + Cutover 1 + Commit 1、F-002)
- fixture: **65 → 約 77 件** (約 12 件追加、Batch D で確定)
- 変更ファイル: 14 → **18 file** 追加 (backend gate 関連 4 file)、+3170 → 約 +3,800 行

### 残 MEDIUM 4 件 (R1 F-015〜F-018) は次 session の R3 で確定

R3 起動時に Phase 2 R1 result.json の MEDIUM 4 件 + 本 R2 採用後の新規 MEDIUM 論点を併せて検出、critical_zero gate (CRITICAL=0 + HIGH≤2) 達成判定。

---

## §10 PR 後の SP-022 task progress (post-本 PR)

| Task | status |
|---|---|
| SP022-T01 framework intake CI 機械化 | ✅ 完了 |
| SP022-T02 `taskhub migrate` 自動化 | ✅ 全 Phase 完遂 |
| SP022-T03 半年 drill SOP | ✅ 完了 |
| SP022-T04 Phase E trace audit | ✅ 完了 |
| SP022-T05 AC-HARD multi-agent re-verify | ⛔ deferred (blocked_by: SP-013) |
| SP022-T06 KPI baseline 3 host | 🟨 light (Mac 単独可) |
| SP022-T07 production checklist skeleton | ✅ 完了 |
| SP022-T08 SP-012 carry-over 9 件 | 🟥 heavy: batch 1-4 ✅ / batch 5-6 carry-over |
| SP022-T09 実機 host migration drill | ⛔ deferred (blocked_by: **本 PR で SP-012 must_ship 2 件 unblock 後着手可**) |

## §11 risk summary

| risk | mitigation |
|---|---|
| keyring loader が PR #80 までの single key signing record を verify 失敗 | legacy `approval-verify-key.pub` 経路を維持 (backward compat)、keyring 経路は fallback |
| dual-trust 期間に old key で署名された malicious record が new key 範囲で verify-pass | each key の `expires_at` を record `signed_at` と厳密 compare (server-owned binding) |
| active.signed marker file が racy に同時 write される | destructive_lock 取得後に write、`O_CREAT|O_EXCL` で atomic create、`migration_epoch` monotonic counter で順序保証 |
| split-brain detection が race window で false negative | cutover 2-party-control + source decommission marker 再 verify (post-stop)、`--remote <host>` で remote marker 状態確認 |

