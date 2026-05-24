# task-05 self review: SP-009-5 Split Docs

## Findings

| finding | severity | decision | result |
|---|---|---|---|
| A new SP-009-5 Pack could be mistaken as authorization to implement `request_revision` without ADR/API updates. | HIGH | adopt | The Pack marks `request_revision` as ADR-00003 / ADR-00004 / ADR-00009 gated and keeps this PR docs-only. |
| Splitting SP-009-5 could accidentally promote SP-009 from `partial_skeleton` to completed. | HIGH | adopt | SP-009 remains `partial_skeleton`; golden E2E, DOM secret scan, and residual enum contract remain open. |
| Read-only UI work and API/state mutation work were initially mixed in the same candidate list. | MEDIUM | adopt | The Pack now separates batches A-C from mutation-gated batches D-E. |
| Registry and backlog could drift if only the Sprint Pack file is added. | MEDIUM | adopt | The registry, P0 backlog, handoff README/current-state/task matrix, and SP-009 cross-reference are updated in the same PR. |
| Notification triage can imply a new event schema even when the implementation is absent. | MEDIUM | adopt | The Pack records ADR-00003 event schema gate and leaves schema/migration work to a later PR. |

## Verification

- [x] New Sprint Pack is light frontmatter and docs-only.
- [x] SP-009 status remains non-completed.
- [x] Cross-references exist in sprint registry, backlog, SP-009, and handoff task matrix.
- [x] Local docs verification commands are listed in task-05.

## Verdict

`READY_FOR_PR`: docs-only split plan; no implementation or migration boundary changes.
