# task-10 SP-009-5 Batch D1 Notification Triage DB/API

## Scope

Implement the accepted Batch D1 slice from `plans/task-09-sp0095-notification-triage-contract-plan.md`.

## Current State

- Batch D planning is complete and ADR-00003 has a notification triage extension note.
- Existing `GET /api/v1/notifications` and `mark_read` compatibility must remain intact.
- The old notification list still returns raw `payload`, so new triage consumers must use a separate redacted contract.

## Required Implementation

1. Add additive notification triage columns with migration up/down coverage:
   - `severity`
   - `required_action`
   - `due_at`
   - `snoozed_until`
   - `resolved_at`
   - `resolved_by_actor_id`
   - `dedupe_key`
2. Add DB constraints and indexes:
   - enum-like checks for `severity` and `required_action`
   - resolved actor/timestamp consistency
   - tenant-scoped resolver actor FK
   - open triage index
   - unresolved-only dedupe partial unique index
3. Add repository and API methods for:
   - redacted triage listing
   - actor-owned snooze
   - actor-owned resolve
4. Add frontend API schema/client functions for the D2 UI follow-up.
5. Add backend, frontend, schema introspection, and migration verification.

## Boundary

- Allowed: DB migration, ORM/repository/API/frontend client schema, tests, docs.
- Not allowed: `/notifications` UI replacement, bulk notification mutation, public caller-supplied `dedupe_key`, approval `request_revision`, raw payload expansion.

## DoD

- [x] Existing list and mark-read API compatibility remains.
- [x] Triage API returns `payload_keys` and `payload_redaction_status`, not raw payload values.
- [x] Snooze and resolve require recipient ownership.
- [x] Resolve binds `resolved_by_actor_id` to the current actor.
- [x] Audit events store metadata only and do not copy raw notification payload or resolution note body.
- [x] Migration upgrade head / downgrade -1 / upgrade head / current is verified on a temporary database.
- [x] D2 UI remains a separate PR.
