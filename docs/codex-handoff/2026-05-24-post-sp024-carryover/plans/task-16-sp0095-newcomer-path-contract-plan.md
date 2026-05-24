# SP-009-5 Batch F Newcomer Path Contract Plan

## Decision

Implement the Newcomer Path as a safe first-use route that starts with read-only diagnosis and an explainable dry-run plan. It must not start a mutating AgentRun, write to a repository, open a PR, resolve a secret, call a provider, merge, or deploy during the first-run checklist.

The first implementation batch must be UI-only and read-only. API, schema, runtime, and CLI behavior follow only after their contracts are explicit.

## Source Trace

| source | requirement | plan mapping |
|---|---|---|
| DI-28 | first-run setup, task intake, plan review, run observation, post-run review, CLI onboarding | F1-F5 split |
| A-UX2-02 | happy path from setup to dry-run plan; block mutating run without understanding repo/policy/action_class | F1 read-only checklist + F2 dry-run gate |
| SP-009 Q-E.5 / D-006.1 | Newcomer Path is P0.1, not SP-009 must_ship | SP-009-5 Batch F only |
| SP-009-5 Batch F | Newcomer Path / advanced approval refinements | this contract plan |
| ADR-00015 / docs/cli/README.md | CLI canonical is `tm`; `tmai` is fallback only | F4 uses `tm` |
| ADR-00025 | L0 default, human-required actions, server-owned policy profile | F1/F2 deny mutating first run |

## User State Model

Use the DI-28 state language as a UI progression model, not as a persisted enum in F1:

```text
not_started
  -> setup_checked
  -> guided_task_ready
  -> dry_run_reviewed
  -> first_decision_done
```

F1 derives visible progress from existing backend/session/settings data and local UI completion only. Persisted onboarding state requires a separate API/schema plan because it would add DB state and possible multi-user semantics.

## F1 Read-only Route

Target route:

```text
/onboarding
```

F1 can use existing surfaces and APIs only:

- current project/session context from the same source as `/settings`
- autonomy level and server-owned policy profile display from project settings
- provider/policy/secret boundary explanations from existing settings components
- links to `/today`, `/timeline`, `/approvals`, `/runs`, `/notifications`, `/settings`
- static guided-task choices that do not submit to the backend

F1 must not:

- POST to a new backend route
- create a ticket, AgentRun, approval, notification, audit event, repo operation, or provider call
- show raw secrets, raw provider payloads, raw audit payloads, raw logs, or capability tokens
- imply that setup is complete when backend state cannot prove it

F1 acceptance:

- `/onboarding` renders when logged in.
- Empty/error state keeps the operator in read-only mode.
- The primary action leads to a safe next step such as reviewing settings or a dry-run contract placeholder, not mutation.
- Browser smoke verifies desktop and mobile layout.
- Vitest or component tests verify the three DI-28 starter choices: research only, plan only, Draft PR with approval required.

## F2 Guided Intake Dry-run Contract

F2 is an API/schema-gated batch, not part of F1.

Planned request shape:

```json
{
  "purpose": "string",
  "target_repo_ref": "string",
  "expected_artifact": "string",
  "allowed_action_class": "read_only|task_write|repo_write|pr_open",
  "budget_cap": "string",
  "due_at": "iso8601|null",
  "reviewer_actor_id": "uuid|null",
  "starter_mode": "research_only|plan_only|draft_pr_requires_approval"
}
```

Planned response shape:

```json
{
  "dry_run_plan": {
    "action_class": "read_only",
    "risk_level": "low",
    "approval_required": true,
    "estimated_cost": "string",
    "rollback_plan": "string",
    "test_plan": ["string"],
    "blocked_reasons": ["string"]
  }
}
```

Contract rules:

- `starter_mode=research_only` and `starter_mode=plan_only` must produce no mutating run.
- `starter_mode=draft_pr_requires_approval` can produce a plan that mentions `pr_open`, but cannot create a PR or start execution.
- `allowed_action_class` is a requested upper bound, not an effective policy decision. The server resolves effective action class and approval requirement.
- `policy_profile` remains server-owned and cannot be supplied.
- The response must not include raw prompt, raw provider payload, raw token, raw secret, capability token, or raw logs.

F2 requires:

- ADR-00003 API contract note.
- Backend schema validation tests.
- Policy/autonomy negative tests for every mutating action class that should remain approval-gated.
- No DB persistence unless a separate storage decision is accepted.

## F3 Plan Review Surface

F3 may render the F2 dry-run plan with:

- action class
- risk level
- approval requirement
- cost cap and estimate
- rollback plan
- test plan
- blocked reasons
- links to relevant evidence and settings

Allowed actions:

- ask why
- request revision
- approve the plan for a future approved execution path only if backend support exists

F3 must not wire approve to an implicit AgentRun start unless the backend contract creates an approval record and runtime handoff explicitly requires human decision.

## F4 CLI Onboarding

Use `tm`, not `tmai`.

Planned CLI entry points are documentation/test candidates until SP-016 implementation accepts them:

```text
tm context show
tm doctor
tm ticket intake --guided
tm run plan --dry-run
```

CLI invariants:

- ambiguous or unresolved context plus mutating command fails closed
- non-interactive mutating dry-run cannot silently become real execution
- `secret_access`, `merge`, `deploy`, and `provider_call` always require human approval
- raw credentials are never stored in CLI output, logs, profile files, audit payloads, or API payloads

## F5 Closeout

Close Batch F only after:

- route parity docs mention `/onboarding`
- SP-009-5 Review lists F1-F4 verification evidence
- frontend route smoke and component tests pass
- API/schema tests pass if F2/F3 introduced backend contracts
- CLI help/contract tests pass if F4 introduced commands
- GitHub inline comments and `codex_pr_full_review.sh` are clean

## Rollback

- F1 rollback: remove `/onboarding` link and route; existing SP-009-5 surfaces remain unaffected.
- F2 rollback: disable dry-run endpoint before removing schema; preserve audit/evidence rows if any were added in later batches.
- F3 rollback: remove plan-review actions first, then backend contract if no persisted rows exist.
- F4 rollback: remove CLI help/entry point and keep `tm` existing commands unaffected.

## Open Questions For Implementation Batches

These do not block the planning PR:

- Whether F2 dry-run plans should be persisted for audit history or kept response-only.
- Whether `/onboarding` should be linked in global navigation immediately or exposed through `/settings` until F1 proves useful.
- Whether starter choices should map to existing ticket creation after the first safe dry-run or remain a separate intake object.
