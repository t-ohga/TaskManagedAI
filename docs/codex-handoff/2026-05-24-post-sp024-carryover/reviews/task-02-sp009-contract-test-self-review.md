# task-02 SP-009 Contract/Test Cleanup Self-Impl-Review

Date: 2026-05-24

## Scope

- Update stale Sprint 9 Playwright assertions to current backend-wired pages.
- Add frontend fail-closed raw payload field rejection for AuditEvent / AgentRunEvent / ContextSnapshot responses.
- Add frontend/backend enum drift contract for closed backend enums.

## Findings

1. HIGH: E2E was reusing an existing Docker service on ports 3000/8000, so the first local run hit a different UI and failed at login. Adopted fix: verified this worktree on separate ports 3109/8109 and documented the run command in verification notes.
2. MEDIUM: non-UUID detail routes render the app 404 page with HTTP 200 under the authenticated admin layout. Adopted fix: assert the visible 404 heading instead of response status.
3. MEDIUM: frontend AuditEvent event_type cannot be exact-set compared yet because backend audit_events is open text with no canonical registry. Adopted fix: contract test keeps response schema open and documents replacement condition.
4. MEDIUM: backend redaction is not enough to prevent a future raw payload field from reaching Server Components. Adopted fix: `NoRawPayloadFieldsSchema` rejects known raw payload/value fields before rendering.
5. LOW: direct E2E specs still hard-coded the old login button label. Adopted fix: shared helper and direct specs accept current Japanese UI plus observed `Sign in` compatibility.

## Verification

- `corepack pnpm@10.18.0 --dir frontend exec tsc --noEmit`
- `corepack pnpm@10.18.0 --dir frontend exec eslint lib/api/redaction.ts lib/api/agent-runs.ts lib/api/audit.ts __tests__/lib/api/agent-runs.test.ts __tests__/lib/api/audit.test.ts tests/e2e/_helpers/login.ts tests/e2e/admin-shell.spec.ts tests/e2e/login.spec.ts tests/e2e/approval-inbox.spec.ts tests/e2e/sprint9-pages.spec.ts --max-warnings=0`
- `corepack pnpm@10.18.0 --dir frontend exec vitest run __tests__/lib/api/agent-runs.test.ts __tests__/lib/api/audit.test.ts __tests__/lib/api/tickets.test.ts __tests__/agent-runs-i18n.test.tsx __tests__/audit-log-i18n.test.tsx __tests__/login-form.test.tsx`
- `uv run pytest tests/contracts/test_frontend_backend_enum_drift.py -q`
- `uv run ruff check tests/contracts/test_frontend_backend_enum_drift.py`
- `PYTHONPATH=cli uv run mypy tests/contracts/test_frontend_backend_enum_drift.py`
- `PLAYWRIGHT_BASE_URL=http://127.0.0.1:3109 PLAYWRIGHT_BACKEND_URL=http://127.0.0.1:8109 ... corepack pnpm@10.18.0 --dir frontend exec playwright test tests/e2e/sprint9-pages.spec.ts --project=chromium`
- `git diff --check`

## Readiness Gate

- CRITICAL: 0
- HIGH: 0
- Open finding: AuditEvent exact-set remains intentionally deferred until backend registry exists.
