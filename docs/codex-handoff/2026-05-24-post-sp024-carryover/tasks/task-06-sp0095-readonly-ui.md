# task-06: SP-009-5 Batch A Read-only UI

## Purpose

Implement the first SP-009-5 batch: a read-only Today/Inbox control plane and minimal KPI strip using existing backend APIs only.

## Scope

- Add `/today` under the admin shell.
- Use existing `tickets`, `agent_runs`, `approvals`, `eval/kpi-rollup`, and current project API clients.
- Add navigation and test coverage for the new route.
- Keep queued AgentRuns in Inbox and in-progress AgentRuns in Today to avoid duplicate lane rows.

## Non-Goals

- No DB migration.
- No new API route.
- No notification triage lifecycle.
- No approval `request_revision` state.
- No mutation controls.

## Verification

```bash
corepack pnpm@10.18.0 --dir frontend exec vitest run __tests__/today-control-plane.test.tsx __tests__/navigation.test.tsx
corepack pnpm@10.18.0 --dir frontend exec tsc --noEmit
corepack pnpm@10.18.0 --dir frontend exec eslint 'app/(admin)/today/page.tsx' components/navigation.tsx __tests__/today-control-plane.test.tsx __tests__/navigation.test.tsx tests/e2e/sprint9-pages.spec.ts --max-warnings=0
corepack pnpm@10.18.0 --dir frontend test
corepack pnpm@10.18.0 --dir frontend lint
git diff --check
```

## Browser Check

Use a local Next server on an unused port when the shared Docker compose already owns `127.0.0.1:3900` / `:8000`.

```bash
INTERNAL_API_URL=http://127.0.0.1:8000 \
TASKMANAGEDAI_INTERNAL_API_URL=http://127.0.0.1:8000 \
DEV_LOGIN_COOKIE_SECRET=local-dev-cookie-secret-32bytes-min \
TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET=local-dev-cookie-secret-32bytes-min \
DEV_LOGIN_TOKEN=local-dev-login-token-for-mac-smoke \
TASKMANAGEDAI_DEV_LOGIN_TOKEN=local-dev-login-token-for-mac-smoke \
corepack pnpm@10.18.0 --dir frontend exec next dev --hostname 127.0.0.1 --port 3300
```
