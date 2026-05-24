# SP-009-5 Batch F2 Guided Intake Dry-run Contract Plan

## Decision

Implement F2 as a response-only deterministic dry-run API. Do not persist the intake or dry-run response in the first implementation.

The endpoint helps a newcomer understand the safest first action, but it must not start execution or create any workflow state. F2 is a contract and validation layer; F3 can render the returned plan, and a later runtime batch can decide whether a reviewed plan becomes an approval-backed execution.

## API Contract

Endpoint:

```text
POST /api/v1/onboarding/dry_run_plan
```

Request:

```python
class OnboardingDryRunPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: str = Field(min_length=1, max_length=4000)
    target_repo_ref: str | None = Field(default=None, max_length=500)
    expected_artifact: str = Field(min_length=1, max_length=1000)
    allowed_action_class: Literal[
        "read_only",
        "task_write",
        "repo_write",
        "pr_open",
    ]
    budget_cap: str | None = Field(default=None, max_length=100)
    due_at: datetime | None = None
    reviewer_actor_id: UUID | None = None
    starter_mode: Literal[
        "research_only",
        "plan_only",
        "draft_pr_requires_approval",
    ]
```

Rules:

- `policy_profile`, `tenant_id`, `project_id`, `actor_id`, `approval_id`, `run_id`, `repository_token`, and `provider_request` are not accepted request fields.
- `allowed_action_class` is a requested upper bound. The server resolves the effective action class.
- F2 only accepts up to `pr_open`; `secret_access`, `merge`, `deploy`, and `provider_call` are rejected at schema/service boundary for first-run intake.
- Raw-secret canaries in `purpose`, `target_repo_ref`, `expected_artifact`, or `budget_cap` are rejected before a response is built.
- `reviewer_actor_id` is advisory for later UI routing only. It is not a decider and does not create approval state in F2.

Response:

```python
class OnboardingDryRunPlanResponse(BaseModel):
    dry_run_plan: OnboardingDryRunPlan

class OnboardingDryRunPlan(BaseModel):
    starter_mode: Literal[
        "research_only",
        "plan_only",
        "draft_pr_requires_approval",
    ]
    requested_action_class: Literal["read_only", "task_write", "repo_write", "pr_open"]
    effective_action_class: Literal["read_only", "task_write", "repo_write", "pr_open"]
    policy_effect: Literal["allow", "deny", "require_approval"]
    approval_required: bool
    risk_level: Literal["low", "medium", "high"]
    estimated_cost: str
    rollback_plan: str
    test_plan: list[str]
    blocked_reasons: list[str]
    next_safe_routes: list[Literal["/settings", "/today", "/timeline", "/approvals", "/runs"]]
    would_create: OnboardingDryRunWouldCreate

class OnboardingDryRunWouldCreate(BaseModel):
    ticket: Literal[False]
    agent_run: Literal[False]
    approval: Literal[False]
    notification: Literal[False]
    audit_event: Literal[False]
    repository_operation: Literal[False]
    provider_call: Literal[False]
```

## Effective Action Rules

| starter mode | requested upper bound | effective action | policy behavior |
|---|---|---|---|
| `research_only` | any accepted value | `read_only` | `allow`, `approval_required=false` |
| `plan_only` | any accepted value | `read_only` | `allow`, `approval_required=false` |
| `draft_pr_requires_approval` | `read_only` | `read_only` | `allow`, blocked reason explains upper bound |
| `draft_pr_requires_approval` | `task_write` / `repo_write` | same as upper bound | resolve through autonomy policy with runtime disabled |
| `draft_pr_requires_approval` | `pr_open` | `pr_open` | resolve through autonomy policy with runtime disabled; expected result is `require_approval` or `deny` |

`read_only` is a dry-run-only sentinel and is not added to the canonical `ActionClass` domain enum in F2. Mutating action classes continue to use `backend.app.domain.policy.action_class.ActionClass`.

## Policy Boundary

- Server resolves the current tenant, actor, project, autonomy level, and policy profile from existing session/project context.
- Callers cannot submit `policy_profile`.
- Mutating effective action classes call the existing autonomy policy engine with `runtime_enabled=false`; this prevents first-run intake from silently becoming auto-execution.
- The dry-run plan may mention a future approval requirement, but F2 does not create `approval_requests`.
- The endpoint returns `Cache-Control: no-store` because the response can reflect tenant/project policy.

## No-Mutation Contract

F2 must not insert, update, or delete rows in:

- `tickets`
- `agent_runs`
- `approval_requests`
- `approval_revision_requests`
- `notification_events`
- `audit_events`

F2 also must not:

- call a provider
- open a PR
- resolve a SecretBroker secret
- run a CLI command
- create a capability token
- write repository files

## Backend Implementation Plan

Add:

- `backend/app/schemas/onboarding.py`
- `backend/app/services/onboarding/dry_run_plan.py`
- `backend/app/api/onboarding.py`
- router include in `backend/app/api/router.py`
- `tests/api/test_onboarding_dry_run_plan.py`
- `tests/services/test_onboarding_dry_run_plan_service.py`

The service should be deterministic. It can produce templated rollback/test-plan strings from validated request fields and policy decisions, but it must not call an LLM.

## Test Plan

Backend tests:

- schema rejects extra fields including `policy_profile`, `tenant_id`, `project_id`, `actor_id`, `approval_id`, `run_id`, and `provider_request`
- `research_only` and `plan_only` always return effective `read_only`, no approval, and all `would_create` fields false
- `draft_pr_requires_approval` with `pr_open` returns `approval_required=true` or `policy_effect=deny`, never `allow` when runtime is disabled
- `secret_access`, `merge`, `deploy`, and `provider_call` are rejected for `allowed_action_class`
- raw-secret canary in each text field is rejected before response construction
- no-mutation regression counts stay unchanged for tickets, agent runs, approvals, approval revisions, notifications, and audit events
- response does not include raw provider payload, raw token, raw secret, capability token, raw logs, or stack detail keys

Local verification for F2b:

- `uv run ruff check backend/app/api/onboarding.py backend/app/schemas/onboarding.py backend/app/services/onboarding/dry_run_plan.py tests/api/test_onboarding_dry_run_plan.py tests/services/test_onboarding_dry_run_plan_service.py`
- `PYTHONPATH=cli uv run mypy backend/app/api/onboarding.py backend/app/schemas/onboarding.py backend/app/services/onboarding/dry_run_plan.py`
- `uv run pytest tests/api/test_onboarding_dry_run_plan.py tests/services/test_onboarding_dry_run_plan_service.py -q`
- no migration commands are required unless a later PR changes the response-only decision

Frontend handoff for F3:

- Add a form to `/onboarding` only after F2b is merged.
- Render the dry-run response as reviewable output.
- Keep the submit action named as dry-run only.
- Do not expose an approve/start execution button until an approval-backed backend contract exists.

## Rollback

1. Remove `/api/v1/onboarding/dry_run_plan` route and router include.
2. Remove F2 schemas/services/tests.
3. Keep F1 `/onboarding` read-only route intact.
4. No DB rollback is needed if F2b keeps the response-only decision.

## Open Decisions

- Whether a later F5 closeout should persist dry-run plans for audit history after the first implementation proves useful.
- Whether `reviewer_actor_id` should be removed from F2b if no UI routing consumes it.
- Whether `target_repo_ref` should be normalized against a repository registry in a later batch.
