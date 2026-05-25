# task-20 SP-009-5 Batch F3 UI Self Review

## Scope Reviewed

- `/onboarding` dry-run intake form.
- Frontend onboarding API schema/client.
- Server action validation and sanitized error handling.
- Dry-run plan review rendering.
- Vitest coverage for page, API client, server action, and plan rendering.

## Findings

| finding | severity | decision | resolution |
|---|---|---|---|
| F3 could accidentally add an approve/start execution path before backend approval/runtime handoff exists. | HIGH | adopt | UI renders only dry-run submission, reason details, and safe links; tests assert no approve/start controls. |
| Optional form fields submitted as `null` could fail frontend validation before reaching the backend. | MEDIUM | adopt | Optional string schema now maps `null` and blank strings to `undefined`. |
| Backend or validation failures could leak raw error details into UI. | HIGH | adopt | Server action returns fixed Japanese error messages and tests use a raw-secret-like rejection to confirm sanitization. |
| The F1 test assertion that no buttons exist became stale after F3. | MEDIUM | adopt | Assertion now permits the dry-run button and explicitly rejects approve/start labels. |
| Rendering the same action class for requested/effective fields made test queries ambiguous. | LOW | adopt | Test uses `getAllByText` for the expected duplicate value and keeps semantic assertions around labels/ledger. |
| Success-state copy did not include the explicit `response-only` invariant term. | MEDIUM | adopt | Success details now say `response-only deterministic response`; browser smoke asserts the term. |

## Invariant Checklist

- [x] No ticket, AgentRun, approval, approval revision, notification, audit, repository operation, provider call, capability token, CLI command, merge, deploy, or persisted onboarding state.
- [x] No approve/start execution button is rendered.
- [x] API schema rejects server-owned request fields.
- [x] Server action validates before API call.
- [x] Backend and unknown failures are sanitized in UI.
- [x] All `would_create` values are rendered as false in the tested plan review.

## Verification

- passed: `corepack pnpm@10.18.0 --dir frontend exec eslint 'app/(admin)/onboarding/page.tsx' 'app/(admin)/onboarding/actions.ts' 'app/(admin)/onboarding/_components/dry-run-plan-form.tsx' lib/api/onboarding.ts __tests__/onboarding-page.test.tsx __tests__/onboarding-dry-run-plan-form.test.tsx __tests__/onboarding-actions.test.ts __tests__/lib/api/onboarding.test.ts --max-warnings=0`
- passed: `corepack pnpm@10.18.0 --dir frontend exec tsc --noEmit`
- passed: `corepack pnpm@10.18.0 --dir frontend exec vitest run __tests__/onboarding-page.test.tsx __tests__/onboarding-dry-run-plan-form.test.tsx __tests__/onboarding-actions.test.ts __tests__/lib/api/onboarding.test.ts __tests__/navigation.test.tsx`
- passed: `uv run alembic upgrade head` against local dev DB, then `uv run python -m backend.app.seeds.runner`
- passed: backend auth + dry-run endpoint smoke (`/auth/dev-login`, `/api/v1/me/current_project`, `/api/v1/onboarding/dry_run_plan` all 200)
- passed: desktop/mobile browser smoke against worktree frontend/backend (`would_create=false`, `response-only`, `read_only`, no approve/start buttons, console error count 0)
- passed: `git diff --check`

## Residual

- F4 CLI onboarding parity remains pending.
- F5 closeout remains pending.
