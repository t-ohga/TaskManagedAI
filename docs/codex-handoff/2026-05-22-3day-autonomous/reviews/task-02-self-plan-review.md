# task-02 Self-Plan-Review (SP-012-8 UI i18n)

Date: 2026-05-22 JST

## Sources Reviewed

- `docs/codex-handoff/2026-05-22-3day-autonomous/README.md`
- `docs/codex-handoff/2026-05-22-3day-autonomous/00-codex-behavior-guide.md`
- `docs/codex-handoff/2026-05-22-3day-autonomous/01-current-state.md`
- `docs/codex-handoff/2026-05-22-3day-autonomous/02-task-priority-matrix.md`
- `docs/codex-handoff/2026-05-22-3day-autonomous/tasks/task-02-sp012-8-ui-i18n.md`
- `docs/sprints/SP-012-8_ui_i18n_japanese.md`
- `.claude/rules/rendering.md`
- `.claude/rules/testing.md`
- `frontend/components/navigation.tsx`
- `frontend/app/(admin)/**/*.tsx`
- `frontend/__tests__/**/*.tsx`
- `frontend/tests/e2e/**/*.spec.ts`

## Working Plan

Batch order follows the Sprint Pack, with task-file naming normalized to the
existing Sprint Pack path `docs/sprints/SP-012-8_ui_i18n_japanese.md`.

1. Batch 1: navigation and admin shell accessible names.
   - Scope: `frontend/components/navigation.tsx`.
   - Test scope: add/update navigation accessible-name tests and E2E references
     that would otherwise drift.
2. Batch 2: tickets pages and ticket form validation messages.
3. Batch 3: approvals list/detail and decision form visible copy.
4. Batch 4: agent-runs list/detail and state labels.
5. Batch 5: audit log and eval dashboard.
6. Batch 6: settings, login, notifications, and shared admin shell text.
7. Batch 7: common loading/error/empty states and enum-label dictionary tests.

## Glossary

Translate visible operational labels into Japanese, but keep protocol,
database, and API identifiers unchanged.

| Source term | UI label |
|---|---|
| Dashboard | ダッシュボード |
| Tickets | チケット |
| Eval Dashboard | 評価ダッシュボード |
| Approvals | 承認待ち |
| Agent Runs | AI 実行 |
| Audit | 監査ログ |
| Settings | 設定 |
| Logout | ログアウト |
| Admin navigation | 管理ナビゲーション |
| payload_data_class | untranslated |
| allowed_data_class | untranslated |
| tenant_id / actor_id / role_id | untranslated |
| action_class / reason_code / event_type | untranslated as raw value, optional Japanese label in UI |

## Round 1: Structural Review

| id | severity | finding | decision | resolution |
|---|---|---|---|---|
| T02-P1-001 | MEDIUM | Task file references `SP-012-8_ui_i18n.md`, but the repo contains `SP-012-8_ui_i18n_japanese.md`. | adopt | Use the existing Sprint Pack as source of truth. Track path-name drift as docs drift if task-08 touches handoff docs. |
| T02-P1-002 | MEDIUM | Navigation labels are also used by Playwright tests; updating only source code would leave E2E expectations stale. | adopt | Batch 1 includes test expectation updates for navigation accessible names. |
| T02-P1-003 | MEDIUM | API error messages are explicitly out of scope in the Sprint Pack but the task checklist asks to decide the scope. | adopt | Keep backend/API structured messages unchanged. Translate UI-local validation/error states only. |
| T02-P1-004 | LOW | `navItems.current` is currently static to Dashboard, but fixing active-route behavior is not required for i18n. | defer | Do not expand batch 1 into routing behavior changes. Keep existing behavior and limit to labels/accessibility. |
| T02-P1-005 | LOW | Sprint Pack mentions future i18n dictionary, while task batch 1 can be a direct label update. | adopt | For batch 1, direct labels are acceptable. Add dictionary only when enum/status labels start repeating across pages. |

## Round 2: Adversarial Review

| id | severity | finding | decision | resolution |
|---|---|---|---|---|
| T02-P2-001 | HIGH | Accessible-name regressions can hide if only visible text is changed and `aria-label` remains English. | adopt | Translate `nav aria-label` alongside visible labels and assert with role/name. |
| T02-P2-002 | MEDIUM | Updating Playwright tests without a component-level regression test leaves batch 1 undercovered by required Vitest. | adopt | Add `frontend/__tests__/navigation.test.tsx` with Testing Library role queries and strong matchers. |
| T02-P2-003 | MEDIUM | Translating technical identifiers in nav-adjacent test comments or route labels could break traceability. | adopt | Keep route paths and technical identifiers unchanged; only user-facing names change. |
| T02-P2-004 | LOW | Japanese labels are wider than English and can cause mobile wrapping. | adopt | Existing navigation uses flex-wrap and stable padding; verify with type/lint/test now and defer browser visual check to broader UI batches unless frontend server is already running. |

## Readiness Gate

- Residual CRITICAL: 0
- Residual HIGH: 0
- Residual MEDIUM: 0 after adopted resolutions
- Residual LOW: 1 deferred, non-blocking (`navItems.current` static behavior)

Verdict: READY for batch 1 implementation.

## Batch 1 Verification Plan

- `cd frontend && pnpm typecheck`
- `cd frontend && pnpm lint`
- `cd frontend && pnpm vitest run`
- Self-Impl-Review after diff:
  - accessible-name translated
  - role semantics unchanged
  - route hrefs unchanged
  - technical identifiers untranslated
  - strong assertions only
