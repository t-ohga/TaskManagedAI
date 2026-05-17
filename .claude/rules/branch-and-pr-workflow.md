# Branch + PR Workflow (Phase D 圧縮 L1 reminder、2026-05-17、本格 spec は skill 移送済)

> **Phase D 圧縮 (2026-05-17、PR #?)**: 本 rule は **30 行 L1 reminder**。詳細 spec (Phase 0-3 worktree workflow / PR convention / Codex auto-review 確認義務 / user 手元作業の代理処理 path / 6 state transfer / safeguards / divergence 防止) は **`.claude/skills/branch-pr-workflow/SKILL.md` に移送済 (L3-auto skill、`disable-model-invocation: false`、description match で auto invoke)**。

## 最小 L1 reminder (1 週間移行期間、auto invoke 観測 clean まで残す)

### 原則 (絶対遵守)

- **1 ticket = 1 PR = 1 worktree branch**
- **main / master への直接 commit / push 禁止** (PR 経由のみ)
- **Claude が PR 起票、user が PR merge 直接** (Claude classifier reject 経路、`gh pr merge` 不可)
- branch / commit / PR は **append-only** (rebase 最小限)

### PR 起票時必須 (skill invoke 必須 trigger)

- **`Skill(skill="branch-pr-workflow")` を `gh pr create` 前に必ず invoke**
- Skill body で branch 命名 convention / PR title format / Codex review baseline 確認手順を確認
- `.claude/scripts/codex_pr_full_review.sh <PR>` で baseline 内容確認必須 (`feedback_codex_pr_review_baseline_check.md` 教訓)

### user 手元作業の代理処理

- uncommitted / staged / untracked / 6 state 全部を漏れなく transfer
- 詳細は skill body の §user-handoff 参照
- secret / sensitive filename / 100 file 超 untracked は **user 確認なしに add しない**

### Codex auto-review 確認義務

- 3 endpoint (`pulls/N/comments` + `issues/N/comments` + `reviews`) × paginated × Codex bot filter
- baseline 内容確認必須 (delta +0 を真の 0 件と誤判定しない、PR #42/#44/#47 で再発)
- 採否判定 3 分類 (adopt / reject / defer)

詳細手順は **`.claude/skills/branch-pr-workflow/SKILL.md`** を参照。本 L1 reminder は 1 週間 auto invoke 観測 clean 達成後に削除予定 (skill description で auto invoke が確実に発動することを観測完了後)。

