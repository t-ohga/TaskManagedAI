# task-06 self review: SP-009-5 Batch A Read-only UI

## Findings

| finding | severity | decision | result |
|---|---|---|---|
| Queued AgentRuns initially appeared in both Today and Inbox, which made lane counts ambiguous. | MEDIUM | adopt | Today now shows in-progress non-terminal runs; queued runs are Inbox-only. |
| The first Playwright config run reused an old Docker frontend/backend on ports 3000/8000 and failed login before reaching `/today`. | MEDIUM | defer-env | Verified the new page on a separate local Next port with the existing backend token/secret; no code change needed. |
| Error messages could leak backend exception detail if rendered directly. | HIGH | adopt | Non-BackendApiError messages are replaced with source-specific generic messages; config errors are sanitized. |
| Minimal KPI strip could overclaim live P0 status when KPI endpoint is unavailable. | MEDIUM | adopt | KPI fallback is fail-closed (`0/5`, `p0_accept=false`) and source label distinguishes fallback/unavailable. |
| Batch A could accidentally introduce mutation affordances. | HIGH | adopt | The page renders links and read-only rows only; no form, button, server action, schema, or API mutation was added. |

## Verification

- [x] targeted Vitest for Today page + navigation
- [x] frontend typecheck
- [x] touched-file eslint
- [x] full frontend Vitest suite
- [x] full frontend lint
- [x] desktop browser check on `/today` with console error capture
- [x] mobile browser check on `/today` with horizontal overflow check
- [x] `git diff --check`

## Verdict

`READY_FOR_PR`: read-only UI batch only; no API/schema/migration boundary changes.
