# task-12 SP-009-5 Batch E Request Revision Plan

## Scope

Plan the Approval `request_revision` loop before runtime implementation. This is a high-risk mutation because it changes approval semantics, stale invalidation behavior, and AgentRun resume expectations.

## Current State

- `approval_requests.status` is limited to `pending`, `approved`, `rejected`, `expired`, and `invalidated`.
- Decision UI supports approve/reject only.
- Existing stale invalidation invalidates approvals when artifact/diff/policy/provider fingerprints drift.
- SP-009-5 Batch C exposes decision packet hashes; Batch D1/D2 notification triage is complete.

## Planned Direction

Use a separate revision request record instead of adding `revision_requested` to `approval_requests.status`.

- Existing approval transitions to `invalidated`.
- A new `approval_revision_requests` row records the human request, reason, original decision packet hashes, and eventual replacement approval.
- Revised artifact submission creates a new approval request. The old approval row is never returned to `pending`.

## Required ADR/API Gates

1. ADR-00003 API contract update:
   - `POST /api/v1/approvals/{approval_id}/request_revision`
   - request body: `rationale` required, max 2000 chars, raw-secret scan before persistence
   - response: invalidated approval detail plus revision request id
2. ADR-00004 AgentRun state machine update:
   - initial implementation does not add an AgentRun status or event enum
   - AgentRun remains blocked/revisable through existing blocked path until a revised artifact creates a new approval
   - any future AgentRunEvent enum addition must be its own 5+ source enum PR
3. ADR-00009 action/approval taxonomy update:
   - self-approval guard applies to request-revision decider
   - revision request is a human decision action, not an agent capability
   - old approval is invalidated and cannot be approved/rejected after revision request

## Planned Implementation Split

| batch | scope | risk control |
|---|---|---|
| E0 | docs-only plan and ADR notes | no code/schema |
| E1 | DB/API contract | additive `approval_revision_requests`; no approval status enum expansion |
| E2 | Approval Detail UI action | human-only form, no bulk action |
| E3 | revised artifact handoff | new approval row creation and stale revision safeguards |

## Boundary

- Allowed in E1/E2: additive table, API route, repository/service, audit event, notification event, frontend detail action, tests.
- Not allowed without a separate plan: adding `revision_requested` to `approval_requests.status`, reusing old approval rows as pending, adding AgentRunEvent enum values, bulk revision requests, agent-decider revision requests.

## DoD For Planning PR

- [x] Status enum expansion is explicitly rejected for the first implementation.
- [x] Old approval invalidation and new approval row semantics are fixed.
- [x] ADR-00003 / ADR-00004 / ADR-00009 update notes are recorded.
- [x] E1/E2/E3 split keeps DB/API/UI/runtime handoff separate.
- [x] Verification requirements include self-approval, stale invalidation, raw-secret scan, and migration up/down.
