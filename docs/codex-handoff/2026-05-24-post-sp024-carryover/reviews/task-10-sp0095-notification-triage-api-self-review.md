# task-10 SP-009-5 Notification Triage API Self-Review

## Round 1 - Structural Review

| finding | severity | decision | result |
|---|---:|---|---|
| Adding lifecycle fields to `notification_events` could break old list/mark-read consumers. | HIGH | adopt | The old response model and endpoints remain unchanged; triage uses a new additive endpoint and frontend schema. |
| Triage responses could accidentally expose raw notification payload values. | HIGH | adopt | `GET /api/v1/notifications/triage` returns sorted `payload_keys` with `payload_redaction_status=keys_only` and no `payload` field. |
| Resolve/snooze could mutate another actor's notification. | HIGH | adopt | API loads by tenant and checks `recipient_actor_id == current_actor_id` before mutation. |
| A resolved notification without resolver identity would weaken the audit trail. | MEDIUM | adopt | DB check requires `resolved_at` and `resolved_by_actor_id` to be both null or both non-null. |

## Round 2 - Adversarial Review

| finding | severity | decision | result |
|---|---:|---|---|
| A public `dedupe_key` input could let clients suppress unrelated notifications. | HIGH | adopt | `dedupe_key` is repository/server-side only; no public API request schema accepts it. |
| Dedupe uniqueness could block historical resolved notifications. | MEDIUM | adopt | Unique index is partial on unresolved rows only. |
| Audit events could store sensitive resolution-note text. | MEDIUM | adopt | Resolve audit stores only `resolution_note_present`; tests assert the note body is absent. |
| Snooze could hide notifications indefinitely. | MEDIUM | adopt | API rejects past timestamps and timestamps more than 30 days ahead. |
| Repeated resolve calls could keep state unchanged but append duplicate audit events. | MEDIUM | adopt | Resolve updates only unresolved rows; already-resolved notifications return 409 before audit append. |
| Migration verification could be skipped because GitHub Actions are quota-blocked. | HIGH | adopt | A temporary local PostgreSQL database is used for upgrade head / downgrade -1 / upgrade head / current plus targeted DB tests. |

## Checklist

- [x] Actor ownership boundary is enforced before mutation.
- [x] Raw payload values are not exposed through the triage response.
- [x] Audit payloads are metadata-only.
- [x] Migration downgrade remains reversible.
- [x] Frontend schema rejects unknown severity/state values.
- [x] Existing notification list and badge behavior remains covered.
- [x] D2 UI scope is deferred rather than bundled into D1.
