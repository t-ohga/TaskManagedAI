# task-07 self review: SP-009-5 Batch B Unified Timeline UI

## Findings

| finding | severity | decision | result |
|---|---|---|---|
| Displaying payload key names verbatim could expose sensitive names such as `raw_prompt`, `token`, or `secret_value`. | HIGH | adopt | Timeline rows filter sensitive key names and render `hidden_keys:N` instead. |
| A unified timeline could imply a new backend event contract. | HIGH | adopt | The implementation uses only existing AgentRun detail, Audit list, Approval list, and KPI clients; no backend/schema/migration change. |
| Partial AgentRun detail fetch failures could hide all other timeline data. | MEDIUM | adopt | AgentRun detail failures are counted and excluded while Audit/Approval/KPI sources still render. |
| KPI fallback could overclaim acceptance status. | MEDIUM | adopt | KPI fallback is fail-closed (`0/5`, `p0_accept=false`) and summary source is shown. |
| Budget is not a dedicated API source yet. | MEDIUM | defer | Budget appears only through existing AgentRun/Audit event types; dedicated budget API remains a future API-gated batch. |

## Verification

- [x] targeted Vitest for Timeline page + navigation
- [x] frontend typecheck
- [x] touched-file eslint
- [x] full frontend Vitest suite
- [x] full frontend lint
- [x] desktop/mobile browser check on `/timeline`
- [x] sensitive key leak check in browser text content
- [x] `git diff --check`

## Verdict

`READY_FOR_PR`: read-only timeline UI only; no API/schema/migration boundary changes.
