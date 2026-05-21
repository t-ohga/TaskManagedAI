# SP-012 Full Implementation Roadmap (autonomous completion plan)

> **2026-05-21 起票**: 「終わってないもの全てを完璧に実装」+ 「完全自走」+ 「計画をたてなければいけないものはしっかり計画」というユーザー絶対指示 (2026-05-21 後半 session 後半) に基づく、SP-012 must_ship 残作業 + TaskManagedAI P0 全体での残作業の正本実装ロードマップ。
>
> Canonical primary source: `.claude/plans/sp012-split-brain-keyring.md` §3.A-§9.10 (Phase 1+2 23 round / 96 findings adopt 済 + Codex R1-R2 16 findings adopt 済 + Batch A/B 部分実装済)。

## §1 TaskManagedAI P0 全体 progress 現在地

### Sprint Pack status (2026-05-21)

| Sprint | status | 完了内容 | 残 |
|---|---|---|---|
| SP-005-5 (output_validator) | ✅ completed | - | - |
| SP-006 (cli_artifact) | ✅ completed | - | - |
| SP-007 (runner_sandbox) | ✅ done_with_phase5_defer | - | Phase 5 deferred to P0.1 |
| SP-008 (github_app_repoproxy) | ⚠️ partial_skeleton | - | P0.1 Sprint で完成 |
| SP-009 (p0_ui_pack) | ⚠️ skeleton_pending_backend | - | P0.1 で backend wiring 後 |
| SP-010 (research_evidence) | ✅ completed | - | - |
| SP-011 (eval_harness) | ✅ completed | - | - |
| SP-011-5 (operational_hardening) | ✅ completed | - | - |
| **SP-012 (p0_acceptance)** | ⚠️ partial_completed_with_carry_over | host migration drill + carry-over | 本 plan 完遂 + SP-022 T08+T09 |
| **SP-022 (framework_intake_hardening)** | 🔵 in_progress (pre-P0.1 unblock sprint) | T00/T01/T02 (Phase 1-5)/T03/T04/T07/T08 (batch 1-4) | T08 batch 5+6 / T06 / T09 / SP-012 carry-over |
| SP-013-016 (P0.1+) | 📋 draft | - | SP-022 完了後 |

### P0.1 unblock path

```
SP-012 must_ship (本 plan) 完遂
  ↓
SP-022 T08 batch 5 (signed journal CLI DB mode + private staging E2E)
  ↓
SP-022 T08 batch 6 (frontend backend wiring)
  ↓
SP-022 T06 KPI baseline (Mac 単独 light)
  ↓
SP-022 T09 host migration drill (Mac→VPS、RTO≤4h、**user 介在必須**)
  ↓
P0 Exit declaration (Hard Gates 7 全件 + KPIs 5 未達 1 個以下)
  ↓
TASKHUB_P0_1_OPENED=1 + sealed guard 解除 + SP-013 着手
```

## §2 自走対象の残作業 (本 session + 後続 session で完遂可能)

### §2.1 SP-012 must_ship 残 (本 plan 直接対象)

