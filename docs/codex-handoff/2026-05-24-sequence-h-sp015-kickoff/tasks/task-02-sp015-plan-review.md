# task-02: SP-015 Self-Plan-Review

## scope

SP-015 inter-agent communication の実装前計画をレビューし、
batch 0 実装に入れる状態まで計画を固める。
この task では原則コード実装をしない。

## inputs

- `docs/sprints/SP-015_inter_agent_communication.md`
- `docs/sprints/SP-014_orchestrator_agent.md`
- `docs/sprints/SP-013_multi_agent_orchestration.md`
- `docs/adr/00018_inter_agent_communication.md`
- `docs/adr/00004_agentrun_state_machine.md`
- `.claude/rules/server-owned-boundary.md`
- `.claude/rules/cross-source-enum-integrity.md`
- `.claude/rules/secretbroker-boundary.md`
- `.claude/rules/sprint-pack-adr-gate.md`

## review targets

### SP015-T01 schema

- exact column set from ADR-00018 §1.
- `12 fields` is historical shorthand, not a literal column count.
- NOT NULL / DEFAULT / CHECK.
- tenant_id / project_id / parent_run / sender / receiver FK strategy.
- unique constraints include `tenant_id`, `project_id`, and `parent_run_id`.
- consume index and idempotency key.
- downgrade path.

### SP015-T02 publisher

- sanitizer pipeline.
- secret canary scan.
- payload_data_class calculation.
- raw body storage boundary.
- previous_hash / seq_no creation.

### SP015-T03 consumer

- atomic consume SQL.
- receiver eligibility.
- role / broadcast receiver subqueries include project_id.
- replay / hijack deny cases.
- expires_at and idempotency duplicate handling.

### SP015-T04 trusted_instruction

- DB CHECK.
- service guard.
- Pydantic guard.
- test guard.
- approval target 4 binding.

### SP015-T05 audit events

- sent / consumed / denied schema.
- no raw secret.
- no raw message body.
- correlation id and hash references.

### SP015-T06 AgentRunEvent refs

- event source enum exactness.
- reconcile stale SP-015 `event_type 22→31` / event 28/29 wording with
  SP-014 completion state `event_type 28→37`.
- ref-only payload.
- relationship with audit_events.

### SP015-T07 backup / restore drill

- parent / child AgentRun FK.
- message sequence / hash / consume state.
- agent_roles soft-delete.
- memory_records source FK if applicable.
- audit_events correlation.

### SP015-T08 SecretBroker negative

- inter-agent token payload negative case.
- reason_code exactness.
- audit denial without raw token.

## Self-Plan-Review

Round 1:

- Identify missing steps, dependency order, and unresolved ADR questions.

Round 2:

- Attack the plan with concurrency, replay, hijack, stale sanitizer,
  cross-tenant, cross-project, and raw payload scenarios.

## readiness gate

- CRITICAL = 0.
- HIGH <= 2.
- batch split for task-03 is concrete.
- STOPPED.md if gate fails.

## outputs

- `reviews/task-02-self-plan-review.md`
- `completion/task-02-completed.md`
- optional patch to SP-015 docs if the plan itself must be clarified.

## DoD checklist

- [ ] SP015-T01-T08 all mapped to tests.
- [ ] ADR-00018 accepted criteria are clear.
- [ ] ADR-00004 update criteria are clear.
- [ ] `payload_data_class` is the canonical name; no new `data_class` drift.
- [ ] receiver eligibility and unique constraints preserve project boundary.
- [ ] stale event_type 22→31 / event 28/29 references are reconciled
      before implementation.
- [ ] migration rollback plan is clear.
- [ ] event_type / audit event source exact set plan is clear.
- [ ] raw secret / raw message body non-exposure plan is clear.
- [ ] task-03 batch split is ready.
