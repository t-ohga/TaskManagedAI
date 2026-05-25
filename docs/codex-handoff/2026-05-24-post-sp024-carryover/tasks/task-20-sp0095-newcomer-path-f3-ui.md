# task-20 SP-009-5 Batch F3 Newcomer Path Plan-review UI

## Scope

Render the F2b `POST /api/v1/onboarding/dry_run_plan` response on `/onboarding` as a reviewable plan.

F3 is frontend/client API wiring only. It may submit a dry-run request and render the deterministic response, but it must not persist onboarding state or start an execution path.

## Boundary

- Add a frontend API schema/client for `/api/v1/onboarding/dry_run_plan`.
- Add a server action that validates form input and calls the dry-run endpoint.
- Render requested/effective action class, policy effect, approval requirement, risk level, cost estimate, rollback plan, test plan, blocked reasons, safe routes, and all-false `would_create` ledger.
- Provide non-mutating review affordances only, such as reason details and links to safe routes.
- Do not add approve/start execution, ticket creation, AgentRun creation, approval creation, notification/audit creation, repository operation, provider call, capability token, CLI command, merge, deploy, or persisted onboarding state.

## DoD

- [x] `/onboarding` includes a dry-run intake form.
- [x] Successful dry-run response renders the plan review surface.
- [x] API/schema mismatch and backend failures return sanitized UI errors.
- [x] No button/form can approve or start execution.
- [x] Component/action/API tests cover success, validation rejection, sanitized errors, and no approve/start controls.
- [x] Desktop/mobile smoke covers the dry-run plan review route.

## Verification

- passed: `corepack pnpm@10.18.0 --dir frontend exec tsc --noEmit`
- passed: targeted frontend ESLint for touched files
- passed: targeted Vitest for onboarding page/action/API tests
- passed: `uv run alembic upgrade head` against local dev DB (`0032_sp018_memory_records` -> `0036_sp0095_request_revision`)
- passed: `uv run python -m backend.app.seeds.runner` against local dev DB (`human:default` actor present)
- passed: backend auth + `POST /api/v1/onboarding/dry_run_plan` smoke on local worktree backend (`200`)
- passed: targeted browser smoke on desktop/mobile against worktree frontend/backend (`would_create=false`, `response-only`, `read_only`, no approve/start buttons, console error count 0)
- passed: `git diff --check`

## Residual

- F4 CLI onboarding parity remains pending.
- F5 closeout remains pending.
