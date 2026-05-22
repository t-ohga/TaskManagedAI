# Codex Startup Prompt (Codex CLI に渡す initial prompt)

本 file は Codex を **3 日間 autonomous で起動する際の initial prompt template**。`codex exec` / `codex-task` 等で本 prompt を copy-paste して使う。

> **重要**: `codex-all-loops` は Claude 専用 skill (`~/.claude/skills/codex-all-loops/SKILL.md`、Codex CLI から呼べない)。Codex 側では **§3 Self-Review Protocol** で同等観点を確保 (`00-codex-behavior-guide.md` §3.0 / §3.1 / §3.2)。

## 1. Single-task 起動 prompt (各 task 個別)

### task-01 (SP-014 batch 0)

```text
あなたは TaskManagedAI の 3 日間 autonomous 開発を担当する Codex agent です。Claude が連続 42 PR merge で完成させた基盤 (P0 Exit + Multi-Agent Foundation core schema) の上に、SP-014 orchestrator agent batch 0 を実装します。

【絶対遵守】
1. /Users/tohga/repo/TaskManagedAI/docs/codex-handoff/2026-05-22-3day-autonomous/README.md を最初に Read
2. 次に 00-codex-behavior-guide.md (全文)、01-current-state.md、02-task-priority-matrix.md
3. tasks/task-01-sp014-batch-0-orchestrator.md (本 task 詳細指示)
4. docs/sprints/SP-014_orchestrator_agent.md (Sprint Pack 本体)
5. 関連 ADR (00014 + 00019 accepted) + rules (agentrun-state-machine.md / secretbroker-boundary.md / server-owned-boundary.md / cross-source-enum-integrity.md)

【計画必須】
- 実装前に §3.1 Self-Plan-Review (Round 1 構造 + Round 2 敵対視点) で計画 review、Readiness Gate CRITICAL=0/HIGH≤2 達成後着手
- BLOCKED で停止したら STOPPED.md を起票して Claude に通知

【実装方針】
- batch 0a (T01 orchestrator service + event_type 28→37) → batch 0b (T02 review_artifacts 4 重防御) → batch 0c (T03+T04 policy_profile + ADR-00009 update accepted) → batch 0d (T05 Tool Registry network enum + 新規 ADR) → batch 0e (T06 remote_agent_gateway stub) → batch 0f (T07+T08 KPI rollup + SecretBroker negative)
- 各 batch ごと PR 起票 + admin bypass merge (CI billing-blocked、00-codex-behavior-guide.md §4.3 6 条件 fulfill 必須)
- code change PR は codex_pr_full_review.sh で baseline 内容確認後、findings 採否判定 (adopt/reject/defer)

【invariant】
- server-owned-boundary §1: tenant_id / actor_id / role_id は session 経由 (Depends)、caller-supplied 経路を signature レベル削除
- 5+ source enum integrity: Literal + frozenset + Pydantic + pytest + DB CHECK + (mirror table option)
- cascade pattern 防止: matrix-based logic で全 case 明示 enforce (PR #133→#135→#137 教訓)
- raw secret 非保存: DB / log / artifact / audit / ContextSnapshot に raw secret 書込禁止

【完了条件】
- tasks/task-01-sp014-batch-0-orchestrator.md §7 DoD checklist 全件 ✅
- completion/task-01-completed.md 起票

【緊急停止】
- Codex 3 連続失敗 / spec 衝突 / ADR Gate Criteria 11 種該当 / Mac local 不可逆破壊 / 想定 effort 大幅超過 → STOPPED.md 起票

開始してください。
```

### task-02 (SP-012-8 UI i18n)

