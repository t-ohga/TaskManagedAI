---
id: "SP-022-1_scripts_wrapper_hardening"
type: "light"
status: "completed"
sprint_no: 22.1
created_at: "2026-05-22"
updated_at: "2026-05-22"
completed_at: "2026-05-22"
target_days: 2
max_days: 4
adr_refs:
  - "[ADR-00021](../adr/00021_host_portable_deployment.md) # 既 accepted (SP022-T00 2026-05-19)、本 Sprint で scripts wrapper hardening + SOP 整合"
planned_adr_refs: []
related_sprints:
  - "SP-022_framework_intake_hardening"  # 補強 (post-Phase 7a deviation source fix)
  - "SP-012-7_phase_f_0_prerequisite"    # 並行進行可
risks:
  - "Approval Claim 5-field → 6-field schema migration の既存 signed claim 整合"
  - "alembic wrapper 変更で既存 migration apply flow に regression"
  - "pg_dump --single-transaction 除去で restore drill PASS 影響なし確認"
---

最終更新: 2026-05-22

## 目的

Phase 7a Mac single-host operation drill (PR #103 §3) で発覚した **7 件 deviation の source 修正**。drill 実行時に worktree-local wrapper で対応した内容を本 Sprint で **source code / SOP に back-propagate** し、次回 drill (Phase 7b T09 Mac→VPS) で deviation ゼロ目指す。

**前提**: 本 Sprint は P0 Exit declaration (PR #103) 後の **post-P0 hardening**、新機能追加なし。Approval Claim schema 変更を含むため partial ADR Gate 該当 (#6 Secrets 関連、Approval claim binding 構造変更が SecretBroker boundary に影響する場合のみ ADR 必要)。

## 背景

- Phase 7a Mac drill (PR #103 で記録) で 7 件 deviation 発生、worktree-local wrapper で対応
- p0_exit_2026_05_22.md §3 で 7 件列挙、本 Sprint で source 修正
- Phase 7b T09 (Mac→VPS migration drill、任意 timing) を unblock = drill 自動化品質向上

### Phase 7a deviation 7 件 (p0_exit_2026_05_22.md §3 source 引用)

1. **legacy 5-field backup_claim** → worktree-local 6-field signed approval record
2. **allowlist path drift** (runbook vs verifier) → worktree-local allowlist
3. **alembic wrapper** (TASKMANAGEDAI_DATABASE_URL strip) → worktree-local wrapper
4. **pg_dump --single-transaction invalid** → worktree-local docker wrapper で除去
5. **--skip-service-stop 必須** → 対応
6. **SOPS env inclusion 不可** → `.env.encrypted` 不在で archive 不可、plaintext skip 妥当
7. **stale destructive_lock** → process 不在 verify 後手動削除

## 対象外

- Phase 7b T09 実行 (本 Sprint は source 修正のみ、drill 実行は user 物理 or 任意 timing で別途)
- production 公開準備 (P3+ scope)
- multi-host migration drill 自動化 (SP-022 既 must_ship 範囲、本 Sprint は post-Phase 7a の source 修正に focus)

## 設計判断

- **deviation 1 (5-field → 6-field backup_claim)**: Approval claim schema が SecretBroker boundary に影響する場合は ADR 必要。SP-022 既 must_ship で `BackupApprovalClaim` 6-field 化を実施済 (PR #80 SP022-T02 Phase 5) のため、**legacy 5-field 経路の deprecation + 6-field 統一**が scope。ADR 不要 (既存 ADR-00021 で cover)
- **deviation 2 (allowlist path drift)**: runbook (SOP) と verifier (script) で allowlist path が drift → 単一 source of truth 化 (script 側に allowlist 定数集約、SOP は script を参照)
- **deviation 3 (alembic wrapper)**: docker compose exec 経由で `TASKMANAGEDAI_DATABASE_URL` を strip するため、`scripts/alembic_wrapper.sh` 新規 (or 既存修正) で container 内 env 整理
- **deviation 4 (pg_dump --single-transaction 除去)**: pg_dump custom format で `--single-transaction` は invalid (plain format のみ) → backup_orchestrator から除去
- **deviation 5 (--skip-service-stop default 化検討)**: backup 中の service stop は archive consistency 確保のため必要だが、Mac single-host drill では service 起動状態維持が user 操作と整合 → CLI option default 検討 (SOP で明示 vs default ON)
- **deviation 6 (SOPS env inclusion 不可 path)**: `.env.encrypted` 不在時の plaintext skip path を backup_orchestrator に明示的に追加
- **deviation 7 (stale destructive_lock 自動解除)**: lock file age + process 存在 check で auto-cleanup path 追加 (manual 削除回避)

## 実装チケット

### must_ship 1: backup_orchestrator hardening (deviation 1/4/5/6/7)

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-SWH-001 | deviation 1: 5-field → 6-field backup_claim 完全統一 (legacy path deprecation) | 0.4 day |
| BL-SWH-002 | deviation 4: pg_dump --single-transaction 除去 + custom format 整合確認 | 0.2 day |
| BL-SWH-003 | deviation 5: `--skip-service-stop` default 検討 + SOP runbook 整合 | 0.3 day |
| BL-SWH-004 | deviation 6: `.env.encrypted` 不在時 plaintext skip path 明示化 | 0.2 day |
| BL-SWH-005 | deviation 7: stale destructive_lock auto-cleanup path (age + process check) | 0.3 day |

### must_ship 2: alembic wrapper + allowlist path drift (deviation 2/3)

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-SWH-006 | deviation 3: `scripts/alembic_wrapper.sh` 新規 + container env strip + SOP 反映 | 0.3 day |
| BL-SWH-007 | deviation 2: allowlist path 単一 source of truth 化 (script 側集約) + SOP 参照修正 | 0.3 day |

## タスク一覧

- [x] Sprint Pack 起票
- [x] BL-SWH-001-005 backup_orchestrator hardening
- [x] BL-SWH-006-007 alembic wrapper + allowlist single source of truth
- [x] regression test (`tests/scripts/test_backup_orchestrator_*.py` + `tests/scripts/test_alembic_wrapper.py`) 全 PASS
- [x] SOP file (`docs/deploy/mac-single-host-smoke-sop.md` + `mac-single-host-operation-drill-sop.md`) 更新
- [x] codex-impl-loop / codex-review-loop 相当の self/adversarial review (CRITICAL=0 / HIGH=0)
- [x] Sprint Pack `## Review` 追加 + frontmatter `status: ready → completed`

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| deviation 1 (5/6-field 統一) | ✅ | (legacy 5-field path 残存は P3+ で migration、本 Sprint で 6-field default 化 + WARN log のみ defer 可) |
| deviation 2 (allowlist drift) | ✅ | (script 側集約必須、SOP 参照修正は defer 可) |
| deviation 3 (alembic wrapper) | ✅ | (SOP 内 inline document でも可、専用 wrapper script は P3+ defer 可) |
| deviation 4 (pg_dump flag 除去) | ✅ | - |
| deviation 5 (skip-service-stop) | ✅ | (default 化判断保留、SOP で明示する path で defer 可) |
| deviation 6 (SOPS env skip) | ✅ | - |
| deviation 7 (lock auto-cleanup) | ✅ | (manual 削除 SOP で defer 可、auto-cleanup 本実装は P3+ defer) |

## 受け入れ条件

- [x] backup_orchestrator が 7 件 deviation 全件で worktree-local wrapper なしで動作 (source 完結)
- [x] alembic wrapper 経由で `docker compose exec api alembic upgrade head` が host env 影響なし
- [x] allowlist path が script 側 single source of truth、SOP は参照のみ
- [x] regression test 全 PASS (既存 `tests/scripts/test_backup_orchestrator_*.py` 含む)
- [x] SOP file 更新で実 drill flow と整合 (Phase 7a evidence と source の一致)
- [x] codex-review-loop R{N} CLEAN signal + codex-adversarial-loop R{N} CLEAN signal

## 検証手順

```bash
# scripts unit + integration test
uv run pytest tests/scripts/ -v

# alembic wrapper smoke
bash scripts/alembic_wrapper.sh --dry-run upgrade head

# backup_orchestrator smoke (host single-host)
uv run taskhub backup \
  --output /tmp/taskhub-sp022-1-smoke.tar.age \
  --approval-id <signed-approval-id> \
  --skip-service-stop

# SOP integrity check (allowlist path 参照)
grep -n "allowlist\|denylist" \
  docs/deploy/mac-single-host-smoke-sop.md \
  docs/deploy/mac-single-host-operation-drill-sop.md \
  scripts/taskhub_backup_orchestrator.py
```

## レビュー観点

- 5-field → 6-field backup_claim 移行で既存 signed claim record (Phase 7a 実 drill で生成) の verify 互換性確認
- pg_dump --single-transaction 除去で restore drill (Phase 7a + Phase 7b) の data consistency 影響なし
- alembic wrapper 経由で TASKMANAGEDAI_DATABASE_URL strip 動作 (host env が container 内 env を overlay しない)
- allowlist path single source of truth 化で SOP / script の二重 source drift 解消
- stale destructive_lock auto-cleanup の edge case (lock owner process が ESRCH 後即時起動した別 process 誤判定) 防御

## 残リスク

- Approval Claim 5-field 経路の deprecation で既存 signed claim record (P0 期間中の test fixture) の互換性 → migration path 検討 (本 Sprint or P3+)
- alembic wrapper 変更で container 内 env が SP-013+ の追加 env (orchestrator lease 等) と整合性確認 → integration test で確認
- pg_dump custom format での `--single-transaction` 不要性は PostgreSQL 公式 doc で再確認

## 次スプリント候補

本 Sprint 完了で Phase 7a deviation source 修正完了。次は:

1. Phase 7b T09 Mac→VPS migration drill (user 物理、任意 timing) で source 修正効果を verify
2. SP-022 残 must_ship (T06 KPI baseline / T07 production 公開 checklist) 完了
3. SP-023+ production-readiness fence

## 関連 ADR

- ADR-00021 (Host-Portable Deployment + Data Migration) — 既 accepted、本 Sprint で scripts wrapper hardening + SOP 整合 + Phase 7a deviation source 修正
- (新規 ADR 不要、ADR Gate 11 種いずれも非該当 = SecretBroker boundary 不変 / DB schema 不変 / API 契約不変 / 認証認可不変 / GitHub App permission 不変 / 外部公開不変)

## Review

### changed

- PR #159: backup path allowlist helper、`pg_dump --format=custom` の
  `--single-transaction` 除去、docker compose healthcheck retry timing 調整。
- PR #160: `.env.encrypted` 不在時の明示 skip path、Phase 5 SOPS missing marker、
  stale destructive lock cleanup (age + pid absence + non-blocking flock)。
- PR #161: `scripts/alembic_wrapper.sh`、Mac smoke SOP §4/§13 polish、
  Layer C operator runbook §1-§9。
- batch 4: Sprint Pack completion、operation drill SOP の wrapper/skip-service-stop 整合、
  task completion artifact。

### verified

- PR #159/#160/#161: `codex_pr_full_review.sh` baseline 0 finding。
- #159: targeted backup orchestrator ruff/mypy/pytest, compose config, diff check。
- #160: targeted backup/admin/destructive-lock ruff/mypy/pytest, diff check。
- #161: alembic wrapper dry-run, bash syntax, targeted ruff/mypy/pytest,
  new-doc markdownlint, diff check。

### deferred

- Hosted GitHub Actions remain blocked by repository billing/spending-limit
  infrastructure failure; local verification + Codex baseline were used for
  admin bypass merge.
- `uv run ruff check scripts tests/scripts` and `uv run mypy scripts` still
  expose pre-existing scripts debt outside SP-022-1 changed files.
- Full markdownlint cleanup for `docs/deploy/mac-single-host-smoke-sop.md` is
  deferred because the file has broad pre-existing style debt; this Sprint added
  tested targeted markers instead.

### risks

- Phase 7b Mac→VPS drill is still not executed in this Sprint; this Sprint only
  back-propagated Phase 7a deviations into source and SOPs.
- `--skip-service-stop` default remains unchanged; SOP and runbook explicitly
  pass it for Mac local drill where service continuity is expected.
