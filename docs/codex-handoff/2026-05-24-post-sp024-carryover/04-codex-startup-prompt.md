# Codex Startup Prompt

Use this prompt for the next autonomous run.

```text
You are continuing TaskManagedAI autonomous development after SP-024 completion.

Read these files in order:
1. docs/codex-handoff/2026-05-24-post-sp024-carryover/README.md
2. docs/codex-handoff/2026-05-24-post-sp024-carryover/00-current-state.md
3. docs/codex-handoff/2026-05-24-post-sp024-carryover/01-carryover-scope-gate.md
4. docs/codex-handoff/2026-05-24-post-sp024-carryover/02-task-priority-matrix.md
5. docs/codex-handoff/2026-05-24-post-sp024-carryover/03-verification-and-review-checklist.md
6. The task file you are implementing under docs/codex-handoff/2026-05-24-post-sp024-carryover/tasks/

Start with Newcomer Path F3 plan-review UI if the user asks to continue SP-009-5 Newcomer Path. Otherwise start with task-01 unless the user explicitly selects another task.

Important:
- Do not re-open SP-014 / SP-015 / SP-016 from stale candidate lists. Repository state marks them completed.
- Do not implement SP-008 / SP-009 / SP-007 carry-over code until the task-specific reconciliation marks the residual READY.
- For SP-009-5 Newcomer Path, read `plans/task-16-sp0095-newcomer-path-contract-plan.md` and `plans/task-18-sp0095-newcomer-path-f2-contract-plan.md` first. F1 read-only `/onboarding`, F2a planning, and F2b response-only backend API/schema work are implemented; F3 must render dry-run results without persisting state or starting execution.
- For code PRs, perform self-plan review, self-implementation review, local gates, GitHub inline review checks, codex_pr_full_review.sh baseline, adopted finding fixes, then admin merge only if all gates are clean.
- If GitHub Actions fail with zero steps because of monthly quota, document it and rely on local equivalent verification.
- If a DB migration is required, run upgrade head, downgrade -1, upgrade head, and current. Document the known alembic check target_metadata debt separately.

Proceed carefully and prefer small PRs.
```
