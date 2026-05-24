# task-03 self review: SP-007 Phase 5 Hook Trust Boundary Plan

## Review Mode

- Round 1: structure review against task-03 required output.
- Round 2: adversarial review for trust-boundary overreach and rollback gaps.

## Round 1 Findings

| finding | severity | decision | result |
|---|---|---|---|
| Plan must separate repo docs, in-repo helper code, repo-external changes, and rollback. | HIGH | adopt | Plan has four explicit sections. |
| ADR-00012 acceptance could be overclaimed as implementation complete. | HIGH | adopt | Plan states ADR accepted but BL-0082/0083/0084 unimplemented. |
| Codex hook commands could accidentally inherit Claude-only `$CLAUDE_PROJECT_DIR`. | MEDIUM | adopt | Plan keeps `.codex/hooks.json` unchanged unless wrapper command works with `PWD` and no Claude-only variables. |
| Rollback needs backup location before settings switch. | MEDIUM | adopt | Plan uses `~/.claude-trusted/backups/taskmanagedai/<timestamp>/` before external install. |

## Round 2 Adversarial Findings

| finding | severity | decision | result |
|---|---|---|---|
| A docs PR could still imply permission to mutate host-level trust roots later. | HIGH | adopt | Plan requires explicit approval at Phase 5C despite broad autonomous permission. |
| Helper tests could mutate the real user home if written naively. | HIGH | adopt | Plan requires temp HOME / temp repo fixtures and forbids real trust root access in tests. |
| Wrapper could verify only the dispatcher and miss child hook replacement. | HIGH | adopt | Plan requires manifest coverage for dispatcher and child hooks, plus missing/chmod-x tests. |
| Snapshot state movement could be partial if pre/post scripts keep hardcoded repo-local state. | MEDIUM | adopt | Plan requires `TASKMANAGEDAI_HOOK_STATE_DIR` support with repo-local default until activation. |
| SP-007 historical Review text still says ADR-00012 was proposed. | LOW | adopt | Plan adds a current-state note instead of rewriting historical batch records. |

## Checklist

- [x] server-owned boundary respected: no caller-supplied trust root is considered active without wrapper verification.
- [x] repo-external changes gated: no host-level write is included in this planning PR.
- [x] Codex/Claude environment split respected: Codex hooks must not rely on Claude-only variables.
- [x] rollback described before settings switch.
- [x] verification commands split between planning PR, helper-code PR, and external install.
- [x] SP-007 status remains `done_with_phase5_defer`.

## Verdict

`READY_FOR_PR`: CRITICAL=0 / HIGH=0 after adopted plan changes.
