# Claude Verification Checklist

## read order

1. `docs/codex-handoff/2026-05-24-sequence-h-sp015-kickoff/README.md`
2. 本 file
3. `COMPLETION_REPORT.md` if present
4. `completion/task-NN-completed.md`
5. `reviews/task-NN-*.md`

## Sequence A: blocker check

- [ ] `STOPPED.md` does not exist.
- [ ] If it exists, inspect and resolve before continuing.

## Sequence B: previous closeout re-check

- [ ] PR #172 is merged.
- [ ] open PR list is empty or known.
- [ ] GitHub Actions failures are quota-only.
- [ ] `docs/codex-handoff/2026-05-22-3day-autonomous/COMPLETION_REPORT.md`
      still says no known CRITICAL / HIGH.

## Sequence C: task-01 verification

- [ ] PR #145-#171 residual classes are all covered.
- [ ] #171 fixes map to the original inline comments.
- [ ] `codex_pr_full_review.sh 171` actionable 0, or new findings classified.
- [ ] matrix-based fixes did not create cascade regressions.
- [ ] Sequence H review log exists in `reviews/`.

## Sequence D: task-02 verification

- [ ] SP-015 prerequisites are still true.
- [ ] ADR-00018 readiness is explicit.
- [ ] ADR-00004 update scope is explicit.
- [ ] migration sequence and rollback are explicit.
- [ ] test matrix includes every SP015-T01 to T08 ticket.
- [ ] remaining HIGH findings are <= 2 and mitigated.

## Sequence E: task-03 verification

Only run this section if task-03 was implemented.

- [ ] `inter_agent_messages` schema has all 12 fields.
- [ ] atomic consume permits exactly one success under concurrency.
- [ ] replay / hijack fixtures deny all cases.
- [ ] trusted_instruction cannot auto-promote.
- [ ] audit payloads include required refs and exclude raw body / secret.
- [ ] AgentRunEvent refs exclude raw payload.
- [ ] downgrade / upgrade path is verified.

## Sequence F: invariant regression

- [ ] caller-supplied `tenant_id` / `project_id` / `actor_id` route params
      were not introduced.
- [ ] enum source sets remain exact.
- [ ] AgentRun 16 status remain exact.
- [ ] blocked_reason 3 values remain exact.
- [ ] raw secret and raw message body are absent from DB/log/audit/artifact.
- [ ] approval 4 binding remains intact.

## Sequence G: next Sprint readiness

- [ ] SP-015 can move from `draft` to `ready`, or blockers are recorded.
- [ ] SP-016 remains plan-only until SP-015 message backend is stable.
- [ ] carry-over is recorded in Sprint Pack or completion report.

## Sequence H: Claude deeper loop

Claude may run `codex-all-loops` after Codex completes task-01 / task-02.

Recommended targets:

```text
docs/sprints/SP-015_inter_agent_communication.md --mode=plan --max-rounds=8
docs/adr/00018_inter_agent_communication.md --mode=plan --max-rounds=6
docs/adr/00004_agentrun_state_machine.md --mode=plan --max-rounds=6
```

If task-03 implementation exists, add:

```text
backend/app/services/inter_agent --mode=code --max-rounds=10
backend/app/db/models --mode=code --max-rounds=6
migrations/versions --mode=code --max-rounds=6
tests/inter_agent --mode=code --max-rounds=8
```

Findings must be classified as adopt / reject / defer.
