# task-22 SP-009-5 Batch F5 Closeout Self Review

## Scope Reviewed

- SP-009-5 Newcomer Path closeout docs/status.
- Handoff startup and task priority drift.
- Sprint Pack review and backlog completion state.
- F2 dry-run persistence decision.

## Findings

| finding | severity | decision | resolution |
|---|---|---|---|
| Marking the whole SP-009-5 Sprint Pack completed would overstate non-Newcomer residuals. | HIGH | adopt | Kept SP-009-5 as `partial_skeleton` while marking only `SP0095-UX-01` Newcomer Path completed. |
| F5 could be misread as permission to persist dry-run plans for audit history. | HIGH | adopt | Recorded the F5 decision to keep dry-run plans response-only and non-persistent until a separate storage plan exists. |
| Startup prompt still routed future autonomous work to F5 after F5 closeout. | MEDIUM | adopt | Updated startup prompt to begin with task-01 unless the user explicitly selects another task. |
| Route/API/CLI parity could drift across task docs, Sprint Pack, and backlog. | MEDIUM | adopt | Added task-22 parity matrix and synchronized SP-009-5 Review, P0 backlog, and task priority matrix. |

## Invariant Checklist

- [x] No new ticket, AgentRun, approval, notification, audit event, repository operation, provider call, SecretBroker resolution, capability token, merge, deploy, or persisted onboarding state is introduced.
- [x] `/onboarding` remains the route-level first-use surface.
- [x] `/api/v1/onboarding/dry_run_plan` remains response-only.
- [x] `tm` remains the canonical CLI spelling.
- [x] GitHub Actions quota failure remains documented as infrastructure/quota, not code failure.

## Verification

- passed: targeted frontend Vitest (`5 passed`, `9 tests`).
- passed: backend/API/CLI ruff and mypy (`32 source files`).
- passed: backend/API/CLI pytest (`67 passed`).
- passed: YAML safe-load, sprint frontmatter hook, `git diff --check`.
- pending after PR creation: `codex_pr_full_review.sh` and thread-aware GitHub comment polling.

## Residual

- SP-009 golden E2E, DOM secret scan, PayloadDataClass/future AuditEventType registry drift, Today/Inbox due display, and timeline budget-source gaps remain outside Newcomer Path closeout.