| # | 作業 | 状態 | 自走可否 | 想定行数 |
|---|---|---|---|---|
| 1 | PR #82 (Batch B logic) Codex R3 polling + clean → admin merge | 🔵 polling 中 | ✅ 自走可 | -|
| 2 | Batch C: keyring CLI logic + caller-supplied actor 削除 + server-owned approval issuance journal + clock monotonicity | ⏳ 未着手 | ✅ 自走可 | +800-1,200 行 |
| 3 | Batch D: PrepareMarker + CommitMarker dataclass + lease binding verify + commit-time finalization + 残 fixture (約 60+ 件) | ⏳ 未着手 | ✅ 自走可 | +1,000-1,400 行 |
| 4 | backend gate L1 (FastAPI dependency) | ⏳ 未着手 | ✅ 自走可 | +200 行 |
| 5 | backend gate L2 (ARQ worker startup + dequeue) | ⏳ 未着手 | ✅ 自走可 | +200 行 |
| 6 | backend gate L3 (SQLAlchemy before_commit) | ⏳ 未着手 | ✅ 自走可 | +200 行 |
| 7 | docker-compose entrypoint script | ⏳ 未着手 | ✅ 自走可 | +80 行 |
| 8 | operator runbook §13 (keyring rotation SOP) | ⏳ 未着手 | ✅ 自走可 | +150 行 docs |
| 9 | operator runbook §14 (active-registry split-brain check SOP) | ⏳ 未着手 | ✅ 自走可 | +100 行 docs |
| 10 | operator runbook §15 (60 ReasonCode reason table) | ⏳ 未着手 | ✅ 自走可 | +200 行 docs |
| 11 | operator runbook §17 (emergency revocation SOP) | ⏳ 未着手 | ✅ 自走可 | +80 行 docs |
| 12 | operator runbook §18 (approval artifact archive Mode A/B) | ⏳ 未着手 | ✅ 自走可 | +60 行 docs |
| 13 | operator runbook §19 (state head deploy SOP) | ⏳ 未着手 | ✅ 自走可 | +100 行 docs |
| 14 | operator runbook §20 (commit-time invariant + ε tolerance) | ⏳ 未着手 | ✅ 自走可 | +60 行 docs |
| 15 | operator runbook §21 (clock attestation 3 mode) | ⏳ 未着手 | ✅ 自走可 | +120 行 docs |
| 16 | operator runbook §22 (cutover SOP) | ⏳ 未着手 | ✅ 自走可 | +150 行 docs |
| 17 | .claude/scripts/check_reason_code_coverage.sh (60 ReasonCode 5-source CI check) | ⏳ 未着手 | ✅ 自走可 | +120 行 |
| 18 | SP-012 Sprint Pack `## Review` 更新 | ⏳ 未着手 | ✅ 自走可 | +80 行 |

**SP-012 残 total**: 約 **+4,000 行** code + docs + 60+ fixture (Batch C/D で約 100-130 fixture 追加)。

### §2.2 SP-022 残作業 (本 plan scope 外、別 PR/Sprint)

| Task | 状態 | 自走可否 | Note |
|---|---|---|---|
| SP022-T08 batch 5 (signed journal CLI DB mode + private staging E2E) | ⏳ | ⚠️ partial (E2E は CI fixture 整備が前提) | DB connection fixture 整備可能なら自走可 |
| SP022-T08 batch 6 (frontend backend wiring) | ⏳ | ✅ 自走可 | UI と backend API 接続、Vitest fixture 追加 |
| SP022-T06 (KPI baseline Mac 単独 light) | ⏳ | ✅ 自走可 | rolling baseline 計測 docs + script |
| SP022-T09 (host migration drill Mac→VPS RTO≤4h) | ⏳ | ❌ **user 介在必須** | 物理 2 host + 半日 drill 実施、自走不可 |

### §2.3 P0 Exit (本 plan scope 外、SP-022 完遂後)

| 作業 | 状態 | 自走可否 |
|---|---|---|
| Hard Gates 7 全件 verify | ⏳ | ⚠️ partial (一部は test fixture で自走可、host migration drill PASS は不可) |
| Quality KPIs 5 計測 | ⏳ | ✅ 自走可 (script + baseline 計測) |
| P0 Exit declaration | ⏳ | ❌ user 判断必須 (TASKHUB_P0_1_OPENED=1 設定) |

## §3 Batch C 詳細実装計画 (次着手対象)

### §3.1 Goal

ADR-00029 (approval keyring rotation) に対応する keyring CLI 実装 + caller-supplied actor 削除 + server-owned approval issuance journal + clock monotonicity attestation の foundational logic + 約 30-40 unit fixture。

### §3.2 実装対象 file (約 4-6 file、+約 800-1,200 行)

1. **scripts/taskhub_keyring.py 拡張** (+約 400 行 logic)
   - SignedManifestEntry dataclass (fingerprint + status + issued_at + expires_at + deprecated_at + revoked_at + revocation_reason_hash + incident_id + source)
   - SignedKeyringManifest dataclass (entries + generation + previous_committed_manifest_hash + commit_log_chain_hash + signature)
   - load_keyring_with_dual_trust(): legacy single-key + signed manifest both 同時 verify path
   - authorization_verify(record, manifest, mode="authorization") vs audit_verify(record, manifest, mode="audit") — predicate 分離 (§9.4 R2 F-005)
   - load_keyring_state_head() — /etc/taskhub/keyring_state.head.signed verify
   - load_revocation_tombstone() — append-only denylist
   - validate_key_format() — taskhub1<base64> Ed25519 32 bytes + sha256 fingerprint match

