# task-02 batch 7 Self-Impl-Review

Date: 2026-05-22 JST

## Scope

- `frontend/app/(admin)/research/page.tsx`
- `frontend/app/(admin)/research/[id]/page.tsx`
- `frontend/app/(admin)/research/[id]/_components.tsx`
- `frontend/lib/i18n/research-labels.ts`
- `frontend/__tests__/app/admin/research/page.test.tsx`
- `frontend/__tests__/app/admin/research/[id].test.tsx`
- `frontend/__tests__/lib/i18n/research-labels.test.ts`
- `docs/sprints/SP-012-8_ui_i18n_japanese.md`
- `docs/codex-handoff/2026-05-22-3day-autonomous/completion/task-02-completed.md`

## Summary

SP-012-8 batch 7 closes the remaining common/research i18n cleanup. Research
list/detail visible labels, empty/error states, status labels, and evidence
relation labels are now Japanese while preserving raw schema identifiers such as
`ResearchTask`, `project_id`, `created_at`, `evidence_set_hash`, `locator`,
`relation`, and `source`.

## Adversarial Findings

| id | severity | finding | decision | resolution |
|---|---|---|---|---|
| T02-B7-I001 | HIGH | Translating Research schema identifiers such as `project_id`, `evidence_set_hash`, `locator`, and `relation` would reduce audit/debug traceability. | adopt | Kept schema identifiers raw or in parentheses while localizing surrounding labels. |
| T02-B7-I002 | HIGH | Hiding raw enum values for research status/relation would break the Sprint Pack enum invariant. | adopt | Added `formatResearchStatus` and `formatEvidenceRelation` as Japanese label + raw enum value. |
| T02-B7-I003 | MEDIUM | Source redaction copy could imply missing backend data rather than deliberate credential stripping. | adopt | Used Japanese labels with raw phrases: `source 未解決 (source unavailable)` and `source 非表示 (redacted source)`. |
| T02-B7-I004 | MEDIUM | Sprint Pack completion without Review/frontmatter update would leave docs drift. | adopt | Updated `SP-012-8_ui_i18n_japanese.md` to `completed` with Review evidence and carry-over notes. |
| T02-B7-I005 | MEDIUM | Existing Research tests only asserted English headings and raw enum strings. | adopt | Updated tests and added `research-labels.test.ts` for status/relation dictionary coverage. |

## §3.5 Checklist

### Invariants

- server-owned-boundary: pass; no API call ownership or request context changed.
- raw secret boundary: pass; Research DOM still excludes secret refs/capability tokens; tests retain negative assertions.
- technical identifiers: pass; schema and audit/debug identifiers remain visible.
- enum label invariant: pass; research status and evidence relation use Japanese label + raw enum value.
- atomic claim: pass; one UI i18n cleanup slice plus Sprint Pack/completion docs.
- approval 4 consistency: non-applicable; no approval behavior changed.
- event/source mismatch: pass; no event source, KPI source, or audit source changed.
- terminal mutation: pass; no state transition logic changed.
- migration verification: non-applicable; no DB/Alembic changes.
- API contract: pass; no request/response schema changed.
- accessible-name consistency: pass; Research list/detail region headings updated and tested.
- docs drift: pass; Sprint Pack Review and completion report added.

### Tests

- weak assertion ban: pass; assertions use visible text, role/name, href, and raw-secret negative checks.
- regression case separation: pass; list page, detail page, and label dictionary tests remain separate.
- raw enum visibility: pass; `完了 (completed)` and `支持 (supports)` tested.
- raw secret negative: pass; secret/capability strings remain absent in detail test.
- snapshot avoidance: pass; no broad snapshots added.
- full frontend regression: pass; full Vitest suite completed.

### PR Description Inputs

- changed files summarized: ready.
- verification commands captured: ready.
- raw identifier preservation called out: ready.
- Sprint Pack completion called out: ready.
- CI/bypass context: ready; expected hosted CI billing-blocked pattern remains external to this batch.

### Local Verification

- `pnpm vitest run __tests__/app/admin/research/page.test.tsx '__tests__/app/admin/research/[id].test.tsx' __tests__/lib/i18n/research-labels.test.ts`: 5 passed.
- `pnpm typecheck`: passed.
- `pnpm lint`: passed.
- `pnpm vitest run`: 90 passed.
- `pnpm build`: passed; emitted existing Next.js config/deprecation warnings only.
- `git diff --check`: passed.

## Readiness Gate

- Residual CRITICAL: 0
- Residual HIGH: 0
- Residual MEDIUM: 0
- Residual LOW: 0

Verdict: READY for PR.
