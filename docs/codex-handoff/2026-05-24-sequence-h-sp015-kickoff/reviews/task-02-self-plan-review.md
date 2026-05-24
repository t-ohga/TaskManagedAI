# task-02 Self-Plan-Review

## verdict

- task: SP-015 Self-Plan-Review + ADR readiness
- status: READY
- unresolved CRITICAL: 0
- unresolved HIGH: 0
- next action: task-03 batch 0a schema and migration

## files reviewed

- `docs/sprints/SP-015_inter_agent_communication.md`
- `docs/sprints/SP-014_orchestrator_agent.md`
- `docs/sprints/SP-013_multi_agent_orchestration.md`
- `docs/adr/00018_inter_agent_communication.md`
- `docs/adr/00004_agentrun_state_machine.md`
- `.claude/rules/server-owned-boundary.md`
- `.claude/rules/cross-source-enum-integrity.md`
- `.claude/rules/secretbroker-boundary.md`
- `backend/app/domain/agent_runtime/event_type.py`
- `backend/app/db/models/agent_run_event.py`
- `migrations/versions/0025_sp014_event_type_37.py`
- `tests/runtime/test_agent_run_events.py`

## Round 1: structure review

- T02-R1-001 / HIGH / event source drift / adopt:
  SP-015 and ADR-00018 still referenced old event_type 22→31 and
  event 28/29 language. ADR-00004 is already accepted with current 37
  event types, and inter-agent refs are event 34/35.
  Updated SP-015 and ADR-00018 to reuse current 37 exact set.

- T02-R1-002 / HIGH / project boundary / adopt:
  ADR-00018 receiver eligibility subqueries checked tenant / run / parent
  but omitted `project_id`. Added `r.project_id =
  inter_agent_messages.project_id` to role and broadcast eligibility.

- T02-R1-003 / HIGH / project boundary / adopt:
  ADR-00018 unique constraints used `(tenant_id, parent_run_id, seq_no)` and
  `(tenant_id, parent_run_id, idempotency_key)`. Updated them to include
  `project_id`, matching the Sprint's project-boundary invariant.

- T02-R1-004 / MEDIUM / naming drift / adopt:
  ADR-00018 used `data_class` while SP-015 and Provider Compliance use
  `payload_data_class`. Updated ADR payload and schema naming to
  `payload_data_class`.

- T02-R1-005 / MEDIUM / schema ambiguity / adopt:
  `12 fields` is historical shorthand, but ADR-00018 §1 contains a larger
  exact column set including server-owned refs and lifecycle fields. Added
  explicit instructions that implementation must use ADR-00018 §1 as source.

- T02-R1-006 / LOW / ADR status / defer:
  ADR-00018 remains `proposed`. Prerequisites appear satisfied, but acceptance
  should happen with the SP-015 implementation PR or explicit kickoff PR, not
  silently inside this planning-only task.

## Round 2: adversarial review

- T02-R2-001 / HIGH / raw payload leakage / adopt:
  AgentRunEvent and audit_events must remain ref-only. Task-03 must add
  `assert_no_raw_secret_and_no_raw_message_body` style helpers and ensure
  message body / artifact body never appears in event payloads.

- T02-R2-002 / HIGH / trusted_instruction promotion / adopt:
  `trusted_instruction` can become a privilege escalation path unless the
  implementation enforces DB CHECK + service guard + Pydantic guard + tests.
  This remains a task-03 must_ship gate.

- T02-R2-003 / MEDIUM / migration rollback / adopt:
  SP-015 should not downgrade or reallocate AgentRunEvent event_type 34/35,
  because they already exist in migration `0025_sp014_event_type_37.py`.
  Task-03 migration must focus on `inter_agent_messages` and audit schema.

- T02-R2-004 / MEDIUM / sanitizer drift / adopt:
  `sanitizer_policy_versions` exists from SP-013. Task-03 must choose and test
  stale sanitizer behavior: deny or re-sanitize, with no silent accept path.

- T02-R2-005 / MEDIUM / SecretBroker negative / defer to implementation:
  SP-015 must define the exact inter-agent token payload denial reason_code in
  task-03 and test it as a 5+ source enum if it becomes a new enum source.

## plan changes applied

- Updated SP-015 frontmatter `updated_at` to `2026-05-24`.
- Moved accepted ADR-00004 from `planned_adr_refs` to `adr_refs`.
- Reconciled SP-015 event references with ADR-00004 current 37 event types.
- Added SP-015 design notes for `12 fields` shorthand and
  `payload_data_class`.
- Updated ADR-00018 receiver eligibility SQL to include `project_id`.
- Updated ADR-00018 unique constraints to include `project_id`.
- Updated ADR-00018 `data_class` naming to `payload_data_class`.
- Updated task-03 batch 0a instructions to use ADR-00018 exact column set.

## task-03 batch split

1. batch 0a:
   schema and migration for `inter_agent_messages`.
2. batch 0b:
   publisher service, sanitizer, payload hash, payload_data_class.
3. batch 0c:
   consumer service, atomic consume, receiver eligibility, replay / hijack.
4. batch 0d:
   trusted_instruction defense and approval target binding.
5. batch 0e:
   audit_events and AgentRunEvent ref payload checks.
6. batch 0f:
   backup / restore drill and SecretBroker negative case.

## readiness gate

- CRITICAL = 0
- HIGH = 0 after adopted plan fixes
- MEDIUM findings are either converted into task-03 gates or deferred with
  explicit implementation decision points
- task-03 may start
