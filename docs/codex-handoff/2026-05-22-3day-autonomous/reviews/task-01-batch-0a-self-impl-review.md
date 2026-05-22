# task-01 batch 0a Self-Impl-Review (2026-05-22)

## scope

- task: task-01 / SP-014 batch 0a orchestrator service module
- protocol: `00-codex-behavior-guide.md` §3.2 Self-Impl-Review
- implementation target:
  - `backend/app/services/orchestrator/`
  - `backend/app/db/models/agent_run.py`
  - AgentRunEvent 28 -> 37 enum sources
  - focused runtime and multi-agent tests

## implemented

- Added `backend/app/services/orchestrator/` primitives:
  - lease renew / stale lease block
  - queued-standby failover promotion
  - kill switch
  - progress recording / no-progress block
  - local dispatch event recording
  - facade service
- Extended AgentRunEvent sources from 28 to 37:
  - Python Literal / tuple
  - ORM CHECK constraint
  - migration `0025_sp014_event_type_37.py`
  - Pydantic schema source
  - pytest exact-set coverage
- Updated AgentRun ORM to map the SP-013 role / lease / progress columns already present in migration 0021.

## adversarial review findings

| id | severity | category | symptom | judgment | fix |
|---|---|---|---|---|---|
| SP014-IMPL-R1-F001 | HIGH | server-owned-boundary | Dispatch event originally accepted `role_id` / `role_scope` parameters and could record caller-supplied role data. | adopt | `OrchestratorDispatcher` now derives role fields from the child `AgentRun` row and rejects missing server-resolved role data. |
| SP014-IMPL-R1-F002 | HIGH | event/source mismatch | `orchestrator_failover_triggered` was added to the enum but no service path emitted it. | adopt | Added `OrchestratorFailover.trigger_existing_standby()` with lease-expired event + failover event in the same transaction. |
| SP014-IMPL-R1-F003 | MEDIUM | token leakage | Lease/failover events could leak raw UUID lease tokens if payloads used DB values directly. | adopt | Event payloads include only SHA-256 lease hashes; tests assert old/new token hex values are absent. |
| SP014-IMPL-R1-F004 | MEDIUM | terminal mutation | Kill/progress/lease operations could mutate terminal runs if predicates were too broad. | adopt | Mutating queries require non-terminal status or `running` as appropriate; terminal kill negative test added. |
| SP014-IMPL-R1-F005 | MEDIUM | migration verification | `uv run alembic check` is required by the handoff, but current `migrations/env.py` still has `target_metadata=None`, so the command cannot run. Enabling it revealed pre-existing global ORM/schema drift outside batch 0a. | defer | Kept batch 0a scoped. Verified `upgrade head -> downgrade -1 -> upgrade head` and record this as residual infrastructure debt for a dedicated migration-drift task. |

## invariant checklist

- server-owned-boundary: PASS for batch 0a service surfaces; dispatch role payload is DB-derived.
- 5+ source enum integrity: PASS for AgentRunEvent 37-source set.
- AgentRun 16 status invariant: PASS; no status enum expansion.
- blocked_reason 3 value invariant: PASS; new paths use `runtime_blocked`.
- raw secret / raw lease token event leakage: PASS; event payloads store hashes only.
- atomic claim pattern: PASS for lease renew; failover uses row lock + conditional promote/block within caller transaction.
- event append same transaction: PASS; service methods rely on caller-owned `AsyncSession` transaction and append in the same session.

## verification

- `uv run ruff check backend tests`: PASS
- `uv run mypy backend`: PASS (`249 source files`)
- `TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/multi_agent/ -q`: PASS (`38 passed`)
- `TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/runtime/test_agent_run_events.py tests/runtime/test_agentrun_transitions.py -q`: PASS (`51 passed`)
- `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`: PASS against `taskmanagedai_test`
- `uv run alembic check`: NOT CLEAN, pre-existing env limitation (`migrations/env.py` does not provide `target_metadata`)

## readiness gate

- residual CRITICAL: 0
- residual HIGH: 0
- deferred: `alembic check` infrastructure drift only, not introduced by batch 0a
- verdict: READY for batch 0a handoff; task-01 batches 0b-0f remain open
