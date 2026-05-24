# task-07: SP-009-5 Batch B Unified Timeline UI

## Purpose

Implement the second SP-009-5 read-only batch: a unified execution timeline using existing AgentRun, Audit, Approval, and KPI API clients.

## Scope

- Add `/timeline` under the admin shell.
- Merge AgentRunEvent, AuditEvent, and pending Approval rows by timestamp.
- Show KPI rollup as summary context.
- Hide sensitive payload key names and expose only safe keys plus hidden-key counts.

## Non-Goals

- No DB migration.
- No new API route.
- No raw payload values.
- No Budget API implementation.
- No notification triage lifecycle.
- No approval `request_revision` state.

## Verification

```bash
corepack pnpm@10.18.0 --dir frontend exec vitest run __tests__/timeline-page.test.tsx __tests__/navigation.test.tsx
corepack pnpm@10.18.0 --dir frontend exec tsc --noEmit
corepack pnpm@10.18.0 --dir frontend exec eslint 'app/(admin)/timeline/page.tsx' components/navigation.tsx __tests__/timeline-page.test.tsx __tests__/navigation.test.tsx tests/e2e/sprint9-pages.spec.ts --max-warnings=0
corepack pnpm@10.18.0 --dir frontend test
corepack pnpm@10.18.0 --dir frontend lint
git diff --check
```
