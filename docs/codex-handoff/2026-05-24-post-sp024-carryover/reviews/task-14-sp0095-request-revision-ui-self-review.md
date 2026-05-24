# task-14 SP-009-5 Batch E2 Self Review

## Scope Reviewed

- Frontend API client for `POST /api/v1/approvals/{approval_id}/request_revision`.
- Approval Detail pending-only request revision form.
- Server action validation and revalidation behavior.
- Tests and SP-009-5 handoff/status docs.

## Findings

| finding | severity | decision | resolution |
|---|---|---|---|
| The pending Approval Detail test initially rendered client forms without a `next/navigation` router mock. | MEDIUM | adopt | Added a router mock and role-based assertions for pending detail UI. |
| The revision form test queried duplicate `修正依頼` text by raw text, making it brittle. | LOW | adopt | Switched to accessible `group` and `button` role queries. |
| Server action DoD mentioned too-long rationale, but the first test pass only covered blank rationale. | MEDIUM | adopt | Added a 2001-character rationale negative test before backend call. |
| Browser E2E could be mistaken as a product regression because it failed after login. | LOW | defer | Failure was caused by the already-running local backend rejecting the default `dev-login-token`; unit/UI coverage passed, and the token mismatch is environment setup rather than this diff. |

## Invariant Checklist

- [x] No `revision_requested` approval status enum was added.
- [x] No AgentRunEvent enum value was added.
- [x] No revised artifact supersession wiring was added in E2.
- [x] The UI action is available only from Approval Detail pending state.
- [x] The server action validates approval UUID and rationale before backend call.
- [x] Rationale is sent only to the E1 backend API and is not echoed in the action result.
- [x] Success path revalidates `/approvals` and `/approvals/{id}`.
- [x] Existing approve/reject action remains available for pending approvals.

## Verification

- passed: `corepack pnpm@10.18.0 --dir frontend exec tsc --noEmit`
- passed: `corepack pnpm@10.18.0 --dir frontend run lint`
- passed: `corepack pnpm@10.18.0 --dir frontend exec eslint app/(admin)/approvals/[id]/page.tsx app/(admin)/approvals/[id]/_components/approval-revision-request-form.tsx app/(admin)/approvals/[id]/_actions/request-revision.ts lib/api/approvals.ts __tests__/approval-detail.test.tsx __tests__/approval-revision-request-actions.test.ts __tests__/approval-revision-request-form-i18n.test.tsx __tests__/lib/api/approvals.test.ts --max-warnings=0`
- passed: `corepack pnpm@10.18.0 --dir frontend exec vitest run`
- passed: `corepack pnpm@10.18.0 --dir frontend exec vitest run __tests__/approval-detail.test.tsx __tests__/approval-revision-request-actions.test.ts`
- passed: `ruby -e 'require "yaml"; require "date"; YAML.safe_load(File.read("docs/sprints/SP-009-5_p0_ui_deferred_surfaces.md"), permitted_classes: [Date], aliases: true); puts "ok"'`
- passed: `.claude/hooks/sprint/check-sprint-pack-frontmatter.sh`
- passed: `git diff --check`
- blocked: `corepack pnpm@10.18.0 --dir frontend exec playwright test tests/e2e/approval-inbox.spec.ts --project=chromium` failed because the existing local backend rejected the default dev login token with `invalid_dev_login_token`.

## Residual

- Batch E3 revised artifact handoff remains the next request_revision batch.
- Newcomer Path remains P0.1 polish.
