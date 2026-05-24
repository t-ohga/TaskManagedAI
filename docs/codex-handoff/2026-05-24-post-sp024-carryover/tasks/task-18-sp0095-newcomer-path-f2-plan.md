# task-18 SP-009-5 Batch F2 Guided Intake Dry-run Plan

## Scope

Plan the Newcomer Path guided intake dry-run API contract before code/schema work.

F2 is a high-risk API boundary because it accepts first-run task intent and returns an execution-shaped plan. The first implementation must stay response-only: no AgentRun, ticket, approval, notification, audit event, repository write, provider call, merge, deploy, or persisted onboarding state.

## Current State

- Batch F0 fixed the Newcomer Path split and safety invariants.
- Batch F1 added read-only `/onboarding`, safe starter cards, navigation, and browser smoke.
- Existing `ActionClass` excludes `read_only`; mutating classes are `task_write`, `repo_write`, `pr_open`, `secret_access`, `merge`, `deploy`, and `provider_call`.
- The autonomy policy engine already resolves server-owned `policy_profile` from caller-visible autonomy level.

## Planned Direction

Use a deterministic dry-run endpoint:

```text
POST /api/v1/onboarding/dry_run_plan
```

The endpoint validates intake input, rejects raw-secret canaries, resolves the effective action class server-side, and returns an explainable plan. It does not persist the plan in F2.

## Required ADR/API Gate

ADR-00003 must record the F2 API contract before implementation:

- request schema with `extra="forbid"`
- no caller-supplied `policy_profile`
- `allowed_action_class` is a requested upper bound only
- `starter_mode=research_only|plan_only` forces effective `read_only`
- `starter_mode=draft_pr_requires_approval` may resolve to `pr_open`, but only as a future approved execution candidate
- response excludes raw prompt, raw provider payload, raw token, raw secret, capability token, raw logs, and stack details

## Planned Implementation Split

| batch | scope | risk control |
|---|---|---|
| F2a | docs-only plan and ADR-00003 note | no code/schema/runtime |
| F2b | backend schema/service/API + tests | response-only; deterministic; no DB persistence |
| F3 | plan review UI for the dry-run response | no implicit AgentRun start |
| F4 | CLI onboarding parity notes/tests | `tm` canonical; mutating commands fail closed |

## Boundary

- Allowed in F2b: Pydantic schemas, deterministic service, API route, frontend client schema, backend tests.
- Not allowed in F2b: DB migration, persisted dry-run plans, ticket creation, AgentRun creation, approval creation, notification/audit creation, provider calls, repository operations, public runtime handoff, or CLI command implementation.

## DoD For Planning PR

- [x] ADR-00003 has a Newcomer Path dry-run intake extension note.
- [x] Endpoint, request, response, and server-owned policy boundaries are fixed.
- [x] Response-only/no-persistence decision is explicit.
- [x] Implementation and UI batches are separated.
- [x] Verification requirements include schema validation, policy negative tests, raw-secret rejection, and no-mutation regression tests.
