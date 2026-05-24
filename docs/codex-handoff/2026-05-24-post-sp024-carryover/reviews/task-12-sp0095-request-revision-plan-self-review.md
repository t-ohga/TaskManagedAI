# task-12 SP-009-5 Request Revision Plan Self-Review

## Round 1 - Structural Review

| finding | severity | decision | result |
|---|---:|---|---|
| Adding `revision_requested` to `approval_requests.status` would require a 5+ source enum migration and could break existing approval inbox, KPI, stale invalidation, and decision-service assumptions. | HIGH | adopt | The plan rejects status enum expansion for the first implementation and uses an additive `approval_revision_requests` table instead. |
| Request revision is a mutation and cannot be bundled with read-only approval detail polish. | HIGH | adopt | The implementation split separates E1 DB/API, E2 UI, and E3 revised-artifact handoff. |
| Revision semantics need an explicit old-row/new-row rule or stale approvals may return to `pending`. | HIGH | adopt | The old approval always transitions to `invalidated`; revised artifacts create a new approval request. |

## Round 2 - Adversarial Review

| finding | severity | decision | result |
|---|---:|---|---|
| Persisting or notifying raw rationale could leak secrets in audit, notification, or DOM surfaces. | HIGH | adopt | The plan requires pre-persistence raw-secret scan and metadata-only notification/audit payloads. |
| A future AgentRunEvent such as `approval_revision_requested` could be added casually and drift from the 5+ source enum sources. | HIGH | adopt | The plan forbids new AgentRun status/event enum values in E1/E2 and requires a separate enum-integrity PR for future runtime events. |
| A duplicate open revision request could invalidate the same approval twice and make supersession ambiguous. | MEDIUM | adopt | The data model requires one open revision request per approval until `superseded_by_approval_request_id` is set. |
| A delegated actor could request revision on their own original request through an impersonation path. | MEDIUM | adopt | The API contract applies the existing self-approval and delegated same-human guard to request revision. |
| Caller-supplied replacement approval ids or hashes could bypass server-owned decision-packet binding. | MEDIUM | adopt | Public callers cannot provide replacement approval ids or decision-packet hash fields; the service snapshots them from the current approval. |

## Checklist

- [x] Status enum expansion rejected for the initial implementation.
- [x] Old approval invalidation and replacement approval creation semantics fixed.
- [x] ADR-00003 / ADR-00004 / ADR-00009 gate notes required before runtime implementation.
- [x] Secret leakage paths covered: rationale persistence, audit payload, notification payload, frontend DOM.
- [x] Self-approval and delegated same-human guard included.
- [x] Duplicate-open revision request constraint included.
- [x] Migration up/down and schema introspection verification specified for E1.
