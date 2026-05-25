# task-19 SP-009-5 Batch F2b API Self Review

## Scope Reviewed

- `POST /api/v1/onboarding/dry_run_plan`
- Pydantic schema boundary
- deterministic response-only service
- API unit tests and service regression tests
- SP-009-5 / handoff / ADR status synchronization

## Findings

| finding | severity | decision | resolution |
|---|---|---|---|
| A first-run `draft_pr_requires_approval` request could become auto-execution if runtime-enabled policy resolution is reused. | HIGH | adopt | Mutating effective classes call the autonomy policy engine with `runtime_enabled=False`; a defensive allow downgrade returns `require_approval`. |
| Adding `read_only` to canonical `ActionClass` would drift the 7-value policy taxonomy. | HIGH | adopt | `read_only` is only a request/response sentinel in onboarding schemas; mutating classes are cast to existing `ActionClass` only after the read-only branch. |
| Caller-supplied ownership fields could bypass server-owned policy/project context. | HIGH | adopt | Request schema uses `extra="forbid"` and tests reject `policy_profile`, tenant/project/actor IDs, approval/run IDs, and provider payload fields. |
| Raw first-run free text can include secrets. | HIGH | adopt | Route scans all text input fields with the shared raw-secret scanner before project lookup, then service re-scans before response construction; API returns sanitized 400 details. |
| Response could leak raw user intent or runtime surfaces. | MEDIUM | adopt | Response is deterministic and excludes raw prompt echo, provider payloads, raw tokens, capability tokens, stack detail keys, and `policy_profile`; tests assert absence. |
| Default FastAPI 422 errors can echo invalid `input` values for rejected extra fields. | HIGH | adopt | Endpoint now validates the raw body inside the route and returns sanitized schema errors without echoing rejected field values. |

## Invariant Checklist

- [x] No DB migration.
- [x] No ticket, AgentRun, approval, approval revision, notification, audit, repository operation, provider call, capability token, CLI command, merge, deploy, or persisted onboarding state.
- [x] Server resolves tenant/actor/project context from dependencies and current project lookup.
- [x] Mutating action candidates are approval-gated or denied; never executable from the dry-run response.
- [x] All `would_create` booleans are false.
- [x] `Cache-Control: no-store` is set on success.
- [x] Raw-secret canary rejection is tested for `purpose`, `target_repo_ref`, `expected_artifact`, and `budget_cap`.
- [x] Raw-secret canary rejection happens before current project lookup.

## Verification

- passed: `uv run ruff check backend/app/api/onboarding.py backend/app/schemas/onboarding.py backend/app/services/onboarding/dry_run_plan.py tests/api/test_onboarding_dry_run_plan.py tests/services/test_onboarding_dry_run_plan_service.py`
- passed: `PYTHONPATH=cli uv run mypy backend/app/api/onboarding.py backend/app/schemas/onboarding.py backend/app/services/onboarding/dry_run_plan.py`
- passed: `uv run pytest tests/api/test_onboarding_dry_run_plan.py tests/services/test_onboarding_dry_run_plan_service.py tests/policy/test_autonomy_policy_engine.py -q`
- passed: YAML safe-load for SP-009-5 and ADR-00003.
- passed: sprint frontmatter hook for SP-009-5.
- passed: `git diff --check`.

## Residual

- PR review baseline and delayed inline review polling remain pending until this local branch can be pushed.
- F3 plan-review UI remains pending.
- F4 CLI onboarding parity was closed by task-21.