2. **scripts/taskhub_approval_issuance.py 拡張** (+約 200 行 logic)
   - IssuanceJournalEntry dataclass (approval_id + claim_hash + issued_at + monotonic_sequence + previous_issued_at + issuer_signer_fingerprint + previous_entry_hash + key_fingerprint_at_issue + key_status_at_issue + monotonic_clock_attestation)
   - issue_approval(claim_canonical_bytes, principal_token_fd) -> approval_id + journal_entry — server-owned issue path
   - verify_issuance_chain(entry, prev_entry) — chain integrity + monotonic_sequence + wall-clock skew + clock attestation
   - 3 mode clock attestation: linux_clock_monotonic (CLOCK_MONOTONIC), tpm_clock (placeholder), trusted_time_attestation (placeholder)

3. **scripts/taskhub_admin.py 拡張** (約 +250 行)
   - `taskhub keyring bootstrap --legacy-key-path <path>` — first deployment marker initialization
   - `taskhub keyring add-key --pubkey <path>` — staging candidate manifest 経由
   - `taskhub keyring remove-key --fingerprint <fp>` — active → deprecated 化
   - `taskhub keyring revoke-key --fingerprint <fp>` — compromise revocation + tombstone append
   - `taskhub keyring commit-manifest --signed-candidate <path>` — atomic install
   - 各 subcommand に `--approval-id` 必須 (caller-supplied actor 削除、principal-token-fd 経路)

4. **scripts/taskhub_approval_cli.py 拡張** (約 +120 行)
   - `--keyring-*` issue args (operation, target_fingerprint, etc.)
   - caller-supplied `--signed-at` 物理削除 (signature レベル)
   - principal-token-fd 経路 (`--principal-token-fd <fd>`)
   - issuance_journal append wrapper

5. **tests/scripts/test_taskhub_keyring.py 新規** (約 +500 行、30-40 fixture)
   - KeyringRotationApprovalClaim 5 variants (bootstrap/add_key/remove_key/revoke_key/commit_manifest)
   - dual-trust verify (legacy + manifest 両方 pass)
   - lifecycle (active/deprecated/revoked) と verify mode (authorization/audit) 分離
   - bootstrap operation (existing record preserve + legacy_not_before validation)
   - commit-manifest transition policy (許可 / 禁止 diff)
   - signed manifest replay defense (generation chain)
   - tombstone denylist (revoked fingerprint 無条件 reject)
   - state head non-rollback check (config_dir snapshot rollback defense)

6. **tests/scripts/test_taskhub_approval_issuance.py 新規** (約 +400 行、15-20 fixture)
   - server-owned issue path + caller-supplied signed_at reject
   - issuance journal chain integrity (previous_entry_hash + monotonic_sequence)
   - clock skew tolerance ε = 5s + regression reject
   - monotonic_clock_attestation independent source
   - reboot detection + attestation requirement

### §3.3 採否判定基準 (Codex R{N})

- **P1 (CRITICAL)**: 即時 adopt + verify fixture 追加
- **P2 (correctness)**: 即時 adopt + 必要なら verify fixture
- **P3 (style)**: 採否判定 (project convention と整合 → adopt、過剰 → reject 理由を記録)
- **stale finding**: 古い commit ref で同 file/line を再指摘 → adopt 済 commit ref を返信、無視

### §3.4 完了条件

- [ ] uv run ruff check All checks passed
- [ ] uv run pytest tests/scripts/test_taskhub_keyring.py: 30-40 PASS
- [ ] uv run pytest tests/scripts/test_taskhub_approval_issuance.py: 15-20 PASS
- [ ] uv run pytest tests/scripts/test_taskhub_signed_approval.py: 36 PASS (regression なし)
- [ ] PR Codex R{N} で critical_zero gate (CRITICAL=0 + HIGH≤2) PASS
- [ ] admin merge bypass で main に merge

## §4 Batch D 詳細実装計画

### §4.1 Goal

2PC PrepareMarker + CommitMarker + immutable archived snapshot + commit-time finalization signature (§9.6 R5 F-001 + §9.7 R6 F-001 + §9.9 R9 F-001) の foundational logic + 約 50-60 fixture。

### §4.2 実装対象 file (約 3-5 file、+約 1,000-1,400 行)

