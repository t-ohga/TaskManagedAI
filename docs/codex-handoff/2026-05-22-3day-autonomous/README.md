# Codex 3-day Autonomous Handoff (2026-05-22 → 2026-05-25)

## 目的

土日・月曜日 (2026-05-23 / 24 / 25) の 3 日間で Codex が autonomous で進める TaskManagedAI 開発 task の **完全な指示書 + 品質担保 contract**。

Claude が **連続 42 PR merge で完成させた基盤** (P0 Exit + Multi-Agent Foundation core schema + 本格的 Ticket CRUD UI + 品質担保 invariant) の上に、Codex が **scope 大の next sprint batch** を実行。最終的に Claude が戻ってきて確認 + 採否判定 + 必要時 fix する flow。

## このディレクトリの読み方

| file | scope | 読む順序 |
|---|---|---|
| **README.md** (本 file) | master index、全体概要 | 1 |
| `00-codex-behavior-guide.md` | Codex がどう振る舞うか (PR 起票 / 品質 / leadership) | 2 (必読) |
| `01-current-state.md` | 現状 snapshot (PR #100-#141、完遂 Sprint、Mac local 状態) | 3 |
| `02-task-priority-matrix.md` | 全 task の優先順位 + 依存 + 並行可能性 | 4 |
| `tasks/task-NN-*.md` | 個別 task 詳細指示 (scope / DoD / 検証手順 / 計画必須判定) | 5 |
| `03-claude-verification-checklist.md` | Claude が戻ってきたときの確認手順 | (Claude 用) |

## 3 日間のスコープ概観

| task | sprint | scope | 想定 effort | 計画必須 | self-review (§3) |
|---|---|---|---|---|---|
| **task-01** | SP-014 batch 0 | orchestrator agent (lease/dispatch/failover) | 1.5-2 day | **必須 (heavy)** | Self-Plan-Review 2 round + Self-Impl-Review 必須 |
| **task-02** | SP-012-8 batch 1-7 | UI 日本語化 | 1-1.5 day | **必須** | Self-Plan-Review 1-2 round + Self-Impl-Review 必須 |
| **task-03** | SP-022-1 | scripts hardening (Phase 7a deviation 7 件) | 0.7-1 day | 推奨 | Self-Plan-Review 1 round + Self-Impl-Review 推奨 |
| **task-04** | SP-012-9 残 | Approvals / Agent Runs / Audit / Settings wiring | 0.5-1 day | 推奨 | Self-Plan-Review 1 round + Self-Impl-Review 推奨 |

合計想定: 3.7-5.5 day = 3 日間 (24h × 3 = 72h、Codex 集中作業時間) で完遂可能。

## 絶対遵守事項 (Codex 厳守)

1. **`00-codex-behavior-guide.md` 全文必読 → その後 task ファイル**
2. **計画必須 task** は実装前に **§3 Self-Plan-Review** (Codex 自身が 1-2 round で plan を review + 敵対視点 + Readiness Gate 自己判定) を実施、CRITICAL=0 / HIGH≤2 達成後着手 (`codex-all-loops` は Claude 専用 skill のため Codex 側で呼べない、§3.0 参照)
3. **code change PR** は `codex_pr_full_review.sh <PR>` で baseline 確認 + adopt/reject/defer 判定 (`00-codex-behavior-guide.md` §6)
4. **invariant fix は matrix-based logic** で全 case enforce (cascade pattern 防止、Claude 教訓 PR #133→#135→#137)
5. **admin bypass merge OK** (CI billing-blocked) ただし `00-codex-behavior-guide.md` §4 の 6 条件を満たす PR のみ
6. **Sprint Pack frontmatter** `status` 更新は **batch 完了時 + Review 章追加**
7. **carry-over は新 Sprint Pack に明示**、defer は TODO comment + Sprint Pack 残リスクに記録
8. **Claude verification 前提**: Codex 完了後、Claude が `03-claude-verification-checklist.md` で確認、必要時 fix PR 起票

## task 依存関係 (並行可能性)

```
task-01 (SP-014 batch 0) ────┐
                              ├──> Claude verification (return)
task-02 (SP-012-8 i18n) ─────┤
                              │
task-03 (SP-022-1 hardening)─┤  (並行可能)
                              │
task-04 (SP-012-9 残 wiring)─┘
```

全 task **並行起動可能** (依存なし)、ただし **同一 file 編集衝突回避** のため `00-codex-behavior-guide.md` §5 で branch 分離戦略を遵守。

## 完了報告 (Codex → Claude)

3 日間終了時に Codex は以下を準備:

1. **完了 task list** (`task-NN` 単位で adopt 件数 / defer 件数 / blocker)
2. **連続 PR merge log** (PR 番号 / merge SHA / 採否判定結果)
3. **Codex finding close 状況** (P1 / P2 / P3 別、cascade pattern 終結確認)
4. **Mac local stack 状態** (alembic head / Ticket 件数 / multi_agent test PASS 数)
5. **carry-over Sprint Pack** (新規起票分 + 既存に追記分)
6. **次 session entry** (Claude 戻り時の次着手 path 明示)

= **本 README の §「3 日間のスコープ概観」表を更新** + handoff memory `~/.claude/projects/-Users-tohga-repo-TaskManagedAI/memory/project_session_2026_05_25_codex_3day_complete.md` 起票。

## Claude 戻り時の確認 path

`03-claude-verification-checklist.md` 参照。要点:

1. 全 PR の Codex auto-review baseline 再確認
2. matrix-based fix の正確性 verify
3. multi_agent contract test 全 PASS 確認 (regression なし)
4. Sprint Pack frontmatter completed 化の妥当性確認
5. carry-over が新 Sprint Pack で carry-over 記載されているか確認

## 参照: 既存 invariant 集

- `.claude/rules/codex-usage-policy.md` (Codex 第一実装エンジン、3 連続失敗保護)
- `.claude/rules/server-owned-boundary.md` (caller-supplied 経路禁止)
- `.claude/rules/cross-source-enum-integrity.md` (5+ source enum drift 防止)
- `.claude/rules/sprint-pack-adr-gate.md` (Sprint Pack + ADR Gate 11 種)
- `feedback_codex_review_must_use_full_helper.md` (`codex_pr_full_review.sh` 必須)

## 緊急停止条件

以下を検知したら Codex は **即座に停止** + handoff file `STOPPED.md` を新規起票して Claude に通知:

- Codex 3 連続失敗 (rate limit / auth / timeout)
- spec 衝突 (本 handoff file 同士で矛盾、または既存 rules / Sprint Pack と矛盾)
- ADR Gate Criteria 11 種に該当する変更が必要 (本 handoff scope 外、Claude による ADR 起票必要)
- Mac local stack 不可逆破壊リスク (DB schema rollback 不能等)
- 想定 effort を大きく超過 (3 day 内に終わらない pattern が確実)
