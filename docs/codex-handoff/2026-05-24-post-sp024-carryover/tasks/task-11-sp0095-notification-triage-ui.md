# task-11 SP-009-5 Batch D2 Notification Triage UI

## Scope

Implement the D2 UI/action layer on top of the D1 notification triage DB/API contract.

## Required Implementation

1. Switch `/notifications` from the legacy raw-payload list to the redacted triage endpoint.
2. Add state navigation for open, snoozed, resolved, and all notifications.
3. Render only `payload_keys` and triage metadata; do not render raw notification payload values.
4. Add per-notification actions:
   - mark read for unread notifications,
   - server-owned one-hour snooze,
   - resolve without a free-form note body.
5. Keep actions actor-owned by using the D1 backend endpoints; do not introduce bulk actions.

## Boundary

- Allowed: frontend page/component/action updates, i18n labels, frontend tests, docs.
- Not allowed: backend contract expansion, public dedupe input, bulk state changes, approval `request_revision`.

## DoD

- [x] `/notifications` uses `listNotificationTriage`.
- [x] state tabs preserve the selected triage state through query params.
- [x] UI renders `payload_keys` only.
- [x] snooze timestamp is computed server-side from a fixed allowed duration.
- [x] resolve sends `resolution_note: null`.
- [x] Vitest covers page rendering and server action request shapes.
