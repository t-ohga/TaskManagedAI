# task-13 SP-009-5 Batch E1 Request Revision DB/API

## Scope

Implement the Batch E1 backend contract for Approval `request_revision`.

This batch follows `plans/task-12-sp0095-request-revision-contract-plan.md` and keeps UI/revised-artifact handoff out of scope.

## Implemented

- Additive `approval_revision_requests` table.
- SQLAlchemy model and repository for revision request snapshots.
- `ApprovalRevisionRequestService` that:
  - accepts only `pending` approvals,
  - applies self-approval and delegated same-human guard,
  - raw-secret scans rationale before persistence,
  - atomically invalidates the old approval,
  - records revision request snapshot fields,
  - appends metadata-only audit and notification events.
- `POST /api/v1/approvals/{approval_id}/request_revision`.
- Backend API and schema introspection tests.

## Explicit Non-Scope

- No `revision_requested` value added to `approval_requests.status`.
- No AgentRunEvent enum value added.
- No frontend UI action.
- No revised artifact handoff / supersession update path.
- No public caller-supplied replacement approval id or hash fields.

## Verification

```text
uv run ruff check backend/app/db/models/approval_revision_request.py backend/app/db/models/__init__.py backend/app/repositories/approval_revision_request.py backend/app/services/policy/revision_request_service.py backend/app/services/policy/self_approval_guard.py backend/app/services/policy/__init__.py backend/app/services/notifications/approval_notifier.py backend/app/api/approval_inbox.py tests/api/test_approval_inbox.py tests/db/test_schema_introspection.py tests/policy/test_approval_decision_service.py tests/policy/test_self_approval_negative.py tests/policy/test_delegated_actor_negative.py tests/policy/test_approval_stale_invalidation.py tests/e2e/test_approval_flow_e2e.py migrations/versions/0036_sp0095_request_revision.py
uv run mypy backend/app/db/models/approval_revision_request.py backend/app/repositories/approval_revision_request.py backend/app/services/policy/revision_request_service.py backend/app/services/policy/self_approval_guard.py backend/app/services/notifications/approval_notifier.py backend/app/api/approval_inbox.py
TASKMANAGEDAI_DATABASE_URL=postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:55434/taskmanagedai_verify_sp0095_e1 TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/api/test_approval_inbox.py tests/policy/test_approval_decision_service.py tests/policy/test_self_approval_negative.py tests/policy/test_delegated_actor_negative.py tests/policy/test_approval_stale_invalidation.py -q
TASKMANAGEDAI_DATABASE_URL=postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:55434/taskmanagedai_verify_sp0095_e1 TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/db/test_schema_introspection.py -q
TASKMANAGEDAI_DATABASE_URL=postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:55434/taskmanagedai_verify_sp0095_e1 uv run alembic upgrade head
TASKMANAGEDAI_DATABASE_URL=postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:55434/taskmanagedai_verify_sp0095_e1 uv run alembic downgrade -1
TASKMANAGEDAI_DATABASE_URL=postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:55434/taskmanagedai_verify_sp0095_e1 uv run alembic upgrade head
TASKMANAGEDAI_DATABASE_URL=postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:55434/taskmanagedai_verify_sp0095_e1 uv run alembic current
```

`uv run alembic check` remains blocked by the existing `migrations/env.py` autogenerate metadata debt.
