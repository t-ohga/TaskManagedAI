# task-02 batch 6 Self-Impl-Review

Date: 2026-05-22 JST

## Scope

- `frontend/app/(admin)/dashboard/page.tsx`
- `frontend/app/(admin)/settings/page.tsx`
- `frontend/app/(admin)/notifications/page.tsx`
- `frontend/app/(admin)/notifications/_components/notification-list-item.tsx`
- `frontend/app/(auth)/login/page.tsx`
- `frontend/components/login-form.tsx`
- `frontend/app/page.tsx`
- `frontend/app/loading.tsx`
- `frontend/app/not-found.tsx`
- `frontend/app/error.tsx`
- affected Vitest and Playwright expectations

## Summary

SP-012-8 batch 6 localized the remaining settings/auth/dashboard/notification
shell copy plus global loading, 404, and error states. Technical identifiers
such as `Dev login token`, `allowed_data_class`, `merge_deny`, `RepoProxy`,
`SecretBroker`, provider names, and route/API paths remain unchanged.

## Adversarial Findings

| id | severity | finding | decision | resolution |
|---|---|---|---|---|
| T02-B6-I001 | HIGH | Translating `Dev login token` could make E2E login selectors and the operator-facing secret-token concept ambiguous. | adopt | Kept the label raw; localized submit/progress/error copy only. |
| T02-B6-I002 | HIGH | `KeyboardReadinessStrip current` still uses canonical English labels for active-state matching; translating the prop would silently drop `aria-current`. | adopt | Kept `current="Project Settings"` and localized the visible settings region/heading only. |
| T02-B6-I003 | MEDIUM | App Router global `error.tsx` must be a Client Component or production build fails. | adopt | Added `"use client"` and verified with `pnpm build`. |
| T02-B6-I004 | MEDIUM | E2E selectors still queried `Sign in`, `Dashboard`, and `Project Settings`, causing drift from localized accessible names. | adopt | Updated Playwright helpers/specs to `ログイン`, `ダッシュボード`, and `設定`. |
| T02-B6-I005 | MEDIUM | Empty/loading/error states lacked regression coverage and could regress silently. | adopt | Added `settings-auth-common-i18n.test.tsx` covering settings, dashboard unavailable, notification empty, login error, root page, loading, 404, and error UI. |
| T02-B6-I006 | LOW | Research detail fallback `source unavailable` and Eval Dashboard skeleton fallback strings remain English. | defer | They are outside this batch's settings/auth/common state scope and should be handled in the final common/research cleanup batch. |

## §3.5 Checklist

### Invariants

- server-owned-boundary: pass; no request ownership, auth boundary, or backend API behavior changed.
- raw secret boundary: pass; no token/secret raw value rendered or logged; `Dev login token` remains a label only.
- technical identifiers: pass; `allowed_data_class`, `merge_deny`, `RepoProxy`, `SecretBroker`, and route paths remain raw.
- 5+ source enum invariant: non-applicable; no backend/source enum changed.
- atomic claim: pass; UI copy and tests only, no mixed behavior change.
- approval 4 consistency: non-applicable; no approval policy/status mutation.
- event/source mismatch: pass; no event schema or source label changed.
- terminal mutation: pass; no status/action mutation added.
- migration verification: non-applicable; no DB/Alembic changes.
- API contract: pass; no request/response schema changed.
- accessibility names: pass; localized role/name selectors updated.
- docs drift: pass; self-review documents residual defer.

### Tests

- weak assertion ban: pass; new tests use roles, accessible names, text visibility, and preserved raw identifier assertions.
- regression case separation: pass; settings, dashboard unavailable, notification empty, login error, root page, and global states are separate cases.
- English selector drift: pass; affected E2E selectors updated.
- error path coverage: pass; login invalid-request, backend unavailable, loading, 404, and global error covered.
- snapshot avoidance: pass; no broad snapshots added.
- full frontend regression: pass; full Vitest suite completed.

### PR Description Inputs

- changed files summarized: ready.
- verification commands captured: ready.
- raw identifier preservation called out: ready.
- deferred residuals called out: ready.
- CI/bypass context: ready; expected hosted CI billing-blocked pattern remains external to this batch.

### Local Verification

- `pnpm vitest run __tests__/login-form.test.tsx __tests__/notification-list.test.tsx __tests__/settings-auth-common-i18n.test.tsx`: 11 passed.
- `pnpm typecheck`: passed.
- `pnpm lint`: passed.
- `pnpm vitest run`: 88 passed.
- `pnpm build`: passed; emitted existing Next.js config/deprecation warnings only.
- `git diff --check`: passed.

## Readiness Gate

- Residual CRITICAL: 0
- Residual HIGH: 0
- Residual MEDIUM: 0
- Residual LOW: 1 deferred (`source unavailable` / Eval skeleton fallback strings for common/research cleanup)

Verdict: READY for PR.
