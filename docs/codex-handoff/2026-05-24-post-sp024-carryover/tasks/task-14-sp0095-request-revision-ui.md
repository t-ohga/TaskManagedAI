# task-14 SP-009-5 Batch E2 Request Revision UI

## Scope

Implement the Approval Detail UI action for the E1 `request_revision` API.

This batch is intentionally frontend-only. The DB/API contract was completed in task-13, and revised artifact supersession remains task E3.

## Boundary

- Add a frontend API client for `POST /api/v1/approvals/{approval_id}/request_revision`.
- Add a server action that validates approval id and rationale before calling the backend.
- Add a pending-only Approval Detail form for requesting revision.
- Keep rationale out of post-submit status messages and read-only detail rendering.
- Do not add bulk actions, `revision_requested` status, AgentRunEvent enum values, or revised artifact supersession wiring.

## DoD

- [x] Approval Detail shows `修正依頼` only while the approval is `pending`.
- [x] Server action rejects invalid UUIDs and blank/too-long rationale before backend call.
- [x] Successful action revalidates `/approvals` and the detail path.
- [x] UI success result does not echo the rationale.
- [x] Existing approve/reject UI remains available and unchanged.
- [x] Tests cover API schema, server action validation, form labels, and detail page wiring.

## Verification

- `corepack pnpm@10.18.0 --dir frontend exec tsc --noEmit`
- `corepack pnpm@10.18.0 --dir frontend exec eslint app/(admin)/approvals/[id]/page.tsx app/(admin)/approvals/[id]/_components/approval-revision-request-form.tsx app/(admin)/approvals/[id]/_actions/request-revision.ts lib/api/approvals.ts __tests__/approval-detail.test.tsx __tests__/approval-revision-request-actions.test.ts __tests__/approval-revision-request-form-i18n.test.tsx __tests__/lib/api/approvals.test.ts --max-warnings=0`
- `corepack pnpm@10.18.0 --dir frontend exec vitest run __tests__/approval-detail.test.tsx __tests__/approval-decide-form-i18n.test.tsx __tests__/approval-revision-request-actions.test.ts __tests__/approval-revision-request-form-i18n.test.tsx __tests__/lib/api/approvals.test.ts`
- Browser smoke for `/approvals/{id}` when a seeded backend is available; otherwise document as not run.

## Residual

- E3 revised artifact handoff still needs supersession wiring and fresh decision-packet hash negative tests.
- Newcomer Path remains P0.1 polish and is not part of this mutation batch.
