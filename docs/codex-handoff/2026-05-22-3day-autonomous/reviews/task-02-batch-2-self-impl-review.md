# task-02 batch 2 Self-Impl-Review

Date: 2026-05-22 JST

## Scope

- `frontend/app/(admin)/tickets/page.tsx`
- `frontend/app/(admin)/tickets/[id]/page.tsx`
- `frontend/app/(admin)/tickets/_components/new-ticket-form.tsx`
- `frontend/app/(admin)/tickets/[id]/_components/edit-ticket-form.tsx`
- `frontend/app/(admin)/tickets/actions.ts`
- `frontend/app/(admin)/tickets/[id]/actions.ts`
- `frontend/lib/i18n/ticket-labels.ts`
- `frontend/__tests__/lib/i18n/ticket-labels.test.ts`
- `frontend/__tests__/tickets-forms-i18n.test.tsx`
- `frontend/tests/e2e/sprint9-pages.spec.ts`
- `frontend/tests/e2e/ticket-crud-flow.spec.ts`

## Summary

SP-012-8 batch 2 localized tickets list/detail pages, create/edit forms,
UI-local validation fallback messages, and ticket status/priority display labels.
Raw enum values remain visible in parentheses to preserve traceability.

## Adversarial Findings

| id | severity | finding | decision | resolution |
|---|---|---|---|---|
| T02-B2-I001 | HIGH | Translating status/priority labels without preserving raw enum values would weaken debugging and contract traceability. | adopt | Added `formatTicketStatus` / `formatTicketPriority` helpers that render Japanese labels with raw values, e.g. `進行中 (in_progress)`. |
| T02-B2-I002 | MEDIUM | Updating pages/forms without test updates would leave existing Playwright label queries stale. | adopt | Updated affected E2E expectations for tickets list, ticket detail region, and create form labels. |
| T02-B2-I003 | MEDIUM | Form label translation can break accessible names and make inputs unreachable by Testing Library role/label queries. | adopt | Added `tickets-forms-i18n.test.tsx` to assert labels, placeholders, combobox names, and option values. |
| T02-B2-I004 | MEDIUM | A dictionary helper could drift from the Zod status/priority enum values. | adopt | Added exact helper tests for every ticket status and priority label. |
| T02-B2-I005 | LOW | Backend/API detail strings may remain English when surfaced through `BackendApiError.message`. | defer | Sprint Pack explicitly keeps API errors structured/English; this batch translates UI-local wrapper/fallback messages only. |

## §3.5 Checklist

### Invariants

- server-owned-boundary: pass; no session/project resolution path changed.
- API contract: pass; request payload field names and enum values unchanged.
- 5+ source enum integrity: pass; no enum source changed, only display helpers added.
- raw value traceability: pass; status/priority raw enum values remain visible.
- accessible-name consistency: pass; form labels and E2E queries updated.
- technical identifiers untranslated: pass; `Slug`, `project`, enum raw values, route paths, and form field names remain unchanged.
- weak assertion ban: pass; tests use exact object equality, role/label queries, `toHaveValue`, and `toBeVisible`.
- cascade risk: low; labels are centralized for ticket status/priority.
- ADR Gate: non-applicable; UI copy and frontend helper only.
- security boundary: pass; no secret/provider/audit payload exposure added.
- route behavior: pass; hrefs and dynamic route validation unchanged.
- docs drift: no new task-file drift introduced.

### Local Verification

- `pnpm vitest run __tests__/lib/i18n/ticket-labels.test.ts __tests__/tickets-forms-i18n.test.tsx __tests__/tickets-actions.test.ts __tests__/tickets-detail-actions.test.ts`: 13 passed.
- `pnpm typecheck`: passed.
- `pnpm lint`: passed.
- `pnpm vitest run`: 76 passed.
- `git diff --check`: passed.
- `rg` old English UI/query pattern sweep over tickets/tests: no matches.

## Readiness Gate

- Residual CRITICAL: 0
- Residual HIGH: 0
- Residual MEDIUM: 0
- Residual LOW: 1 deferred (`BackendApiError.message` raw backend detail)

Verdict: READY for PR.