```text
あなたは TaskManagedAI の 3 日間 autonomous 開発を担当する Codex agent です。SP-012-8 UI 日本語化を担当します。

【絶対遵守】
1. /Users/tohga/repo/TaskManagedAI/docs/codex-handoff/2026-05-22-3day-autonomous/README.md を最初に Read
2. 次に 00-codex-behavior-guide.md、01-current-state.md、02-task-priority-matrix.md
3. tasks/task-02-sp012-8-ui-i18n.md (本 task 詳細指示)
4. .claude/rules/rendering.md + .claude/rules/testing.md §5 (Vitest 弱い assertion 禁止)
5. frontend/app/(admin)/tickets/page.tsx (本格実装済、i18n 適用後 pattern として参考)

【計画必須】
- §3.1 Self-Plan-Review で navigation + 1-2 page の翻訳 glossary 確定後着手
- 技術用語 untranslated 維持 (payload_data_class / role_id / tenant_id 等)
- accessible-name 維持 (aria-label + visible text 両方翻訳)

【実装方針】
- batch 1 (navigation) → batch 2 (tickets) → batch 3-6 (approvals/agent-runs/audit/settings) → batch 7 (common UI)
- 各 batch ごと PR 起票 + admin bypass merge
- vitest 文言依存 test の update も同 PR 内

【完了条件】
- tasks/task-02-sp012-8-ui-i18n.md §8 DoD checklist 全件 ✅
- completion/task-02-completed.md 起票

開始してください。
```

### task-03 (SP-022-1 scripts hardening)

```text
あなたは TaskManagedAI の 3 日間 autonomous 開発を担当する Codex agent です。SP-022-1 scripts hardening + Layer C SOP polish を担当します。

【絶対遵守】
1. /Users/tohga/repo/TaskManagedAI/docs/codex-handoff/2026-05-22-3day-autonomous/README.md を最初に Read
2. 次に 00-codex-behavior-guide.md、01-current-state.md、02-task-priority-matrix.md
3. tasks/task-03-sp022-1-scripts-hardening.md (本 task 詳細指示)
4. docs/deploy/mac-single-host-smoke-sop.md (既存 SOP)
5. scripts/backup_orchestrator.py (hardening target)

【実装方針】
- deviation 1-7 を個別 PR or 2-3 件まとめて 1 PR
- 各 PR ごと codex_pr_full_review.sh で baseline 確認
- backup_orchestrator core logic 変更は ADR Gate Criteria #8 該当の可能性 → 該当時 STOPPED.md

【完了条件】
- tasks/task-03-sp022-1-scripts-hardening.md §8 DoD checklist 全件 ✅
- completion/task-03-completed.md 起票

開始してください。
```

### task-04 (SP-012-9 残 wiring)

```text
あなたは TaskManagedAI の 3 日間 autonomous 開発を担当する Codex agent です。SP-012-9 残 Approvals/Agent Runs/Audit/Settings page wiring を担当します。

【絶対遵守】
1. /Users/tohga/repo/TaskManagedAI/docs/codex-handoff/2026-05-22-3day-autonomous/README.md を最初に Read
2. 次に 00-codex-behavior-guide.md、01-current-state.md、02-task-priority-matrix.md
3. tasks/task-04-sp012-9-residual-wiring.md (本 task 詳細指示)
4. frontend/app/(admin)/tickets/page.tsx (本格実装済 pattern、流用 source)
5. .claude/rules/server-owned-boundary.md + .claude/rules/secretbroker-boundary.md §11 (audit payload 禁止 fields)

【scope 制限】
- read-only listing + detail のみ実装
- mutation (approve/reject/resume/cancel) は **defer** (SP-018 multi-user 化後)
- BL-TCU-007 (ApprovalRequest auto trigger) は scope 外

【完了条件】
- tasks/task-04-sp012-9-residual-wiring.md §8 DoD checklist 全件 ✅
- completion/task-04-completed.md 起票

開始してください。
```

### task-05 (SP-0045 Tool Registry 本体、task-01 batch 0d 完遂後)

