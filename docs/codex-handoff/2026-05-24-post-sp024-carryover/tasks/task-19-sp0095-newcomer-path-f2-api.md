# task-19 SP-009-5 Batch F2b Guided Intake Dry-run Backend API

## Scope

Implement the response-only Newcomer Path guided intake dry-run API from `plans/task-18-sp0095-newcomer-path-f2-contract-plan.md`.

F2b is backend contract work only. It validates first-run intent, resolves the effective action class server-side, and returns an explainable plan. It must not persist state or start execution.

## Boundary

- Add `POST /api/v1/onboarding/dry_run_plan`.
- Use Pydantic request/response schemas with `extra="forbid"`.
- Keep `read_only` as a dry-run-only sentinel; do not add it to the canonical backend `ActionClass`.
- Resolve mutating first-run candidates through the existing autonomy policy engine with `runtime_enabled=False`.
- Reject raw-secret canaries in all text input fields before response construction.
- Return `Cache-Control: no-store`.
- Do not create tickets, AgentRuns, approvals, approval revision requests, notifications, audit events, repository operations, provider calls, capability tokens, CLI commands, merge/deploy actions, or persisted onboarding state.

## DoD

- [x] Backend schemas exist for request, response, and all-false `would_create` ledger.
- [x] API route is wired into the main API router.
- [x] `research_only` and `plan_only` force effective `read_only`.
- [x] `draft_pr_requires_approval` with mutating upper bound uses runtime-disabled policy resolution.
- [x] Runtime-disabled `allow` cannot leak into an executable first-run result; it is fail-closed to `require_approval`.
- [x] Server-owned fields such as `policy_profile`, `tenant_id`, `project_id`, `actor_id`, `approval_id`, `run_id`, and `provider_request` are rejected.
- [x] `secret_access`, `merge`, `deploy`, and `provider_call` are rejected for first-run intake.
- [x] Raw-secret canaries are rejected with sanitized API error details.
- [x] Raw-secret canaries are rejected before current project lookup.
- [x] Schema validation errors are sanitized and do not echo rejected input values.
- [x] Response excludes raw prompt echo, provider payloads, raw tokens, capability tokens, raw secrets, raw logs, stack details, and `policy_profile`.
- [x] No DB migration is required.

## Verification

- `uv run ruff check backend/app/api/onboarding.py backend/app/schemas/onboarding.py backend/app/services/onboarding/dry_run_plan.py tests/api/test_onboarding_dry_run_plan.py tests/services/test_onboarding_dry_run_plan_service.py`
- `PYTHONPATH=cli uv run mypy backend/app/api/onboarding.py backend/app/schemas/onboarding.py backend/app/services/onboarding/dry_run_plan.py`
- `uv run pytest tests/api/test_onboarding_dry_run_plan.py tests/services/test_onboarding_dry_run_plan_service.py tests/policy/test_autonomy_policy_engine.py -q`
- YAML safe-load for SP-009-5 and ADR-00003
- sprint frontmatter hook for SP-009-5
- `git diff --check`

## Residual

- F3 must add the `/onboarding` plan-review surface and frontend client wiring without adding an approve/start execution shortcut.
- F4 must keep `tm` as the canonical CLI wording and fail closed for ambiguous mutating onboarding commands.
- F5 closeout must reconcile route parity, browser/Vitest/API contract evidence, and SP-009 residual status.
