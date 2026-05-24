# task-17 SP-009-5 Batch F1 Newcomer Path UI

## Scope

Implement the first Newcomer Path UI batch from `plans/task-16-sp0095-newcomer-path-contract-plan.md`.

F1 is read-only. It introduces `/onboarding` and safe navigation only; it does not add backend API routes, schema, migrations, CLI commands, tickets, approvals, AgentRuns, repository writes, provider calls, or persisted onboarding state.

## Boundary

- Use existing session/project APIs only: `getCurrentProject()` and `listCurrentProjects()`.
- Render the DI-28 starter choices as static cards, not as a form or submit action.
- Keep the first-run path useful when project context cannot be read: show the sanitized project-context error, safe starter choices, safe links, and `tm` CLI reminders.
- Use `tm`, not stale `tmai`.
- Do not expose raw secrets, raw provider payloads, raw logs, capability tokens, or backend stack details.

## DoD

- [x] `/onboarding` renders under the admin shell.
- [x] Global navigation links to `/onboarding`.
- [x] Starter choices are visible: research only, plan only, Draft PR with approval required.
- [x] No button/form starts mutation from the page.
- [x] Error state preserves read-only choices and safe links.
- [x] Desktop and mobile Playwright smoke passes for the new page.

## Verification

- `corepack pnpm@10.18.0 --dir frontend exec tsc --noEmit`
- `corepack pnpm@10.18.0 --dir frontend exec eslint 'app/(admin)/onboarding/page.tsx' components/navigation.tsx __tests__/onboarding-page.test.tsx __tests__/navigation.test.tsx tests/e2e/sprint9-pages.spec.ts tests/e2e/a11y.spec.ts tests/e2e/responsive.spec.ts --max-warnings=0`
- `corepack pnpm@10.18.0 --dir frontend exec vitest run __tests__/onboarding-page.test.tsx __tests__/navigation.test.tsx`
- `PLAYWRIGHT_BASE_URL=http://127.0.0.1:3100 ... corepack pnpm@10.18.0 --dir frontend exec playwright test tests/e2e/sprint9-pages.spec.ts --grep "newcomer" --project=chromium --project=mobile-chromium`
- `git diff --check`

## Residual

- F2 guided intake dry-run API/schema contract remains unimplemented.
- F3 plan-review actions remain unimplemented.
- F4 CLI onboarding commands remain documentation candidates until SP-016 parity work accepts them.
