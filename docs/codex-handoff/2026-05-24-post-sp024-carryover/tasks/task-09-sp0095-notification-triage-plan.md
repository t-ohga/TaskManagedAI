# task-09 SP-009-5 Batch D Notification Triage Plan

## Scope

Plan SP-009-5 Batch D before code/schema work. This batch is high-risk because it changes notification state, API contract, and DB schema.

## Current State

- `notification_events` currently stores `event_type`, raw JSON `payload`, `recipient_actor_id`, and `read_at`.
- `GET /api/v1/notifications` returns raw `payload`.
- UI renders only `event_type` and created time, but the API contract is not yet a redacted triage contract.
- There is no first-class `severity`, `required_action`, `due_at`, `snoozed_until`, `resolved_at`, or `dedupe_key`.

## Required Plan Before Implementation

1. Add an ADR-00003 update note for notification triage API/event-schema boundaries.
2. Use a new redacted triage response contract instead of expanding raw `payload` usage.
3. Add migration-backed state fields only after the plan is merged:
   - `severity`
   - `required_action`
   - `due_at`
   - `snoozed_until`
   - `resolved_at`
   - `resolved_by_actor_id`
   - `dedupe_key`
4. Keep old mark-read behavior intact for compatibility.
5. Add resolve/snooze APIs as actor-owned state transitions with audit events.

## Boundary

- Allowed in implementation PR: DB migration, ORM/repository/API updates, redacted frontend triage UI, tests, migration up/down verification.
- Not allowed: approval `request_revision`, notification raw payload rendering, caller-supplied dedupe keys through public API, cross-actor triage updates, bulk actions.

## Planned Implementation Split

| batch | scope | risk control |
|---|---|---|
| D1 | DB/API contract + repository + tests | additive columns, old API compatibility, redacted triage response |
| D2 | `/notifications` triage UI + resolve/snooze actions | actor-owned transitions, no bulk action |
| D3 | cleanup/deprecation note for old raw payload response | only after D1/D2 prove stable |

## DoD For Planning PR

- [x] Existing notification model/API/UI are mapped.
- [x] ADR-00003 has a notification triage extension note.
- [x] Implementation batches and migration verification are specified.
- [x] Raw payload exposure is explicitly not expanded.
- [x] No code or migration is changed in this plan PR.
