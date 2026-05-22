# task-01 Self-Plan-Review (2026-05-22)

## scope

- task: task-01 / SP-014 batch 0 orchestrator agent core
- protocol: `00-codex-behavior-guide.md` §3.1 Self-Plan-Review
- read inputs:
  - `docs/codex-handoff/2026-05-22-3day-autonomous/{README.md,00-codex-behavior-guide.md,01-current-state.md,02-task-priority-matrix.md}`
  - `docs/codex-handoff/2026-05-22-3day-autonomous/tasks/task-01-sp014-batch-0-orchestrator.md`
  - `docs/sprints/SP-014_orchestrator_agent.md`
  - `docs/adr/00014_multi_agent_orchestration.md`
  - `docs/adr/00019_role_taxonomy.md`
  - `docs/adr/00009_action_class_taxonomy.md`
  - `.claude/rules/{agentrun-state-machine.md,secretbroker-boundary.md,server-owned-boundary.md,cross-source-enum-integrity.md,sprint-pack-adr-gate.md}`

## Round 1 findings (structure)

| id | severity | category | symptom | judgment | implementation decision |
|---|---|---|---|---|---|
| SP014-PLAN-R1-F001 | HIGH | enum drift | `task-01` batch 0c example includes `read_only` in policy_profile 14-row seed, but ADR-00009 and `backend/app/domain/policy/action_class.py` fix the 7 action classes as `task_write/repo_write/pr_open/secret_access/merge/deploy/provider_call`. | adopt | Use `provider_call`; never introduce `read_only` action_class. Read/search remains Tool Registry `allowed_actions`. |
| SP014-PLAN-R1-F002 | HIGH | ADR path / numbering | `SP-014` and task-01 refer to new `docs/adr/00021_tool_registry_network_enum.md`, but ADR-00021 already exists as host-portable deployment and Tool Registry's actual ADR is `ADR-00027`. | adopt | Do not create a second ADR-00021. Batch 0d must amend/promote `docs/adr/00027_tool_registry_security_boundary.md` for `network_access` / `tool_network_policies`, then move SP-014 refs to ADR-00027. |
| SP014-PLAN-R1-F003 | HIGH | dependency order | batch 0a requires lease renew / failover / kill / progress events, but new event types are scheduled in batch 0f. Existing DB/domain enum only has 28 event types, so batch 0a cannot append the required events without first extending event_type sources. | adopt | Move the AgentRunEvent 28-to-37 enum extension to a prerequisite slice in batch 0a, before lease service methods append new events. |
| SP014-PLAN-R1-F004 | MEDIUM | ORM drift | migration 0021 already added `agent_runs.role_id`, lease, kill, and progress columns, but `backend/app/db/models/agent_run.py` does not map them. | adopt | Batch 0a must update `AgentRun` ORM columns before implementing lease/progress services. |
| SP014-PLAN-R1-F005 | MEDIUM | 5+ source coverage | Existing event_type integrity has DB migration, ORM CheckConstraint, Python Literal, and pytest exact-set tests, but no Pydantic event schema source currently exists. | adopt | Add `backend/app/schemas/agent_run_event.py` with a Pydantic event type field and include it in exact-set tests for the 28-to-37 expansion. |
| SP014-PLAN-R1-F006 | MEDIUM | state transition mapping | New event types include status-preserving events (`orchestrator_lease_renewed`) and state-affecting events (`orchestrator_lease_expired`, `orchestrator_kill_engaged`). `transition_with_event` only supports mapped status transitions. | adopt | Use direct `append_event` for status-preserving events in the same transaction as atomic updates; extend state-machine mapping only where status changes are intended. |

## Round 2 findings (adversarial)

| id | severity | category | symptom | judgment | implementation decision |
|---|---|---|---|---|---|
| SP014-PLAN-R2-F001 | HIGH | lease race | A heartbeat implementation that reads the run, checks lease, then updates can allow two orchestrators to believe they own the same lease under concurrency. | adopt | Lease renew/claim must be a single conditional `UPDATE ... WHERE tenant_id/run_id/lease_token/expires_at/status/role_id ... RETURNING`; 0 rows is deny. |
| SP014-PLAN-R2-F002 | HIGH | raw secret / token logging | Lease tokens are UUIDs and must not be treated as secret capability tokens, but raw lease tokens in event payloads would create replay and audit leakage risk. | adopt | Event payloads store only SHA-256 lease token hashes or redacted prefixes, never raw `orchestrator_lease_token`. |
| SP014-PLAN-R2-F003 | MEDIUM | role boundary | Existing DB trigger permits project-scoped standard roles. If orchestrator lease code accepts any `role_scope` without checking `role_id`, non-orchestrator agent runs could renew/kill leases. | adopt | Lease/progress services must require `AgentRun.role_id == "orchestrator"` for orchestrator-owned operations. |
| SP014-PLAN-R2-F004 | MEDIUM | terminal mutation | Failover/progress/kill logic could mutate terminal child runs if queries do not exclude terminal statuses. | adopt | All state mutation queries must exclude terminal states (`completed/failed/cancelled/provider_refused/repair_exhausted`). |
| SP014-PLAN-R2-F005 | MEDIUM | idempotency / event duplication | Lease renew retry can append duplicate events if the retry happens after a successful update but before client observes success. | adopt | Use deterministic idempotency keys for service operations (`orchestrator-lease-renew:<run_id>:<new_token_hash>` etc.) where operation identity is known. |
| SP014-PLAN-R2-F006 | LOW | handoff wording drift | Several docs still say `event_type 22 -> 31`; current implementation has 28 event types and SP-014 adds 9 more. | adopt | Implementation and tests use 28 -> 37; completion report notes the wording drift. |

## readiness gate

- residual CRITICAL: 0
- residual HIGH: 0 after adopted plan adjustments
- deferred findings: 0
- verdict: READY for batch 0a implementation

## batch 0a adjusted implementation order

1. Extend AgentRunEvent enum sources from 28 to 37:
   - Python Literal / tuple
   - ORM CheckConstraint
   - Alembic migration
   - Pydantic schema
   - pytest exact-set tests
2. Update `AgentRun` ORM mapping for role/lease/progress columns already present in migration 0021.
3. Implement `backend/app/services/orchestrator/`:
   - `lease_manager.py`: atomic renew/expire/failover primitives
   - `kill_switch.py`: human actor kill event + runtime block
   - `progress_lease.py`: progress update and no-progress block
   - `dispatcher.py`: local child dispatch guard skeleton
   - `orchestrator.py`: facade service
4. Add focused tests first for enum drift and atomic lease negative cases, then service behavior tests.
