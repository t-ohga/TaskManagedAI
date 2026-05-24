# task-17 SP-009-5 Batch F1 Self Review

## Scope Reviewed

- `/onboarding` server component.
- Admin navigation addition.
- New Vitest coverage and Playwright route smoke.
- SP-009-5 / handoff / backlog status synchronization.

## Findings

| finding | severity | decision | resolution |
|---|---|---|---|
| Initial implementation hid all starter choices when project context was unavailable. | HIGH | adopt | Error state now keeps the `初回チェック` landmark, safe starter choices, safe links, and `tm` CLI reminders visible. |
| The first Playwright assertion required `初回チェック` to have role `region`, but the error fallback correctly uses `role=status`. | MEDIUM | adopt | E2E now locates the shared `aria-label` so both healthy and sanitized error states are covered. |
| A stale or missing local `.env.local` in the worktree can make browser smoke use the wrong dev login token. | LOW | adopt | Browser smoke reads the existing root repo `.env.local` without printing secret values. |
| The page could accidentally become a mutation entry point if starter choices were implemented as buttons. | HIGH | adopt | Starter choices are static cards; the page has no submit button and only links to read-only/safe existing pages. |

## Invariant Checklist

- [x] No backend API, schema, migration, CLI, ticket, approval, AgentRun, repo, provider, merge, or deploy mutation.
- [x] No persisted onboarding state.
- [x] No caller-supplied `policy_profile`.
- [x] No stale `tmai` canonical wording.
- [x] Raw secrets, provider payloads, logs, capability tokens, and backend stack details are not rendered.
- [x] Project-context failure remains read-only and actionable.

## Verification

- passed: `corepack pnpm@10.18.0 --dir frontend exec tsc --noEmit`
- passed: targeted frontend ESLint for touched files.
- passed: `corepack pnpm@10.18.0 --dir frontend exec vitest run __tests__/onboarding-page.test.tsx __tests__/navigation.test.tsx`
- passed: `corepack pnpm@10.18.0 --dir frontend exec vitest run`
- passed: desktop/mobile Playwright smoke for `/onboarding` on port 3100.
- passed: sprint frontmatter hook and YAML safe-load for SP-009-5.
- passed: handoff / sprint / backlog cross-reference check.
- passed: `git diff --check`.

## Residual

- F2 guided intake dry-run API/schema contract remains unimplemented.
- F3 plan-review surface remains unimplemented.
- F4 CLI onboarding implementation remains tied to SP-016 parity contract work.
