# task-08 SP-009-5 Batch C Decision Packet Hash Visibility

## Scope

Implement SP-009-5 Batch C as a read-only Approval Detail enhancement.

## Plan

1. Confirm the current `ApprovalRequest` storage and Approval Detail API fields.
2. Add missing read-only `stale_after_event_seq` to the existing Approval Detail API contract.
3. Render a Decision packet panel on `/approvals/[id]` with:
   - `artifact_hash`
   - `diff_hash`
   - `policy_version`
   - `policy_pack_lock`
   - `provider_request_fingerprint`
   - `stale_after_event_seq`
4. Do not add a mutation, state transition, notification lifecycle, migration, or new route.
5. Treat non-SHA-256 hash-like values as non-renderable in the UI so raw artifact / diff / provider request text cannot appear in DOM from legacy or malformed rows.

## Boundary

- Allowed: additive API response field for an existing DB column, frontend schema update, read-only UI, tests, status docs.
- Not allowed: approval `request_revision`, notification triage lifecycle, policy editor, bulk actions, DB migration, raw provider request payload display.

## Verification

- [x] `uv run ruff check backend/app/api/approval_inbox.py tests/api/test_approval_inbox.py`
- [x] `uv run mypy backend/app/api/approval_inbox.py`
- [x] `uv run pytest tests/api/test_approval_inbox.py -q` (`2 passed, 11 skipped`; DB-backed route tests skip without `TASKMANAGEDAI_RUN_DB_TESTS=1`)
- [x] `corepack pnpm@10.18.0 --dir frontend exec vitest run __tests__/approval-detail.test.tsx __tests__/lib/api/approvals.test.ts`
- [x] `corepack pnpm@10.18.0 --dir frontend exec tsc --noEmit`
- [x] touched-file eslint
- [x] `corepack pnpm@10.18.0 --dir frontend test` (`31 passed / 113 tests`)
- [x] `corepack pnpm@10.18.0 --dir frontend lint`
- [x] desktop/mobile browser smoke for `/approvals/00000000-0000-4000-8000-000000009951` against current worktree API on 8001 and Next on 3300: decision packet values visible, `consoleErrors=[]`, `pageErrors=[]`, `horizontalOverflow=false`; smoke fixture removed afterward.

## DoD

- [x] `stale_after_event_seq` is exposed through Approval Detail API.
- [x] `/approvals/[id]` shows all available decision packet hash/snapshot fields.
- [x] The UI does not render malformed non-hash values for hash fields.
- [x] No mutation or DB schema change is introduced.
- [ ] Review/inline comments are checked after PR creation and all actionable findings are resolved.