1. **scripts/taskhub_active_registry.py 拡張** (+約 500 行 logic)
   - PrepareMarker dataclass (cutover_id + host_id + role + lease binding hash + signature)
   - CommitMarker dataclass (cutover_id + source_prepare_marker_hash + target_prepare_marker_hash + commit_finalization_preimage_hash + host_finalization_signatures (list) + committed_at + commit_approval_claim_hash + signature)
   - acquire_cutover_lease(): fleet-wide root-signed lease + concurrent cutover_id reject
   - perform_2pc_prepare(): source side + target side prepare phase
   - perform_2pc_commit(): commit certificate + finalization signature 全件 verify + lease window check
   - load_archived_lease_snapshot() / load_archived_fleet_membership_snapshot() — immutable archive

2. **scripts/taskhub_active_registry_reconciliation_gate.py 新規** (+約 200 行)
   - benign vs security-relevant drift 判定
   - successor transition required vs invalidate marker

3. **scripts/taskhub_admin.py 拡張** (+約 150 行)
   - `taskhub cutover --target-host <id>` subcommand (2PC orchestration)
   - `taskhub active-registry list` subcommand
   - `taskhub active-registry verify-marker <path>` subcommand

4. **tests/scripts/test_taskhub_active_registry.py 拡張** (+約 600 行、50-60 fixture)
   - 2PC pattern: prepare + commit + partial confirmation reject
   - fleet-wide lease: concurrent cutover_id reject + required_host partial confirmation reject
   - lease window check: lease_acquired_at <= committed_at < lease_expires_at
   - commit-time invariant (§9.9 R9 F-001 logic correction): max(host_commit_confirmed_at) <= committed_at
   - immutable archived snapshot: lease 自然失効後も past CommitMarker verify pass
   - reconciliation gate: benign drift で successor transition required (既存 CommitMarker invalidate しない)
   - signer-host ownership: target signer cannot activate source / source cannot commit target
   - approval artifact verify: missing / random hash / field mismatch reject

## §5 backend gate (L1+L2+L3) 詳細実装計画

### §5.1 Goal

active-registry write gate を defense-in-depth 3 layer で実装 (§9.10 R10 F-001)。

### §5.2 実装対象 file (約 6 file、+約 600 行)

1. **backend/app/api/dependencies/active_registry_gate.py** 新規 (+約 150 行)
   - FastAPI dependency (Depends)
   - load current fleet + active marker → host_id 一致 + status active + valid_to > now() check
   - fail-closed: 503 Service Unavailable + reason_code taskhub_active_registry_write_rejected_by_gate

2. **backend/app/workers/active_registry_worker_gate.py** 新規 (+約 150 行)
   - ARQ worker startup + job dequeue 前 verify
   - graceful cancel on freeze marker (SIGTERM in-flight)
   - retry-after timer on transient failure

3. **backend/app/db/active_registry_mutation_gate.py** 新規 (+約 200 行)
   - SQLAlchemy `before_commit` event listener
   - read fleet + active marker (cached with ttl)
   - IntegrityError raise on gate fail

4. **backend/app/main.py 拡張** (+約 50 行) — L1 dependency wiring

5. **backend/app/workers/main.py 拡張** (+約 50 行) — L2 gate integration

6. **scripts/taskhub_entrypoint_active_registry_check.sh** 新規 (+約 80 行)
   - Docker container entrypoint pre-check
   - active marker + fleet membership + signature verify → fail で exit 1
   - docker-compose.yml 統合

## §6 Operator runbook 詳細実装計画

### §6.1 docs/deploy/operator-runbook.md 拡張 (+約 1,100 行 docs)

