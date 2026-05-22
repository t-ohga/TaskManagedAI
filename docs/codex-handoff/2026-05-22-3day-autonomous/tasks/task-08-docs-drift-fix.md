# task-08: Documentation drift fix (rules + reference + Sprint Pack cross-reference 整合)

**優先**: P3、**計画必須**: 不要 (light)、**self-review**: Plan 1 round + Impl 1 round 推奨、**想定 effort**: 0.3-0.5 day、**依存**: なし

> `codex-all-loops` は Claude 専用 skill (`00-codex-behavior-guide.md` §3.0)。Codex は §3 Self-Review Protocol で同等観点を確保。

## 1. 目的

PR #100-#143 の累積で生じた **documentation drift** を fix。`instincts.md` §17「docs drift を放置しない」遵守。

## 2. 起動 protocol

### 2.1 Read order

1-5. handoff 共通 file
6. **本 file**
7. `.claude/rules/instincts.md` §17 docs drift
8. `.claude/CLAUDE.md` (project instructions)
9. `.claude/rules/` 全件
10. `.claude/reference/` 全件

### 2.2 worktree

```bash
git worktree add .claude/worktrees/codex-task-08-docs-drift origin/main
```

## 3. 計画 phase (§3.1 Round 1 のみ)

Round 1: drift inventory

```bash
# cross-reference 切れ link 検出
rg -n '\[\[([^\]]+)\]\]' .claude/ docs/ | head -30
rg -n '\[.*\]\([^)]*\.md\)' .claude/rules/ .claude/reference/ docs/ | head -50

# 用語 drift 検出
rg -c 'AgentRun 16 状態|agent_runs 16 状態|16 状態 AgentRun' .claude/ docs/
rg -c 'event_type 22|event_type 23|event_type 25|event_type 28|event_type 31|event_type 37' .claude/ docs/
rg -c 'standard role 10 種|10 standard role|10 種 standard role' .claude/ docs/

# 古い PR 番号引用 (master plan / 計画書 / Sprint Pack で stale)
rg -n 'PR #[0-9]+' docs/ .claude/ | head -30
```

## 4. 実装 phase

### 4.1 batch A: AgentRun event_type drift

- AgentRun status は 16 状態 (`.claude/rules/agentrun-state-machine.md` §1) で一貫
- event_type は **P0 期間中 28 種**、SP-014 完遂後 37 種 (P0.1+)
- 古い「22 種 / 25 種 / 31 種」言及を **28 種 (P0) → 37 種 (P0.1+)** に統一

### 4.2 batch B: standard role 10 種言及統一

- `taxonomy.py` の Literal 10 種 + 名称
- SP-013 batch 0 で確定 (PR #133-#140)
- 古い「7 種」「P0.1 で 10 種に拡張」等の stale 表現を fix

### 4.3 batch C: PR 番号 reference fix

- master plan / Sprint Pack で参照されている古い PR 番号を最新 reference に更新
- PR #100-#143 の累積 reference を最新化

### 4.4 batch D: `.claude/rules/` cross-reference 整合

- `branch-and-pr-workflow.md` (Phase D 圧縮 30 行 L1 reminder) ↔ `branch-pr-workflow/SKILL.md` の整合
- `codex-usage-policy.md` §14 mandatory Codex review gates ↔ `sprint-pack-adr-gate.md` §12 ADR accepted promotion
- `cross-source-enum-integrity.md` ↔ `server-owned-boundary.md` の cross link
- `agentrun-state-machine.md` §6.1 P0.1+ event_type 37 拡張 ↔ ADR-00004 update

### 4.5 batch E: `.claude/CLAUDE.md` §6.5 各 subsection 正本 link 確認

PR #42 Phase A 圧縮で各 §6.5 subsection が正本 link 化された。drift 確認 + 必要時 link 修正。

## 5. 検証手順

local verify 不要 (docs-only):

- markdown link check (任意): `markdownlint docs/ .claude/`
- 用語整合 grep (上記 §3 計画 phase の grep を再実行、drift count が 0 or 統一済)
- handoff file 内 cross-reference 切れなし

## 6. PR 起票 + admin bypass merge

1 PR で全件まとめて起票:

```bash
git push -u origin docs/docs-drift-fix-pr100-143-cumulative-2026-05-25
gh pr create --base main --title "docs(drift-fix): PR #100-#143 累積による rules / reference / Sprint Pack 用語 + cross-reference 整合" --body "..."
```

## 7. Codex auto-review baseline 確認 (必須)

```bash
sleep 60
.claude/scripts/codex_pr_full_review.sh <PR_NUM> 2>&1 | head -100
```

## 8. DoD checklist

- [ ] AgentRun event_type 28→37 統一 (P0 vs P0.1+ 区別明示)
- [ ] standard role 10 種言及統一
- [ ] PR 番号 reference stale fix
- [ ] `.claude/rules/` cross-reference 整合
- [ ] CLAUDE.md §6.5 各 subsection link 確認
- [ ] 完了報告 `completion/task-08-completed.md` 起票

## 9. blocker / 緊急停止

- drift fix で既存 invariant の意図的差異が発覚 (例: 古い `22 種` が「Sprint 5 時点の counted」で意図的、現在の「28 種」とは別 context) → STOPPED.md
- cross-reference 切れ修正で循環 link 検出 → STOPPED.md

## 10. 関連

- `.claude/rules/instincts.md` §17 docs drift を放置しない
- `.claude/rules/agentrun-state-machine.md` §6.1 P0.1+ event_type 37 拡張
- 過去類似 PR: PR #117 (master plan §10-§11 update)、PR #98 (post-merge SOP polish)
