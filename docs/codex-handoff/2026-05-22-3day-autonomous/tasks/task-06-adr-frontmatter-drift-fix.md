# task-06: ADR + Sprint Pack frontmatter drift retroactive fix

**優先**: P2、**計画必須**: 不要 (light、scope 明確)、**self-review**: Plan 1 round + Impl 1 round 推奨、**想定 effort**: 0.3-0.5 day、**依存**: なし (独立並行可)

> `codex-all-loops` は Claude 専用 skill (`00-codex-behavior-guide.md` §3.0)。Codex は §3 Self-Review Protocol で同等観点を確保。

## 1. 目的

PR #100-#143 で merge された ADR / Sprint Pack の **frontmatter drift retroactive fix**:

- `proposed` のまま実装着手した ADR を `accepted` 化 (sprint-pack-adr-gate.md §12)
- 完遂 Sprint Pack の `completed_at` / `completed_at` 抜けを補完
- `adr_refs` と `planned_adr_refs` の整合 (accepted 化済み ADR を `planned_adr_refs` → `adr_refs` に移送)
- Wave 13 amendment 2 件 (2026-05-22 deadline 経過、retroactive accepted promotion 必要)

## 2. 起動 protocol

### 2.1 Read order

1-5. handoff 共通 file (00 / 01 / 02 / README)
6. **本 file**
7. `.claude/rules/sprint-pack-adr-gate.md` §12 ADR accepted promotion
8. `docs/sprints/SP-013_multi_agent_orchestration.md` (PR #141 で completed 化、本 task で他 Sprint Pack も同様 fix)
9. `docs/adr/` 配下全 ADR の frontmatter status

### 2.2 worktree

```bash
cd /Users/tohga/repo/TaskManagedAI
git worktree add .claude/worktrees/codex-task-06-adr-drift origin/main
cd .claude/worktrees/codex-task-06-adr-drift
bash scripts/worktree_setup.sh
```

## 3. 計画 phase (§3.1 Round 1 のみ)

Round 1: 構造 review = drift inventory 作成

```bash
# 全 ADR status
for f in docs/adr/*.md; do
  id=$(awk -F'"' '/^id:/{print $2; exit}' "$f")
  status=$(awk -F'"' '/^status:/{print $2; exit}' "$f")
  echo "$status | $id"
done | sort
```

```bash
# 全 Sprint Pack status + completed_at
for f in docs/sprints/SP-*.md; do
  id=$(awk -F'"' '/^id:/{print $2; exit}' "$f")
  status=$(awk -F'"' '/^status:/{print $2; exit}' "$f")
  completed=$(awk -F'"' '/^completed_at:/{print $2; exit}' "$f")
  echo "$status | $completed | $id"
done | sort
```

## 4. 実装 phase

### 4.1 batch A: ADR accepted retroactive promotion

各 proposed ADR で、対応 Sprint Pack 実装が完遂しているなら `accepted` 化:

- ADR-00009 update (task-01 batch 0c で accepted、retroactive 確認)
- ADR-00012 Hook Trust Boundary (task-05 で accepted)
- ADR-00013 Remote Agent Extension (proposed → accepted、関連実装完了確認)
- ADR-00014 Multi-Agent Orchestration (PR #109 で accepted、frontmatter 確認)
- ADR-00019 Role Taxonomy (PR #109 で accepted、frontmatter 確認)
- ADR-00016 sanitizer_policy_versions (PR #139 関連、accepted 化)

### 4.2 batch B: Sprint Pack `completed_at` 補完

完遂 Sprint Pack で `completed_at` 欠落分:

- SP-012-7 / SP-012-10 / SP-012-11 / SP-012-11.1 (本 session 完遂)
- SP-022 (P0 Exit、PR #99 で完遂)
- SP-013 (PR #141 で `completed_at: 2026-05-22` 設定済、再確認)

### 4.3 batch C: `adr_refs` ↔ `planned_adr_refs` 整合

accepted 化済 ADR が `planned_adr_refs` に残っている Sprint Pack を `adr_refs` に移送。

### 4.4 batch D: Wave 13 amendment 2 件 retroactive accepted

`docs/adr/wave-13-amendment-*.md` の 2 件 (deadline 2026-05-22 経過、Codex audit で deferred):
- 内容確認 + accepted promotion path 適用

## 5. 検証手順

```bash
# frontmatter drift check (no breaking change)
rg -l 'status:.*proposed' docs/adr/ | wc -l  # 修正後 count
rg -l 'status:.*completed' docs/sprints/ | wc -l  # 修正後 count

# markdown lint (任意)
# 既存 link 切れ確認
```

local verify は不要 (docs-only、code 変更なし、CI 影響なし)。

## 6. PR 起票 + admin bypass merge

1 PR で全件まとめて起票 (light task、scope 明確):

```bash
git push -u origin feat/sp-handoff-adr-frontmatter-drift-fix-2026-05-24
gh pr create --base main --title "fix(docs): ADR + Sprint Pack frontmatter drift retroactive fix" --body "..."
```

## 7. Codex auto-review baseline 確認 (必須)

```bash
sleep 60
.claude/scripts/codex_pr_full_review.sh <PR_NUM> 2>&1 | head -100
```

## 8. DoD checklist

- [ ] proposed ADR 全件 confirm + 該当分 accepted 化 (sprint-pack-adr-gate.md §12 promotion 条件 satisfied)
- [ ] Sprint Pack `completed_at` 補完
- [ ] `adr_refs` ↔ `planned_adr_refs` 整合 (移送完了)
- [ ] Wave 13 amendment 2 件 accepted (内容確認 + status 更新)
- [ ] 完了報告 `completion/task-06-completed.md` 起票

## 9. blocker / 緊急停止

- ADR の accepted 化条件 (§12.2 promotion 条件 checklist) を満たさない ADR があれば、その ADR は **defer** + 理由を Sprint Pack 残リスクに記録 (本 task scope 内で完遂しなくて OK)
- Wave 13 amendment の内容が ADR Gate Criteria 11 種に該当する変更 → STOPPED.md

## 10. 関連

- `.claude/rules/sprint-pack-adr-gate.md` §12 ADR accepted promotion (必須要件 + drift 検出)
- 過去類似: PR #141 (SP-013 frontmatter completed 化 + Review 章)