§13-§22 を追加 (sections 詳細は §2.1 #8-#16 参照)。

## §7 Execution sequence (本 session + 後続 session の取扱)

### §7.1 Phase 1: PR #82 (Batch B) clean + merge (本 session 継続)

1. ScheduleWakeup `21:41:00` で Codex R3 polling
2. R3 findings 全件 adopt → R4 trigger
3. R{N} critical_zero gate clean signal 到達
4. admin merge bypass で main へ merge

### §7.2 Phase 2: Batch C (本 session または次 session、約 4-6 commits)

1. 新 branch `worktree-sp012-batch-c` を merged main から作成
2. taskhub_keyring.py logic 実装 + 30-40 unit fixture
3. taskhub_approval_issuance.py logic 実装 + 15-20 unit fixture
4. taskhub_admin.py keyring CLI 5 subcommand 追加
5. taskhub_approval_cli.py principal-token-fd 経路 + caller-supplied 削除
6. PR 起票 + Codex R{N} adopt loop + admin merge bypass

### §7.3 Phase 3: Batch D (次 session、約 3-5 commits)

1. 新 branch `worktree-sp012-batch-d` を merged main から作成
2. PrepareMarker + CommitMarker dataclass + 2PC logic
3. acquire_cutover_lease + perform_2pc_prepare + perform_2pc_commit
4. reconciliation gate + archived snapshot loaders
5. test 50-60 fixture 追加
6. PR + Codex review + merge

### §7.4 Phase 4: backend gate L1+L2+L3 (次 session、約 2-3 commits)

1. 新 branch `worktree-sp012-backend-gate`
2. L1 FastAPI dependency + main.py wiring + endpoint integration
3. L2 ARQ worker startup + dequeue gate
4. L3 SQLAlchemy before_commit listener
5. backend test 追加 (FastAPI TestClient + worker fixture + SQLAlchemy session fixture)
6. PR + Codex review + merge

### §7.5 Phase 5: operator runbook §13-§22 (次 session、1 commit)

1. 新 branch `worktree-sp012-runbook` (docs-only、relatively low risk)
2. operator-runbook.md §13-§22 追記 (約 +1,100 行 docs)
3. PR + Codex review (docs-only PR は Codex skip の可能性、その場合は author self-review で merge)

### §7.6 Phase 6: SP-012 Sprint Pack `## Review` 更新 + SP-022 carry-over status

1. 新 branch `worktree-sp012-sprint-exit`
2. docs/sprints/SP-012_p0_acceptance.md `## Review` を `completed` status に書き換え
3. SP-022 progress を「SP-012 carry-over 完遂」で更新
4. PR + admin merge

### §7.7 Phase 7: SP-022 残作業 (別 Sprint Pack scope、別 session 群)

- T08 batch 5 (signed journal CLI DB mode + private staging E2E)
- T08 batch 6 (frontend backend wiring)
- T06 KPI baseline (Mac 単独)
- T09 host migration drill — **user 介在必須、自走 scope 外**

## §8 完全自走の制約 (絶対遵守)

- **Codex R{N} 採否判定 3 分類**: adopt / reject / defer。adopt は即時実装、reject は理由記録、defer は user 確認後
- **admin merge bypass**: PR #67-#82 pattern、CI billing-blocked のため `gh api -X PUT pulls/N/merge` 直接 (user 明示指示済の運用継承)
- **Codex 3 連続失敗**: rate limit / 401 / 空 response が 3 連続なら AskUserQuestion で確認
- **ADR Gate**: ADR-00028/00029 既 accepted、本 plan 内の変更は ADR 追加不要 (Sprint Pack で対応)
- **Sprint Pack adr_refs**: SP-012 Sprint Pack の adr_refs に ADR-00028/00029 を追加 (Phase 6 で実施)
- **テスト無し commit 禁止**: 各 Batch で実装と同時に unit fixture 追加、regression PASS verify
- **plan-only PR**: docs-only / plan-only PR は Codex auto-review が skip する場合あり、その時は self-review で merge 可

## §9 Risk + mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Codex rate limit | Medium | progress 停滞 | 3 連続失敗で AskUserQuestion、時間を空けて retry |
| context budget 切れ | High | session 終了 | memory handoff を各 Phase 完遂時に更新、次 session で continuation |
| Batch C で deep design 欠陥発覚 | Medium | rework | 直前 PR #82 と同様 Codex R{N} で iterative fix |
| backend gate で既存 endpoint regression | Medium | test fail | TestClient regression test を Phase 4 で必須化 |
| SP-022 T09 user 介在必須 | High | 自走不可 | T09 docs prep を完了させ、user 実行時に script ready 状態にする |

## §10 完遂条件

本 roadmap は以下達成で完遂:
- [x] SP-012 must_ship Phase 1 (PR #82 Batch B merged) — 本 session 中
- [ ] SP-012 must_ship Phase 2 (Batch C merged)
- [ ] SP-012 must_ship Phase 3 (Batch D merged)
- [ ] SP-012 must_ship Phase 4 (backend gate merged)
- [ ] SP-012 must_ship Phase 5 (operator runbook merged)
- [ ] SP-012 must_ship Phase 6 (Sprint Pack Review section)
- [ ] (post-handoff) SP-022 T08 batch 5+6 / T06 完了 (別 session)
- [ ] (user 介在) SP-022 T09 host migration drill PASS
- [ ] (user 判断) P0 Exit declaration + TASKHUB_P0_1_OPENED=1

各 Phase 完遂時に memory handoff (`project_session_2026_05_21_sp012_*.md`) を更新、次 session の entry point を明示する。
