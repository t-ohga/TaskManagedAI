# task-08 SP-009-5 Decision Packet Self-Review

## Round 1 - Structural Review

| finding | severity | decision | result |
|---|---:|---|---|
| `stale_after_event_seq` was present in the DB model but absent from Approval Detail API/frontend schema. | HIGH | adopt | Added it as a read-only response field; no migration was needed. |
| `/approvals/[id]` already displayed hash fields but mixed them into generic evidence copy. | MEDIUM | adopt | Split a dedicated Decision packet panel with field-level labels. |
| Batch C could drift into `request_revision` or notification triage. | HIGH | adopt | Kept the PR to read-only detail/API contract visibility only. |

## Round 2 - Adversarial Review

| finding | severity | decision | result |
|---|---:|---|---|
| A malformed or legacy row could put raw provider request text into `provider_request_fingerprint` and the Server Component would render it. | HIGH | adopt | Hash-like UI fields render only lowercase SHA-256 hex; malformed values are replaced with a non-rendered marker. |
| Adding `stale_after_event_seq` could imply a new stale-invalidation state machine. | MEDIUM | adopt | The field is display-only; no status transition or invalidation logic changed. |
| Backend tests could pass only with DB integration skipped. | MEDIUM | adopt | Added a no-DB Pydantic contract test plus the existing DB-backed route test. |
| Frontend could fail hard during additive rollout if it talks to an older backend lacking `stale_after_event_seq`. | MEDIUM | adopt | Frontend schema treats the missing field as `null` while current backend still returns it. |

## Checklist

- [x] server-owned boundary preserved: UI reads existing API output only.
- [x] no raw payload/provider request value is rendered by the UI for hash fields.
- [x] no migration added.
- [x] no approval mutation added.
- [x] API contract change is additive and tested.

## Local Verification

- `uv run ruff check backend/app/api/approval_inbox.py tests/api/test_approval_inbox.py` passed.
- `uv run mypy backend/app/api/approval_inbox.py` passed.
- `uv run pytest tests/api/test_approval_inbox.py -q` returned `2 passed, 11 skipped`; skipped cases are DB-gated integration tests.
- `corepack pnpm@10.18.0 --dir frontend exec vitest run __tests__/approval-detail.test.tsx __tests__/lib/api/approvals.test.ts` passed.
- `corepack pnpm@10.18.0 --dir frontend exec tsc --noEmit` passed.
- touched-file eslint, full frontend Vitest (`31 files / 113 tests`), and full frontend lint passed.
- Browser smoke on desktop and mobile passed against the current worktree API/frontend with `consoleErrors=[]`, `pageErrors=[]`, and no horizontal overflow. Temporary DB fixture was deleted after the check.
