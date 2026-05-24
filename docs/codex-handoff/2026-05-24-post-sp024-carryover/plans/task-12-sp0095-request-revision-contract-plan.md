# SP-009-5 Batch E Request Revision Contract Plan

## Decision

Do not add `revision_requested` to `approval_requests.status` in the first implementation.

The safer contract is:

1. A human decider requests revision on a `pending` approval.
2. The current approval becomes `invalidated`.
3. A separate `approval_revision_requests` record stores the revision request and decision-packet snapshot.
4. The revised artifact creates a new approval request.

This keeps the existing approval status enum, KPI queries, Approval Inbox filters, stale invalidation tests, and decision service assumptions stable.

## Data Model

Planned additive table:

```text
approval_revision_requests
- id uuid primary key
- tenant_id bigint not null
- approval_request_id uuid not null
- requested_by_actor_id uuid not null
- rationale text not null
- artifact_hash text nullable
- diff_hash text nullable
- policy_version text not null
- policy_pack_lock text nullable
- provider_request_fingerprint text nullable
- stale_after_event_seq bigint nullable
- superseded_by_approval_request_id uuid nullable
- created_at timestamptz not null
- metadata jsonb not null default {"rls_ready": true}
```

Required constraints:

- composite FK `(tenant_id, approval_request_id)` to `approval_requests(tenant_id, id)`
- composite FK `(tenant_id, requested_by_actor_id)` to `actors(tenant_id, id)`
- optional composite FK `(tenant_id, superseded_by_approval_request_id)` to `approval_requests(tenant_id, id)`
- unique open revision request per `(tenant_id, approval_request_id)` while `superseded_by_approval_request_id is null`
- non-empty `rationale`

## API Contract

Endpoint:

```text
POST /api/v1/approvals/{approval_id}/request_revision
```

Request:

```json
{
  "rationale": "Explain the required change without secrets."
}
```

Response:

```json
{
  "approval": { "...": "existing ApprovalDetail, now status=invalidated" },
  "revision_request_id": "uuid"
}
```

Rules:

- only `pending` approvals can receive a revision request
- requester and decider cannot be the same actor or delegated same human
- rationale is raw-secret scanned before persistence
- rationale is not copied into notification payloads
- public callers cannot provide replacement approval ids or hash values

## State And Runtime Semantics

- Existing approval row becomes `invalidated`; it cannot later be approved or rejected.
- Revised artifact submission creates a new approval row with fresh hashes/fingerprints.
- The initial E1/E2 implementation does not add new AgentRun statuses or AgentRunEvent enum values.
- Any future runtime event such as `approval_revision_requested` in `agent_run_events` must be a separate PR with DB CHECK, ORM, Python Literal, Pydantic/frontend schema, and pytest drift checks.

## Audit And Notification

Audit event:

- `approval_revision_requested`
- metadata-only payload:
  - approval id
  - revision request id
  - action class
  - resource ref
  - risk level
  - decision packet hash presence flags

Notification event:

- event_type: `approval_revision_requested`
- recipient: original requester actor
- `severity`: `medium`
- `required_action`: `inspect_run`
- payload keys only need approval id and revision request id; raw rationale is not copied

## Implementation Batches

| batch | scope | verification |
|---|---|---|
| E1 | migration, ORM, repository/service, API route | ruff, mypy, DB API tests, schema introspection, migration up/down |
| E2 | Approval Detail UI action and read-only revision request display | frontend lint/typecheck/Vitest/browser smoke |
| E3 | revised artifact handoff and supersession wiring | runtime/API integration tests and stale hash negative tests |

## Test Plan

- pending approval can request revision and becomes invalidated
- approved/rejected/expired/invalidated approvals return 409
- self-approval and delegated same-human revision requests return 409
- old approval cannot be approved/rejected after revision request
- rationale secret canary is rejected before DB insert
- notification/audit payloads do not contain raw rationale
- duplicate open revision request for one approval is rejected
- replacement approval must have fresh decision-packet hashes
- migration upgrade head / downgrade -1 / upgrade head / current

## Rollback

1. Revert UI action first; approve/reject remains available for pending approvals.
2. Revert API route/service.
3. Downgrade the additive table migration if no production revision requests exist.
4. If production rows exist, forward-fix by disabling the route and preserving the table for audit history.
