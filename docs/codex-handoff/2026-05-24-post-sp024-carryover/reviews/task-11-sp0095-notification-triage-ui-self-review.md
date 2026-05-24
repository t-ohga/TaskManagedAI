# task-11 SP-009-5 Notification Triage UI Self-Review

## Round 1 - Structural Review

| finding | severity | decision | result |
|---|---:|---|---|
| `/notifications` could keep using the legacy raw-payload API and silently bypass D1 redaction. | HIGH | adopt | Page now calls `listNotificationTriage` and renders `payload_keys` only. |
| UI actions could accept arbitrary snooze timestamps from the browser. | HIGH | adopt | Server action accepts only fixed minute values and computes `snoozed_until` server-side. |
| Resolve UI could send free-form note text that users assume is stored safely. | MEDIUM | adopt | D2 resolve sends `resolution_note: null`; no textarea is rendered. |
| State filters could drift from backend enum values. | MEDIUM | adopt | Page uses the frontend `NotificationTriageState` type and parse guard. |

## Round 2 - Adversarial Review

| finding | severity | decision | result |
|---|---:|---|---|
| Bulk actions would make actor-owned transition failures hard to reason about. | HIGH | adopt | D2 exposes only per-row forms. |
| Rendering payload key chips could still become raw payload rendering later. | MEDIUM | adopt | Tests assert the triage page renders keys and does not render a raw payload value. |
| Existing notification empty-state i18n test could continue mocking the old API. | MEDIUM | adopt | Test now mocks `listNotificationTriage` so the page contract is exercised. |
| Client component errors could fail silently. | LOW | adopt | Action failures are surfaced as per-row status messages. |

## Checklist

- [x] No backend/API/schema changes in D2.
- [x] No raw payload value rendering.
- [x] Snooze and resolve remain server-action mediated.
- [x] Existing mark-read compatibility is preserved.
- [x] Frontend lint, typecheck, and targeted Vitest pass.
