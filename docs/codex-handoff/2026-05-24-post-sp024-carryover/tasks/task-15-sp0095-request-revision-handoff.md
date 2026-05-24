# task-15 SP-009-5 Batch E3 Request Revision Handoff

## Scope

Implement the internal handoff that turns an open `approval_revision_requests` row into a fresh replacement approval.

This is not a public API batch. The goal is to wire the server-owned runtime/service path that E3 needs before any future UI or AgentRun resume automation can consume it.

## Boundary

- Use the existing `superseded_by_approval_request_id` column from Batch E1.
- Create a new pending approval row instead of reusing the invalidated approval.
- Require fresh revised artifact/diff/provider fingerprint and advancing `stale_after_event_seq`.
- Notify the revision-requesting human as the reviewer of the replacement approval.
- Do not add `revision_requested` status, AgentRunEvent enum values, public replacement-approval API, or caller-supplied replacement approval ids.

## DoD

- [x] Open revision request can be superseded exactly once.
- [x] Replacement approval is a new `pending` approval row with fresh decision-packet fields.
- [x] Original approval remains `invalidated`.
- [x] Stale artifact hash reuse is rejected before creating a replacement approval.
- [x] Non-advancing `stale_after_event_seq` is rejected.
- [x] Existing `create_pending_approval` can persist `stale_after_event_seq` for replacement approvals.

## Verification

- `uv run ruff check backend/app/repositories/approval_request.py backend/app/repositories/approval_revision_request.py backend/app/services/policy/revision_request_service.py backend/app/services/policy/__init__.py tests/api/test_approval_inbox.py`
- `uv run mypy backend/app/repositories/approval_request.py backend/app/repositories/approval_revision_request.py backend/app/services/policy/revision_request_service.py backend/app/services/policy/__init__.py backend/app/api/approval_inbox.py`
- `TASKMANAGEDAI_DATABASE_URL=postgresql+asyncpg://.../taskmanagedai_verify_sp0095_e3 TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/api/test_approval_inbox.py -q`
- `git diff --check`

## Residual

- No AgentRun resume automation was added. A future runtime batch can call this service after revised artifact validation.
- No public endpoint was added for replacement approval creation.
