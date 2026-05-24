# Verification and Review Checklist

## Before PR

- [ ] Confirm working tree is clean except intended files.
- [ ] Confirm branch is based on current remote `main` or document why a GitHub API branch was used.
- [ ] Run exact local gates for touched backend/frontend/docs files.
- [ ] Run `git diff --check`.
- [ ] Run Sprint Pack frontmatter hook for any edited Sprint Pack.
- [ ] Self-review the diff for security, API contract, DB migration, enum drift, and raw secret exposure.

## After PR Creation

- [ ] Wait for GitHub review activity.
- [ ] Query reviews, comments, and review threads through `gh api graphql`.
- [ ] Run `.claude/scripts/codex_pr_full_review.sh <PR>` and inspect the full output, not just the final count.
- [ ] Classify every finding as adopt, reject, or defer.
- [ ] Commit fixes for all adopted findings.
- [ ] Re-run local gates that cover the changed files.
- [ ] Re-check GitHub review threads after fixes.

## GitHub Actions Quota Handling

Actions may fail with zero steps because the monthly quota is exhausted. Treat that as infrastructure-only only when:

- the workflow jobs show no executed steps,
- local equivalent checks passed,
- the PR description names the quota limitation,
- no review thread remains unresolved.

## Admin Merge Gate

Merge only when:

- local verification is green,
- delayed inline review check is clean,
- `codex_pr_full_review.sh` has no adopted residual,
- Actions failure is quota/no-steps only,
- Sprint Pack / ADR docs are synchronized,
- the branch has no unrelated changes.

## Post-Merge

- [ ] Confirm PR merged.
- [ ] Delete remote branch when `gh pr merge --delete-branch` could not do it automatically.
- [ ] Confirm `gh pr list --state open` for this repo.
- [ ] Record PR number, merge commit, verification, review outcome, and deferred work in the relevant completion or Sprint Review section.
