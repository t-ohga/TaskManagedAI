# Task Priority Matrix

## priority

| 優先 | task | scope | 計画必須 | effort | gate |
|---|---|---|---|---|---|
| P0 | task-01 | Sequence H residual verification | 必須 | 0.5-1 day | CRITICAL=0 / HIGH=0 preferred |
| P0 | task-02 | SP-015 Self-Plan-Review + ADR readiness | 必須 | 0.5-1 day | CRITICAL=0 / HIGH<=2 |
| P0 | task-03 | SP-015 batch 0 inter-agent message core | 必須 | 2-3 day | task-02 READY |
| P1 | task-04 | SP-016 inventory / plan-only | 推奨 | 0.3-0.5 day | task-01 READY |

## DAG

```text
origin/main (#172)
  |
  v
task-01 Sequence H residual verification
  |
  +--> task-02 SP-015 Self-Plan-Review
  |       |
  |       v
  |     task-03 SP-015 batch 0 implementation
  |
  +--> task-04 SP-016 inventory / plan-only
```

## execution rule

- task-01 is first.
- task-02 starts only after task-01 has no unresolved CRITICAL / HIGH.
- task-03 starts only after task-02 is `READY`.
- task-04 can run after task-01, but must not implement SP-016 code.

## collision risk

| area | task | risk |
|---|---|---|
| `backend/app/db/models/` | task-03 | new table / FK drift |
| `migrations/versions/` | task-03 | alembic head and rollback |
| `backend/app/services/` | task-03 | orchestrator publisher stub replacement |
| `backend/app/domain/agent_run/` | task-03 | event_type drift |
| `backend/app/api/` | task-03 | caller-supplied boundary |
| `docs/adr/00018*` | task-02 / task-03 | proposed to accepted timing |
| `docs/adr/00004*` | task-02 / task-03 | event_type update timing |
| `docs/cli/README.md` | task-04 | must remain plan-only |

## must ship by task

### task-01

- PR #145-#171 merge list verified.
- #171 residual classes reviewed against code or tests.
- Codex review helper baseline is clean or any finding is classified.
- Sequence H result recorded in `reviews/`.

### task-02

- SP-015 ticket order reviewed and revised if needed.
- ADR-00018 and ADR-00004 update readiness checked.
- stale SP-015 event_type 22→31 / event 28/29 references reconciled
  with SP-014 event_type 28→37 completion state.
- migration order, rollback path, and test matrix defined.
- SP-015 implementation split into safe batches.

### task-03

- inter_agent_messages 12 fields.
- atomic consume with receiver eligibility.
- replay / hijack deny fixtures.
- trusted_instruction 4-layer defense.
- audit_events sent / consumed / denied payload schema.
- AgentRunEvent ref events without raw body.
- backup / restore drill update.
- SecretBroker inter-agent token negative case.

### task-04

- SP-016 dependency inventory.
- CLI capability list checked against SP-015 readiness.
- no code implementation.
- carry-over plan recorded.

## defer

- SP-016 code implementation.
- SP-017 Web UI timeline.
- SP-018 memory backend.
- full remote adapter / Codex app-server / Claude SDK adapter.
- GitHub Actions quota restoration.
