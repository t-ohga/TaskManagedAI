# task-02 batch 4 Self-Impl-Review

Date: 2026-05-22 JST

## Scope

- `frontend/app/(admin)/runs/page.tsx`
- `frontend/app/(admin)/runs/[id]/page.tsx`
- `frontend/app/(admin)/_components/sprint9-admin-ui.tsx`
- `frontend/__tests__/agent-runs-i18n.test.tsx`
- `frontend/tests/e2e/sprint9-pages.spec.ts`

## Summary

SP-012-8 batch 4 localized Agent Runs list/detail pages and the shared
AgentRun state-machine viewer. Raw `AgentRun` status, `AgentRunEvent`,
`blocked_reason`, `actor_id`, and `ContextSnapshot` identifiers remain visible
for contract traceability.

## Adversarial Findings

| id | severity | finding | decision | resolution |
|---|---|---|---|---|
| T02-B4-I001 | HIGH | Translating the keyboard navigation `label` field directly would break `aria-current` because callers pass the English internal label. | adopt | Added `displayLabel`; internal `label` remains unchanged for `current` comparison. |
| T02-B4-I002 | HIGH | AgentRun 16-state raw identifiers must not be translated because tests and state-machine contracts depend on exact enum strings. | adopt | Translated descriptions/labels only; code pills still render raw status values. |
| T02-B4-I003 | MEDIUM | List accessible names changed and would make Playwright expectations stale. | adopt | Updated sprint9 E2E list/detail expectations to Japanese accessible names. |
| T02-B4-I004 | MEDIUM | Shared `sprint9-admin-ui` affects other pages beyond Agent Runs. | adopt | Only user-facing shared keyboard labels changed; internal labels and hrefs remain unchanged. |
| T02-B4-I005 | LOW | Some technical panel titles intentionally retain identifiers like `ContextSnapshot metadata contract`. | reject | Sprint Pack glossary keeps technical identifiers untranslated; surrounding description is Japanese. |

## §3.5 Checklist

### Invariants

- AgentRun 16 state enum: pass; raw values unchanged and tested.
- blocked_reason 3 enum: pass; raw values unchanged and tested.
- AgentRunEvent raw event_type: pass; raw event names unchanged.
- server-owned-boundary: pass; route UUID guard and data flow unchanged.
- API contract: pass; no API client or backend request changed.
- accessible-name consistency: pass; updated list/region names and tests.
- technical identifiers untranslated: pass; AgentRun, AgentRunEvent, blocked_reason, ContextSnapshot, actor_id remain raw where contract-bound.
- keyboard current behavior: pass; internal labels still drive `aria-current`.
- weak assertion ban: pass; role/name, `toHaveAttribute`, and raw-value visibility assertions.
- cascade risk: low; `displayLabel` avoids changing current prop callers.
- ADR Gate: non-applicable; UI copy only.
- security boundary: pass; raw secret exclusion text preserved and no secret values added.

### Local Verification

- `pnpm vitest run __tests__/agent-runs-i18n.test.tsx`: 1 passed.
- `pnpm typecheck`: passed.
- `pnpm lint`: passed.
- `pnpm vitest run`: 81 passed.
- `git diff --check`: passed.
- `rg` old Agent Runs UI pattern sweep: only internal labels/comments remain.

## Readiness Gate

- Residual CRITICAL: 0
- Residual HIGH: 0
- Residual MEDIUM: 0
- Residual LOW: 0

Verdict: READY for PR.
