# task-01: Sequence H Residual Verification

## scope

前回 handoff の residual closure を再検証し、SP-015 実装前に品質を固定する。
この task は原則 docs / review artifact のみで、コード修正は finding が出た時だけ行う。

## inputs

- `docs/codex-handoff/2026-05-22-3day-autonomous/COMPLETION_REPORT.md`
- `docs/codex-handoff/2026-05-22-3day-autonomous/03-claude-verification-checklist.md`
- `docs/codex-handoff/2026-05-22-3day-autonomous/completion/*.md`
- PR #145-#171
- PR #172
- `.claude/scripts/codex_pr_full_review.sh`

## required review

### Round 1: closeout structure

- [ ] task 8 / 8 completion artifacts exist.
- [ ] PR #145-#171 merge list matches completion report.
- [ ] PR #171 maps to all listed residual comments.
- [ ] PR #172 closeout docs exist.
- [ ] open PR list is empty or explained.

### Round 2: adversarial residual

- [ ] server-owned-boundary regression not introduced.
- [ ] event/source enum mismatch not introduced.
- [ ] token leakage not introduced.
- [ ] terminal mutation / script hardening fixes do not hide failures.
- [ ] migration verification debt is correctly classified as infrastructure debt.
- [ ] cascade pattern did not create follow-up regressions.

## verification

Preferred commands:

```bash
gh pr list --repo t-ohga/TaskManagedAI --state open --json number,title
gh pr view 172 --repo t-ohga/TaskManagedAI --json state,mergedAt,mergeCommit
.claude/scripts/codex_pr_full_review.sh 171
.claude/scripts/codex_pr_full_review.sh 172
```

If GitHub Actions are failing only because of quota, record that separately.

## outputs

- `reviews/task-01-self-plan-review.md`
- `completion/task-01-completed.md`

## DoD checklist

- [ ] all prior residual classes classified.
- [ ] any new finding is adopt / reject / defer.
- [ ] unresolved CRITICAL = 0.
- [ ] unresolved HIGH = 0 preferred. If HIGH remains, task-02 cannot start.
- [ ] next action is explicitly either task-02 READY or STOPPED.
