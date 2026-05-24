# task-15 SP-009-5 Batch E3 Self Review

## Scope Reviewed

- `ApprovalRevisionRequestService.create_revised_approval`.
- `ApprovalRevisionRequestRepository.supersede_open_revision_request`.
- `ApprovalRequestRepository.create_pending_approval` `stale_after_event_seq` persistence.
- Approval Inbox DB/API regression tests that exercise E3 handoff.

## Findings

| finding | severity | decision | resolution |
|---|---|---|---|
| Replacement approval creation initially could not preserve `stale_after_event_seq` because `create_pending_approval` lacked the parameter. | HIGH | adopt | Added an optional `stale_after_event_seq` parameter and asserted persistence in E3 tests. |
| Supersession through generic `update` would not prove the revision request was still open at update time. | HIGH | adopt | Added `supersede_open_revision_request` with `superseded_by_approval_request_id is null` in the update predicate. |
| Freshness could be interpreted as "new approval id only" while reusing stale hashes. | HIGH | adopt | Added service validation and negative tests for stale `artifact_hash` and non-advancing `stale_after_event_seq`. |
| Whitespace-padded revised hashes could bypass equality checks if validation and persistence used different normalized values. | MEDIUM | adopt | Normalize revised artifact/diff/provider/policy values before validation and persistence; test stores trimmed values. |
| First DB pytest attempt used the wrong local password; second attempt used a dedicated temporary DB and passed. | LOW | adopt | Created `taskmanagedai_verify_sp0095_e3`, ran tests there, and documented the credential/setup issue. |

## Invariant Checklist

- [x] No approval status enum expansion.
- [x] No AgentRunEvent enum expansion.
- [x] Original approval stays `invalidated`.
- [x] Replacement approval is a new row.
- [x] Public callers cannot provide replacement approval ids.
- [x] Open revision request is closed by server-owned supersession wiring.
- [x] Fresh revised decision packet is enforced before the DB write.
- [x] Notification creation stays inside existing `create_pending_approval` transaction path.

## Verification

- passed: `uv run ruff check backend/app/repositories/approval_request.py backend/app/repositories/approval_revision_request.py backend/app/services/policy/revision_request_service.py tests/api/test_approval_inbox.py`
- passed: `uv run mypy backend/app/repositories/approval_request.py backend/app/repositories/approval_revision_request.py backend/app/services/policy/revision_request_service.py backend/app/services/policy/__init__.py backend/app/api/approval_inbox.py`
- passed: `TASKMANAGEDAI_DATABASE_URL=postgresql+asyncpg://.../taskmanagedai_verify_sp0095_e3 TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/api/test_approval_inbox.py -q` (`21 passed`)
- note: the first DB pytest attempt with the default `taskmanagedai/taskmanagedai` credential failed before tests with `InvalidPasswordError`; this was an environment credential mismatch.

## Residual

- AgentRun resume automation remains a future runtime batch.
- Public replacement approval API remains intentionally absent.
