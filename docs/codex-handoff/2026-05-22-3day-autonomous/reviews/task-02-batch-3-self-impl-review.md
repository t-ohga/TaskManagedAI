# task-02 batch 3 Self-Impl-Review

Date: 2026-05-22 JST

## Scope

- `frontend/app/(admin)/approvals/page.tsx`
- `frontend/app/(admin)/approvals/[id]/page.tsx`
- `frontend/app/(admin)/approvals/[id]/_components/approval-decide-form.tsx`
- `frontend/app/(admin)/approvals/[id]/_actions/decide.ts`
- `frontend/lib/i18n/approval-labels.ts`
- `frontend/__tests__/approval-inbox.test.tsx`
- `frontend/__tests__/approval-decide-form-i18n.test.tsx`
- `frontend/__tests__/lib/i18n/approval-labels.test.ts`
- `frontend/tests/e2e/approval-inbox.spec.ts`
- `frontend/tests/e2e/a11y.spec.ts`
- `frontend/tests/e2e/responsive.spec.ts`

## Summary

SP-012-8 batch 3 localized Approval Inbox, approval detail, and approval
decision form text. `action_class`, approval `status`, and `risk_level` display
helpers keep raw enum values visible for policy/audit traceability.

## Adversarial Findings

| id | severity | finding | decision | resolution |
|---|---|---|---|---|
| T02-B3-I001 | HIGH | Translating approval status/action/risk labels without raw values would make policy and audit triage harder. | adopt | Added approval label helpers rendering Japanese labels with raw values, e.g. `リポジトリ書込 (repo_write)`. |
| T02-B3-I002 | MEDIUM | Approval decision buttons must keep submit values `approve`/`reject` even when labels are Japanese. | adopt | Only button text changed; tests assert values remain `approve` and `reject`. |
| T02-B3-I003 | MEDIUM | Existing Approval Inbox tests would keep querying English headings/links and fail after localization. | adopt | Updated Vitest and E2E expectations to Japanese accessible names. |
| T02-B3-I004 | MEDIUM | Date locale remained English in approval detail after visible text localization. | adopt | Switched detail date formatting to `ja-JP`. |
| T02-B3-I005 | LOW | Test titles still mention `Approval Inbox`. | reject | Test titles are not user-facing UI and are useful as historical Sprint references. |

## §3.5 Checklist

### Invariants

- server-owned-boundary: pass; approval API calls and route params unchanged.
- API contract: pass; `approve` / `reject` request values unchanged.
- 5+ source enum integrity: pass; enum sources unchanged, display helper only.
- raw value traceability: pass; action/status/risk raw values remain visible.
- accessible-name consistency: pass; headings, links, form labels, and E2E queries updated.
- technical identifiers untranslated: pass; `action_class`, policy identifiers, hashes, and provider fingerprint names remain raw where traceability matters.
- weak assertion ban: pass; tests use role/label queries, exact object equality, and value assertions.
- cascade risk: low; approval label helpers centralize mapping.
- ADR Gate: non-applicable; UI copy and frontend helper only.
- security boundary: pass; no raw secret/provider payload exposure added.
- route behavior: pass; links and route paths unchanged.
- terminal mutation: pass; approval decision semantics unchanged.

### Local Verification

- `pnpm vitest run __tests__/approval-inbox.test.tsx __tests__/approval-decide-form-i18n.test.tsx __tests__/lib/i18n/approval-labels.test.ts`: 6 passed.
- `pnpm typecheck`: passed.
- `pnpm lint`: passed.
- `pnpm vitest run`: 80 passed.
- `git diff --check`: passed.
- `rg` old approval UI pattern sweep: no user-facing matches.

## Readiness Gate

- Residual CRITICAL: 0
- Residual HIGH: 0
- Residual MEDIUM: 0
- Residual LOW: 0

Verdict: READY for PR.