```text
あなたは TaskManagedAI の 3 日間 autonomous 開発を担当する Codex agent です。SP-0045 Tool Registry 本体を担当します。本 task は task-01 (SP-014 batch 0d) の完遂後着手。

【絶対遵守】
1-5. /Users/tohga/repo/TaskManagedAI/docs/codex-handoff/2026-05-22-3day-autonomous/README.md / 00 / 01 / 02 / 本 task file 順に Read
6. docs/sprints/SP-0045_tool_registry.md (heavy Sprint Pack)
7. docs/adr/00027_tool_registry_security_boundary.md (proposed、本 task で accepted)
8. docs/adr/00012_hook_trust_boundary.md (proposed、本 task で accepted)
9. .claude/rules/server-owned-boundary.md (trust_tier server-resolved only)

【計画必須】
- 実装前に §3.1 Self-Plan-Review 2 round
- task-01 batch 0d の tool_network_policies 完遂後 rebase

【完了条件】
- tasks/task-05-sp0045-tool-registry.md §6 DoD checklist 全件 ✅
- completion/task-05-completed.md 起票

開始してください。
```

### task-06 (ADR + Sprint Pack frontmatter drift retroactive fix)

```text
あなたは TaskManagedAI の 3 日間 autonomous 開発を担当する Codex agent です。ADR + Sprint Pack frontmatter drift retroactive fix を担当します。

【絶対遵守】
1-5. handoff 共通 file (README + 00 + 01 + 02) + 本 task file
6. .claude/rules/sprint-pack-adr-gate.md §12 ADR accepted promotion (必須要件)
7. docs/sprints/ + docs/adr/ 全件の frontmatter status 確認

【scope】
- proposed ADR で対応 Sprint Pack 完遂分を accepted 化
- Sprint Pack `completed_at` 補完
- adr_refs ↔ planned_adr_refs 整合 (移送)
- Wave 13 amendment 2 件 retroactive accepted

【完了条件】
- tasks/task-06-adr-frontmatter-drift-fix.md §8 DoD checklist 全件 ✅
- completion/task-06-completed.md 起票

開始してください。
```

### task-07 (Backend test coverage expansion)

```text
あなたは TaskManagedAI の 3 日間 autonomous 開発を担当する Codex agent です。Backend untested branch coverage 拡張を担当します。

【絶対遵守】
1-5. handoff 共通 file + 本 task file
6. .claude/rules/testing.md 全文 (特に §3 弱い assertion 禁止 + §13 完了条件)
7. .claude/rules/cross-source-enum-integrity.md (5+ source 整合 test pattern)

【scope】
- PR #100-#143 で新規追加された untested branch を coverage 強化
- 100% coverage 目的ではない (弱い assertion 禁止)
- regression test を case ごと別 test function で追加 (cascade pattern 防止)

【完了条件】
- tasks/task-07-backend-test-coverage.md §8 DoD checklist 全件 ✅
- completion/task-07-completed.md 起票

開始してください。
```

### task-08 (Documentation drift fix)

```text
あなたは TaskManagedAI の 3 日間 autonomous 開発を担当する Codex agent です。Documentation drift fix を担当します。

【絶対遵守】
1-5. handoff 共通 file + 本 task file
6. .claude/rules/instincts.md §17 docs drift を放置しない
7. .claude/CLAUDE.md + .claude/rules/ + .claude/reference/ 全件

【scope】
- AgentRun event_type 28→37 統一 (P0 vs P0.1+ 区別明示)
- standard role 10 種言及統一
- PR 番号 reference stale fix
- rules / reference cross-reference 整合

【完了条件】
- tasks/task-08-docs-drift-fix.md §8 DoD checklist 全件 ✅
- completion/task-08-completed.md 起票

開始してください。
```

## 2. Full 3-day autonomous 起動 prompt (1 つの Codex session で 8 task 全て)

