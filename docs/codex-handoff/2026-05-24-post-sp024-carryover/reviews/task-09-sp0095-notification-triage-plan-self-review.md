# task-09 SP-009-5 Notification Triage Plan Self-Review

## Round 1 - Structural Review

| finding | severity | decision | result |
|---|---:|---|---|
| Current notification API returns raw `payload`, which is unsafe to extend into a triage UI. | HIGH | adopt | Plan introduces a separate redacted triage response with `payload_keys` only. |
| Notification lifecycle requires DB/API/mutation changes and should not be bundled with read-only UI PRs. | HIGH | adopt | Plan splits D1 DB/API and D2 UI/actions, with migration verification before UI rollout. |
| Existing mark-read compatibility could be broken by a new triage contract. | MEDIUM | adopt | Existing endpoints remain; new triage endpoint is additive. |

## Round 2 - Adversarial Review

| finding | severity | decision | result |
|---|---:|---|---|
| Public API could accept caller-supplied `dedupe_key` and let clients collapse unrelated notifications. | HIGH | adopt | Plan states dedupe is server-computed and not accepted from public API requests. |
| Snooze/resolve could allow cross-actor mutation. | HIGH | adopt | Plan requires actor-owned recipient scope checks and resolver binding to current actor. |
| Dedupe uniqueness could block historical resolved notifications. | MEDIUM | adopt | Plan uses a partial unique index only for unresolved rows. |
| Audit payload could accidentally copy raw notification payload. | MEDIUM | adopt | Audit contract includes metadata keys only, never notification payload values. |

## Checklist

- [x] ADR/API/schema gate acknowledged before implementation.
- [x] migration up/down verification specified.
- [x] raw payload exposure not expanded.
- [x] actor-owned mutation boundary specified.
- [x] implementation split keeps rollback simple.
