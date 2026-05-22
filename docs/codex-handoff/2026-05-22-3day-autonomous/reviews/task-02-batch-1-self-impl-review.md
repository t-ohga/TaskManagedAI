# task-02 batch 1 Self-Impl-Review

Date: 2026-05-22 JST

## Scope

- `frontend/components/navigation.tsx`
- `frontend/components/notification-badge.tsx`
- `frontend/__tests__/navigation.test.tsx`
- `frontend/tests/e2e/admin-shell.spec.ts`
- `frontend/tests/e2e/login.spec.ts`
- `frontend/tests/e2e/responsive.spec.ts`
- `frontend/tests/e2e/a11y.spec.ts`
- `docs/codex-handoff/2026-05-22-3day-autonomous/reviews/task-02-self-plan-review.md`

## Summary

SP-012-8 batch 1 translated the admin navigation surface into Japanese while
preserving route hrefs and semantic roles. The notification badge screen-reader
label was included because it is part of the header navigation affordance.

## Adversarial Findings

| id | severity | finding | decision | resolution |
|---|---|---|---|---|
| T02-B1-I001 | MEDIUM | A hidden English label in `NotificationBadge` would leave an untranslated accessible name in the navigation header. | adopt | Translated the screen-reader label from `Notifications` to `通知`. |
| T02-B1-I002 | MEDIUM | E2E tests used the old `Admin`/`Dashboard`/`Logout` accessible names, which would fail after the UI copy changed. | adopt | Updated affected Playwright expectations to Japanese names. |
| T02-B1-I003 | MEDIUM | Batch 1 would lack Vitest coverage if only Playwright expectations were updated. | adopt | Added `navigation.test.tsx` with role/name assertions and exact href checks. |
| T02-B1-I004 | LOW | The existing static `aria-current` behavior still marks Dashboard as current on every route. | defer | Existing behavior is outside i18n scope; do not mix routing behavior changes into this batch. |

## §3.5 Checklist

### Invariants

- server-owned-boundary: non-applicable; no server/API/DB contract changed.
- 5+ source enum integrity: non-applicable; no enum changed.
- raw secret / token leakage: checked; no secret-bearing UI text added.
- terminal mutation / destructive action: non-applicable; logout remains the existing `/login` link.
- accessible-name consistency: pass; visible nav labels and `aria-label` are Japanese.
- route boundary: pass; hrefs are unchanged.
- technical identifiers untranslated: pass; no protocol identifiers were translated.
- cascade risk: low; tests assert every route label/href pair.
- ADR Gate: non-applicable; UI copy polish only.
- Sprint Pack alignment: pass; follows SP-012-8 batch 1.
- test assertion strength: pass; uses `toHaveAttribute`, `toBeVisible`, and role/name queries.
- docs drift: task-file path drift noted in self-plan-review for task-08 follow-up if needed.

### Local Verification

- `pnpm vitest run __tests__/navigation.test.tsx`: 1 passed.
- `pnpm typecheck`: passed.
- `pnpm lint`: passed.
- `pnpm vitest run`: 72 passed.
- `git diff --check`: passed.

## Readiness Gate

- Residual CRITICAL: 0
- Residual HIGH: 0
- Residual MEDIUM: 0
- Residual LOW: 1 deferred, non-blocking static `aria-current` behavior

Verdict: READY for PR.
