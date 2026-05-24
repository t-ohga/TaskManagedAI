# task-13 SP-009-5 Request Revision API Self-Review

## Round 1 - Structural Review

| finding | severity | decision | result |
|---|---:|---|---|
| Expanding `approval_requests.status` would create DB/API/frontend enum drift and invalidate the Batch E0 plan. | HIGH | adopt | The migration adds only `approval_revision_requests`; `ApprovalStatus` remains unchanged. |
| Request revision could accidentally copy rationale into `ApprovalRequest.rationale`, notification payload, or audit payload. | HIGH | adopt | The service stores rationale only on the revision request row and uses metadata-only audit/notification payloads. |
| The mutation must be atomic or an approval could remain pending after a revision row is created. | HIGH | adopt | The service performs pending-only invalidation and revision row/audit/notification in one transaction; API commits only after all operations complete. |

## Round 2 - Adversarial Review

| finding | severity | decision | result |
|---|---:|---|---|
| Self-approval guard raised `ValueError` and could surface as a 500 instead of a 409 response. | HIGH | adopt | `ApprovalRevisionRequestService` wraps guard failures as `ApprovalRevisionConflictError`; API maps it to 409. |
| Raw secret canaries in rationale could be persisted before validation. | HIGH | adopt | Rationale is trimmed and scanned with the shared raw-secret scanner before DB mutation. |
| Existing approval regression tests failed against head schema because old fixtures truncated FK-referenced approval rows without `CASCADE`. | MEDIUM | adopt | Approval test fixtures now use cascade resets so head-schema FK references do not mask regression results. |
| Approved/rejected fixture rows could violate the temporal check if `decided_at` is generated before server `requested_at`. | MEDIUM | adopt | The API fixture now writes explicit `requested_at` and matching `decided_at` for decided rows. |
| Duplicate open revision requests could make supersession ambiguous. | MEDIUM | adopt | The migration adds a partial unique index, and the service checks for an existing open revision before invalidating. |

## Checklist

- [x] Status enum unchanged.
- [x] AgentRunEvent enum unchanged.
- [x] Additive table has tenant boundary, composite FKs, metadata default, and partial unique open-request constraint.
- [x] Rationale secret scan occurs before DB mutation.
- [x] Audit/notification payloads exclude raw rationale.
- [x] Self-approval and delegated same-human guard enforced.
- [x] Non-pending, duplicate-open, self-approval, and secret-canary negative cases covered.
- [x] Migration up/down/up/current verified on temporary PostgreSQL database.