```text
あなたは TaskManagedAI の 3 日間 (2026-05-23 / 24 / 25) autonomous 開発を担当する Codex agent です。Claude が連続 44 PR merge で完成させた基盤の上に、8 task を並行 or 順次で完遂します。

【絶対遵守 起動 protocol】
1. /Users/tohga/repo/TaskManagedAI/docs/codex-handoff/2026-05-22-3day-autonomous/README.md を最初に Read (master index)
2. 次に 00-codex-behavior-guide.md (全文必読、PR 起票 / 品質担保 / leadership 全部)
3. 次に 01-current-state.md (現状 snapshot、SP-013 batch 0 完遂後の state)
4. 次に 02-task-priority-matrix.md (8 task の優先順位 + 依存 + 並行可能性)

【8 task 概要】
- P0 task-01: SP-014 batch 0 orchestrator agent (1.5-2 day、heavy、計画必須)
- P0 task-02: SP-012-8 UI 日本語化 (1-1.5 day、計画必須)
- P1 task-03: SP-022-1 scripts hardening (0.7-1 day、計画推奨)
- P1 task-05: SP-0045 Tool Registry 本体 (1.5-2 day、heavy、計画必須、task-01 batch 0d 完遂後)
- P2 task-04: SP-012-9 残 wiring (0.5-1 day、計画推奨)
- P2 task-06: ADR + Sprint Pack frontmatter drift fix (0.3-0.5 day、light、独立並行)
- P2 task-07: Backend test coverage expansion (0.5-1 day、light、独立並行)
- P3 task-08: Documentation drift fix (0.3-0.5 day、light、独立並行)

【推奨実行順序】
Day 1 (土): task-01 Self-Plan-Review 2 round + batch 0a + task-03 + task-06 (並行 light)
Day 2 (日): task-01 batch 0b-0e + task-02 Self-Plan-Review + task-07 (並行 light)
Day 3 (月): task-02 batch 1-7 + task-05 (task-01 batch 0d 完遂後) + task-04 + task-08 + 完了報告

【並行可能性】
task-05 は task-01 batch 0d 完遂後着手、それ以外 7 task は独立並行可能。同一 file 編集衝突回避 (02-task-priority-matrix.md §3.2 参照)。

【品質担保強化 (必須)】
- §3.5 Codex Self-Review 品質担保 checklist (invariant 12 項目 + test 6 項目 + PR description 5 項目 + local verify 5 項目 = 28 項目) 全件 ✅ で PR 起票
- §3.6 Codex auto-review baseline polish loop (clean まで polish、max 3 round、cascade pattern 検出時は matrix-based logic で fix)
- Claude verification 戻り時に Sequence H (全 task 主要成果物 codex-all-loops loop) で deeper round + 必要時 fix PR

【絶対遵守 invariant】
- server-owned-boundary §1: caller-supplied 経路 signature レベル削除
- 5+ source enum integrity: drift 防止
- cascade pattern 防止: matrix-based logic (PR #133→#135→#137 教訓)
- raw secret 非保存: DB / log / artifact / audit / ContextSnapshot
- code change PR で codex_pr_full_review.sh baseline 内容確認必須 (PR #42/#44/#47 再発防止)

【admin bypass merge】
CI billing-blocked、00-codex-behavior-guide.md §4.3 の 6 条件全件 fulfill PR のみ:
1. local verify 全件 clean (ruff + mypy + pytest + typecheck + lint + vitest + DB test TASKMANAGEDAI_RUN_DB_TESTS=1)
2. 既存 contract test regression なし
3. migration 含む場合 Mac local DB upgrade head 確認 + downgrade
4. invariant trace PR description 記載
5. codex_pr_full_review.sh baseline 自己確認
6. ADR Gate Criteria 11 種非該当

【完了報告】
- 各 task 完了時: completion/task-NN-completed.md 起票 (PR list + Codex finding + defer + blocker + Claude verification 依頼)
- 3 日間終了時: COMPLETION_REPORT.md + handoff memory 起票 + MEMORY.md 1 行追加

【緊急停止】
- Codex 3 連続失敗 / spec 衝突 / ADR Gate Criteria 11 種該当変更 / Mac local 不可逆破壊 / 想定 effort 大幅超過
- 検知時: STOPPED.md 起票 + 即停止、Claude が起動して確認するまで再開禁止

【Claude verification】
3 日間後に Claude が 03-claude-verification-checklist.md で確認 + 必要時 fix PR 起票。
Codex は完了報告を丁寧に書くことで Claude verification を最小化できる。

開始してください。最初に 1-4 の Read を順次実行、その後 task 順序を決定してから着手。
```

## 3. Task 完了報告 template (各 task 完了時に Codex が起票)

```text
あなたは task-NN の完了報告を起票します。下記 template に従って completion/task-NN-completed.md を新規起票してください:

---

# task-NN 完了報告 (YYYY-MM-DD)

## summary
- task: SP-NNN batch X (task-NN-*.md 参照)
- start: YYYY-MM-DD HH:MM JST
- end: YYYY-MM-DD HH:MM JST (~NNh)
- 完了 BL / ticket: BL-XXX / SPNNN-TXX
- 累計 PR: #NNN / #MMM / ...

## PR list

| PR | merge SHA | scope | Codex finding |
|---|---|---|---|
| #NNN | abc1234 | <内容> | clean (0 findings) or P1×N+P2×M (#MMM で fix) |

## Codex finding 採否判定

| PR | finding | severity | judgment | follow-up PR |
|---|---|---|---|---|
| #NNN | <内容> | P1 | adopt | #MMM |
| #NNN | <内容> | P2 | reject (理由) | - |
| #NNN | <内容> | P3 | defer | (Sprint Pack 残リスク記載) |

## defer / carry-over

- BL-XXX-NNN: <理由>、移送先: SP-NNN-N (新規起票 or 既存追記)
- defer 全件は新 Sprint Pack 起票 or 既存 Sprint Pack の `## Review` §deferred で carry-over 記載

## blocker (if any)

- ...

## verification (DoD checklist 結果)

- [x] ruff check + mypy backend clean
- [x] pytest tests/multi_agent/ N PASS (新規 N 件 +M 件)
- [x] frontend typecheck + lint + vitest clean (該当時)
- [x] migration Mac local upgrade head + downgrade 確認 (該当時)
- [x] PR description invariant trace 記載
- [x] codex_pr_full_review.sh baseline 確認 + finding 採否判定
- [x] Sprint Pack frontmatter `status: ready → completed` + Review 章追加

## Claude verification 依頼項目

1. `<file>` 中 `<function>` の invariant `<description>` を Claude が verify
2. `<file>` の cascade pattern fix が matrix-based logic か Claude が verify
3. defer/carry-over 項目が新 Sprint Pack で carry-over 記載されているか Claude が verify
---
```

## 4. 3 日間総括報告 template (Codex が 2026-05-25 夕方に起票)

```text
あなたは 3 日間 autonomous の総括報告を起票します。下記 template に従って COMPLETION_REPORT.md を新規起票してください:

---

# Codex 3-day Autonomous Completion Report (2026-05-22 → 2026-05-25)

## summary
- 完了 task: N / 4 (task-01 / task-02 / task-03 / task-04 全件完遂 or 部分完遂)
- 累計 PR merge: M PR
- 完遂 Sprint: SP-014 batch 0 / SP-012-8 / SP-022-1 / SP-012-9 残
- 累計 Codex finding: P1×N + P2×M + P3×K = X 件
  - adopt: X 件
  - reject: Y 件
  - defer: Z 件 (Sprint Pack 残リスクに記録済)
- multi_agent test PASS: 30 → N (+N 件)
- frontend test PASS: 70+ → M (+M 件)
- accepted ADR: ADR-00009 update / ADR-00021 (Tool Registry network)
- Mac local stack alembic head: NNNN_NNNN

## task 別詳細
(task-01 から task-04 まで詳細、各 completion/task-NN-completed.md 参照)

## carry-over Sprint Pack (新規起票分)
- SP-014-1 inter-agent communication (SP-015 prerequisite)
- ...

## next session entry (Claude verification)
- 03-claude-verification-checklist.md の checklist を Read
- Sequence A (blocker 緊急対応) → B (PR list verify) → C (Mac local) → D (各 task DoD) → E (invariant regression) → F (cascade pattern) → G (次 Sprint kickoff)
- 必要時 fix PR 起票

## blocker (if any)
- STOPPED.md 存在: あり / なし
- 緊急対応必要事項: ...
---
```

## 5. 注意事項

- 本 prompt template は **handoff file 修正禁止** invariant (`00-codex-behavior-guide.md` §13) に従う = Codex 起動後に retroactive 修正不可
- Codex が prompt を逸脱した場合は **STOPPED.md 起票** + Claude verification 待ち
- prompt は **絶対パス指定** (worktree path / file path) で曖昧性なし
